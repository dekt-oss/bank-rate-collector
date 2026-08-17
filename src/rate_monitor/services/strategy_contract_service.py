"""전략 화면 전용 stable product identity / universe 계약.

공식 검색 화면의 발행 계약은 그대로 두고, 전략 Release Gate가 켜진 빌드에서만
canonical table에서 전략 비교군을 필터한 뒤 ``product_id``를 덧붙인다. 전략 화면은
이 stable id로 상품 대표값을 묶는다. 표현 계층은 ``web/templates/strategy.html``이
직접 소유한다. Stage A 이후 이 모듈은 HTML 표현 치환을 수행하지 않는다.

Stage H1부터 전략 후보 업권은 저축은행·신협·새마을금고·농축협으로 확장하지만,
실제 strategy payload에는 공식 최고금리 계약이 증명된 업권만 싣는다. 최고금리
미지원 업권은 행을 억지로 싣거나 ``base_rate``로 대체하지 않고 universe metadata에
coverage와 차단 사유를 남긴다.
"""

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.services.dashboard_service import DashboardBuildError

PRODUCT_ID_COLUMN = "product_id"
STRATEGY_SECTOR = "savings_bank"  # 기존 caller 호환용 기본 업권
STRATEGY_PRODUCT_TYPE = "term_deposit"
STRATEGY_TERMS = frozenset({6, 12, 24, 36})
STRATEGY_CANDIDATE_SECTORS = ("savings_bank", "cu", "kfcc", "nh_local")
STRATEGY_MAX_RATE_ENABLED_SECTORS = frozenset({"savings_bank", "cu", "nh_local"})
STRATEGY_MAX_ONLY_PUBLISHED_SECTORS = frozenset({"nh_local"})
STRATEGY_SECTOR_LABELS = {
    "savings_bank": "저축은행",
    "cu": "신협",
    "kfcc": "새마을금고",
    "nh_local": "농·축협",
}
STRATEGY_MAX_RATE_EVIDENCE = {
    "savings_bank": "existing_savings_bank_max_rate_contract",
    "cu": "official_high_rate_same_product_term_institution",
    "kfcc": "individual_official_max_rate_exists_but_registry_linkage_unproven",
    "nh_local": "official_ejoy_same_brc_product_term_interval_internet_variant",
}
STRATEGY_BLOCK_REASONS = {
    "kfcc": (
        "중앙 공시는 기본이율 중심이며 개별 금고 공식 최고금리 페이지와 "
        "gmgo_cd의 전국 결정론적 연결이 아직 증명되지 않음"
    ),
}
_IDENTITY_KEY_COLUMNS = (
    "source_id",
    "institution",
    "product",
    "product_type",
    "term_months",
    "payment_method",
    "interest_method",
    "join_channel",
)


def _decode(table: dict[str, Any], column: str, value: Any) -> Any:
    lookup = (table.get("lookups") or {}).get(column)
    if lookup is None or value is None:
        return value
    return lookup[value]


def _row_key(table: dict[str, Any], row: list[Any]) -> tuple[Any, ...]:
    columns = {name: index for index, name in enumerate(table.get("columns") or [])}
    return tuple(
        _decode(table, name, row[columns[name]]) for name in _IDENTITY_KEY_COLUMNS
    )


def _rate_present(value: Any) -> bool:
    if value is None or value == "":
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _sorted_decoded_values(
    table: dict[str, Any],
    rows: list[list[Any]],
    source_columns: dict[str, int],
    column: str,
) -> list[str]:
    index = source_columns.get(column)
    if index is None:
        return []
    values = {
        str(value)
        for row in rows
        if (value := _decode(table, column, row[index])) not in (None, "")
    }
    return sorted(values)


def strategy_universe_metadata(table: dict[str, Any]) -> dict[str, Any]:
    """후보 업권의 최고금리 capability/coverage를 strategy contract로 만든다.

    metadata는 **전체 canonical table을 읽어 계산**하지만 실제 strategy payload에
    unsupported 업권 행을 포함시키지는 않는다. 따라서 KFCC/NH의 0% ``max_rate``를
    저축은행/CU 최고금리와 섞지 않으면서도 UI가 왜 disabled인지 설명할 수 있다.
    """
    columns = list(table.get("columns") or [])
    source_columns = {name: index for index, name in enumerate(columns)}
    required = {"sector", "product_type", "term_months"}
    missing = sorted(required.difference(source_columns))
    if missing:
        raise DashboardBuildError(
            "전략 universe에 필요한 table 열이 없다: " + ", ".join(missing)
        )

    by_sector: dict[str, list[list[Any]]] = {
        sector: [] for sector in STRATEGY_CANDIDATE_SECTORS
    }
    for row in table.get("rows") or []:
        sector = _decode(table, "sector", row[source_columns["sector"]])
        if sector not in by_sector:
            continue
        product_type = _decode(
            table, "product_type", row[source_columns["product_type"]]
        )
        term = row[source_columns["term_months"]]
        if product_type == STRATEGY_PRODUCT_TYPE and term in STRATEGY_TERMS:
            by_sector[sector].append(row)

    max_index = source_columns.get("max_rate")
    effective_index = source_columns.get("source_effective_at")
    sectors: dict[str, dict[str, Any]] = {}

    for sector in STRATEGY_CANDIDATE_SECTORS:
        rows = by_sector[sector]
        max_rows = (
            sum(_rate_present(row[max_index]) for row in rows)
            if max_index is not None
            else 0
        )
        capability = sector in STRATEGY_MAX_RATE_ENABLED_SECTORS
        selectable = capability and max_rows > 0
        latest_effective_at = None
        if effective_index is not None:
            effective_values = [
                str(value)
                for row in rows
                if (value := _decode(table, "source_effective_at", row[effective_index]))
                not in (None, "")
            ]
            if effective_values:
                latest_effective_at = max(effective_values)

        terms: dict[str, dict[str, Any]] = {}
        for term in sorted(STRATEGY_TERMS):
            term_rows = [row for row in rows if row[source_columns["term_months"]] == term]
            term_max_rows = (
                sum(_rate_present(row[max_index]) for row in term_rows)
                if max_index is not None
                else 0
            )
            terms[str(term)] = {
                "rows": len(term_rows),
                "max_rate_rows": term_max_rows,
                "coverage_ratio": (
                    round(term_max_rows / len(term_rows), 6) if term_rows else None
                ),
                "selectable": capability and term_max_rows > 0,
            }

        if not capability:
            state = "unsupported"
        elif not rows:
            state = "no_rows"
        elif not max_rows:
            state = "no_max_rate_data"
        else:
            state = "supported"

        sectors[sector] = {
            "label": STRATEGY_SECTOR_LABELS[sector],
            "state": state,
            "max_rate_capability": capability,
            "selectable": selectable,
            "rows": len(rows),
            "max_rate_rows": max_rows,
            "coverage_ratio": round(max_rows / len(rows), 6) if rows else None,
            "latest_source_effective_at": latest_effective_at,
            "geo_basis": _sorted_decoded_values(
                table, rows, source_columns, "geo_basis"
            ),
            "rate_scope": _sorted_decoded_values(
                table, rows, source_columns, "rate_scope"
            ),
            "availability_scope": _sorted_decoded_values(
                table, rows, source_columns, "availability_scope"
            ),
            "evidence": STRATEGY_MAX_RATE_EVIDENCE[sector],
            "blocked_reason": STRATEGY_BLOCK_REASONS.get(sector),
            "terms": terms,
        }

    return {
        "metric_basis": "max_rate",
        "default_mode": "savings_bank",
        "candidate_sectors": list(STRATEGY_CANDIDATE_SECTORS),
        "published_sectors": [
            sector
            for sector in STRATEGY_CANDIDATE_SECTORS
            if sector in STRATEGY_MAX_RATE_ENABLED_SECTORS
        ],
        "base_rate_fallback": False,
        "sectors": sectors,
    }


def slice_strategy_table(table: dict[str, Any]) -> dict[str, Any]:
    """canonical table에서 evidence-backed 전략 payload 행만 고른다.

    Stage G2 evidence가 열린 농·축협(NH local)도 strategy capability에 포함한다.
    다만 NH는 기본행·e-joy 원천행까지 payload를 중복 확장하지 않고 evidence-backed
    ``max_rate``가 있는 internet variant만 싣는다. KFCC는 metadata에 차단 사유만
    남긴다. 값 변환·금리 fallback은 하지 않는다.
    """
    columns = list(table.get("columns") or [])
    source_columns = {name: index for index, name in enumerate(columns)}
    required = {"sector", "product_type", "term_months"}
    missing = sorted(required.difference(source_columns))
    if missing:
        raise DashboardBuildError(
            "전략 slice에 필요한 table 열이 없다: " + ", ".join(missing)
        )

    universe = strategy_universe_metadata(table)
    max_index = source_columns.get("max_rate")
    rows = []
    for row in table.get("rows") or []:
        sector = _decode(table, "sector", row[source_columns["sector"]])
        product_type = _decode(
            table, "product_type", row[source_columns["product_type"]]
        )
        term = row[source_columns["term_months"]]
        if (
            sector in STRATEGY_MAX_RATE_ENABLED_SECTORS
            and product_type == STRATEGY_PRODUCT_TYPE
            and term in STRATEGY_TERMS
        ):
            if sector in STRATEGY_MAX_ONLY_PUBLISHED_SECTORS and (
                max_index is None or not _rate_present(row[max_index])
            ):
                continue
            rows.append(row)

    return {**table, "rows": rows, "strategy_universe": universe}


def _product_id_index(db_path: Path) -> dict[tuple[Any, ...], str | None]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT
                r.source_id,
                i.canonical_name,
                p.name,
                p.product_type,
                v.term_months,
                v.payment_method,
                v.interest_method,
                v.join_channel,
                p.id
            FROM rate_observations o
            JOIN collection_runs r ON r.id = o.run_id
            JOIN product_variants v ON v.id = o.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN institutions i ON i.id = p.institution_id
            WHERE o.valid_to IS NULL
              AND o.validation_status != 'error'
            """
        ).fetchall()
    finally:
        conn.close()

    candidates: dict[tuple[Any, ...], set[str]] = {}
    for row in rows:
        key = tuple(row[:-1])
        candidates.setdefault(key, set()).add(str(row[-1]))
    return {
        key: next(iter(ids)) if len(ids) == 1 else None
        for key, ids in candidates.items()
    }


def augment_strategy_table(
    db_path: Path, table: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    """전략 slice에 압축 ``product_id`` 열을 추가한다.

    신규 site build는 DB query에서 stable id를 직접 운반한다. 과거 caller를 위해
    display-key 재조인 경로는 남겨 두지만, 이미 ``product_id``가 있으면 재조인하지
    않는다. 이 경우에도 null id는 즉시 build 실패다.
    """
    columns = list(table.get("columns") or [])
    if PRODUCT_ID_COLUMN in columns:
        product_id_index = columns.index(PRODUCT_ID_COLUMN)
        rows = table.get("rows") or []
        unmatched = sum(row[product_id_index] is None for row in rows)
        if unmatched:
            raise DashboardBuildError(
                "전략 비교상품 stable product_id 직접 전달 실패: "
                f"{unmatched}행"
            )
        return table, {"matched": len(rows), "unmatched": 0}

    source_columns = {name: index for index, name in enumerate(columns)}
    required = set(_IDENTITY_KEY_COLUMNS) | {"sector"}
    missing = sorted(required.difference(source_columns))
    if missing:
        raise DashboardBuildError(
            "전략 stable identity에 필요한 table 열이 없다: " + ", ".join(missing)
        )

    product_ids = _product_id_index(db_path)
    id_lookup: list[str] = []
    id_positions: dict[str, int] = {}
    rows: list[list[Any]] = []
    target_unmatched = 0
    matched = 0

    for source_row in table.get("rows") or []:
        row = list(source_row)
        product_id = product_ids.get(_row_key(table, row))
        if product_id is not None:
            matched += 1
            if product_id not in id_positions:
                id_positions[product_id] = len(id_lookup)
                id_lookup.append(product_id)
            row.append(id_positions[product_id])
        else:
            row.append(None)
            sector = _decode(table, "sector", row[source_columns["sector"]])
            product_type = _decode(
                table, "product_type", row[source_columns["product_type"]]
            )
            term = row[source_columns["term_months"]]
            if (
                sector in STRATEGY_MAX_RATE_ENABLED_SECTORS
                and product_type == STRATEGY_PRODUCT_TYPE
                and term in STRATEGY_TERMS
            ):
                target_unmatched += 1
        rows.append(row)

    if target_unmatched:
        raise DashboardBuildError(
            "전략 비교상품 stable product_id 매칭 실패: "
            f"{target_unmatched}행"
        )

    lookups = dict(table.get("lookups") or {})
    lookups[PRODUCT_ID_COLUMN] = id_lookup
    return (
        {**table, "columns": [*columns, PRODUCT_ID_COLUMN], "lookups": lookups, "rows": rows},
        {"matched": matched, "unmatched": len(rows) - matched},
    )
