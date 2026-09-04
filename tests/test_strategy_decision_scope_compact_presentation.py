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


def test_decision_scope_is_four_step_navigation_with_safety_boundary() -> None:
    rendered = inject_strategy_decision_scope_compact(_strategy_html())

    assert "의사결정 메뉴" in rendered
    assert "금리 의사결정 4단계 바로가기" in rendered
    assert 'data-decision-step="market"' in rendered
    assert 'data-decision-step="competitors"' in rendered
    assert 'data-decision-step="detail"' in rendered
    assert 'data-decision-step="boundary"' in rendered
    assert '>01</span>' in rendered
    assert '>02</span>' in rendered
    assert '>03</span>' in rendered
    assert '>04</span>' in rendered
    assert "시장 방향" in rendered
    assert "경쟁사 TOP5" in rendered
    assert "세부 비교" in rendered
    assert "자동추천 범위" in rendered
    assert "scrollIntoView" in rendered
    assert "내부 실적 보정 전에는 최적금리 자동추천으로 해석하지 않습니다." in rendered
    assert 'card.dataset.decisionScopeCompact="1"' in rendered
    assert 'data-decision-scope-compact="1"' in rendered


def test_decision_scope_preserves_owner_dom_but_hides_old_readiness_items() -> None:
    rendered = inject_strategy_decision_scope_compact(_strategy_html())

    assert '.ux-readiness-title>span{display:none!important}' in rendered
    assert '.ux-readiness-item{display:none!important}' in rendered
    assert 'const kicker=title.querySelector("span")' in rendered
    assert 'kicker.textContent=""' in rendered
    assert "remove()" not in rendered


def test_decision_navigation_resolves_targets_at_click_time() -> None:
    rendered = inject_strategy_decision_scope_compact(_strategy_html())

    assert 'market:[".strategy-market-direction"]' in rendered
    assert 'competitors:[".top5-card"]' in rendered
    assert 'detail:[".market-flow",".workspace-decision","#planning-zone"]' in rendered
    assert 'boundary:["#planning-zone",".prediction-panel"]' in rendered
    assert "resolveTarget(step)" in rendered
    assert "gotoStep(button.dataset.decisionStep)" in rendered


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
