"""Strategy decision-first workspace presentation 계약."""

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_decision_cockpit import inject_strategy_decision_cockpit
from rate_monitor.services.strategy_workspace_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_workspace_presentation,
)


def _full_strategy_fixture() -> str:
    return """<!doctype html>
<html>
<head><title>strategy</title></head>
<body>
<script id="rate-monitor-data" type="application/json">{"strategy":{}}</script>
<section class="grid kpis"><article class="kpi"></article><article class="kpi"></article></section>
<section class="planning-zone" id="planning-zone"><section id="prediction-panel"></section></section>
<section id="external-market-context"></section>
<section id="market-intelligence"></section>
<section class="grid market-flow" id="market-flow"><details class="card changes" open></details></section>
<section class="grid interpretation"><article class="preference-card"></article></section>
<section id="preference-intelligence"></section>
<section class="grid primary"><article class="mapcard"><div class="mapstage"></div></article></section>
<script>function predictInflow(args){return args}</script>
</body>
</html>"""


def test_injection_is_idempotent() -> None:
    once = inject_strategy_workspace_presentation(_full_strategy_fixture())
    twice = inject_strategy_workspace_presentation(once)

    assert once == twice
    assert once.count(STYLE_MARKER) == 1
    assert once.count(SCRIPT_MARKER) == 1


def test_workspace_reorders_existing_sections_without_new_calculation() -> None:
    html = inject_strategy_workspace_presentation(_full_strategy_fixture())

    assert 'decision-first-v1' in html
    assert 'evidenceAnchor.parentNode.insertBefore(planning,evidenceAnchor)' in html
    assert 'pref.parentNode.insertBefore(interpretation,pref)' in html
    assert 'detailAfter.insertAdjacentElement("afterend",primary)' in html
    assert 'changes.removeAttribute("open")' in html
    assert '기존 우대조건 트렌드 요약' in html
    assert '01","금리 결정"' in html
    assert '02","시장 근거"' in html
    assert '03","상품 설계"' in html
    assert '04","지역 · 경쟁사 상세"' in html


def test_mobile_density_and_detail_compaction_are_explicit() -> None:
    html = inject_strategy_workspace_presentation(_full_strategy_fixture())

    assert '.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}' in html
    assert '.evidence-strip{grid-template-columns:repeat(2,minmax(0,1fr))}' in html
    assert '.workspace-detail.primary:not(.busan-focus) .mapstage{height:270px}' in html
    assert '.primary.busan-focus' not in html
    assert 'external-context-rates,.external-context-flows{display:flex;overflow-x:auto' in html


def test_workspace_preserves_busan_focus_by_only_compacting_non_focus_map() -> None:
    html = inject_strategy_workspace_presentation(_full_strategy_fixture())

    assert 'workspace-detail.primary:not(.busan-focus)' in html
    assert 'workspace-detail.primary.busan-focus' not in html


def test_decision_cockpit_composes_workspace_after_existing_presentations() -> None:
    html = inject_strategy_decision_cockpit(_full_strategy_fixture())

    assert STYLE_MARKER in html
    assert SCRIPT_MARKER in html
    assert 'id="market-intelligence-briefing-script"' in html
    assert 'id="external-market-context-script"' in html
    assert 'id="preference-intelligence-script"' in html
    assert html.index('id="preference-intelligence-script"') < html.index(SCRIPT_MARKER)


def test_injection_fails_closed_without_existing_layout_contract() -> None:
    with pytest.raises(DashboardBuildError, match="기존 레이아웃 계약"):
        inject_strategy_workspace_presentation("<html><head></head><body></body></html>")


def test_partial_injection_fails_closed() -> None:
    partial = _full_strategy_fixture().replace(
        "</head>", f'<style {STYLE_MARKER}></style></head>'
    )
    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_strategy_workspace_presentation(partial)
