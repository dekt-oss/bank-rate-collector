"""수신상품 전략 화면의 내부 실적 보정 전 구조 예측엔진.

현재 저장소에는 고려저축은행 상품별 실제 신규취급액·만기도래액·재예치액의
학습 이력이 없다. 따라서 여기의 계수는 은행별 추정치가 아니라 민감도 스트레스
밴드다. 계산 구조와 단위를 고정해 두고, 향후 내부 실적을 확보하면 같은 공개
계약을 유지한 채 계수만 보정하는 것이 목적이다.

현재 계산식의 단계별 설명과 숫자 예제:
``docs/specs/20260822-inflow-structural-v1-calculation-guide.md``
외부 방법론 근거와 현재 미검증 가정의 구분:
``docs/specs/20260822-inflow-structural-v1-evidence-registry.md``

금리 숫자는 ``3.70 == 연 3.70%``처럼 percent 단위다. 10bp는 0.10%p다.
금액은 억원, 기간은 개월이다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

MODEL_VERSION = "inflow-structural-v1"
CALIBRATION_STATUS = "uncalibrated"
RATE_STEP_PERCENTAGE_POINT = 0.10
MAX_ABS_NEW_MONEY_LOG_EFFECT = 1.5
_MIN_PROBABILITY = 0.001
_MAX_PROBABILITY = 0.999
_ZERO_STEP_TOLERANCE = 1e-12


@dataclass(frozen=True)
class SensitivityScenario:
    """+10bp 상대포지션 이동에 대한 미보정 민감도 스트레스 가정."""

    key: str
    label: str
    new_money_log_change_per_10bp: float
    rollover_log_odds_change_per_10bp: float


SCENARIOS: tuple[SensitivityScenario, ...] = (
    SensitivityScenario(
        key="low",
        label="저민감",
        new_money_log_change_per_10bp=0.02,
        rollover_log_odds_change_per_10bp=0.04,
    ),
    SensitivityScenario(
        key="base",
        label="기준",
        new_money_log_change_per_10bp=0.05,
        rollover_log_odds_change_per_10bp=0.08,
    ),
    SensitivityScenario(
        key="high",
        label="고민감",
        new_money_log_change_per_10bp=0.10,
        rollover_log_odds_change_per_10bp=0.16,
    ),
)


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


def public_model_config() -> dict[str, Any]:
    """브라우저 계산기가 Python 엔진과 같은 계약을 쓰도록 공개 설정을 반환한다."""
    return {
        "version": MODEL_VERSION,
        "calibration_status": CALIBRATION_STATUS,
        "rate_step_percentage_point": RATE_STEP_PERCENTAGE_POINT,
        "baseline_anchor": "current_our_max_rate",
        "relative_market_reference": "market_top10_rate",
        "max_abs_new_money_log_effect": MAX_ABS_NEW_MONEY_LOG_EFFECT,
        "rollover_probability_guardrail": {
            "min": _MIN_PROBABILITY,
            "max": _MAX_PROBABILITY,
        },
        "scenarios": [asdict(scenario) for scenario in SCENARIOS],
        "amount_unit": "KRW_100M",
        "rate_unit": "percent",
        "term_unit": "month",
        "cost_metric": "simple_surface_interest_total_delta",
        "coefficient_provenance": "uncalibrated_stress_assumptions",
    }


def predict_scenario(
    *,
    baseline_new_money: float,
    maturity_amount: float,
    current_rollover_rate_pct: float,
    current_own_rate: float,
    proposed_rate: float,
    market_top10_rate: float,
    term_months: int,
    scenario: SensitivityScenario,
) -> dict[str, float | str]:
    """한 민감도 시나리오의 신규자금·재예치·총수신을 계산한다.

    ``baseline_new_money``는 현재 당사 대표금리에서 관측한 월 신규취급액 anchor다.
    시장 top10선 자체를 고정한 counterfactual이므로 금액 변화는 현재 대비 상대금리
    이동량으로 계산한다. top10 gap은 현재/제안 포지션을 감사할 수 있도록 별도 반환한다.
    """
    baseline = _nonnegative("baseline_new_money", baseline_new_money)
    maturity = _nonnegative("maturity_amount", maturity_amount)
    own_rate = _finite("current_own_rate", current_own_rate)
    proposed = _finite("proposed_rate", proposed_rate)
    top10 = _finite("market_top10_rate", market_top10_rate)
    if term_months <= 0:
        raise ValueError("term_months는 1 이상이어야 한다")

    p0 = _probability_from_percent(current_rollover_rate_pct)
    current_gap = own_rate - top10
    proposed_gap = proposed - top10
    relative_change = proposed_gap - current_gap
    rate_steps = relative_change / RATE_STEP_PERCENTAGE_POINT

    raw_log_effect = scenario.new_money_log_change_per_10bp * rate_steps
    log_effect = max(
        -MAX_ABS_NEW_MONEY_LOG_EFFECT,
        min(MAX_ABS_NEW_MONEY_LOG_EFFECT, raw_log_effect),
    )
    new_money_multiplier = math.exp(log_effect)
    predicted_new = baseline * new_money_multiplier

    if abs(rate_steps) <= _ZERO_STEP_TOLERANCE:
        predicted_rollover_probability = p0
    else:
        logit_anchor = min(_MAX_PROBABILITY, max(_MIN_PROBABILITY, p0))
        rollover_logit = (
            _logit(logit_anchor)
            + scenario.rollover_log_odds_change_per_10bp * rate_steps
        )
        predicted_rollover_probability = _logistic(rollover_logit)
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
        "current_top10_gap_pp": round(current_gap, 4),
        "proposed_top10_gap_pp": round(proposed_gap, 4),
        "relative_change_pp": round(relative_change, 4),
        "rate_steps_10bp": round(rate_steps, 6),
        "raw_new_money_log_effect": round(raw_log_effect, 6),
        "applied_new_money_log_effect": round(log_effect, 6),
        "new_money_multiplier": round(new_money_multiplier, 6),
        "predicted_new_money": _round_amount(predicted_new),
        "baseline_rollover_rate_pct": round(p0 * 100.0, 4),
        "predicted_rollover_rate_pct": round(
            predicted_rollover_probability * 100.0, 4
        ),
        "predicted_rollover": _round_amount(predicted_rollover),
        "baseline_total": _round_amount(baseline_total),
        "predicted_total": _round_amount(predicted_total),
        "incremental_total": _round_amount(incremental_total),
        "baseline_surface_interest": _round_amount(baseline_surface_interest),
        "predicted_surface_interest": _round_amount(predicted_surface_interest),
        "surface_interest_delta": _round_amount(surface_interest_delta),
    }


def predict_range(
    *,
    baseline_new_money: float,
    maturity_amount: float,
    current_rollover_rate_pct: float,
    current_own_rate: float,
    proposed_rate: float,
    market_top10_rate: float,
    term_months: int,
) -> dict[str, Any]:
    """저/기준/고민감 결과와 총수신 범위를 한 번에 반환한다."""
    results = {
        scenario.key: predict_scenario(
            baseline_new_money=baseline_new_money,
            maturity_amount=maturity_amount,
            current_rollover_rate_pct=current_rollover_rate_pct,
            current_own_rate=current_own_rate,
            proposed_rate=proposed_rate,
            market_top10_rate=market_top10_rate,
            term_months=term_months,
            scenario=scenario,
        )
        for scenario in SCENARIOS
    }
    totals = [float(result["predicted_total"]) for result in results.values()]
    return {
        "model": public_model_config(),
        "base": results["base"],
        "scenarios": results,
        "predicted_total_range": {
            "min": _round_amount(min(totals)),
            "max": _round_amount(max(totals)),
        },
    }
