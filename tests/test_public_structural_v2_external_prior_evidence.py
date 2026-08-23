from __future__ import annotations

import calendar
import json
import sqlite3
from datetime import date, datetime, timedelta

from rate_monitor.services.public_structural_v2_external_prior_evidence import (
    BALANCE_CODES,
    BOK_MACRO_SOURCE,
    BOK_POLICY_SOURCE,
    COEFFICIENT_CHANGE_DECISION,
    POLICY_RATE_CODE,
    PRIMARY_RATE_CODE,
    RATE_SIGNAL_CODES,
    build_external_prior_evidence,
)


def _month_end(year: int, month: int, offset: int) -> date:
    total = year * 12 + month - 1 + offset
    target_year, month0 = divmod(total, 12)
    target_month = month0 + 1
    return date(
        target_year,
        target_month,
        calendar.monthrange(target_year, target_month)[1],
    )


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE market_indicators (
            indicator_code TEXT NOT NULL,
            indicator_name TEXT NOT NULL,
            source_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            source_effective_at TEXT,
            value TEXT NOT NULL,
            unit TEXT NOT NULL,
            validation_status TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            sector TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE collection_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL
        )
        """
    )
    return conn


def _insert_indicator(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    code: str,
    when: date,
    value: float,
    unit: str,
) -> None:
    conn.execute(
        """
        INSERT INTO market_indicators (
            indicator_code, indicator_name, source_id, observed_at,
            source_effective_at, value, unit, validation_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'valid')
        """,
        (
            code,
            code,
            source_id,
            f"{when.isoformat()}T12:00:00",
            when.isoformat(),
            f"{value:.6f}",
            unit,
        ),
    )


def _seed_public_series(conn: sqlite3.Connection, months: int = 48) -> None:
    rate_levels: dict[str, list[float]] = {code: [] for code in RATE_SIGNAL_CODES}
    base_rates = {
        PRIMARY_RATE_CODE: 3.0,
        RATE_SIGNAL_CODES[1]: 3.05,
        RATE_SIGNAL_CODES[2]: 3.1,
    }
    monthly_delta_pp = (0.05, 0.02, 0.0, -0.03, -0.01, 0.04)

    for offset in range(months):
        when = _month_end(2022, 1, offset)
        for index, code in enumerate(RATE_SIGNAL_CODES):
            previous = rate_levels[code][-1] if rate_levels[code] else base_rates[code]
            if offset:
                previous += monthly_delta_pp[(offset + index) % len(monthly_delta_pp)]
            rate_levels[code].append(previous)
            _insert_indicator(
                conn,
                source_id=BOK_MACRO_SOURCE,
                code=code,
                when=when,
                value=previous,
                unit="percent",
            )

        policy = 3.0 + 0.25 * ((offset // 8) % 3)
        _insert_indicator(
            conn,
            source_id=BOK_POLICY_SOURCE,
            code=POLICY_RATE_CODE,
            when=when,
            value=policy,
            unit="percent",
        )

    primary = rate_levels[PRIMARY_RATE_CODE]
    for sector_index, (_sector, code) in enumerate(BALANCE_CODES.items()):
        balance = 100.0 + sector_index * 20.0
        for offset in range(months):
            when = _month_end(2022, 1, offset)
            if offset:
                prior_rate_change_bp = 0.0
                if offset > 1:
                    prior_rate_change_bp = (
                        primary[offset - 1] - primary[offset - 2]
                    ) * 100
                growth_pct = 0.15 + 0.025 * prior_rate_change_bp + sector_index * 0.005
                balance *= 1.0 + growth_pct / 100.0
            _insert_indicator(
                conn,
                source_id=BOK_MACRO_SOURCE,
                code=code,
                when=when,
                value=balance,
                unit="trillion_krw",
            )

    for sector in ("savings_bank", "cu", "kfcc", "nh_local"):
        source_id = f"source-{sector}"
        conn.execute("INSERT INTO sources (id, sector) VALUES (?, ?)", (source_id, sector))
        for offset in range(3):
            month = _month_end(2026, 6, offset)
            started = datetime(month.year, month.month, 1)
            conn.execute(
                """
                INSERT INTO collection_runs (id, source_id, started_at, finished_at, status)
                VALUES (?, ?, ?, ?, 'success')
                """,
                (
                    f"{sector}-{offset}",
                    source_id,
                    started.isoformat(),
                    (started + timedelta(minutes=5)).isoformat(),
                ),
            )
    conn.commit()


def test_strong_aggregate_association_does_not_authorize_coefficient_change() -> None:
    conn = _connection()
    _seed_public_series(conn)

    evidence = build_external_prior_evidence(conn)

    assert evidence["status"] == "ready"
    assert evidence["gate"]["coefficient_change"] == COEFFICIENT_CHANGE_DECISION == "NO_GO"
    assert evidence["gate"]["public_prior_role"] == "context_only_not_parameter_calibration"
    assert (
        "aggregate_series_do_not_identify_bank_specific_new_money_or_rollover_response"
        in evidence["gate"]["blocking_reasons"]
    )
    assert evidence["interpretation_contract"]["bank_specific_elasticity"] == "not_identified"

    lag_one = evidence["associations"]["savings_bank"][PRIMARY_RATE_CODE][1]
    assert lag_one["status"] == "descriptive_only"
    assert lag_one["pair_count"] >= 36
    assert lag_one["role"] == "descriptive_association_not_causal"
    assert lag_one["chronological_split"]["status"] == "descriptive_stability_check"


def test_time_order_regime_and_sample_size_are_explicit() -> None:
    conn = _connection()
    _seed_public_series(conn)

    evidence = build_external_prior_evidence(conn)
    screen = evidence["temporal_oos_screen"]["savings_bank"]
    regime = evidence["regime_summary"]["savings_bank"]

    assert evidence["source_scope"]["lags_months"] == [0, 1, 2, 3]
    assert screen["required_train_months"] == 24
    assert screen["required_holdout_months"] == 12
    assert screen["aggregate_temporal_split_feasible"] is True
    assert screen["meaning"] == "aggregate_context_only_not_bank_specific_oos"
    assert regime["basis"] == "primary_bank_rate_monthly_change_sign"
    assert sum(regime[key]["month_count"] for key in ("rising", "flat", "falling")) > 0


def test_repo_market_history_is_only_supplementary_context() -> None:
    conn = _connection()
    _seed_public_series(conn)

    evidence = build_external_prior_evidence(conn)
    repo_history = evidence["repo_market_history"]

    assert repo_history["status"] == "ready"
    assert repo_history["role"] == "supplementary_public_market_history_not_calibration_target"
    assert repo_history["sectors"]["savings_bank"]["successful_run_count"] == 3
    assert repo_history["sectors"]["savings_bank"]["distinct_calendar_months"] == 3


def test_missing_public_series_fails_closed_to_partial_no_go() -> None:
    conn = _connection()
    _insert_indicator(
        conn,
        source_id=BOK_MACRO_SOURCE,
        code=PRIMARY_RATE_CODE,
        when=date(2026, 7, 31),
        value=3.0,
        unit="percent",
    )
    conn.commit()

    evidence = build_external_prior_evidence(conn)

    assert evidence["status"] == "partial"
    assert evidence["gate"]["coefficient_change"] == "NO_GO"
    assert "required_public_series_missing" in evidence["gate"]["blocking_reasons"]
    assert evidence["source_scope"]["missing_required_series"]


def test_missing_schema_is_no_go_without_fake_evidence() -> None:
    conn = sqlite3.connect(":memory:")

    evidence = build_external_prior_evidence(conn)

    assert evidence["status"] == "schema_unavailable"
    assert evidence["gate"]["coefficient_change"] == "NO_GO"
    assert evidence["gate"]["blocking_reasons"] == ["market_indicator_schema_unavailable"]


def test_public_evidence_output_contains_no_bank_specific_parameters() -> None:
    conn = _connection()
    _seed_public_series(conn)

    serialized = json.dumps(build_external_prior_evidence(conn), ensure_ascii=False).lower()

    assert '"beta"' not in serialized
    assert '"gamma"' not in serialized
    assert "recommended_rate" not in serialized
    assert "optimal_rate" not in serialized
    assert "achievement_probability" not in serialized
