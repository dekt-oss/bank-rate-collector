"""공식 금융사 evidence와 중앙 원천의 모순을 read-only로 우선순위화한다.

FSB와 FINLIFE가 서로 일치해 일반 mismatch queue에는 잡히지 않더라도 개별 저축은행
공식 공시가 양쪽을 모두 부정할 수 있다. 이 모듈은 그런 silent consensus contradiction과
공식 evidence 내부 충돌을 별도 queue로 노출한다. canonical 값이나 source authority는
절대 변경하지 않는다.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from rate_monitor.domain.normalization import normalize_product_name
from rate_monitor.services.institution_matching import normalize_institution

OFFICIAL_CONTRADICTION_POLICY_VERSION = "2026-08-20-v1"
ACTIONABLE_SIGNALS = {"official_conflict", "neither_supported", "mixed_support"}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _decimal(value: object) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _key(
    institution: object,
    product: object,
    product_type: object,
    term_months: object,
) -> tuple[str, str, str, int | None]:
    term = None if term_months in {None, ""} else int(term_months)
    return (
        normalize_institution(institution),
        normalize_product_name(str(product or "")),
        str(product_type or ""),
        term,
    )


def _matches_by_key(
    report: dict[str, Any],
) -> dict[tuple[str, str, str, int | None], dict[str, Any]]:
    result: dict[tuple[str, str, str, int | None], dict[str, Any]] = {}
    for match in report.get("matches", []):
        if not isinstance(match, dict):
            continue
        primary = match.get("primary") if isinstance(match.get("primary"), dict) else {}
        secondary = match.get("secondary") if isinstance(match.get("secondary"), dict) else {}
        key = _key(
            primary.get("institution") or secondary.get("institution"),
            primary.get("product") or secondary.get("product"),
            primary.get("product_type") or secondary.get("product_type"),
            (
                primary.get("term_months")
                if primary.get("term_months") is not None
                else secondary.get("term_months")
            ),
        )
        result[key] = match
    return result


def _classification(signal: str, match_status: str | None) -> str:
    if signal == "official_conflict":
        return "official_internal_conflict"
    if signal == "neither_supported" and match_status in {
        "agree",
        "agree_rate_date_diff",
        "agree_rate_date_unknown",
    }:
        return "source_consensus_official_contradiction"
    if signal == "neither_supported":
        return "official_rejects_both_sources"
    return "official_partial_contradiction"


def _score(signal: str, classification: str) -> int:
    if classification == "source_consensus_official_contradiction":
        return 100
    if signal == "official_conflict":
        return 95
    if signal == "neither_supported":
        return 90
    return 70


def _priority(signal: str) -> str:
    if signal in {"official_conflict", "neither_supported"}:
        return "P0"
    return "P1"


def _suggested_action(signal: str, classification: str) -> str:
    if classification == "source_consensus_official_contradiction":
        return (
            "중앙 두 원천이 서로 일치해도 공식 공시와 모순된다. FSB/FINLIFE raw payload의 "
            "상품·채널·이자방식·기준일을 공식 공시와 함께 재검증한다."
        )
    if signal == "official_conflict":
        return "공식 상품공시와 시행 공지 중 어떤 값이 현재 적용되는지 적용범위·시행일을 확인한다."
    if signal == "neither_supported":
        return "공식 공시가 양 중앙 원천을 모두 지지하지 않으므로 양쪽 raw evidence를 재검증한다."
    return "공식 evidence가 부분적으로만 일치하므로 필드·상품 variant·기준일을 재검증한다."


def _source_pair(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(match, dict):
        return None
    primary = match.get("primary") if isinstance(match.get("primary"), dict) else {}
    secondary = match.get("secondary") if isinstance(match.get("secondary"), dict) else {}
    max_cmp = match.get("max_rate_comparison")
    if not isinstance(max_cmp, dict):
        max_cmp = {}
    base_cmp = match.get("base_rate_comparison")
    if not isinstance(base_cmp, dict):
        base_cmp = {}
    return {
        "status": match.get("status"),
        "effective_date_status": match.get("effective_date_status"),
        "max_rate_comparison": {
            "status": max_cmp.get("status"),
            "primary": max_cmp.get("primary"),
            "secondary": max_cmp.get("secondary"),
            "delta_primary_minus_secondary": max_cmp.get("delta_primary_minus_secondary"),
        },
        "base_rate_comparison": {
            "status": base_cmp.get("status"),
            "primary": base_cmp.get("primary"),
            "secondary": base_cmp.get("secondary"),
            "delta_primary_minus_secondary": base_cmp.get("delta_primary_minus_secondary"),
        },
        "effective_date": {
            "primary": primary.get("source_effective_at"),
            "secondary": secondary.get("source_effective_at"),
        },
        "provenance": {
            "primary_source_id": primary.get("source_id"),
            "secondary_source_id": secondary.get("source_id"),
            "primary_raw_artifact_path": primary.get("raw_artifact_path"),
            "secondary_raw_artifact_path": secondary.get("raw_artifact_path"),
            "primary_source_locator": primary.get("base_source_locator"),
            "secondary_source_locator": secondary.get("base_source_locator"),
        },
    }


def annotate_official_contradictions(report: dict[str, Any]) -> dict[str, Any]:
    """Actionable official-evidence contradictions를 별도 deterministic queue로 만든다."""
    matches_by_key = _matches_by_key(report)
    queue: list[dict[str, Any]] = []

    for group in report.get("official_evidence_groups", []):
        if not isinstance(group, dict):
            continue
        signal = str(group.get("reconciliation_signal") or "")
        if signal not in ACTIONABLE_SIGNALS:
            continue

        comparison_product = group.get("comparison_product") or group.get("official_product")
        key = _key(
            group.get("institution"),
            comparison_product,
            group.get("product_type"),
            group.get("term_months"),
        )
        match = matches_by_key.get(key)
        match_status = str(match.get("status") or "") if isinstance(match, dict) else None
        classification = _classification(signal, match_status)
        score = _score(signal, classification)
        source_pair = _source_pair(match)

        official_max_rates = [str(value) for value in group.get("official_max_rates", [])]
        official_base_rates = [str(value) for value in group.get("official_base_rates", [])]
        official_max = (
            _decimal(official_max_rates[0]) if len(official_max_rates) == 1 else None
        )
        source_max = None
        if source_pair is not None:
            max_cmp = source_pair["max_rate_comparison"]
            primary_max = _decimal(max_cmp.get("primary"))
            secondary_max = _decimal(max_cmp.get("secondary"))
            if primary_max is not None and primary_max == secondary_max:
                source_max = primary_max

        consensus_official_delta = (
            abs(source_max - official_max)
            if source_max is not None and official_max is not None
            else None
        )

        queue.append(
            {
                "rank": None,
                "priority": _priority(signal),
                "score": score,
                "classification": classification,
                "evidence_group": group.get("evidence_group"),
                "institution": group.get("institution"),
                "official_product": group.get("official_product"),
                "comparison_product": comparison_product,
                "product_type": group.get("product_type"),
                "term_months": group.get("term_months"),
                "official_status": group.get("status"),
                "reconciliation_signal": signal,
                "source_support": group.get("source_support"),
                "official_base_rates": official_base_rates,
                "official_max_rates": official_max_rates,
                "source_pair": source_pair,
                "source_consensus_max_rate": (
                    format(source_max, "f") if source_max is not None else None
                ),
                "consensus_official_absolute_delta": (
                    format(consensus_official_delta, "f")
                    if consensus_official_delta is not None
                    else None
                ),
                "evidence_records": group.get("records", []),
                "suggested_action": _suggested_action(signal, classification),
            }
        )

    queue.sort(
        key=lambda item: (
            PRIORITY_ORDER[str(item["priority"])],
            -int(item["score"]),
            -(
                _decimal(item["consensus_official_absolute_delta"])
                or Decimal("0")
            ),
            str(item["institution"] or ""),
            str(item["official_product"] or ""),
            int(item["term_months"] or 0),
        )
    )
    for rank, item in enumerate(queue, start=1):
        item["rank"] = rank

    priorities = Counter(str(item["priority"]) for item in queue)
    classifications = Counter(str(item["classification"]) for item in queue)
    report["official_contradictions"] = {
        "policy_version": OFFICIAL_CONTRADICTION_POLICY_VERSION,
        "scope": "official_evidence_groups_with_actionable_contradiction",
        "authority_semantics": (
            "investigation_priority_only; official evidence never overwrites canonical values"
        ),
        "summary": {
            "queue_size": len(queue),
            "P0": priorities["P0"],
            "P1": priorities["P1"],
            "P2": priorities["P2"],
            "P3": priorities["P3"],
            "source_consensus_contradictions": classifications[
                "source_consensus_official_contradiction"
            ],
            "classifications": dict(sorted(classifications.items())),
        },
        "queue": queue,
    }
    report.setdefault("summary", {})["official_contradiction_queue_size"] = len(queue)
    scope = report.setdefault("scope", {})
    scope["official_contradiction_mutates_canonical"] = False
    scope["official_contradiction_selects_authority"] = False
    return report
