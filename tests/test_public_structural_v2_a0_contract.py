from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "data" / "public_structural_v2_market_position_vectors.json"
FINAL_PLAN = ROOT / "docs" / "specs" / "20260822-public-structural-v2-decision-cockpit-final.md"
RATE_EXPONENT = Decimal("0.0001")


def _quantize(value: str | float) -> Decimal:
    return Decimal(str(value)).quantize(RATE_EXPONENT)


def _expand(case: dict) -> list[Decimal]:
    rates: list[Decimal] = []
    anchor_rate = _quantize(case["anchor_rate"])
    removed_anchor = False
    for cluster in case["clusters"]:
        rate = _quantize(cluster["rate"])
        for _ in range(int(cluster["count"])):
            if rate == anchor_rate and not removed_anchor:
                removed_anchor = True
                continue
            rates.append(rate)
    assert removed_anchor, f"{case['name']}: anchor rate must exist"
    return rates


def _relation(candidate: Decimal, competitor: Decimal) -> str:
    if candidate > competitor:
        return "ahead"
    if candidate < competitor:
        return "behind"
    return "tied"


def _expected_from_contract(case: dict) -> dict[str, int | str]:
    competitor_rates = _expand(case)
    current = _quantize(case["current_rate"])
    proposal = _quantize(case["proposal_rate"])
    universe_count = len(competitor_rates) + 1

    higher = sum(rate > proposal for rate in competitor_rates)
    ties = sum(rate == proposal for rate in competitor_rates)

    transitions = {
        "newly_outpriced": 0,
        "newly_tied": 0,
        "newly_lost_to": 0,
        "newly_tied_down": 0,
    }
    for rate in competitor_rates:
        before = _relation(current, rate)
        after = _relation(proposal, rate)
        if before in {"behind", "tied"} and after == "ahead":
            transitions["newly_outpriced"] += 1
        if before == "behind" and after == "tied":
            transitions["newly_tied"] += 1
        if before in {"ahead", "tied"} and after == "behind":
            transitions["newly_lost_to"] += 1
        if before == "ahead" and after == "tied":
            transitions["newly_tied_down"] += 1

    counterfactual = sorted([*competitor_rates, proposal], reverse=True)

    def cutoff(share: float) -> Decimal:
        count = max(1, math.ceil(universe_count * share))
        return counterfactual[count - 1]

    return {
        "universe_count": universe_count,
        "higher_count": higher,
        "tie_competitor_count": ties,
        "rank_best": higher + 1,
        "rank_worst": higher + ties + 1,
        "top10_cutoff": f"{cutoff(0.10):.4f}",
        "top25_cutoff": f"{cutoff(0.25):.4f}",
        **transitions,
    }


def test_a0_vectors_match_the_approved_market_position_contract() -> None:
    payload = json.loads(VECTORS.read_text(encoding="utf-8"))

    assert payload["version"] == "public-structural-v2-market-position-v1"
    assert payload["rate_normalization_decimals"] == 4
    assert payload["counterfactual"] == "replace_anchor_product"
    assert payload["cases"]

    for case in payload["cases"]:
        assert _expected_from_contract(case) == case["expected"], case["name"]


def test_final_plan_closes_review_blockers_before_implementation() -> None:
    text = FINAL_PLAN.read_text(encoding="utf-8")

    required = (
        "공동순위 범위",
        "소수점 4자리로 정규화",
        "replace",
        "newly_outpriced",
        "시장 순위·밀집도 변화는 금액식에 직접 반영되지 않습니다",
        "structural amount target finder 제외",
        "`rank efficiency` 삭제",
        "absorbing boundary",
        "고정 5bp grid의 인접점",
        "Pareto/dominance 기능은 제외",
    )
    for phrase in required:
        assert phrase in text

    forbidden_headlines = (
        "top_share_pct = rank / N",
        "추천금리 자동",
    )
    for phrase in forbidden_headlines:
        assert phrase not in text
