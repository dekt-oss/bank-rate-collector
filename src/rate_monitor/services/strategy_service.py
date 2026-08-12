"""전략 대시보드용 read-only 집계.

검색·조회 화면의 데이터 계약은 건드리지 않는다. 전략 화면에서만 필요한
최근 금리 변경 이력을 기존 ``rate_observations`` 변경이력에서 읽는다.

중요: 관측 행은 값이 바뀔 때만 새로 생긴다. 따라서 ``valid_from`` 순서의
직전 행과 현재 행을 비교하면 실제로 감지된 변경을 복원할 수 있다.
"""

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.domain.preference_taxonomy import labels as preference_labels
from rate_monitor.domain.timeutil import kst_iso

MARKET_CHANGE_WINDOW_DAYS = 30
MARKET_CHANGE_ITEM_LIMIT = 12


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _change_cte() -> str:
    """저축은행 12개월 정기예금의 최고금리 변경 후보.

    윈도 함수는 전체 이력에 먼저 적용한다. 30일 조건을 안쪽에 넣으면 31일
    전에 있던 직전 값을 못 보고, 월초 첫 변경을 신규값처럼 놓칠 수 있다.
    """
    return """
        WITH history AS (
            SELECT
                o.id,
                o.variant_id,
                o.valid_from,
                o.max_rate,
                o.validation_status,
                LAG(o.max_rate) OVER (
                    PARTITION BY o.variant_id
                    ORDER BY o.valid_from, o.id
                ) AS previous_max_rate
            FROM rate_observations o
            WHERE o.validation_status != 'error'
        ), changes AS (
            SELECT
                h.id,
                h.valid_from AS changed_at,
                h.previous_max_rate,
                h.max_rate,
                i.canonical_name AS institution,
                p.name AS product,
                v.term_months AS term_months
            FROM history h
            JOIN product_variants v ON v.id = h.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN institutions i ON i.id = p.institution_id
            WHERE i.sector = 'savings_bank'
              AND p.product_type = 'term_deposit'
              AND v.term_months = 12
              AND h.valid_from >= datetime('now', ?)
              AND h.previous_max_rate IS NOT NULL
              AND h.max_rate IS NOT NULL
              AND h.previous_max_rate != h.max_rate
        )
    """


def build_strategy_summary(db_path: Path) -> dict[str, Any]:
    """전략 화면에만 인라인할 가벼운 시장 변화 요약을 만든다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = None
    window = f"-{MARKET_CHANGE_WINDOW_DAYS} days"
    try:
        aggregate = _rows(
            conn,
            _change_cte()
            + """
                SELECT
                    COUNT(*) AS count,
                    SUM(CASE WHEN CAST(max_rate AS REAL) > CAST(previous_max_rate AS REAL)
                             THEN 1 ELSE 0 END) AS up_count,
                    SUM(CASE WHEN CAST(max_rate AS REAL) < CAST(previous_max_rate AS REAL)
                             THEN 1 ELSE 0 END) AS down_count,
                    MAX(changed_at) AS latest_changed_at
                FROM changes
            """,
            (window,),
        )[0]

        items = _rows(
            conn,
            _change_cte()
            + """
                SELECT
                    institution,
                    product,
                    term_months,
                    previous_max_rate,
                    max_rate,
                    changed_at
                FROM changes
                ORDER BY
                    ABS(CAST(max_rate AS REAL) - CAST(previous_max_rate AS REAL)) DESC,
                    changed_at DESC,
                    institution,
                    product
                LIMIT ?
            """,
            (window, MARKET_CHANGE_ITEM_LIMIT),
        )
    finally:
        conn.close()

    for item in items:
        before = float(item["previous_max_rate"])
        after = float(item["max_rate"])
        item["previous_max_rate"] = before
        item["max_rate"] = after
        item["delta"] = round(after - before, 4)
        item["changed_at"] = kst_iso(item["changed_at"])

    latest = aggregate.get("latest_changed_at")
    return {
        "preference_labels": preference_labels(),
        "market_changes": {
            "window_days": MARKET_CHANGE_WINDOW_DAYS,
            "count": int(aggregate.get("count") or 0),
            "up_count": int(aggregate.get("up_count") or 0),
            "down_count": int(aggregate.get("down_count") or 0),
            "latest_changed_at": kst_iso(latest) if latest else None,
            "items": items,
            "scope": {
                "sector": "savings_bank",
                "product_type": "term_deposit",
                "term_months": 12,
                "rate_field": "max_rate",
            },
        },
    }
