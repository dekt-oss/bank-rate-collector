"""Stage C2 Market Intelligence presentation 계약."""

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.market_intelligence_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_market_intelligence_presentation,
)
from rate_monitor.services.strategy_decision_cockpit import inject_strategy_decision_cockpit


def _minimal_html() -> str:
    return """
    <html><head></head><body>
      <script id="rate-monitor-data" type="application/json">
      {"strategy":{"market_intelligence":{"scopes":[]}}}
      </script>
      <section id="market-flow"></section>
    </body></html>
    """


def test_market_intelligence_briefing_is_injected_once() -> None:
    rendered = inject_market_intelligence_presentation(_minimal_html())

    assert rendered.count(STYLE_MARKER) == 1
    assert rendered.count(SCRIPT_MARKER) == 1
    assert "최근 시장 금리 경쟁 방향" in rendered
    assert 'savings_bank:"저축은행"' in rendered
    assert 'cu:"신협"' in rendered
    assert 'kfcc:"새마을금고"' in rendered
    assert 'nh_local:"농·축협"' in rendered
    assert 'data-mi-sector="${k}"' in rendered
    assert "[6,12,24,36]" in rendered
    assert 'data-mi-term="${v}"' in rendered
    assert "[7,30]" in rendered
    assert 'data-mi-window="${v}"' in rendered
    assert "market_intelligence" in rendered
    assert "observed_days" in rendered
    assert "coverage_ratio" in rendered
    assert "upper_decile_change_bp" in rendered
    assert "top_decile_churn_rate" in rendered
    assert "spread_change_bp" in rendered
    assert "근거가 확보되기 전에는 0 또는 추정값으로 대체하지 않습니다" in rendered

    assert inject_market_intelligence_presentation(rendered) == rendered


def test_market_intelligence_partial_injection_fails_closed() -> None:
    html = _minimal_html().replace("</head>", f"<style {STYLE_MARKER}></style></head>")

    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_market_intelligence_presentation(html)


def test_stage_b_composition_adds_c2_only_for_full_strategy_contract() -> None:
    html = """
    <html><head></head><body>
      <script id="rate-monitor-data" type="application/json">
      {"strategy":{"market_intelligence":{"scopes":[]}}}
      </script>
      <div id="prediction-panel"></div>
      <section id="market-flow"></section>
      <script>function predictInflow(){return {}}</script>
    </body></html>
    """

    rendered = inject_strategy_decision_cockpit(html)

    assert rendered.count('id="rate-response-cockpit-style"') == 1
    assert rendered.count('id="market-intelligence-briefing-style"') == 1
    assert rendered.count('id="market-intelligence-briefing-script"') == 1
