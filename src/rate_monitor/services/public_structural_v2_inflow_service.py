"""Public Structural v2의 미보정 수신반응 엔진.

v1의 low/base/high 민감도 계수와 신규자금 exponential 구조는 그대로 사용한다.
차이는 재예치 확률 경계 처리다. exact 0%/100%는 logit의 수학적 극한처럼
absorbing boundary로 유지하고, (0, 1) 내부에서만 logit shift를 적용한다.

이 모델은 시장 순위·밀집도를 금액식에 반영하지 않는다. 시장위치는 별도 factual
layer가 계산하며, 두 값을 인과관계처럼 해석해서는 안 된다.
"""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

from rate_monitor.services.inflow_prediction_service import (
    MAX_ABS_NEW_MONEY_LOG_EFFECT,
    RATE_STEP_PERCENTAGE_POINT,
    SCENARIOS,
    SensitivityScenario,
)

MODEL_VERSION = "inflow-structural-v2-public"
CALIBRATION_STATUS = "uncalibrated"
MARKET_POSITION_EFFECT = "not_applied_to_amount_formula"
_ZERO_STEP_TOLERANCE = 1e-12


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name}은 유한한 숫자여야 한다")
    return number


def _nonnegative(name: str, value: float) -> float:
    number = _finite(name, value)
    if number < 0:
        raise ValueError(f"{name}은 0 이상이어야 한다")
    return number


def _probability_from_percent(value: float) -> float:
    percent = _finite("current_rollover_rate_pct", value)
    if percent < 0 or percent > 100:
        raise ValueError("current_rollover_rate_pct는 0~100 범위여야 한다")
    return percent / 100.0


def _logit(probability: float) -> float:
    return math.log(probability / (1.0 - probability))


def _logistic(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _round_amount(value: float) -> float:
    return round(value, 4)


def shift_rollover_probability(probability: float, log_odds_delta: float) -> float:
    """재예치 확률을 log-odds만큼 이동하되 exact boundary를 보존한다."""
    p0 = _finite("probability", probability)
    delta = _finite("log_odds_delta", log_odds_delta)
    if p0 < 0 or p0 > 1:
        raise ValueError("probability는 0~1 범위여야 한다")
    if p0 == 0.0 or p0 == 1.0 or abs(delta) <= _ZERO_STEP_TOLERANCE:
        return p0
    return _logistic(_logit(p0) + delta)


def public_structural_v2_config() -> dict[str, Any]:
    """브라우저 mirror가 공유할 공개 구조모델 설정을 반환한다."""
    return {
        "version": MODEL_VERSION,
        "calibration_status": CALIBRATION_STATUS,
        "rate_step_percentage_point": RATE_STEP_PERCENTAGE_POINT,
        "max_abs_new_money_log_effect": MAX_ABS_NEW_MONEY_LOG_EFFECT,
        "rollover_transform": "logit_interior_exact_boundaries",
        "market_position_effect": MARKET_POSITION_EFFECT,
        "scenarios": [asdict(scenario) for scenario in SCENARIOS],
        "amount_unit": "KRW_100M",
        "rate_unit": "percent",
        "term_unit": "month",
        "cost_metric": "simple_surface_interest_total_delta",
        "coefficient_provenance": "uncalibrated_stress_assumptions",
    }


def predict_structural_v2_scenario(
    *,
    baseline_new_money: float,
    maturity_amount: float,
    current_rollover_rate_pct: float,
    current_own_rate: float,
    proposed_rate: float,
    term_months: int,
    scenario: SensitivityScenario,
) -> dict[str, float | str]:
    """한 민감도 시나리오의 신규자금·재예치·총수신을 계산한다."""
    baseline = _nonnegative("baseline_new_money", baseline_new_money)
    maturity = _nonnegative("maturity_amount", maturity_amount)
    own_rate = _finite("current_own_rate", current_own_rate)
    proposed = _finite("proposed_rate", proposed_rate)
    if term_months <= 0:
        raise ValueError("term_months는 1 이상이어야 한다")

    p0 = _probability_from_percent(current_rollover_rate_pct)
    relative_change = proposed - own_rate
    rate_steps = relative_change / RATE_STEP_PERCENTAGE_POINT

    raw_log_effect = scenario.new_money_log_change_per_10bp * rate_steps
    log_effect = max(
        -MAX_ABS_NEW_MONEY_LOG_EFFECT,
        min(MAX_ABS_NEW_MONEY_LOG_EFFECT, raw_log_effect),
    )
    new_money_multiplier = math.exp(log_effect)
    predicted_new = baseline * new_money_multiplier

    rollover_delta = scenario.rollover_log_odds_change_per_10bp * rate_steps
    predicted_rollover_probability = shift_rollover_probability(p0, rollover_delta)
    predicted_rollover = maturity * predicted_rollover_probability

    baseline_rollover = maturity * p0
    baseline_total = baseline + baseline_rollover
    predicted_total = predicted_new + predicted_rollover
    incremental_total = predicted_total - baseline_total

    term_factor = term_months / 12.0
    baseline_surface_interest = baseline_total * own_rate / 100.0 * term_factor
    predicted_surface_interest = predicted_total * proposed / 100.0 * term_factor
    surface_interest_delta = predicted_surface_interest - baseline_surface_interest

    return {
        "scenario": scenario.key,
        "relative_change_pp": round(relative_change, 4),
        "rate_steps_10bp": round(rate_steps, 6),
        "raw_new_money_log_effect": round(raw_log_effect, 6),
        "applied_new_money_log_effect": round(log_effect, 6),
        "new_money_multiplier": round(new_money_multiplier, 6),
        "predicted_new_money": _round_amount(predicted_new),
        "baseline_rollover_rate_pct": round(p0 * 100.0, 4),
        "predicted_rollover_rate_pct": round(
            predicted_rollover_probability * 100.0,
            4,
        ),
        "predicted_rollover": _round_amount(predicted_rollover),
        "baseline_total": _round_amount(baseline_total),
        "predicted_total": _round_amount(predicted_total),
        "incremental_total": _round_amount(incremental_total),
        "baseline_surface_interest": _round_amount(baseline_surface_interest),
        "predicted_surface_interest": _round_amount(predicted_surface_interest),
        "surface_interest_delta": _round_amount(surface_interest_delta),
    }


def predict_structural_v2_range(
    *,
    baseline_new_money: float,
    maturity_amount: float,
    current_rollover_rate_pct: float,
    current_own_rate: float,
    proposed_rate: float,
    term_months: int,
) -> dict[str, Any]:
    """저/기준/고민감 결과와 실제 min/max stress range를 반환한다."""
    results = {
        scenario.key: predict_structural_v2_scenario(
            baseline_new_money=baseline_new_money,
            maturity_amount=maturity_amount,
            current_rollover_rate_pct=current_rollover_rate_pct,
            current_own_rate=current_own_rate,
            proposed_rate=proposed_rate,
            term_months=term_months,
            scenario=scenario,
        )
        for scenario in SCENARIOS
    }
    totals = [float(result["predicted_total"]) for result in results.values()]
    return {
        "model": public_structural_v2_config(),
        "base": results["base"],
        "scenarios": results,
        "predicted_total_range": {
            "min": _round_amount(min(totals)),
            "max": _round_amount(max(totals)),
        },
    }
