"""전략 화면 전용 stable product identity table 계약.

공식 검색 화면의 발행 계약은 그대로 두고, 전략 Release Gate가 켜진 빌드에서만
canonical table에서 전략 비교군을 필터한 뒤 ``product_id``를 덧붙인다. 전략 화면은
이 stable id로 상품 대표값을 묶는다. 표현 계층은 ``web/templates/strategy.html``이
직접 소유한다. Stage A 이후 이 모듈은 HTML 표현 치환을 수행하지 않는다.
"""

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.services.dashboard_service import DashboardBuildError

PRODUCT_ID_COLUMN = "product_id"
_STRATEGY_TERMS = frozenset({6, 12, 24, 36})
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


def slice_strategy_table(table: dict[str, Any]) -> dict[str, Any]:
    """canonical table에서 Stage B 전략 universe 행만 그대로 고른다.

    값 변환·집계·재정렬을 하지 않는다. columns/lookups는 canonical table 계약을
    그대로 유지하고 rows만 저축은행 정기예금 6/12/24/36개월로 제한한다.
    """
    columns = list(table.get("columns") or [])
    source_columns = {name: index for index, name in enumerate(columns)}
    required = {"sector", "product_type", "term_months"}
    missing = sorted(required.difference(source_columns))
    if missing:
        raise DashboardBuildError(
            "전략 slice에 필요한 table 열이 없다: " + ", ".join(missing)
        )

    rows = []
    for row in table.get("rows") or []:
        sector = _decode(table, "sector", row[source_columns["sector"]])
        product_type = _decode(
            table, "product_type", row[source_columns["product_type"]]
        )
        term = row[source_columns["term_months"]]
        if (
            sector == "savings_bank"
            and product_type == "term_deposit"
            and term in _STRATEGY_TERMS
        ):
            rows.append(row)

    return {**table, "rows": rows}


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

    검색 화면의 기본 빌드에서는 호출하지 않는다. 전략 비교 universe에 해당하는
    저축은행 정기예금 6/12/24/36개월 행이 stable id와 매칭되지 않으면 build를
    실패시킨다. 이름 기반 fallback으로 조용히 순위를 만드는 것보다 안전하다.
    """
    columns = list(table.get("columns") or [])
    if PRODUCT_ID_COLUMN in columns:
        return table, {"matched": len(table.get("rows") or []), "unmatched": 0}

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
                sector == "savings_bank"
                and product_type == "term_deposit"
                and term in _STRATEGY_TERMS
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
