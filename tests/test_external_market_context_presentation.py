from __future__ import annotations

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.external_market_context_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_external_market_context_presentation,
)
from tests.strategy_output_helper import built_strategy_html


def _minimal_html() -> str:
    return (
        "<html><head></head><body>"
        '<script id="rate-monitor-data" type="application/json">{}</script>'
        '<section id="market-flow"></section>'
        "</body></html>"
    )


def test_external_context_presentation_is_idempotent() -> None:
    once = inject_external_market_context_presentation(_minimal_html())
    twice = inject_external_market_context_presentation(once)

    assert once == twice
    assert once.count(STYLE_MARKER) == 1
    assert once.count(SCRIPT_MARKER) == 1
    assert 'panel.id="external-market-context"' in once


def test_partial_injection_fails_closed() -> None:
    html = _minimal_html().replace("</head>", f'<style {STYLE_MARKER}></style></head>')

    with pytest.raises(DashboardBuildError, match="불완전"):
        inject_external_market_context_presentation(html)


def test_built_strategy_contains_external_context_payload_and_semantic_guards() -> None:
    html = built_strategy_html()

    assert STYLE_MARKER in html
    assert SCRIPT_MARKER in html
    assert '"external_features"' in html
    assert "시장 자금환경" in html
    assert "은행 순수저축성예금 신규취급" in html
    assert "광의 상호금융 수신잔액 MoM" in html
    assert "농·축협과 1:1 동일하지 않음" in html
    assert "당사 수신효과나 인과를 추정한 값이 아닙니다" in html
    assert "은행채·CD·COFIX는 Stage E v1 직접변수에서 제외" in html
