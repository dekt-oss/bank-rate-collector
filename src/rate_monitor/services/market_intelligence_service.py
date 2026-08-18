"""Stage C1 시장이력 파생계약.

현재 Strategy의 역사 집계는 저축은행·12개월 중심이다. 이 모듈은 화면을 먼저
늘리지 않고 7D/30D × 6/12/24/36M × Strategy 4업권의 데이터 가용성과 시장
움직임을 같은 계약으로 계산한다.

중요한 원칙은 fail-closed다. 요청기간의 80% 이상·125% 이하 범위에 맞는 이력이
없으면 7D/30D라는 라벨로 변화량을 만들지 않는다. 또한 NH local의 전략
최고금리는 e-joy base+add 1:1 결합이 필요한데 과거 snapshot에서 그 전략 rate
basis를 아직 재구성하지 않는다. 따라서 NH historical intelligence는 v1에서
명시적으로 ``unsupported_rate_contract``로 닫는다.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime
from typing import Any

from rate_monitor.services.dashboard_service import dedupe_sources

SECTORS = ("savings_bank", "cu", "kfcc", "nh_local")
TERMS = (6, 12, 24, 36)
WINDOWS = (7, 30)
MIN_HISTORY_RATIO = 0.80
MAX_HISTORY_RATIO = 1.25
OUR_INSTITUTION_NAME = "고려저축은행"

_RATE_CONTRACT = {
    "savings_bank": "observation_product_representative_max",
    "cu": "observation_product_representative_max",
    "kfcc": "observation_product_representative_max",
    "nh_local": "unsupported_historical_strategy_rate_basis",
}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _top_decile_cutoff(rows: dict[str, dict[str, Any]]) -> float | None:
    if not rows:
        return None
    ordered = sorted((float(row["rate"]) for row in rows.values()), reverse=True)
    count = max(1, math.ceil(len(ordered) * 0.10))
    return ordered[count - 1]


def _top_decile_ids(rows: dict[str, dict[str, Any]]) -> set[str]:
    if not rows:
        return set()
    ordered = sorted(
        rows.values(),
        key=lambda row: (-float(row["rate"]), str(row["product_id"])),
    )
    count = max(1, math.ceil(len(ordered) * 0.10))
    return {str(row["product_id"]) for row in ordered[:count]}


def _source_precedence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """메인 presentation의 db_only_sources 후퇴 규칙을 historical snapshot에 적용."""
    retreating = set(dedupe_sources())
    if not retreating:
        return rows
    covered = {
        (
            str(row.get("normalized_institution") or row.get("institution") or ""),
            row.get("product_type"),
            row.get("term_months"),
        )
        for row in rows
        if row.get("source_id") not in retreating
    }
    if not covered:
        return rows
    visible: list[dict[str, Any]] = []
    for row in rows:
        key = (
            str(row.get("normalized_institution") or row.get("institution") or ""),
            row.get("product_type"),
            row.get("term_months"),
        )
        if row.get("source_id") in retreating and key in covered:
            continue
        visible.append(row)
    return visible


def _sector_run_times(conn: sqlite3.Connection, sector: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT COALESCE(r.finished_at, r.started_at) AS snapshot_at
        FROM collection_runs r
        JOIN sources s ON s.id = r.source_id
        WHERE s.sector = ?
          AND r.status IN ('success', 'partial', 'no_change')
          AND COALESCE(r.finished_at, r.started_at) IS NOT NULL
        ORDER BY snapshot_at
        """,
        (sector,),
    ).fetchall()
    return [str(row[0]) for row in rows if row[0]]


def _snapshot_products(
    conn: sqlite3.Connection,
    *,
    sector: str,
    term_months: int,
    at: str,
) -> dict[str, dict[str, Any]]:
    normalized_expr = (
        "i.normalized_name"
        if _column_exists(conn, "institutions", "normalized_name")
        else "i.canonical_name"
    )
    rows = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT
                p.id AS product_id,
                i.canonical_name AS institution,
                {normalized_expr} AS normalized_institution,
                p.product_type AS product_type,
                v.term_months AS term_months,
                r.source_id AS source_id,
                CAST(o.max_rate AS REAL) AS rate
            FROM rate_observations o
            JOIN collection_runs r ON r.id = o.run_id
            JOIN product_variants v ON v.id = o.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN institutions i ON i.id = p.institution_id
            WHERE i.sector = ?
              AND p.product_type = 'term_deposit'
              AND v.term_months = ?
              AND o.validation_status != 'error'
              AND o.max_rate IS NOT NULL
              AND o.valid_from <= ?
              AND (o.valid_to IS NULL OR o.valid_to > ?)
            """,
            (sector, term_months, at, at),
        ).fetchall()
    ]
    rows = _source_precedence(rows)
    representatives: dict[str, dict[str, Any]] = {}
    for row in rows:
        product_id = str(row["product_id"])
        current = representatives.get(product_id)
        if current is None or float(row["rate"]) > float(current["rate"]):
            representatives[product_id] = row
    return representatives


def _snapshot_summary(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["rate"]) for row in rows.values()]
    median = _median(values)
    cutoff = _top_decile_cutoff(rows)
    return {
        "product_count": len(rows),
        "median_rate": round(median, 4) if median is not None else None,
        "upper_decile_cutoff": round(cutoff, 4) if cutoff is not None else None,
    }


def _nearest_baseline(run_times: list[str], end_at: str, window_days: int) -> str | None:
    end_dt = _parse_dt(end_at)
    if end_dt is None:
        return None
    target = end_dt.timestamp() - window_days * 86400
    candidates: list[tuple[float, str]] = []
    for raw in run_times:
        dt = _parse_dt(raw)
        if dt is None or dt.timestamp() > target:
            continue
        candidates.append((dt.timestamp(), raw))
    return max(candidates, default=(0.0, ""))[1] or None


def _history_days(start_at: str, end_at: str) -> float | None:
    start = _parse_dt(start_at)
    end = _parse_dt(end_at)
    if start is None or end is None:
        return None
    # collection timestamps are stored with one timezone convention within this DB.
    # Comparing like-for-like here is sufficient; mixed aware/naive values fail closed.
    try:
        return max(0.0, (end - start).total_seconds() / 86400)
    except TypeError:
        return None


def _empty_scope(
    *, sector: str, term_months: int, window_days: int, status: str, reason: str
) -> dict[str, Any]:
    return {
        "sector": sector,
        "term_months": term_months,
        "window_days": window_days,
        "status": status,
        "reason": reason,
        "rate_contract": _RATE_CONTRACT[sector],
        "start_snapshot_at": None,
        "end_snapshot_at": None,
        "observed_days": None,
        "coverage_ratio": 0.0,
        "start": None,
        "end": None,
        "comparable_product_count": 0,
        "up_count": None,
        "down_count": None,
        "unchanged_count": None,
        "up_share": None,
        "down_share": None,
        "breadth_score": None,
        "median_change_bp": None,
        "upper_decile_change_bp": None,
        "comparable_mean_change_bp": None,
        "top_decile_entrants": None,
        "top_decile_exits": None,
        "top_decile_churn_rate": None,
        "direction": "insufficient",
        "our_company": None,
    }


def _scope_metric(
    conn: sqlite3.Connection,
    *,
    sector: str,
    term_months: int,
    window_days: int,
    run_times: list[str],
    cache: dict[tuple[str, int, str], dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    if _RATE_CONTRACT[sector].startswith("unsupported"):
        return _empty_scope(
            sector=sector,
            term_months=term_months,
            window_days=window_days,
            status="unsupported_rate_contract",
            reason=(
                "NH historical은 e-joy base+add 전략 최고금리 재구성 계약이 없어 "
                "Stage C1 v1에서 변화량을 계산하지 않는다"
            ),
        )
    if not run_times:
        return _empty_scope(
            sector=sector,
            term_months=term_months,
            window_days=window_days,
            status="no_history",
            reason="성공/부분성공/no_change 수집 이력이 없다",
        )

    end_at = run_times[-1]
    end_key = (sector, term_months, end_at)
    end_rows = cache.setdefault(
        end_key,
        _snapshot_products(conn, sector=sector, term_months=term_months, at=end_at),
    )
    if not end_rows:
        result = _empty_scope(
            sector=sector,
            term_months=term_months,
            window_days=window_days,
            status="no_data",
            reason="최신 snapshot에 해당 기간 정기예금 데이터가 없다",
        )
        result["end_snapshot_at"] = end_at
        return result

    start_at = _nearest_baseline(run_times, end_at, window_days)
    if start_at is None:
        result = _empty_scope(
            sector=sector,
            term_months=term_months,
            window_days=window_days,
            status="insufficient_history",
            reason=f"{window_days}일 이전 baseline snapshot이 없다",
        )
        result["end_snapshot_at"] = end_at
        result["end"] = _snapshot_summary(end_rows)
        return result

    observed_days = _history_days(start_at, end_at)
    coverage_ratio = (
        observed_days / window_days if observed_days is not None and window_days else 0.0
    )
    if (
        observed_days is None
        or coverage_ratio < MIN_HISTORY_RATIO
        or coverage_ratio > MAX_HISTORY_RATIO
    ):
        result = _empty_scope(
            sector=sector,
            term_months=term_months,
            window_days=window_days,
            status="insufficient_history",
            reason=(
                f"요청기간의 {MIN_HISTORY_RATIO:.0%}~{MAX_HISTORY_RATIO:.0%} 범위 "
                "baseline 이력이 필요하다"
            ),
        )
        result.update(
            {
                "start_snapshot_at": start_at,
                "end_snapshot_at": end_at,
                "observed_days": round(observed_days, 2) if observed_days is not None else None,
                "coverage_ratio": round(coverage_ratio, 4),
                "end": _snapshot_summary(end_rows),
            }
        )
        return result

    start_key = (sector, term_months, start_at)
    start_rows = cache.setdefault(
        start_key,
        _snapshot_products(conn, sector=sector, term_months=term_months, at=start_at),
    )
    if not start_rows:
        result = _empty_scope(
            sector=sector,
            term_months=term_months,
            window_days=window_days,
            status="insufficient_history",
            reason="baseline snapshot에 비교 가능한 상품 데이터가 없다",
        )
        result.update(
            {
                "start_snapshot_at": start_at,
                "end_snapshot_at": end_at,
                "observed_days": round(observed_days, 2),
                "coverage_ratio": round(coverage_ratio, 4),
                "end": _snapshot_summary(end_rows),
            }
        )
        return result

    common = sorted(set(start_rows) & set(end_rows))
    if not common:
        result = _empty_scope(
            sector=sector,
            term_months=term_months,
            window_days=window_days,
            status="insufficient_comparable_products",
            reason="시작/종료 snapshot 사이 stable product identity가 겹치지 않는다",
        )
        result.update(
            {
                "start_snapshot_at": start_at,
                "end_snapshot_at": end_at,
                "observed_days": round(observed_days, 2),
                "coverage_ratio": round(coverage_ratio, 4),
                "start": _snapshot_summary(start_rows),
                "end": _snapshot_summary(end_rows),
            }
        )
        return result

    deltas = {
        product_id: float(end_rows[product_id]["rate"])
        - float(start_rows[product_id]["rate"])
        for product_id in common
    }
    up = sum(1 for delta in deltas.values() if delta > 1e-9)
    down = sum(1 for delta in deltas.values() if delta < -1e-9)
    unchanged = len(common) - up - down
    comparable = len(common)
    start_summary = _snapshot_summary(start_rows)
    end_summary = _snapshot_summary(end_rows)
    median_change_bp = round(
        (float(end_summary["median_rate"]) - float(start_summary["median_rate"])) * 100,
        2,
    )
    upper_change_bp = round(
        (
            float(end_summary["upper_decile_cutoff"])
            - float(start_summary["upper_decile_cutoff"])
        )
        * 100,
        2,
    )
    mean_change_bp = round(sum(deltas.values()) / comparable * 100, 2)
    breadth = round((up - down) / comparable, 4)
    if median_change_bp > 0 and breadth > 0:
        direction = "rising"
    elif median_change_bp < 0 and breadth < 0:
        direction = "falling"
    elif median_change_bp == 0 and breadth == 0:
        direction = "flat"
    else:
        direction = "mixed"

    start_top = _top_decile_ids(start_rows)
    end_top = _top_decile_ids(end_rows)
    entrants = end_top - start_top
    exits = start_top - end_top
    union = start_top | end_top
    churn = round(len(start_top ^ end_top) / len(union), 4) if union else 0.0

    our_company: dict[str, Any] | None = None
    if sector == "savings_bank":
        start_own = [
            float(row["rate"])
            for row in start_rows.values()
            if row["institution"] == OUR_INSTITUTION_NAME
        ]
        end_own = [
            float(row["rate"])
            for row in end_rows.values()
            if row["institution"] == OUR_INSTITUTION_NAME
        ]
        if start_own and end_own:
            start_rate = max(start_own)
            end_rate = max(end_own)
            start_spread = (start_rate - float(start_summary["median_rate"])) * 100
            end_spread = (end_rate - float(end_summary["median_rate"])) * 100
            our_company = {
                "start_rate": round(start_rate, 4),
                "end_rate": round(end_rate, 4),
                "rate_change_bp": round((end_rate - start_rate) * 100, 2),
                "spread_vs_median_start_bp": round(start_spread, 2),
                "spread_vs_median_end_bp": round(end_spread, 2),
                "spread_change_bp": round(end_spread - start_spread, 2),
            }

    return {
        "sector": sector,
        "term_months": term_months,
        "window_days": window_days,
        "status": "supported",
        "reason": None,
        "rate_contract": _RATE_CONTRACT[sector],
        "start_snapshot_at": start_at,
        "end_snapshot_at": end_at,
        "observed_days": round(observed_days, 2),
        "coverage_ratio": round(coverage_ratio, 4),
        "start": start_summary,
        "end": end_summary,
        "comparable_product_count": comparable,
        "up_count": up,
        "down_count": down,
        "unchanged_count": unchanged,
        "up_share": round(up / comparable, 4),
        "down_share": round(down / comparable, 4),
        "breadth_score": breadth,
        "median_change_bp": median_change_bp,
        "upper_decile_change_bp": upper_change_bp,
        "comparable_mean_change_bp": mean_change_bp,
        "top_decile_entrants": len(entrants),
        "top_decile_exits": len(exits),
        "top_decile_churn_rate": churn,
        "direction": direction,
        "our_company": our_company,
    }


def build_market_intelligence(conn: sqlite3.Connection) -> dict[str, Any]:
    """지원 가능한 scope만 계산하고 이력 부족 scope는 이유와 함께 닫는다."""
    required_tables = {
        "institutions",
        "products",
        "product_variants",
        "rate_observations",
        "collection_runs",
        "sources",
    }
    required_columns = {
        ("rate_observations", "valid_from"),
        ("rate_observations", "valid_to"),
        ("rate_observations", "max_rate"),
        ("collection_runs", "source_id"),
        ("sources", "sector"),
    }
    if not all(_table_exists(conn, table) for table in required_tables) or not all(
        _column_exists(conn, table, column) for table, column in required_columns
    ):
        return {
            "version": "market-intelligence-v1",
            "status": "schema_unavailable",
            "history_gate": {
                "minimum_window_coverage_ratio": MIN_HISTORY_RATIO,
                "maximum_window_coverage_ratio": MAX_HISTORY_RATIO,
            },
            "scopes": [],
            "supported_scope_count": 0,
        }

    conn.row_factory = sqlite3.Row
    run_times = {sector: _sector_run_times(conn, sector) for sector in SECTORS}
    cache: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = {}
    scopes = [
        _scope_metric(
            conn,
            sector=sector,
            term_months=term,
            window_days=window,
            run_times=run_times[sector],
            cache=cache,
        )
        for sector in SECTORS
        for term in TERMS
        for window in WINDOWS
    ]
    supported = sum(1 for scope in scopes if scope["status"] == "supported")
    return {
        "version": "market-intelligence-v1",
        "status": "ready" if supported else "insufficient_history",
        "history_gate": {
            "minimum_window_coverage_ratio": MIN_HISTORY_RATIO,
            "maximum_window_coverage_ratio": MAX_HISTORY_RATIO,
            "windows_days": list(WINDOWS),
            "terms_months": list(TERMS),
            "sectors": list(SECTORS),
            "product_type": "term_deposit",
            "rate_field": "max_rate",
            "product_identity": "products.id",
            "source_precedence": "presentation.db_only_sources",
            "upper_tier_definition": "top_ceil_10pct_cutoff",
            "churn_definition": "top_decile_jaccard_distance",
        },
        "supported_scope_count": supported,
        "scopes": scopes,
    }
