"""개별 저축은행 공식 evidence의 read-only reconciliation 신호를 만든다.

FSB/FINLIFE canonical 값은 절대 수정하지 않는다. 공식 홈페이지 evidence 자체가
충돌할 수 있으므로, evidence group 내부 일관성을 먼저 확인한 뒤 어느 source를
지지하는지 참고 신호만 계산한다.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _records(payload: object) -> tuple[list[dict[str, Any]], bool]:
    if isinstance(payload, dict):
        records = payload.get("records")
        wrapped = True
    else:
        records = payload
        wrapped = False
    if not isinstance(records, list):
        raise ValueError("official evidence JSON은 배열 또는 {records:[...]} 형식이어야 한다")
    if not all(isinstance(item, dict) for item in records):
        raise ValueError("official evidence record는 객체여야 한다")
    return [dict(item) for item in records], wrapped


def prepare_official_evidence_payload(payload: object) -> object:
    """수동 검증된 evidence alias를 기존 v1 비교계약에 안전하게 투영한다.

    ``comparison_product``는 official evidence -> 수집 source 매칭에만 사용한다.
    FSB <-> FINLIFE 자동 상품 매칭이나 canonical identity는 변경하지 않는다.
    """
    records, wrapped = _records(payload)
    prepared: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        item = dict(record)
        item.setdefault("evidence_id", f"official-{index + 1}")
        comparison_product = str(item.get("comparison_product") or "").strip()
        if comparison_product:
            item.setdefault("official_product", item.get("product"))
            item["product"] = comparison_product
            item["evidence_match_method"] = "manual_evidence_alias"
        else:
            item.setdefault("official_product", item.get("product"))
            item["evidence_match_method"] = "exact_official_product"
        prepared.append(item)

    if not wrapped:
        return prepared
    root = dict(payload)
    root["records"] = prepared
    return root


def write_prepared_official_evidence(source_path: Path, out_path: Path) -> None:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    prepared = prepare_official_evidence_payload(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(prepared, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _group_id(official: dict[str, Any]) -> str:
    explicit = str(official.get("evidence_group") or "").strip()
    if explicit:
        return explicit
    return "|".join(
        [
            str(official.get("institution") or ""),
            str(official.get("official_product") or official.get("product") or ""),
            str(official.get("product_type") or ""),
            str(official.get("term_months") or ""),
        ]
    )


def _official_rates(items: list[dict[str, Any]], field: str) -> list[str]:
    return sorted(
        {
            str(item["official"].get(field))
            for item in items
            if item["official"].get(field) not in {None, ""}
        }
    )


def _source_support(
    items: list[dict[str, Any]],
    label: str,
    *,
    official_status: str,
) -> str:
    # 공식 evidence가 서로 충돌하면 source matching 성공/실패와 무관하게
    # authority 판정을 차단한다. not_matched가 conflict gate를 우회하면 안 된다.
    if official_status == "conflict":
        return "blocked_by_official_conflict"

    matched = [
        item["sources"][label]
        for item in items
        if item.get("sources", {}).get(label) is not None
    ]
    if not matched:
        return "not_matched"

    signals: list[str] = []
    for source in matched:
        for field in ("base_rate_comparison", "max_rate_comparison"):
            status = str(source.get(field, {}).get("status") or "")
            if status in {"agree", "mismatch"}:
                signals.append(status)

    if not signals:
        return "insufficient"
    if all(status == "agree" for status in signals):
        return "supported"
    if all(status == "mismatch" for status in signals):
        return "not_supported"
    return "partial"


def _reconciliation_signal(source_support: dict[str, str], official_status: str) -> str:
    if official_status == "conflict":
        return "official_conflict"

    primary = source_support["primary"]
    secondary = source_support["secondary"]
    if primary == "supported" and secondary == "supported":
        return "both_supported"
    if primary == "supported":
        return "primary_supported"
    if secondary == "supported":
        return "secondary_supported"
    if "partial" in {primary, secondary}:
        return "mixed_support"
    if {primary, secondary} <= {"not_matched", "insufficient"}:
        return "insufficient_official_evidence"
    return "neither_supported"


def annotate_official_evidence_policy(report: dict[str, Any]) -> dict[str, Any]:
    """official evidence group 일관성과 source 지지 신호를 report에 추가한다."""
    comparisons = report.get("official_evidence")
    if not isinstance(comparisons, list):
        comparisons = []

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in comparisons:
        if not isinstance(item, dict) or not isinstance(item.get("official"), dict):
            continue
        grouped[_group_id(item["official"])].append(item)

    groups: list[dict[str, Any]] = []
    status_counter: Counter[str] = Counter()
    signal_counter: Counter[str] = Counter()

    for group_id, items in sorted(grouped.items()):
        base_rates = _official_rates(items, "base_rate")
        max_rates = _official_rates(items, "max_rate")
        conflict_fields = []
        if len(base_rates) > 1:
            conflict_fields.append("base_rate")
        if len(max_rates) > 1:
            conflict_fields.append("max_rate")

        if conflict_fields:
            official_status = "conflict"
        elif base_rates or max_rates:
            official_status = "consistent"
        else:
            official_status = "incomplete"

        source_support = {
            label: _source_support(items, label, official_status=official_status)
            for label in ("primary", "secondary")
        }
        signal = _reconciliation_signal(source_support, official_status)
        status_counter[official_status] += 1
        signal_counter[signal] += 1

        first = items[0]["official"]
        groups.append(
            {
                "evidence_group": group_id,
                "institution": first.get("institution"),
                "official_product": first.get("official_product") or first.get("product"),
                "comparison_product": first.get("product"),
                "product_type": first.get("product_type"),
                "term_months": first.get("term_months"),
                "status": official_status,
                "conflict_fields": conflict_fields,
                "official_base_rates": base_rates,
                "official_max_rates": max_rates,
                "source_support": source_support,
                "reconciliation_signal": signal,
                "records": [
                    {
                        "evidence_id": item["official"].get("evidence_id"),
                        "evidence_kind": item["official"].get("evidence_kind"),
                        "effective_at": item["official"].get("effective_at"),
                        "captured_at": item["official"].get("captured_at"),
                        "url": item["official"].get("url"),
                        "base_rate": item["official"].get("base_rate"),
                        "max_rate": item["official"].get("max_rate"),
                    }
                    for item in items
                ],
            }
        )

    report["official_evidence_groups"] = groups
    scope = report.setdefault("scope", {})
    scope["official_evidence_authority"] = "read_only_support_only"
    scope["official_conflict_blocks_authority"] = True

    summary = report.setdefault("summary", {})
    summary["official_evidence_groups"] = len(groups)
    summary["official_evidence_consistent_groups"] = status_counter["consistent"]
    summary["official_evidence_conflicts"] = status_counter["conflict"]
    summary["official_evidence_incomplete_groups"] = status_counter["incomplete"]
    summary["official_primary_supported_groups"] = signal_counter["primary_supported"]
    summary["official_secondary_supported_groups"] = signal_counter["secondary_supported"]
    summary["official_both_supported_groups"] = signal_counter["both_supported"]
    summary["official_mixed_support_groups"] = signal_counter["mixed_support"]
    summary["official_neither_supported_groups"] = signal_counter["neither_supported"]
    return report
