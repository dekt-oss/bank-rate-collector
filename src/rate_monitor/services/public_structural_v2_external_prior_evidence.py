"""Public Structural v2 Stage I 공개자료 External Prior Evidence Gate.

이 모듈은 공개 BOK/시장 시계열의 시간순서·시차·regime·표본길이를
기술통계 수준에서 점검한다. 결과는 aggregate context일 뿐이며 은행별
신규자금/재예치 elasticity나 인과효과로 해석하지 않는다.
"""

from __future__ import annotations

import calendar
import math
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime
from statistics import median
from typing import Any

EVIDENCE_VERSION = "public-structural-v2-external-prior-evidence-v1"
EVIDENCE_ROLE = "descriptive_association_not_causal"
COEFFICIENT_CHANGE_DECISION = "NO_GO"
PUBLIC_PRIOR_ROLE = "context_only_not_parameter_calibration"

BOK_MACRO_SOURCE = "bok_ecos_macro"
BOK_POLICY_SOURCE = "bok_ecos"
POLICY_RATE_CODE = "bok_base_rate"
PRIMARY_RATE_CODE = "bok_bank_pure_savings_deposit_rate"
RATE_SIGNAL_CODES = (
    PRIMARY_RATE_CODE,
    "bok_bank_savings_deposit_rate",
    "bok_bank_term_deposit_1y_rate",
)
BALANCE_CODES = {
    "savings_bank": "bok_savings_bank_deposit_balance",
    "credit_union": "bok_credit_union_deposit_balance",
    "broad_mutual_finance": "bok_broad_mutual_finance_deposit_balance",
    "kfcc": "bok_kfcc_deposit_balance",
}
REPO_MARKET_SECTORS = ("savings_bank", "cu", "kfcc", "nh_local")
LAGS_MONTHS = (0, 1, 2, 3)

# 연구 충분성 screen일 뿐 통계적 유의성 기준이 아니다. 너무 적은 점으로
# correlation 숫자를 노출하지 않기 위한 최소 descriptive pair 수다.
MIN_DESCRIPTIVE_PAIRS = 8
MIN_SPLIT_PAIRS_PER_HALF = 6
# aggregate 시계열의 시간분할 가능성만 보는 research screen이다.
# 은행별 coefficient 변경 허용조건이 아니며, 24개월 학습 + 12개월 후행검증을 뜻한다.
TEMPORAL_TRAIN_MONTHS = 24
TEMPORAL_HOLDOUT_MONTHS = 12


class EvidenceDataError(ValueError):
    """Stage I 공개자료 계약을 만족하지 못한 경우."""


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _month_key(value: object) -> str | None:
    text = str(value or "").strip()[:10]
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed.strftime("%Y-%m")


def _month_number(month: str) -> int:
    year, mon = (int(part) for part in month.split("-", 1))
    return year * 12 + mon - 1


def _shift_month(month: str, offset: int) -> str:
    total = _month_number(month) + offset
    year, month0 = divmod(total, 12)
    return f"{year:04d}-{month0 + 1:02d}"


def _month_end(month: str) -> date:
    year, mon = (int(part) for part in month.split("-", 1))
    return date(year, mon, calendar.monthrange(year, mon)[1])


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _indicator_series(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    indicator_code: str,
) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT source_effective_at, value
        FROM market_indicators
        WHERE source_id = ?
          AND indicator_code = ?
          AND validation_status = 'valid'
          AND source_effective_at IS NOT NULL
        ORDER BY source_effective_at
        """,
        (source_id, indicator_code),
    ).fetchall()
    result: dict[str, float] = {}
    for raw_date, raw_value in rows:
        month = _month_key(raw_date)
        if month is None:
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            result[month] = value
    return result


def _coverage(series: dict[str, float]) -> dict[str, Any]:
    months = sorted(series, key=_month_number)
    if not months:
        return {
            "status": "no_data",
            "point_count": 0,
            "first_month": None,
            "last_month": None,
            "calendar_span_months": 0,
        }
    return {
        "status": "ready",
        "point_count": len(months),
        "first_month": months[0],
        "last_month": months[-1],
        "calendar_span_months": _month_number(months[-1]) - _month_number(months[0]) + 1,
    }


def _consecutive_rate_changes(series: dict[str, float]) -> dict[str, float]:
    changes: dict[str, float] = {}
    months = sorted(series, key=_month_number)
    for previous, current in zip(months, months[1:], strict=False):
        if _month_number(current) - _month_number(previous) != 1:
            continue
        changes[current] = round((series[current] - series[previous]) * 100.0, 6)
    return changes


def _consecutive_balance_growth(series: dict[str, float]) -> dict[str, float]:
    growth: dict[str, float] = {}
    months = sorted(series, key=_month_number)
    for previous, current in zip(months, months[1:], strict=False):
        if _month_number(current) - _month_number(previous) != 1:
            continue
        before = series[previous]
        if before <= 0:
            continue
        growth[current] = round((series[current] / before - 1.0) * 100.0, 6)
    return growth


def _month_end_policy_series(
    conn: sqlite3.Connection,
    target_months: Iterable[str],
) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT source_effective_at, value
        FROM market_indicators
        WHERE source_id = ?
          AND indicator_code = ?
          AND validation_status = 'valid'
          AND source_effective_at IS NOT NULL
        ORDER BY source_effective_at
        """,
        (BOK_POLICY_SOURCE, POLICY_RATE_CODE),
    ).fetchall()
    points: list[tuple[date, float]] = []
    for raw_date, raw_value in rows:
        text = str(raw_date or "").strip()[:10]
        try:
            when = date.fromisoformat(text)
            value = float(raw_value)
        except (ValueError, TypeError):
            continue
        if math.isfinite(value):
            points.append((when, value))

    result: dict[str, float] = {}
    for month in sorted(set(target_months), key=_month_number):
        cutoff = _month_end(month)
        eligible = [value for when, value in points if when <= cutoff]
        if eligible:
            result[month] = eligible[-1]
    return result


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    dx = [value - mean_x for value in xs]
    dy = [value - mean_y for value in ys]
    denom_x = math.sqrt(sum(value * value for value in dx))
    denom_y = math.sqrt(sum(value * value for value in dy))
    if denom_x == 0 or denom_y == 0:
        return None
    return round(sum(x * y for x, y in zip(dx, dy, strict=True)) / (denom_x * denom_y), 4)


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        average = (cursor + 1 + end) / 2.0
        for position in order[cursor:end]:
            ranks[position] = average
        cursor = end
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return _pearson(_average_ranks(xs), _average_ranks(ys))


def _aligned_pairs(
    rate_changes: dict[str, float],
    balance_growth: dict[str, float],
    *,
    lag_months: int,
) -> list[tuple[str, float, float]]:
    pairs: list[tuple[str, float, float]] = []
    for outcome_month in sorted(balance_growth, key=_month_number):
        signal_month = _shift_month(outcome_month, -lag_months)
        if signal_month in rate_changes:
            pairs.append(
                (
                    outcome_month,
                    rate_changes[signal_month],
                    balance_growth[outcome_month],
                )
            )
    return pairs


def _sign(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "zero"


def _association(pairs: list[tuple[str, float, float]], lag_months: int) -> dict[str, Any]:
    n = len(pairs)
    base: dict[str, Any] = {
        "lag_months": lag_months,
        "pair_count": n,
        "first_outcome_month": pairs[0][0] if pairs else None,
        "last_outcome_month": pairs[-1][0] if pairs else None,
        "role": EVIDENCE_ROLE,
        "pearson": None,
        "spearman": None,
        "chronological_split": {"status": "insufficient_pairs"},
    }
    if n < MIN_DESCRIPTIVE_PAIRS:
        return {**base, "status": "insufficient_pairs"}

    xs = [row[1] for row in pairs]
    ys = [row[2] for row in pairs]
    pearson = _pearson(xs, ys)
    spearman = _spearman(xs, ys)
    result = {**base, "status": "descriptive_only", "pearson": pearson, "spearman": spearman}

    midpoint = n // 2
    early = pairs[:midpoint]
    late = pairs[midpoint:]
    if len(early) < MIN_SPLIT_PAIRS_PER_HALF or len(late) < MIN_SPLIT_PAIRS_PER_HALF:
        return result
    early_pearson = _pearson([row[1] for row in early], [row[2] for row in early])
    late_pearson = _pearson([row[1] for row in late], [row[2] for row in late])
    result["chronological_split"] = {
        "status": "descriptive_stability_check",
        "early_pair_count": len(early),
        "late_pair_count": len(late),
        "early_pearson": early_pearson,
        "late_pearson": late_pearson,
        "sign_stable": (
            _sign(early_pearson) == _sign(late_pearson)
            and _sign(early_pearson) not in {"unavailable", "zero"}
        ),
    }
    return result


def _regime_summary(
    rate_changes: dict[str, float],
    balance_growth: dict[str, float],
) -> dict[str, Any]:
    buckets: dict[str, list[float]] = {"rising": [], "flat": [], "falling": []}
    for month, outcome in balance_growth.items():
        change = rate_changes.get(month)
        if change is None:
            continue
        if change > 0:
            buckets["rising"].append(outcome)
        elif change < 0:
            buckets["falling"].append(outcome)
        else:
            buckets["flat"].append(outcome)

    result: dict[str, Any] = {"basis": "primary_bank_rate_monthly_change_sign"}
    for key, values in buckets.items():
        result[key] = {
            "month_count": len(values),
            "median_balance_growth_pct": round(float(median(values)), 4) if values else None,
        }
    return result


def _repo_market_history(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "sources") or not _table_exists(conn, "collection_runs"):
        return {"status": "schema_unavailable", "sectors": {}}
    sectors: dict[str, Any] = {}
    for sector in REPO_MARKET_SECTORS:
        row = conn.execute(
            """
            SELECT MIN(COALESCE(r.finished_at, r.started_at)),
                   MAX(COALESCE(r.finished_at, r.started_at)),
                   COUNT(*),
                   COUNT(DISTINCT substr(COALESCE(r.finished_at, r.started_at), 1, 7))
            FROM collection_runs r
            JOIN sources s ON s.id = r.source_id
            WHERE s.sector = ?
              AND r.status IN ('success', 'partial', 'no_change')
              AND COALESCE(r.finished_at, r.started_at) IS NOT NULL
            """,
            (sector,),
        ).fetchone()
        first = _parse_datetime(row[0]) if row else None
        last = _parse_datetime(row[1]) if row else None
        span_days: float | None = None
        if first is not None and last is not None:
            try:
                span_days = round(max(0.0, (last - first).total_seconds() / 86400.0), 2)
            except TypeError:
                span_days = None
        sectors[sector] = {
            "first_snapshot_at": row[0] if row else None,
            "last_snapshot_at": row[1] if row else None,
            "successful_run_count": int(row[2] or 0) if row else 0,
            "distinct_calendar_months": int(row[3] or 0) if row else 0,
            "span_days": span_days,
        }
    return {
        "status": "ready",
        "role": "supplementary_public_market_history_not_calibration_target",
        "sectors": sectors,
    }


def build_external_prior_evidence(conn: sqlite3.Connection) -> dict[str, Any]:
    """공개 시계열을 기술적으로 점검하고 coefficient 변경 Gate를 반환한다."""
    if not _table_exists(conn, "market_indicators"):
        return {
            "version": EVIDENCE_VERSION,
            "status": "schema_unavailable",
            "evidence_role": EVIDENCE_ROLE,
            "gate": {
                "coefficient_change": COEFFICIENT_CHANGE_DECISION,
                "public_prior_role": PUBLIC_PRIOR_ROLE,
                "stress_range_status": "retain_uncalibrated_stress_assumptions",
                "blocking_reasons": ["market_indicator_schema_unavailable"],
            },
        }

    rate_levels = {
        code: _indicator_series(conn, source_id=BOK_MACRO_SOURCE, indicator_code=code)
        for code in RATE_SIGNAL_CODES
    }
    balance_levels = {
        sector: _indicator_series(
            conn,
            source_id=BOK_MACRO_SOURCE,
            indicator_code=indicator_code,
        )
        for sector, indicator_code in BALANCE_CODES.items()
    }
    target_months = set().union(*(series.keys() for series in rate_levels.values()))
    policy_levels = _month_end_policy_series(conn, target_months)

    rate_changes = {code: _consecutive_rate_changes(series) for code, series in rate_levels.items()}
    balance_growth = {
        sector: _consecutive_balance_growth(series) for sector, series in balance_levels.items()
    }

    associations: dict[str, Any] = {}
    regime: dict[str, Any] = {}
    temporal_screens: dict[str, Any] = {}
    primary_changes = rate_changes[PRIMARY_RATE_CODE]
    required_temporal_pairs = TEMPORAL_TRAIN_MONTHS + TEMPORAL_HOLDOUT_MONTHS

    for sector, outcome in balance_growth.items():
        sector_associations: dict[str, Any] = {}
        for code, signal in rate_changes.items():
            sector_associations[code] = [
                _association(
                    _aligned_pairs(signal, outcome, lag_months=lag),
                    lag,
                )
                for lag in LAGS_MONTHS
            ]
        associations[sector] = sector_associations
        regime[sector] = _regime_summary(primary_changes, outcome)
        primary_pair_counts = [
            len(_aligned_pairs(primary_changes, outcome, lag_months=lag))
            for lag in LAGS_MONTHS
        ]
        best_pair_count = max(primary_pair_counts, default=0)
        temporal_screens[sector] = {
            "best_primary_rate_aligned_pair_count": best_pair_count,
            "required_train_months": TEMPORAL_TRAIN_MONTHS,
            "required_holdout_months": TEMPORAL_HOLDOUT_MONTHS,
            "aggregate_temporal_split_feasible": best_pair_count >= required_temporal_pairs,
            "meaning": "aggregate_context_only_not_bank_specific_oos",
        }

    coverage = {
        "policy_rate": _coverage(policy_levels),
        "rate_signals": {code: _coverage(series) for code, series in rate_levels.items()},
        "sector_balances": {sector: _coverage(series) for sector, series in balance_levels.items()},
    }
    repo_history = _repo_market_history(conn)

    missing_required = [
        code
        for code in (PRIMARY_RATE_CODE, *BALANCE_CODES.values())
        if (
            coverage["rate_signals"].get(code, {}).get("status") == "no_data"
            if code in RATE_SIGNAL_CODES
            else next(
                (
                    details.get("status") == "no_data"
                    for sector, details in coverage["sector_balances"].items()
                    if BALANCE_CODES[sector] == code
                ),
                True,
            )
        )
    ]

    blockers = [
        "aggregate_series_do_not_identify_bank_specific_new_money_or_rollover_response",
        "no_bank_specific_new_money_rollover_decomposition_in_public_sources",
        "causal_identification_not_established_by_descriptive_time_series",
    ]
    if missing_required:
        blockers.append("required_public_series_missing")

    return {
        "version": EVIDENCE_VERSION,
        "status": "ready" if not missing_required else "partial",
        "evidence_role": EVIDENCE_ROLE,
        "source_scope": {
            "bok_macro_source": BOK_MACRO_SOURCE,
            "bok_policy_source": BOK_POLICY_SOURCE,
            "lags_months": list(LAGS_MONTHS),
            "rate_change_unit": "bp_per_month",
            "balance_growth_unit": "percent_mom",
            "missing_required_series": missing_required,
        },
        "coverage": coverage,
        "associations": associations,
        "regime_summary": regime,
        "temporal_oos_screen": temporal_screens,
        "repo_market_history": repo_history,
        "interpretation_contract": {
            "causal_claim": "prohibited",
            "bank_specific_elasticity": "not_identified",
            "correlations": "descriptive_context_only",
            "chronological_split": "stability_screen_not_model_validation",
            "aggregate_oos": "does_not_authorize_bank_specific_parameter_change",
        },
        "gate": {
            "coefficient_change": COEFFICIENT_CHANGE_DECISION,
            "public_prior_role": PUBLIC_PRIOR_ROLE,
            "stress_range_status": "retain_uncalibrated_stress_assumptions",
            "blocking_reasons": blockers,
        },
    }
