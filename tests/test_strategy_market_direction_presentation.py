from __future__ import annotations

import inspect

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)
from rate_monitor.services.strategy_market_direction_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_market_direction,
)


def _strategy_html() -> str:
    return (
        "<html><head></head><body><main>"
        '<div id="market-scope"></div>'
        '<script id="rate-monitor-data" type="application/json">'
        '{"strategy":{"market_changes":{"up_count":7,"down_count":3,"count":10}}}'
        "</script>"
        '<section class="ux-decision-readiness"></section>'
        "</main></body></html>"
    )


def test_market_direction_injection_is_idempotent() -> None:
    rendered = inject_strategy_market_direction(_strategy_html())

    assert STYLE_MARKER in rendered
    assert SCRIPT_MARKER in rendered
    assert rendered.count(STYLE_MARKER) == 1
    assert rendered.count(SCRIPT_MARKER) == 1
    assert inject_strategy_market_direction(rendered) == rendered


def test_market_direction_is_factual_event_balance_not_prediction_score() -> None:
    rendered = inject_strategy_market_direction(_strategy_html())

    assert "strategy?.market_changes" in rendered
    assert "up_count" in rendered
    assert "down_count" in rendered
    assert "up/total*100" in rendered
    assert 'up>down?"상승 우세":down>up?"하락 우세":"혼조"' in rendered
    assert "변화 없음" in rendered
    assert "실제 금리 변경 이벤트의 방향 균형을 표시합니다. 예측·추천 점수가 아닙니다." in rendered
    assert "강한 상향" not in rendered
    assert "약한 상향" not in rendered


def test_secondary_insights_are_preserved_in_closed_details() -> None:
    rendered = inject_strategy_market_direction(_strategy_html())

    assert 'document.querySelector(".decision-integrated-insight")' in rendered
    assert 'document.createElement("details")' in rendered
    assert 'summary.textContent="세부 인사이트"' in rendered
    assert 'details.append(insight)' in rendered
    assert 'details.open' not in rendered
    assert "경쟁강도·지역 편차·우대조건 구조 등 보조 판단 근거입니다." in rendered


def test_market_direction_partial_injection_fails_closed() -> None:
    html = _strategy_html().replace(
        "</head>",
        '<style id="strategy-market-direction-style"></style></head>',
        1,
    )

    with pytest.raises(DashboardBuildError, match="market-direction"):
        inject_strategy_market_direction(html)


def test_non_strategy_html_is_unchanged() -> None:
    html = "<html><head></head><body><main>search</main></body></html>"
    assert inject_strategy_market_direction(html) == html


def test_market_direction_composes_after_first_screen_ux() -> None:
    source = inspect.getsource(inject_dashboard_ui_refinement)
    first_screen = source.index("inject_strategy_first_screen_ux(rendered)")
    market_direction = source.index("inject_strategy_market_direction(rendered)")

    assert first_screen < market_direction
