"""Public Structural v2의 provider-agnostic Decision Surface.

시장위치는 실제 비교상품으로 계산하고, 수신금액은 sanitized public forecast를
사용한다. 두 영역은 같은 후보금리 축을 공유하지만 인과관계로 합치지 않는다.
"""

from __future__ import annotations

from typing import Any

from rate_monitor.services.public_structural_v2_decision_contract import (
    build_candidate_rate_sets,
    build_public_structural_v2_forecast,
)
from rate_monitor.services.public_structural_v2_market_position_service import market_position

SURFACE_VERSION = "public-structural-v2-decision-surface-v1"
RANGE_SEMANTICS = "uncalibrated_stress_range_not_prediction_interval"
MARKET_AMOUNT_RELATION = "separate_no_direct_market_effect_in_amount_formula"
DISCLOSURE = (
    "구조적 수신 시나리오는 현재 대비 당사 금리변화폭에 대한 미보정 민감도입니다. "
    "시장 순위·밀집도 변화는 금액식에 직접 반영되지 않습니다."
)


def _unique_sorted(rates: list[float]) -> list[float]:
    return sorted(set(rates))


def build_public_structural_v2_surface(
    *,
    generated_at: str,
    market_rows: list[dict[str, Any]],
    anchor_product_id: str,
    current_own_rate: float,
    proposal_rate: float,
    economics_min_rate: float,
    economics_max_rate: float,
    baseline_new_money: float,
    maturity_amount: float,
    current_rollover_rate_pct: float,
    term_months: int,
) -> dict[str, Any]:
    """시장 factual + sanitized structural forecast를 분리된 view model로 반환한다."""
    proposal_position = market_position(
        rows=market_rows,
        anchor_product_id=anchor_product_id,
        current_own_rate=current_own_rate,
        proposal_rate=proposal_rate,
    )
    candidate_set = build_candidate_rate_sets(
        current_rate=current_own_rate,
        proposal_rate=proposal_rate,
        top25_cutoff=float(proposal_position["top25_cutoff"]),
        top10_cutoff=float(proposal_position["top10_cutoff"]),
        market_max_rate=float(proposal_position["market_max_rate"]),
        economics_min_rate=economics_min_rate,
        economics_max_rate=economics_max_rate,
    )
    display_rates = _unique_sorted(
        [*candidate_set["economics_grid"], float(candidate_set["proposal_rate"])]
    )
    market_positions = [
        market_position(
            rows=market_rows,
            anchor_product_id=anchor_product_id,
            current_own_rate=current_own_rate,
            proposal_rate=rate,
        )
        for rate in display_rates
    ]
    forecast = build_public_structural_v2_forecast(
        generated_at=generated_at,
        candidate_rates=display_rates,
        baseline_new_money=baseline_new_money,
        maturity_amount=maturity_amount,
        current_rollover_rate_pct=current_rollover_rate_pct,
        current_own_rate=current_own_rate,
        term_months=term_months,
    )

    return {
        "version": SURFACE_VERSION,
        "generated_at": str(generated_at),
        "range_semantics": RANGE_SEMANTICS,
        "market_amount_relation": MARKET_AMOUNT_RELATION,
        "disclosure": DISCLOSURE,
        "candidate_set": candidate_set,
        "market_positions": market_positions,
        "forecast": forecast,
    }
