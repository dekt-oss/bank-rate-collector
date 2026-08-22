"""Public Structural v2의 실제 시장위치 계산 엔진.

이 모듈은 현재 Strategy 비교상품의 실제 금리만 사용한다. 수신금액 민감도나
내부실적은 사용하지 않는다. 제안금리 counterfactual은 현재 당사 anchor 상품 1개를
제거하고 동일 자리에 proposal을 넣는 replace 계약이다.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any

from rate_monitor.db.types import MAX_RATE, RATE_EXPONENT

MARKET_POSITION_VERSION = "public-structural-v2-market-position-v1"
TOP10_SHARE = Decimal("0.10")
TOP25_SHARE = Decimal("0.25")
CROWDING_5BP = Decimal("0.05")
CROWDING_10BP = Decimal("0.10")


def normalize_rate(value: object) -> Decimal:
    """저장 Rate 계약과 같은 소수 4자리 금리값으로 정규화한다."""
    try:
        rate = Decimal(str(value)).quantize(RATE_EXPONENT)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("rate는 소수 4자리로 정규화 가능한 숫자여야 한다") from exc
    if not rate.is_finite() or rate < 0 or rate > MAX_RATE:
        raise ValueError("rate가 지원 범위를 벗어났다")
    return rate


def public_market_position_config() -> dict[str, Any]:
    return {
        "version": MARKET_POSITION_VERSION,
        "rate_normalization_decimals": 4,
        "counterfactual": "replace_anchor_product",
        "top10_share": float(TOP10_SHARE),
        "top25_share": float(TOP25_SHARE),
        "crowding_windows_pp": [float(CROWDING_5BP), float(CROWDING_10BP)],
    }


def _row_product_id(row: dict[str, Any]) -> str:
    product_id = str(row.get("product_id") or "").strip()
    if not product_id:
        raise ValueError("product_id가 필요하다")
    return product_id


def _normalized_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise ValueError("market rows가 비어 있다")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        product_id = _row_product_id(row)
        if product_id in seen:
            raise ValueError(f"duplicate product_id: {product_id}")
        seen.add(product_id)
        normalized.append({"product_id": product_id, "rate": normalize_rate(row.get("rate"))})
    return normalized


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal(2)


def _cutoff(values: list[Decimal], share: Decimal) -> Decimal:
    ordered = sorted(values, reverse=True)
    count = max(1, math.ceil(len(ordered) * float(share)))
    return ordered[count - 1]


def _relation(candidate: Decimal, competitor: Decimal) -> str:
    if candidate > competitor:
        return "ahead"
    if candidate < competitor:
        return "behind"
    return "tied"


def _to_float(value: Decimal) -> float:
    return float(value.quantize(RATE_EXPONENT))


def _gap_bp(left: Decimal, right: Decimal) -> float:
    return float(((left - right) * Decimal(100)).quantize(Decimal("0.01")))


def market_position(
    *,
    rows: list[dict[str, Any]],
    anchor_product_id: str,
    current_own_rate: float,
    proposal_rate: float,
) -> dict[str, Any]:
    """제안금리의 factual market position을 counterfactual replace로 계산한다."""
    normalized = _normalized_rows(rows)
    anchor_id = str(anchor_product_id or "").strip()
    if not anchor_id:
        raise ValueError("anchor_product_id가 필요하다")

    current = normalize_rate(current_own_rate)
    proposal = normalize_rate(proposal_rate)
    anchor_rows = [row for row in normalized if row["product_id"] == anchor_id]
    if len(anchor_rows) != 1:
        raise ValueError("anchor_product_id는 market rows에서 정확히 1개여야 한다")
    if anchor_rows[0]["rate"] != current:
        raise ValueError("anchor rate와 current_own_rate가 일치하지 않는다")

    competitors = [row for row in normalized if row["product_id"] != anchor_id]
    competitor_rates = [row["rate"] for row in competitors]
    counterfactual_rates = [*competitor_rates, proposal]
    universe_count = len(counterfactual_rates)

    higher = sum(rate > proposal for rate in competitor_rates)
    ties = sum(rate == proposal for rate in competitor_rates)
    rank_best = higher + 1
    rank_worst = higher + ties + 1

    mean_rate = sum(counterfactual_rates, Decimal(0)) / Decimal(universe_count)
    median_rate = _median(counterfactual_rates)
    top10 = _cutoff(counterfactual_rates, TOP10_SHARE)
    top25 = _cutoff(counterfactual_rates, TOP25_SHARE)
    market_max = max(counterfactual_rates)

    transitions = {
        "newly_outpriced": 0,
        "newly_tied": 0,
        "newly_lost_to": 0,
        "newly_tied_down": 0,
    }
    for row in competitors:
        before = _relation(current, row["rate"])
        after = _relation(proposal, row["rate"])
        if before in {"behind", "tied"} and after == "ahead":
            transitions["newly_outpriced"] += 1
        if before == "behind" and after == "tied":
            transitions["newly_tied"] += 1
        if before in {"ahead", "tied"} and after == "behind":
            transitions["newly_lost_to"] += 1
        if before == "ahead" and after == "tied":
            transitions["newly_tied_down"] += 1

    exact_tie_count = ties
    within_5bp = sum(abs(rate - proposal) <= CROWDING_5BP for rate in competitor_rates)
    within_10bp = sum(abs(rate - proposal) <= CROWDING_10BP for rate in competitor_rates)

    return {
        "version": MARKET_POSITION_VERSION,
        "status": "ready",
        "universe_count": universe_count,
        "proposal_rate": _to_float(proposal),
        "rank_best": rank_best,
        "rank_worst": rank_worst,
        "tie_competitor_count": ties,
        "mean_rate": _to_float(mean_rate),
        "median_rate": _to_float(median_rate),
        "top25_cutoff": _to_float(top25),
        "top10_cutoff": _to_float(top10),
        "market_max_rate": _to_float(market_max),
        "gap_to_mean_bp": _gap_bp(proposal, mean_rate),
        "gap_to_median_bp": _gap_bp(proposal, median_rate),
        "gap_to_top25_bp": _gap_bp(proposal, top25),
        "gap_to_top10_bp": _gap_bp(proposal, top10),
        "gap_to_market_max_bp": _gap_bp(proposal, market_max),
        "exact_tie_count": exact_tie_count,
        "within_5bp_count": within_5bp,
        "within_10bp_count": within_10bp,
        "top25_reached": proposal >= top25,
        "top25_exceeded": proposal > top25,
        "top10_reached": proposal >= top10,
        "top10_exceeded": proposal > top10,
        "market_max_reached": proposal >= market_max,
        "market_max_exceeded": proposal > market_max,
        **transitions,
    }
