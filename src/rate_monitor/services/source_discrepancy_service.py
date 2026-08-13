"""저축은행 금리 원천 간 불일치를 read-only로 감사한다.

이 서비스는 canonical 값을 고치지 않는다. FSB를 화면의 1차 원천으로 유지한 채
DB에 보존된 finlife_savings_bank 관측과 나란히 놓고, 확실히 같은 상품으로
매칭되는 경우에만 금리를 비교한다. 상품명이 안 붙는 행은 억지로 합치지 않고
매칭 불확실로 남긴다.

개별 저축은행 공식 홈페이지 증거는 수집 DB에 쓰지 않고 별도 JSON 파일로
주입할 수 있다. URL·캡처시각·기준일을 그대로 리포트에 보존한다.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from rate_monitor.domain.normalization import normalize_product_name
from rate_monitor.services.institution_matching import normalize_institution

CONFIRMED_RUN_STATUSES = ("success", "partial", "no_change")
DEFAULT_PRIMARY_SOURCE = "fsb"
DEFAULT_SECONDARY_SOURCE = "finlife_savings_bank"


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_json(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _rate_comparison(primary: object, secondary: object) -> dict[str, str | None]:
    left = _decimal(primary)
    right = _decimal(secondary)
    if left is None and right is None:
        status = "both_missing"
        delta = None
    elif left is None or right is None:
        status = "incomplete"
        delta = None
    else:
        delta = left - right
        status = "agree" if delta == 0 else "mismatch"
    return {
        "status": status,
        "primary": _decimal_json(left),
        "secondary": _decimal_json(right),
        "delta_primary_minus_secondary": _decimal_json(delta),
    }


def _latest_confirmed_runs(
    conn: sqlite3.Connection, source_ids: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    placeholders = ",".join("?" for _ in CONFIRMED_RUN_STATUSES)
    for source_id in source_ids:
        row = conn.execute(
            "SELECT id, source_id, started_at, finished_at, status "
            "FROM collection_runs "
            "WHERE source_id = ? "
            f"AND status IN ({placeholders}) "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            (source_id, *CONFIRMED_RUN_STATUSES),
        ).fetchone()
        if row is not None:
            runs[source_id] = dict(row)
    return runs


def _current_source_rows(
    conn: sqlite3.Connection, run_ids: Iterable[str]
) -> list[dict[str, Any]]:
    run_ids = tuple(run_ids)
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    cursor = conn.execute(
        "SELECT lr.source_id, o.id AS observation_id, o.run_id, o.last_run_id, "
        "       i.canonical_name AS institution, p.name AS product, "
        "       p.product_type, pv.term_months, pv.join_channel, pv.interest_method, "
        "       o.base_rate, o.max_rate, o.source_effective_at, o.last_seen_at, "
        "       o.base_source_locator, o.option_source_locator, o.source_record_hash, "
        "       ra.relative_path AS raw_artifact_path, ra.sha256 AS raw_artifact_sha256 "
        "FROM rate_observations o "
        "JOIN collection_runs lr ON lr.id = o.last_run_id "
        "JOIN product_variants pv ON pv.id = o.variant_id "
        "JOIN products p ON p.id = pv.product_id "
        "JOIN institutions i ON i.id = p.institution_id "
        "JOIN raw_artifacts ra ON ra.id = o.raw_artifact_id "
        f"WHERE o.last_run_id IN ({placeholders}) "
        "  AND o.validation_status = 'valid' "
        "  AND o.valid_to IS NULL "
        "  AND i.sector = 'savings_bank'",
        run_ids,
    )
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _product_key(row: dict[str, Any]) -> tuple[str, str, str, int | None]:
    return (
        normalize_institution(row.get("institution")),
        normalize_product_name(str(row.get("product") or "")),
        str(row.get("product_type") or ""),
        row.get("term_months"),
    )


def _broad_key(row: dict[str, Any]) -> tuple[str, str, int | None]:
    return (
        normalize_institution(row.get("institution")),
        str(row.get("product_type") or ""),
        row.get("term_months"),
    )


def _prefer_representative(
    current: dict[str, Any] | None, candidate: dict[str, Any]
) -> dict[str, Any]:
    """같은 source/product/term의 variant 중 대표 최고금리 행을 고른다."""
    if current is None:
        return candidate
    current_rate = _decimal(current.get("max_rate"))
    candidate_rate = _decimal(candidate.get("max_rate"))
    if candidate_rate is not None and (
        current_rate is None or candidate_rate > current_rate
    ):
        return candidate
    if current_rate is not None and candidate_rate is None:
        return current
    if current_rate == candidate_rate:
        current_effective = str(current.get("source_effective_at") or "")
        candidate_effective = str(candidate.get("source_effective_at") or "")
        if candidate_effective > current_effective:
            return candidate
    return current


def _representatives(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str, str, int | None], dict[str, Any]]:
    result: dict[tuple[str, str, str, int | None], dict[str, Any]] = {}
    for row in rows:
        key = _product_key(row)
        result[key] = _prefer_representative(result.get(key), row)
    return result


def _provenance(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row.get("source_id"),
        "institution": row.get("institution"),
        "product": row.get("product"),
        "product_type": row.get("product_type"),
        "term_months": row.get("term_months"),
        "join_channel": row.get("join_channel"),
        "interest_method": row.get("interest_method"),
        "base_rate": _decimal_json(_decimal(row.get("base_rate"))),
        "max_rate": _decimal_json(_decimal(row.get("max_rate"))),
        "source_effective_at": row.get("source_effective_at"),
        "last_seen_at": row.get("last_seen_at"),
        "run_id": row.get("run_id"),
        "last_run_id": row.get("last_run_id"),
        "observation_id": row.get("observation_id"),
        "base_source_locator": row.get("base_source_locator"),
        "option_source_locator": row.get("option_source_locator"),
        "source_record_hash": row.get("source_record_hash"),
        "raw_artifact_path": row.get("raw_artifact_path"),
        "raw_artifact_sha256": row.get("raw_artifact_sha256"),
    }


def _classify_pair(
    primary: dict[str, Any], secondary: dict[str, Any]
) -> tuple[str, str, dict[str, str | None], dict[str, str | None]]:
    base_comparison = _rate_comparison(primary.get("base_rate"), secondary.get("base_rate"))
    max_comparison = _rate_comparison(primary.get("max_rate"), secondary.get("max_rate"))

    left_date = str(primary.get("source_effective_at") or "")
    right_date = str(secondary.get("source_effective_at") or "")
    if not left_date or not right_date:
        date_status = "unknown"
    elif left_date == right_date:
        date_status = "same"
    else:
        date_status = "different"

    max_status = max_comparison["status"]
    if max_status in {"incomplete", "both_missing"}:
        status = "incomplete_rate"
    elif max_status == "agree":
        if date_status == "different":
            status = "agree_rate_date_diff"
        elif date_status == "unknown":
            status = "agree_rate_date_unknown"
        else:
            status = "agree"
    elif date_status == "different":
        status = "rate_mismatch_date_diff"
    elif date_status == "unknown":
        status = "rate_mismatch_date_unknown"
    else:
        status = "rate_mismatch"
    return status, date_status, base_comparison, max_comparison


def _source_only_record(
    row: dict[str, Any],
    *,
    side: str,
    opposite_by_broad: dict[tuple[str, str, int | None], list[dict[str, Any]]],
) -> dict[str, Any]:
    candidates = opposite_by_broad.get(_broad_key(row), [])
    return {
        "status": "unmatched_product" if candidates else "source_only",
        "side": side,
        "record": _provenance(row),
        "candidate_products": sorted({str(item.get("product") or "") for item in candidates}),
    }


def _load_official_evidence(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("official evidence JSON은 배열 또는 {records:[...]} 형식이어야 한다")
    required = {
        "institution",
        "product",
        "product_type",
        "term_months",
        "captured_at",
        "url",
    }
    result: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"official evidence records[{index}]는 객체여야 한다")
        missing = sorted(required - set(record))
        if missing:
            detail = ", ".join(missing)
            raise ValueError(f"official evidence records[{index}] 필수값 없음: {detail}")
        cleaned = dict(record)
        cleaned["term_months"] = int(cleaned["term_months"])
        cleaned["base_rate"] = _decimal_json(_decimal(cleaned.get("base_rate")))
        cleaned["max_rate"] = _decimal_json(_decimal(cleaned.get("max_rate")))
        result.append(cleaned)
    return result


def _evidence_key(record: dict[str, Any]) -> tuple[str, str, str, int | None]:
    return (
        normalize_institution(record.get("institution")),
        normalize_product_name(str(record.get("product") or "")),
        str(record.get("product_type") or ""),
        int(record.get("term_months")) if record.get("term_months") is not None else None,
    )


def _compare_official_evidence(
    evidence: list[dict[str, Any]],
    primary: dict[tuple[str, str, str, int | None], dict[str, Any]],
    secondary: dict[tuple[str, str, str, int | None], dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for record in evidence:
        key = _evidence_key(record)
        sources: dict[str, Any] = {}
        for label, mapping in (("primary", primary), ("secondary", secondary)):
            matched = mapping.get(key)
            if matched is None:
                sources[label] = None
                continue
            sources[label] = {
                "record": _provenance(matched),
                "base_rate_comparison": _rate_comparison(
                    matched.get("base_rate"), record.get("base_rate")
                ),
                "max_rate_comparison": _rate_comparison(
                    matched.get("max_rate"), record.get("max_rate")
                ),
            }
        result.append({"official": record, "sources": sources})
    return result


def build_source_discrepancy_report(
    db_path: Path,
    *,
    primary_source: str = DEFAULT_PRIMARY_SOURCE,
    secondary_source: str = DEFAULT_SECONDARY_SOURCE,
    official_evidence_path: Path | None = None,
) -> dict[str, Any]:
    """현재 확인된 두 저축은행 원천을 비교해 JSON 직렬화 가능한 리포트를 만든다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        source_ids = (primary_source, secondary_source)
        runs = _latest_confirmed_runs(conn, source_ids)
        rows = _current_source_rows(conn, [item["id"] for item in runs.values()])
    finally:
        conn.close()

    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_source[str(row["source_id"])].append(row)
    primary = _representatives(by_source.get(primary_source, []))
    secondary = _representatives(by_source.get(secondary_source, []))

    matches = []
    status_counter: Counter[str] = Counter()
    base_status_counter: Counter[str] = Counter()
    for key in sorted(primary.keys() & secondary.keys(), key=str):
        left, right = primary[key], secondary[key]
        status, date_status, base_comparison, max_comparison = _classify_pair(left, right)
        status_counter[status] += 1
        base_status_counter[str(base_comparison["status"])] += 1
        matches.append(
            {
                "status": status,
                "effective_date_status": date_status,
                "delta_max_rate_primary_minus_secondary": max_comparison[
                    "delta_primary_minus_secondary"
                ],
                "base_rate_comparison": base_comparison,
                "max_rate_comparison": max_comparison,
                "match": {
                    "institution_key": key[0],
                    "product_key": key[1],
                    "product_type": key[2],
                    "term_months": key[3],
                    "method": "normalized_institution+normalized_product+type+term",
                },
                "primary": _provenance(left),
                "secondary": _provenance(right),
            }
        )

    primary_broad: dict[tuple[str, str, int | None], list[dict[str, Any]]] = defaultdict(list)
    secondary_broad: dict[tuple[str, str, int | None], list[dict[str, Any]]] = defaultdict(list)
    for row in primary.values():
        primary_broad[_broad_key(row)].append(row)
    for row in secondary.values():
        secondary_broad[_broad_key(row)].append(row)

    source_only = [
        *(
            _source_only_record(row, side="primary", opposite_by_broad=secondary_broad)
            for key, row in primary.items()
            if key not in secondary
        ),
        *(
            _source_only_record(row, side="secondary", opposite_by_broad=primary_broad)
            for key, row in secondary.items()
            if key not in primary
        ),
    ]
    source_only_counter = Counter(item["status"] for item in source_only)

    evidence = _load_official_evidence(official_evidence_path)
    evidence_comparisons = _compare_official_evidence(evidence, primary, secondary)

    mismatch_names = (
        "rate_mismatch",
        "rate_mismatch_date_diff",
        "rate_mismatch_date_unknown",
        "incomplete_rate",
    )
    mismatch_count = sum(status_counter[name] for name in mismatch_names)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "sector": "savings_bank",
            "primary_source": primary_source,
            "secondary_source": secondary_source,
            "canonical_mutated": False,
            "automatic_match_method": (
                "normalized institution + exact normalized product + product type + term"
            ),
            "unmatched_policy": "do_not_guess",
        },
        "source_runs": runs,
        "summary": {
            "primary_products": len(primary),
            "secondary_products": len(secondary),
            "exact_matches": len(matches),
            "agree": status_counter["agree"],
            "agree_rate_date_diff": status_counter["agree_rate_date_diff"],
            "agree_rate_date_unknown": status_counter["agree_rate_date_unknown"],
            "rate_mismatch": status_counter["rate_mismatch"],
            "rate_mismatch_date_diff": status_counter["rate_mismatch_date_diff"],
            "rate_mismatch_date_unknown": status_counter["rate_mismatch_date_unknown"],
            "incomplete_rate": status_counter["incomplete_rate"],
            "mismatch_or_incomplete": mismatch_count,
            "base_rate_agree": base_status_counter["agree"],
            "base_rate_mismatch": base_status_counter["mismatch"],
            "base_rate_incomplete": base_status_counter["incomplete"],
            "base_rate_both_missing": base_status_counter["both_missing"],
            "unmatched_product": source_only_counter["unmatched_product"],
            "source_only": source_only_counter["source_only"],
            "official_evidence_records": len(evidence),
        },
        "matches": matches,
        "source_only": source_only,
        "official_evidence": evidence_comparisons,
    }


def write_source_discrepancy_report(
    db_path: Path,
    out_path: Path,
    *,
    primary_source: str = DEFAULT_PRIMARY_SOURCE,
    secondary_source: str = DEFAULT_SECONDARY_SOURCE,
    official_evidence_path: Path | None = None,
) -> dict[str, Any]:
    report = build_source_discrepancy_report(
        db_path,
        primary_source=primary_source,
        secondary_source=secondary_source,
        official_evidence_path=official_evidence_path,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return report
