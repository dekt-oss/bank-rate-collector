"""Strategy용 수신시장·기관별 자금조달 경쟁 read-only 집계.

D0는 ECOS 업권 수신잔액, D1은 Data.go 기관별 예수부채를 사용한다.
잔액 변화는 순유입으로 부르지 않으며, 기관 순위/4분면은 verified identity만 쓴다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from statistics import median
from typing import Any

from rate_monitor.services.strategy_service_base import _apply_source_precedence

ECOS_CODES = {
    "savings_bank": "bok_savings_bank_deposit_balance",
    "cu": "bok_credit_union_deposit_balance",
    "nh_local": "bok_broad_mutual_finance_deposit_balance",
}
SECTOR_LABELS = {
    "savings_bank": "저축은행",
    "cu": "신협",
    "nh_local": "농·축협",
}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _prior_year(month: str) -> str:
    year, value = month.split("-", 1)
    return f"{int(year) - 1:04d}-{value}"


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current / previous - 1.0) * 100.0, 2)


def _market_flow(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "market_indicators"):
        return []
    codes = tuple(ECOS_CODES.values())
    placeholders = ",".join("?" for _ in codes)
    rows = _rows(
        conn,
        f"""
        SELECT
            indicator_code,
            substr(source_effective_at, 1, 7) AS month,
            CAST(value AS REAL) AS value,
            unit
        FROM market_indicators
        WHERE indicator_code IN ({placeholders})
        ORDER BY source_effective_at
        """,
        codes,
    )
    reverse = {code: sector for sector, code in ECOS_CODES.items()}
    by_sector: dict[str, dict[str, float]] = {}
    for row in rows:
        sector = reverse.get(str(row["indicator_code"]))
        month = str(row.get("month") or "")
        if not sector or len(month) != 7 or row.get("unit") != "trillion_krw":
            continue
        by_sector.setdefault(sector, {})[month] = float(row["value"])

    result: list[dict[str, Any]] = []
    for sector, series in by_sector.items():
        if not series:
            continue
        latest_month = max(series)
        latest = series[latest_month]
        prior_month = _prior_year(latest_month)
        prior = series.get(prior_month)
        yoy = _pct_change(latest, prior) if prior is not None else None
        result.append(
            {
                "sector": sector,
                "label": SECTOR_LABELS.get(sector, sector),
                "latest_month": latest_month,
                "balance_trillion_krw": round(latest, 3),
                "yoy_pct": yoy,
                "basis": "ECOS 업권 수신잔액(말잔)",
                "indicator_code": ECOS_CODES[sector],
            }
        )
    return sorted(result, key=lambda item: item["sector"])


def _funding_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "institution_funding_observations"):
        return []
    return _rows(
        conn,
        """
        SELECT
            f.institution_id,
            i.canonical_name AS institution,
            f.source_institution_key,
            f.sector,
            f.source_effective_month AS month,
            CAST(f.value AS REAL) AS value_million_krw,
            f.identity_status,
            f.population_scope
        FROM institution_funding_observations f
        LEFT JOIN institutions i ON i.id = f.institution_id
        WHERE f.valid_to IS NULL
          AND f.metric_code = 'deposit_liabilities_total'
          AND f.population_scope != 'agri_coop_central_excluded_from_local_sum'
        """,
    )


def _growth_rankings(
    funding_rows: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_sector_month: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in funding_rows:
        sector = str(row["sector"])
        month = str(row["month"])
        by_sector_month.setdefault(sector, {}).setdefault(month, []).append(row)

    rankings: dict[str, list[dict[str, Any]]] = {}
    coverage: dict[str, dict[str, Any]] = {}
    for sector, months in by_sector_month.items():
        if not months:
            continue
        latest_month = max(months)
        previous_month = _prior_year(latest_month)
        latest_rows = months[latest_month]
        mapped_latest = [
            row
            for row in latest_rows
            if row.get("institution_id")
            and str(row.get("identity_status") or "").startswith("mapped_")
        ]
        coverage[sector] = {
            "latest_month": latest_month,
            "institution_count": len(
                {str(row["source_institution_key"]) for row in latest_rows}
            ),
            "verified_identity_count": len(
                {str(row["source_institution_key"]) for row in mapped_latest}
            ),
            "unverified_identity_count": len(
                {
                    str(row["source_institution_key"])
                    for row in latest_rows
                    if not row.get("institution_id")
                    or not str(row.get("identity_status") or "").startswith("mapped_")
                }
            ),
        }
        previous_by_id = {
            str(row["institution_id"]): row
            for row in months.get(previous_month, [])
            if row.get("institution_id")
            and str(row.get("identity_status") or "").startswith("mapped_")
        }
        items: list[dict[str, Any]] = []
        for row in mapped_latest:
            institution_id = str(row["institution_id"])
            previous = previous_by_id.get(institution_id)
            if previous is None:
                continue
            current_value = float(row["value_million_krw"])
            previous_value = float(previous["value_million_krw"])
            yoy = _pct_change(current_value, previous_value)
            if yoy is None:
                continue
            items.append(
                {
                    "institution_id": institution_id,
                    "institution": str(row.get("institution") or ""),
                    "sector": sector,
                    "latest_month": latest_month,
                    "previous_month": previous_month,
                    "balance_trillion_krw": round(current_value / 1_000_000, 4),
                    "yoy_pct": yoy,
                }
            )
        items.sort(
            key=lambda item: (
                -float(item["yoy_pct"]),
                -float(item["balance_trillion_krw"]),
                item["institution"],
            )
        )
        count = len(items)
        for index, item in enumerate(items, start=1):
            item["rank"] = index
            item["sector_count"] = count
            item["sector_percentile"] = (
                100.0
                if count <= 1
                else round((count - index) / (count - 1) * 100.0, 1)
            )
        rankings[sector] = items
    return rankings, coverage


def _current_savings_rates(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    required = (
        "rate_observations",
        "collection_runs",
        "product_variants",
        "products",
        "institutions",
    )
    if not all(_table_exists(conn, table) for table in required):
        return {}
    rows = _rows(
        conn,
        """
        SELECT
            i.id AS institution_id,
            i.canonical_name AS institution,
            i.normalized_name AS normalized_institution,
            p.id AS product_id,
            p.product_type,
            v.term_months,
            r.source_id,
            CAST(o.max_rate AS REAL) AS max_rate
        FROM rate_observations o
        JOIN collection_runs r ON r.id = o.run_id
        JOIN product_variants v ON v.id = o.variant_id
        JOIN products p ON p.id = v.product_id
        JOIN institutions i ON i.id = p.institution_id
        WHERE i.sector = 'savings_bank'
          AND p.product_type = 'term_deposit'
          AND v.term_months = 12
          AND o.valid_to IS NULL
          AND o.validation_status != 'error'
          AND o.max_rate IS NOT NULL
        """,
    )
    visible = _apply_source_precedence(rows)
    product_representatives: dict[str, dict[str, Any]] = {}
    for row in visible:
        product_id = str(row["product_id"])
        current = product_representatives.get(product_id)
        if current is None or float(row["max_rate"]) > float(current["max_rate"]):
            product_representatives[product_id] = row

    by_institution: dict[str, dict[str, Any]] = {}
    for row in product_representatives.values():
        institution_id = str(row["institution_id"])
        current = by_institution.get(institution_id)
        if current is None or float(row["max_rate"]) > float(current["max_rate"]):
            by_institution[institution_id] = {
                "institution_id": institution_id,
                "institution": row["institution"],
                "max_rate": round(float(row["max_rate"]), 4),
            }
    return by_institution


def _quadrant(
    savings_ranking: list[dict[str, Any]],
    rate_by_institution: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    matched = [
        item
        for item in savings_ranking
        if item["institution_id"] in rate_by_institution
    ]
    rates = [
        float(rate_by_institution[item["institution_id"]]["max_rate"])
        for item in matched
    ]
    if not rates:
        return {
            "available": False,
            "items": [],
            "reason": "verified 기관별 예수부채와 현재 12개월 금리를 동시에 연결할 표본이 없다",
        }
    market_median = float(median(rates))
    items: list[dict[str, Any]] = []
    for funding in matched:
        rate = float(rate_by_institution[funding["institution_id"]]["max_rate"])
        x_bp = round((rate - market_median) * 100.0, 1)
        growth = float(funding["yoy_pct"])
        if x_bp >= 0 and growth >= 0:
            quadrant = "고금리 · 성장"
        elif x_bp < 0 and growth >= 0:
            quadrant = "저금리 · 성장"
        elif x_bp >= 0 and growth < 0:
            quadrant = "고금리 · 감소"
        else:
            quadrant = "저금리 · 감소"
        items.append(
            {
                **funding,
                "rate_pct": rate,
                "rate_vs_market_bp": x_bp,
                "quadrant": quadrant,
            }
        )
    return {
        "available": True,
        "sector": "savings_bank",
        "items": items,
        "market_median_rate_pct": round(market_median, 4),
        "x_axis": "현재 12개월 정기예금 기관 최고금리 - 연결표본 중앙값(bp)",
        "y_axis": "Data.go 예수부채 YoY(%)",
        "causality": "descriptive_position_only",
    }


def build_market_funding_strategy(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    try:
        market_flow = _market_flow(conn)
        funding_rows = _funding_rows(conn)
        rankings, coverage = _growth_rankings(funding_rows)
        quadrant = _quadrant(
            rankings.get("savings_bank", []),
            _current_savings_rates(conn),
        )
    finally:
        conn.close()

    return {
        "available": bool(market_flow or any(rankings.values())),
        "market_flow": market_flow,
        "growth_rankings": rankings,
        "coverage": coverage,
        "quadrant": quadrant,
        "sector_labels": SECTOR_LABELS,
        "contract": {
            "market_basis": "ECOS 업권 수신잔액(말잔)",
            "institution_basis": "Data.go 재무상태표 예수부채",
            "growth_basis": "동일 기준월 전년 대비(YoY)",
            "ranking_scope": "업권 내부 verified identity만",
            "balance_change_is_net_flow": False,
            "quadrant_is_causal": False,
            "agri_central_in_local_ranking": False,
        },
    }
