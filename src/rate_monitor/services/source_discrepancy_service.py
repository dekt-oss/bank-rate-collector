"""저축은행 금리 원천 간 불일치를 read-only로 감사한다.

이 서비스는 canonical 값을 고치지 않는다. FSB를 화면의 1차 원천으로 유지한 채
DB에 보존된 finlife_savings_bank 관측과 나란히 놓고, 확실히 같은 상품/variant로
매칭되는 경우에만 금리를 비교한다. 상품명·가입채널·이자방식이 불명확한 행은
억지로 합치지 않고 매칭 불확실로 남긴다.

개별 저축은행 공식 홈페이지 증거는 수집 DB에 쓰지 않고 별도 JSON 파일로
주입할 수 있다. URL·캡처시각·기준일·surface·variant를 그대로 리포트에 보존한다.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from rate_monitor.domain.normalization import normalize_product_name
from rate_monitor.services.institution_matching import normalize_institution

CONFIRMED_RUN_STATUSES = ("success", "partial", "no_change")
DEFAULT_PRIMARY_SOURCE = "fsb"
DEFAULT_SECONDARY_SOURCE = "finlife_savings_bank"

BaseProductKey = tuple[str, str, str, int | None]
ProductKey = tuple[str, str, str, int | None, str, str]


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


def _date(value: object) -> date | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _age_days(as_of: datetime, value: object) -> int | None:
    parsed = _date(value)
    if parsed is None:
        return None
    return max((as_of.date() - parsed).days, 0)


def _facet(value: object) -> str:
    text = str(value or "").strip().lower()
    return text or "unknown"


def _is_wildcard_facet(value: str) -> bool:
    return value in {"any", "unknown"}


def _facet_relation(source_value: str, evidence_value: str) -> str:
    if source_value == evidence_value:
        return "exact"
    if _is_wildcard_facet(source_value) or _is_wildcard_facet(evidence_value):
        return "wildcard"
    return "conflict"


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
        "       pv.payment_method, "
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


def _base_product_key(row: dict[str, Any]) -> BaseProductKey:
    return (
        normalize_institution(row.get("institution")),
        normalize_product_name(str(row.get("product") or "")),
        str(row.get("product_type") or ""),
        row.get("term_months"),
    )


def _product_key(row: dict[str, Any]) -> ProductKey:
    return (
        *_base_product_key(row),
        _facet(row.get("join_channel")),
        _facet(row.get("interest_method")),
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
    """같은 source/product/term/channel/method의 중복 행 중 대표 최고금리를 고른다."""
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
) -> tuple[
    dict[ProductKey, dict[str, Any]],
    dict[ProductKey, list[dict[str, Any]]],
]:
    """6D key별 대표행과 payment-method 금리 모호성을 분리한다.

    FSB처럼 payment_method를 제공하지 않는 source와 FINLIFE처럼 정액/자유를
    구분하는 source를 비교할 때, 서로 다른 payment_method가 서로 다른 금리를
    가지면 최고금리 하나를 임의 대표로 고르지 않는다. payment_method가 달라도
    금리가 완전히 같다면 금리 감사 결론은 같으므로 비교를 허용한다.
    """
    grouped: dict[ProductKey, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_product_key(row)].append(row)

    result: dict[ProductKey, dict[str, Any]] = {}
    ambiguous: dict[ProductKey, list[dict[str, Any]]] = {}
    for key, candidates in grouped.items():
        payment_methods = {_facet(item.get("payment_method")) for item in candidates}
        rate_pairs = {
            (
                _decimal_json(_decimal(item.get("base_rate"))),
                _decimal_json(_decimal(item.get("max_rate"))),
            )
            for item in candidates
        }
        if len(payment_methods) > 1 and len(rate_pairs) > 1:
            ambiguous[key] = candidates
            continue

        representative: dict[str, Any] | None = None
        for candidate in candidates:
            representative = _prefer_representative(representative, candidate)
        if representative is not None:
            result[key] = representative
    return result, ambiguous


def _rows_by_base(
    mapping: dict[ProductKey, dict[str, Any]],
) -> dict[BaseProductKey, list[dict[str, Any]]]:
    grouped: dict[BaseProductKey, list[dict[str, Any]]] = defaultdict(list)
    for row in mapping.values():
        grouped[_base_product_key(row)].append(row)
    return grouped


def _rows_by_base_with_ambiguities(
    mapping: dict[ProductKey, dict[str, Any]],
    ambiguities: dict[ProductKey, list[dict[str, Any]]],
) -> dict[BaseProductKey, list[dict[str, Any]]]:
    """Official wildcard matching에서도 차단된 variant를 candidate에서 보존한다."""
    grouped = _rows_by_base(mapping)
    for candidates in ambiguities.values():
        for row in candidates:
            grouped[_base_product_key(row)].append(row)
    return grouped


def _freshness(row: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    return {
        "as_of": as_of.isoformat(),
        "source_effective_at": row.get("source_effective_at"),
        "last_seen_at": row.get("last_seen_at"),
        "effective_age_days": _age_days(as_of, row.get("source_effective_at")),
        "last_seen_age_days": _age_days(as_of, row.get("last_seen_at")),
        "effective_at_known": _date(row.get("source_effective_at")) is not None,
        "last_seen_at_known": _date(row.get("last_seen_at")) is not None,
    }


def _provenance(row: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    return {
        "source_id": row.get("source_id"),
        "institution": row.get("institution"),
        "product": row.get("product"),
        "product_type": row.get("product_type"),
        "term_months": row.get("term_months"),
        "join_channel": row.get("join_channel"),
        "interest_method": row.get("interest_method"),
        "payment_method": row.get("payment_method"),
        "base_rate": _decimal_json(_decimal(row.get("base_rate"))),
        "max_rate": _decimal_json(_decimal(row.get("max_rate"))),
        "source_effective_at": row.get("source_effective_at"),
        "last_seen_at": row.get("last_seen_at"),
        "freshness": _freshness(row, as_of),
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


def _candidate_variant(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "product": row.get("product"),
        "join_channel": row.get("join_channel"),
        "interest_method": row.get("interest_method"),
        "payment_method": row.get("payment_method"),
        "base_rate": _decimal_json(_decimal(row.get("base_rate"))),
        "max_rate": _decimal_json(_decimal(row.get("max_rate"))),
        "source_effective_at": row.get("source_effective_at"),
    }


def _dimension_ambiguity_record(
    key: ProductKey,
    candidates: list[dict[str, Any]],
    *,
    side: str,
    as_of: datetime,
    counterpart: dict[str, Any] | None = None,
) -> dict[str, Any]:
    first = candidates[0]
    return {
        "status": "ambiguous_variant_dimension",
        "dimension": "payment_method",
        "side": side,
        "institution": first.get("institution"),
        "product": first.get("product"),
        "product_type": first.get("product_type"),
        "term_months": key[3],
        "join_channel": key[4],
        "interest_method": key[5],
        "candidate_payment_methods": sorted(
            {_facet(item.get("payment_method")) for item in candidates}
        ),
        "candidate_variants": [_candidate_variant(item) for item in candidates],
        "provenance": [_provenance(item, as_of) for item in candidates],
        "counterpart_side": "secondary" if side == "primary" else "primary",
        "counterpart": _provenance(counterpart, as_of) if counterpart is not None else None,
        "reason": (
            "same 6D source key has multiple payment_method values with different rates; "
            "rate comparison is blocked instead of selecting the highest representative"
        ),
    }


def _source_only_record(
    row: dict[str, Any],
    *,
    side: str,
    opposite_by_base: dict[BaseProductKey, list[dict[str, Any]]],
    opposite_by_broad: dict[tuple[str, str, int | None], list[dict[str, Any]]],
    as_of: datetime,
) -> dict[str, Any]:
    variant_candidates = opposite_by_base.get(_base_product_key(row), [])
    broad_candidates = opposite_by_broad.get(_broad_key(row), [])
    if variant_candidates:
        status = "unmatched_variant"
    elif broad_candidates:
        status = "unmatched_product"
    else:
        status = "source_only"
    return {
        "status": status,
        "side": side,
        "record": _provenance(row, as_of),
        "candidate_products": sorted({str(item.get("product") or "") for item in broad_candidates}),
        "candidate_variants": [_candidate_variant(item) for item in variant_candidates],
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


def _evidence_base_key(record: dict[str, Any]) -> BaseProductKey:
    return (
        normalize_institution(record.get("institution")),
        normalize_product_name(str(record.get("product") or "")),
        str(record.get("product_type") or ""),
        int(record.get("term_months")) if record.get("term_months") is not None else None,
    )


def _select_official_candidate(
    record: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    evidence_channel = _facet(record.get("join_channel"))
    evidence_method = _facet(record.get("interest_method"))
    compatible: list[tuple[int, dict[str, Any], dict[str, str]]] = []

    for candidate in candidates:
        source_channel = _facet(candidate.get("join_channel"))
        source_method = _facet(candidate.get("interest_method"))
        channel_relation = _facet_relation(source_channel, evidence_channel)
        method_relation = _facet_relation(source_method, evidence_method)
        if "conflict" in {channel_relation, method_relation}:
            continue
        score = int(channel_relation == "exact") + int(method_relation == "exact")
        compatible.append(
            (
                score,
                candidate,
                {
                    "join_channel": channel_relation,
                    "interest_method": method_relation,
                },
            )
        )

    compatible.sort(key=lambda item: item[0], reverse=True)
    if not compatible:
        return None, {
            "status": "no_compatible_variant",
            "evidence_join_channel": evidence_channel,
            "evidence_interest_method": evidence_method,
            "candidate_variants": [_candidate_variant(item) for item in candidates],
        }

    best_score = compatible[0][0]
    best = [item for item in compatible if item[0] == best_score]
    if len(best) != 1:
        return None, {
            "status": "ambiguous_variant",
            "evidence_join_channel": evidence_channel,
            "evidence_interest_method": evidence_method,
            "candidate_variants": [_candidate_variant(item[1]) for item in best],
        }

    _, matched, relations = best[0]
    mode = (
        "exact_variant"
        if all(value == "exact" for value in relations.values())
        else "unambiguous_wildcard"
    )
    return matched, {
        "status": "matched",
        "mode": mode,
        "relations": relations,
        "evidence_join_channel": evidence_channel,
        "evidence_interest_method": evidence_method,
        "source_join_channel": _facet(matched.get("join_channel")),
        "source_interest_method": _facet(matched.get("interest_method")),
    }


def _compare_official_evidence(
    evidence: list[dict[str, Any]],
    primary_by_base: dict[BaseProductKey, list[dict[str, Any]]],
    secondary_by_base: dict[BaseProductKey, list[dict[str, Any]]],
    as_of: datetime,
) -> list[dict[str, Any]]:
    result = []
    for record in evidence:
        key = _evidence_base_key(record)
        sources: dict[str, Any] = {}
        variant_matching: dict[str, Any] = {}
        for label, mapping in (
            ("primary", primary_by_base),
            ("secondary", secondary_by_base),
        ):
            matched, match_meta = _select_official_candidate(record, mapping.get(key, []))
            variant_matching[label] = match_meta
            if matched is None:
                sources[label] = None
                continue
            sources[label] = {
                "record": _provenance(matched, as_of),
                "variant_match": match_meta,
                "base_rate_comparison": _rate_comparison(
                    matched.get("base_rate"), record.get("base_rate")
                ),
                "max_rate_comparison": _rate_comparison(
                    matched.get("max_rate"), record.get("max_rate")
                ),
            }
        result.append(
            {
                "official": record,
                "variant_matching": variant_matching,
                "sources": sources,
            }
        )
    return result


def build_source_discrepancy_report(
    db_path: Path,
    *,
    primary_source: str = DEFAULT_PRIMARY_SOURCE,
    secondary_source: str = DEFAULT_SECONDARY_SOURCE,
    official_evidence_path: Path | None = None,
) -> dict[str, Any]:
    """현재 확인된 두 저축은행 원천을 variant-aware 방식으로 비교한다."""
    generated_at = datetime.now(UTC)
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

    primary, primary_ambiguous = _representatives(by_source.get(primary_source, []))
    secondary, secondary_ambiguous = _representatives(by_source.get(secondary_source, []))
    primary_by_base = _rows_by_base(primary)
    secondary_by_base = _rows_by_base(secondary)
    primary_official_by_base = _rows_by_base_with_ambiguities(primary, primary_ambiguous)
    secondary_official_by_base = _rows_by_base_with_ambiguities(secondary, secondary_ambiguous)
    dimension_ambiguities = [
        *(
            _dimension_ambiguity_record(
                key,
                candidates,
                side="primary",
                as_of=generated_at,
                counterpart=secondary.get(key),
            )
            for key, candidates in primary_ambiguous.items()
        ),
        *(
            _dimension_ambiguity_record(
                key,
                candidates,
                side="secondary",
                as_of=generated_at,
                counterpart=primary.get(key),
            )
            for key, candidates in secondary_ambiguous.items()
        ),
    ]

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
                    "join_channel": key[4],
                    "interest_method": key[5],
                    "method": (
                        "normalized_institution+normalized_product+type+term"
                        "+join_channel+interest_method"
                    ),
                },
                "primary": _provenance(left, generated_at),
                "secondary": _provenance(right, generated_at),
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
            _source_only_record(
                row,
                side="primary",
                opposite_by_base=secondary_by_base,
                opposite_by_broad=secondary_broad,
                as_of=generated_at,
            )
            for key, row in primary.items()
            if key not in secondary and key not in secondary_ambiguous
        ),
        *(
            _source_only_record(
                row,
                side="secondary",
                opposite_by_base=primary_by_base,
                opposite_by_broad=primary_broad,
                as_of=generated_at,
            )
            for key, row in secondary.items()
            if key not in primary and key not in primary_ambiguous
        ),
    ]
    source_only_counter = Counter(item["status"] for item in source_only)

    evidence = _load_official_evidence(official_evidence_path)
    evidence_comparisons = _compare_official_evidence(
        evidence,
        primary_official_by_base,
        secondary_official_by_base,
        generated_at,
    )

    mismatch_names = (
        "rate_mismatch",
        "rate_mismatch_date_diff",
        "rate_mismatch_date_unknown",
        "incomplete_rate",
    )
    mismatch_count = sum(status_counter[name] for name in mismatch_names)
    return {
        "generated_at": generated_at.isoformat(),
        "scope": {
            "sector": "savings_bank",
            "primary_source": primary_source,
            "secondary_source": secondary_source,
            "canonical_mutated": False,
            "automatic_match_method": (
                "normalized institution + exact normalized product + product type + term "
                "+ join_channel + interest_method"
            ),
            "variant_unknown_policy": (
                "source-to-source requires exact stored facet; official evidence may use "
                "only a unique non-conflicting wildcard candidate"
            ),
            "dimension_ambiguity_policy": (
                "if one source has multiple payment_method values with different rates under "
                "the same 6D key, block rate comparison; never select the highest rate"
            ),
            "freshness_metadata_policy": "observational_only; never_selects_source_authority",
            "unmatched_policy": "do_not_guess",
        },
        "source_runs": runs,
        "summary": {
            "primary_products": len(primary) + len(primary_ambiguous),
            "secondary_products": len(secondary) + len(secondary_ambiguous),
            "comparable_primary_products": len(primary),
            "comparable_secondary_products": len(secondary),
            "ambiguous_variant_dimension": len(dimension_ambiguities),
            "ambiguous_payment_method": sum(
                item["dimension"] == "payment_method" for item in dimension_ambiguities
            ),
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
            "unmatched_variant": source_only_counter["unmatched_variant"],
            "unmatched_product": source_only_counter["unmatched_product"],
            "source_only": source_only_counter["source_only"],
            "official_evidence_records": len(evidence),
        },
        "matches": matches,
        "dimension_ambiguities": dimension_ambiguities,
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
