"""Strategy 금리결정·시장근거 세부 refinement presentation 계약."""

from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.inflow_prediction_service import SCENARIOS
from rate_monitor.services.strategy_decision_cockpit import inject_strategy_decision_cockpit
from rate_monitor.services.strategy_decision_evidence_refinement_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_decision_evidence_refinement,
)

ROOT = Path(__file__).resolve().parents[1]


def _fixture() -> str:
    return """<!doctype html>
<html>
<head>
<style id="strategy-workspace-style"></style>
<style id="strategy-ux-refinement-style"></style>
<style id="strategy-readability-preference-v2-style"></style>
</head>
<body>
<section id="planning-zone"><div id="prediction-panel"></div></section>
<section id="market-flow"></section>
</body>
</html>"""


def test_injection_is_idempotent_and_fails_closed() -> None:
    once = inject_strategy_decision_evidence_refinement(_fixture())
    twice = inject_strategy_decision_evidence_refinement(once)

    assert once == twice
    assert once.count(STYLE_MARKER) == 1
    assert once.count(SCRIPT_MARKER) == 1

    with pytest.raises(DashboardBuildError, match="선행 계약"):
        inject_strategy_decision_evidence_refinement(
            "<html><head></head><body><section id='market-flow'></section></body></html>"
        )


def test_prediction_readability_formula_and_three_sensitivity_contracts_are_explicit() -> None:
    html = inject_strategy_decision_evidence_refinement(_fixture())

    assert ".workspace-decision .planning-strip b{color:#2e1c32" in html
    assert ".workspace-decision .prediction-head b" in html
    assert "font-size:16px!important" in html
    assert "계산 수식 · 숫자가 만들어지는 순서" in html
    assert "rate_steps = (제안금리 − 현재 당사금리) ÷ 0.10%p" in html
    assert "신규자금 = 최근월 신규수신 × exp" in html
    assert "logit(p1) = logit(현재 재예치율) + γ × rate_steps" in html
    assert "총수신 = 신규자금 + 재예치액" in html
    assert "모형 근거 · 외부 연구 / 가정 경계" in html
    assert 'className="decision-model-evidence"' in html
    assert 'data-sensitivity="${esc(s.key)}"' in html
    assert "decision-range-legacy" in html
    assert "ensurePredictionBridge" in html
    assert "window.predictInflow=args=>predictAll(args)" in html

    assert [scenario.label for scenario in SCENARIOS] == ["저민감", "기준", "고민감"]
    assert [scenario.new_money_log_change_per_10bp for scenario in SCENARIOS] == [
        0.02,
        0.05,
        0.10,
    ]
    assert [scenario.rollover_log_odds_change_per_10bp for scenario in SCENARIOS] == [
        0.04,
        0.08,
        0.16,
    ]


def test_market_evidence_copy_separates_flows_rates_snapshot_and_events() -> None:
    html = inject_strategy_decision_evidence_refinement(_fixture())

    assert "업권 수신잔액 흐름" in html
    assert "공식 월간통계 최신 공표월" in html
    assert "예금은행 순수저축성예금 신규취급액 가중평균" in html
    assert "예금은행 1년 정기예금 신규취급액 가중평균" in html
    assert "공시상품 단순평균 아님" in html
    assert "아직 공표되지 않은 월을 추정·보간하지 않습니다" in html
    assert "동일 stable product의 시작/종료 snapshot" in html
    assert "최근 30일 상품변경 이벤트" in html
    assert "인상 ${Number(item.up_count||0)" in html
    assert "인하 ${Number(item.down_count||0)" in html
    assert "이동없음 ${Number(item.unchanged_count||0)" in html
    assert "상위 10% 구성 교체율" in html
    assert "상위군 churn" not in html


def test_trend_defaults_to_bp_delta_and_recent_events_stay_open() -> None:
    html = inject_strategy_decision_evidence_refinement(_fixture())

    assert 'const trendState={mode:"delta"}' in html
    assert "기준일 대비 변화(bp)" in html
    assert "각 선의 첫 관측값을 0bp" in html
    assert "절대 금리 수준(%)" in html
    assert "details.open=true" in html
    assert 'if(!details.open)details.open=true' in html


def test_decision_ia_moves_insight_and_top5_under_readiness() -> None:
    html = inject_strategy_decision_evidence_refinement(_fixture())

    assert 'readiness.insertAdjacentElement("afterend",insight)' in html
    assert '(insight||readiness).insertAdjacentElement("afterend",top5)' in html
    assert 'title.textContent="금리결정 인사이트"' in html
    assert 'if(interpretation)interpretation.hidden=true' in html
    assert 'if(primary)primary.hidden=true' in html
    assert 'labelProduct.querySelector("strong").textContent="상품·우대조건 설계"' in html
    assert 'tag==="저축은행 시장 방향"||tag==="당사 위치"' in html


def test_full_strategy_cockpit_composes_refinement_after_readability() -> None:
    template = (ROOT / "web/templates/strategy.html").read_text(encoding="utf-8")
    html = inject_strategy_decision_cockpit(template)

    assert STYLE_MARKER in html
    assert SCRIPT_MARKER in html
    assert html.index('id="strategy-readability-preference-v2-script"') < html.index(
        SCRIPT_MARKER
    )
