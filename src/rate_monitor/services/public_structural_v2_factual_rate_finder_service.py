"""Public Structural v2 Stage G factual-only 시장조건 금리 finder.

당사 anchor를 제거한 competitor-only 현재 시장에서 TOP10/TOP25/시장 최고 benchmark를
고정한 뒤, 현재 Strategy UI에서 선택 가능한 최소 금리만 계산한다. 제안금리,
수신금액, 구조 시나리오, 내부실적은 입력받지 않는다.
"""

from __future__ import annotations

import math
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any

from rate_monitor.db.types import MAX_RATE, RATE_EXPONENT
from rate_monitor.services.public_structural_v2_market_position_service import normalize_rate

FACTUAL_RATE_FINDER_VERSION = "public-structural-v2-factual-rate-finder-v1"
BENCHMARK_UNIVERSE = "competitor_only_anchor_removed"
SELECTION_SEMANTICS = "strategy_ui_selectable_granularity_not_business_pricing_policy"
DEFAULT_SELECTION_STEP_PP = Decimal("0.01")
TOP10_SHARE = Decimal("0.10")
TOP25_SHARE = Decimal("0.25")


def _normalize_selection_step(value: object) -> Decimal:
    try:
        step = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("selection step은 숫자여야 한다") from exc
    if not step.is_finite() or step <= 0 or step > MAX_RATE:
        raise ValueError("selection step이 지원 범위를 벗어났다")
    units = step / RATE_EXPONENT
    if units != units.to_integral_value():
        raise ValueError("selection step은 RATE_EXPONENT의 정수배여야 한다")
    return step.quantize(RATE_EXPONENT)


def _normalized_market_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise ValueError("market rows가 비어 있다")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        product_id = str(row.get("product_id") or "").strip()
        if not product_id:
            raise ValueError("product_id가 필요하다")
        if product_id in seen:
            raise ValueError(f"duplicate product_id: {product_id}")
        seen.add(product_id)
        normalized.append({"product_id": product_id, "rate": normalize_rate(row.get("rate"))})
    return normalized


def _cutoff(values: list[Decimal], share: Decimal) -> Decimal:
    ordered = sorted(values, reverse=True)
    count = max(1, math.ceil(len(ordered) * float(share)))
    return ordered[count - 1]


def _to_float(value: Decimal) -> float:
    return float(value.quantize(RATE_EXPONENT))


def competitor_market_benchmarks(
    *,
    rows: list[dict[str, Any]],
    anchor_product_id: str,
    current_own_rate: object,
) -> dict[str, Any]:
    """당사 anchor와 proposal을 제외한 현재 competitor-only benchmark를 반환한다."""
    normalized = _normalized_market_rows(rows)
    anchor_id = str(anchor_product_id or "").strip()
    if not anchor_id:
        raise ValueError("anchor_product_id가 필요하다")
    current = normalize_rate(current_own_rate)
    anchor_rows = [row for row in normalized if row["product_id"] == anchor_id]
    if len(anchor_rows) != 1:
        raise ValueError("anchor_product_id는 market rows에서 정확히 1개여야 한다")
    if anchor_rows[0]["rate"] != current:
        raise ValueError("anchor rate와 current_own_rate가 일치하지 않는다")

    competitor_rates = [row["rate"] for row in normalized if row["product_id"] != anchor_id]
    if not competitor_rates:
        raise ValueError("competitor-only benchmark를 계산할 비교상품이 없다")

    return {
        "benchmark_universe": BENCHMARK_UNIVERSE,
        "competitor_count": len(competitor_rates),
        "top10_cutoff": _to_float(_cutoff(competitor_rates, TOP10_SHARE)),
        "top25_cutoff": _to_float(_cutoff(competitor_rates, TOP25_SHARE)),
        "market_max_rate": _to_float(max(competitor_rates)),
    }


def _ceil_to_step(rate: Decimal, step: Decimal) -> Decimal:
    ticks = (rate / step).to_integral_value(rounding=ROUND_CEILING)
    return (ticks * step).quantize(RATE_EXPONENT)


def _minimum_reach(rate: Decimal, step: Decimal) -> Decimal | None:
    candidate = _ceil_to_step(rate, step)
    return candidate if candidate <= MAX_RATE else None


def _minimum_exceed(rate: Decimal, step: Decimal) -> Decimal | None:
    candidate = _ceil_to_step(rate, step)
    if candidate <= rate:
        candidate = (candidate + step).quantize(RATE_EXPONENT)
    return candidate if candidate <= MAX_RATE else None


def _condition(
    *,
    target: str,
    relation: str,
    label: str,
    benchmark: Decimal,
    minimum: Decimal | None,
    reason: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "target": target,
        "relation": relation,
        "label": label,
        "benchmark_rate_pct": _to_float(benchmark),
        "status": "ready" if minimum is not None else "unavailable",
    }
    if minimum is not None:
        row["minimum_selectable_rate_pct"] = _to_float(minimum)
    else:
        row["reason"] = reason or "minimum_selectable_rate_out_of_range"
    return row


def factual_rate_constraints(
    *,
    rows: list[dict[str, Any]],
    anchor_product_id: str,
    current_own_rate: object,
    selection_step_pp: object = DEFAULT_SELECTION_STEP_PP,
) -> dict[str, Any]:
    """competitor-only benchmark에 대한 factual 조건충족 최소 선택금리를 계산한다."""
    step = _normalize_selection_step(selection_step_pp)
    benchmarks = competitor_market_benchmarks(
        rows=rows,
        anchor_product_id=anchor_product_id,
        current_own_rate=current_own_rate,
    )
    top10 = normalize_rate(benchmarks["top10_cutoff"])
    top25 = normalize_rate(benchmarks["top25_cutoff"])
    market_max = normalize_rate(benchmarks["market_max_rate"])

    market_max_tie = market_max if market_max % step == 0 else None
    conditions = [
        _condition(
            target="top10",
            relation="reach",
            label="상위 10% 진입선 도달",
            benchmark=top10,
            minimum=_minimum_reach(top10, step),
        ),
        _condition(
            target="top10",
            relation="exceed",
            label="상위 10% 진입선 초과",
            benchmark=top10,
            minimum=_minimum_exceed(top10, step),
        ),
        _condition(
            target="top25",
            relation="reach",
            label="상위 25% 진입선 도달",
            benchmark=top25,
            minimum=_minimum_reach(top25, step),
        ),
        _condition(
            target="top25",
            relation="exceed",
            label="상위 25% 진입선 초과",
            benchmark=top25,
            minimum=_minimum_exceed(top25, step),
        ),
        _condition(
            target="market_max",
            relation="tie",
            label="시장 최고 동률",
            benchmark=market_max,
            minimum=market_max_tie,
            reason="exact_tie_not_selectable_on_ui_grid",
        ),
        _condition(
            target="market_max",
            relation="exceed",
            label="시장 최고 초과",
            benchmark=market_max,
            minimum=_minimum_exceed(market_max, step),
        ),
    ]
    return {
        "version": FACTUAL_RATE_FINDER_VERSION,
        "status": "ready",
        "benchmark_universe": BENCHMARK_UNIVERSE,
        "competitor_count": benchmarks["competitor_count"],
        "selection_step_pp": _to_float(step),
        "selection_step_bp": float(step * Decimal(100)),
        "selection_semantics": SELECTION_SEMANTICS,
        "conditions": conditions,
    }
