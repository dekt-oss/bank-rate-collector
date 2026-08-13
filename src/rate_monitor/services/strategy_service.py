"""전략 대시보드용 read-only 집계.

검색·조회 화면의 데이터 계약은 건드리지 않는다. 전략 화면에서만 필요한
최근 금리 변경 이력과 기간별 시장 추이를 기존 DB에서 읽는다.

중요: 관측 행은 값이 바뀔 때만 새로 생긴다. 따라서 ``valid_from`` 순서의
직전 행과 현재 행을 비교하면 실제로 감지된 변경을 복원할 수 있다.

가입채널·이자방식처럼 같은 상품 아래 여러 variant가 한 수집 실행에서 같은
금리로 함께 움직일 수 있다. 전략 화면에서 이것을 여러 시장 이벤트로 세면
변경 건수가 부풀려지므로, **같은 run + 같은 상품 + 같은 전후 금리**는 상품
변경 1건으로 묶는다. 원본 관측 행은 수정하거나 삭제하지 않는다.
"""

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.domain.preference_taxonomy import labels as preference_labels
from rate_monitor.domain.timeutil import kst_iso

MARKET_CHANGE_WINDOW_DAYS = 30
MARKET_CHANGE_ITEM_LIMIT = 12
MARKET_TREND_WINDOW_DAYS = 63
MARKET_TREND_POINT_LIMIT = 9
OUR_INSTITUTION_NAME = "고려저축은행"


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
    ).fetchone()
    return row is not None


def _change_cte() -> str:
    """저축은행 12개월 정기예금의 상품 단위 최고금리 변경 후보."""
    return """
        WITH history AS (
            SELECT
                o.id,
                o.variant_id,
                o.run_id,
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
                h.run_id,
                h.valid_from AS changed_at,
                h.previous_max_rate,
                h.max_rate,
                i.canonical_name AS institution,
                p.id AS product_id,
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
        ), product_changes AS (
            SELECT
                run_id,
                product_id,
                institution,
                product,
                term_months,
                previous_max_rate,
                max_rate,
                MAX(changed_at) AS changed_at,
                COUNT(*) AS variant_count
            FROM changes
            GROUP BY
                run_id,
                product_id,
                institution,
                product,
                term_months,
                previous_max_rate,
                max_rate
        )
    """


def _empty_rate_trend() -> dict[str, Any]:
    return {
        "window_days": MARKET_TREND_WINDOW_DAYS,
        "points": [],
        "scope": {
            "sector": "savings_bank",
            "product_type": "term_deposit",
            "term_months": 12,
            "rate_field": "max_rate",
            "aggregation": "product_representative_mean",
            "our_institution": OUR_INSTITUTION_NAME,
            "our_company_aggregation": "institution_product_representative_max",
        },
    }


def _build_rate_trend(conn: sqlite3.Connection) -> dict[str, Any]:
    """최근 수집일별 12개월 정기예금 시장·우리회사 금리 추이를 복원한다.

    관측은 값이 바뀔 때만 새 행이 생기므로 단순히 ``valid_from``을 날짜별로
    평균 내면 "그날 바뀐 상품"만 평균하게 된다. 여기서는 각 정상 수집일의
    마지막 시각을 snapshot으로 잡고, 그 시각에 유효했던 관측 구간
    (valid_from <= t < valid_to)을 복원한 뒤 상품별 최고금리 대표값을 만든다.

    시장 평균과 시장 최고는 전체 상품 대표값에서 계산한다. 우리회사 선은
    같은 snapshot에서 고려저축은행의 상품 대표 최고금리 중 가장 높은 값을
    사용한다. 과거 시점에 데이터가 없으면 NULL로 남겨 현재값을 과거에
    소급하지 않는다.
    """
    required = ("collection_runs", "sources", "rate_observations")
    if not all(_table_exists(conn, table) for table in required):
        return _empty_rate_trend()

    window = f"-{MARKET_TREND_WINDOW_DAYS} days"
    snapshots = _rows(
        conn,
        """
        SELECT
            date(COALESCE(r.finished_at, r.started_at)) AS snapshot_date,
            MAX(COALESCE(r.finished_at, r.started_at)) AS snapshot_at
        FROM collection_runs r
        JOIN sources s ON s.id = r.source_id
        WHERE s.sector = 'savings_bank'
          AND r.status IN ('success', 'partial', 'no_change')
          AND COALESCE(r.finished_at, r.started_at) IS NOT NULL
          AND COALESCE(r.finished_at, r.started_at) >= datetime('now', ?)
        GROUP BY date(COALESCE(r.finished_at, r.started_at))
        ORDER BY snapshot_at DESC
        LIMIT ?
        """,
        (window, MARKET_TREND_POINT_LIMIT),
    )
    snapshots.reverse()

    points: list[dict[str, Any]] = []
    for snapshot in snapshots:
        at = snapshot["snapshot_at"]
        row = _rows(
            conn,
            """
            SELECT
                AVG(product_max_rate) AS mean_max_rate,
                MAX(product_max_rate) AS market_max_rate,
                MAX(CASE WHEN institution = ? THEN product_max_rate END)
                    AS our_company_max_rate,
                COUNT(*) AS product_count
            FROM (
                SELECT
                    p.id AS product_id,
                    i.canonical_name AS institution,
                    MAX(CAST(o.max_rate AS REAL)) AS product_max_rate
                FROM rate_observations o
                JOIN product_variants v ON v.id = o.variant_id
                JOIN products p ON p.id = v.product_id
                JOIN institutions i ON i.id = p.institution_id
                WHERE i.sector = 'savings_bank'
                  AND p.product_type = 'term_deposit'
                  AND v.term_months = 12
                  AND o.validation_status != 'error'
                  AND o.max_rate IS NOT NULL
                  AND o.valid_from <= ?
                  AND (o.valid_to IS NULL OR o.valid_to > ?)
                GROUP BY p.id, i.canonical_name
            )
            """,
            (OUR_INSTITUTION_NAME, at, at),
        )[0]
        if row.get("mean_max_rate") is None:
            continue
        our_rate = row.get("our_company_max_rate")
        points.append(
            {
                "date": snapshot["snapshot_date"],
                "snapshot_at": kst_iso(at),
                "mean_max_rate": round(float(row["mean_max_rate"]), 4),
                "market_max_rate": round(float(row["market_max_rate"]), 4),
                "our_company_max_rate": (
                    round(float(our_rate), 4) if our_rate is not None else None
                ),
                "product_count": int(row.get("product_count") or 0),
            }
        )

    trend = _empty_rate_trend()
    trend["points"] = points
    return trend


def build_strategy_summary(db_path: Path) -> dict[str, Any]:
    """전략 화면에만 인라인할 가벼운 시장 변화·추이 요약을 만든다."""
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
                    SUM(variant_count) AS affected_variant_count,
                    MAX(changed_at) AS latest_changed_at
                FROM product_changes
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
                    changed_at,
                    variant_count
                FROM product_changes
                ORDER BY
                    ABS(CAST(max_rate AS REAL) - CAST(previous_max_rate AS REAL)) DESC,
                    changed_at DESC,
                    institution,
                    product
                LIMIT ?
            """,
            (window, MARKET_CHANGE_ITEM_LIMIT),
        )
        rate_trend = _build_rate_trend(conn)
    finally:
        conn.close()

    for item in items:
        before = float(item["previous_max_rate"])
        after = float(item["max_rate"])
        item["previous_max_rate"] = before
        item["max_rate"] = after
        item["variant_count"] = int(item.get("variant_count") or 1)
        item["delta"] = round(after - before, 4)
        item["changed_at"] = kst_iso(item["changed_at"])

    latest = aggregate.get("latest_changed_at")
    return {
        "preference_labels": preference_labels(),
        "rate_trend": rate_trend,
        "market_changes": {
            "window_days": MARKET_CHANGE_WINDOW_DAYS,
            "count": int(aggregate.get("count") or 0),
            "up_count": int(aggregate.get("up_count") or 0),
            "down_count": int(aggregate.get("down_count") or 0),
            "affected_variant_count": int(aggregate.get("affected_variant_count") or 0),
            "latest_changed_at": kst_iso(latest) if latest else None,
            "items": items,
            "scope": {
                "sector": "savings_bank",
                "product_type": "term_deposit",
                "term_months": 12,
                "rate_field": "max_rate",
                "event_unit": "run_product_rate_transition",
            },
        },
    }
