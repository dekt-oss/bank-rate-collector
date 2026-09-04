# ruff: noqa: E501
from __future__ import annotations

import inspect

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)
from rate_monitor.services.strategy_decision_scope_compact_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_decision_scope_compact,
)


def _strategy_html() -> str:
    return (
        "<html><head></head><body><main>"
        '<div id="market-scope"></div>'
        '<section class="ux-decision-readiness">'
        '<div class="ux-readiness-title"><span>DECISION READINESS</span><strong>금리결정 준비도</strong><p>설명</p></div>'
        '<div class="ux-readiness-grid">'
        '<div class="ux-readiness-item ready"><b>A</b><span>a</span></div>'
        '<div class="ux-readiness-item ready"><b>B</b><span>b</span></div>'
        '<div class="ux-readiness-item pending"><b>C</b><span>c</span></div>'
        '<div class="ux-readiness-foot"><b>현재 결론:</b> 기존 경계</div>'
        "</div></section></main></body></html>"
    )


def test_compact_decision_scope_injection_is_idempotent() -> None:
    rendered = inject_strategy_decision_scope_compact(_strategy_html())

    assert STYLE_MARKER in rendered
    assert SCRIPT_MARKER in rendered
    assert rendered.count(STYLE_MARKER) == 1
    assert rendered.count(SCRIPT_MARKER) == 1
    assert inject_strategy_decision_scope_compact(rendered) == rendered


def test_compact_decision_scope_preserves_safety_boundary_in_business_language() -> None:
    rendered = inject_strategy_decision_scope_compact(_strategy_html())

    assert "의사결정 범위" in rendered
    assert "시장 비교 가능" in rendered
    assert "수신반응은 시나리오" in rendered
    assert "최적금리 자동추천은 아직 불가" in rendered
    assert "내부 실적 보정 전에는 최적금리 자동추천으로 해석하지 않습니다." in rendered
    assert 'card.dataset.decisionScopeCompact="1"' in rendered
    assert 'data-decision-scope-compact="1"' in rendered


def test_compact_decision_scope_hides_visible_internal_kicker_without_deleting_owner_dom() -> None:
    rendered = inject_strategy_decision_scope_compact(_strategy_html())

    assert '.ux-readiness-title>span{display:none!important}' in rendered
    assert 'const kicker=title.querySelector("span")' in rendered
    assert 'kicker.textContent=""' in rendered
    assert "remove()" not in rendered


def test_compact_decision_scope_partial_injection_fails_closed() -> None:
    html = _strategy_html().replace(
        "</head>",
        '<style id="strategy-decision-scope-compact-style"></style></head>',
        1,
    )

    with pytest.raises(DashboardBuildError, match="decision-scope compact"):
        inject_strategy_decision_scope_compact(html)


def test_non_strategy_html_is_unchanged() -> None:
    html = "<html><head></head><body><main>search</main></body></html>"
    assert inject_strategy_decision_scope_compact(html) == html


def test_compact_decision_scope_composes_after_market_direction() -> None:
    source = inspect.getsource(inject_dashboard_ui_refinement)
    direction = source.index("inject_strategy_market_direction(rendered)")
    compact = source.index("inject_strategy_decision_scope_compact(rendered)")

    assert direction < compact
