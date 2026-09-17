"""Strategy market-first workspace presentation 계약."""

from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_decision_cockpit import inject_strategy_decision_cockpit
from rate_monitor.services.strategy_workspace_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_workspace_presentation,
)

ROOT = Path(__file__).resolve().parents[1]


def _full_strategy_fixture() -> str:
    return """<!doctype html>
<html>
<head><title>strategy</title></head>
<body>
<script id="rate-monitor-data" type="application/json">{"strategy":{}}</script>
<section class="evidence-strip"><article class="evidence-card"></article></section>
<section class="grid kpis">
  <article class="kpi"></article><article class="kpi"></article>
</section>
<section class="planning-zone" id="planning-zone">
  <section id="prediction-panel"></section>
</section>
<section id="external-market-context"><h2>외부 자금환경</h2></section>
<section id="market-intelligence"><h2>시장 방향</h2></section>
<section class="grid market-flow" id="market-flow">
  <section class="card chartcard"><h2>기간별 현재금리</h2></section>
  <details class="card changes" open>
    <summary>최근 시장 변화 <span class="chip">30D</span></summary>
  </details>
</section>
<section class="grid interpretation">
  <article class="insightcard"><h2>상품구조</h2></article>
  <article class="preference-card"></article>
</section>
<section id="preference-intelligence"><h2>우대조건</h2></section>
<section class="grid primary">
  <article class="mapcard"><h2>지역별 금리</h2><div class="mapstage"></div></article>
  <article class="top5-card"><h2>경쟁사 TOP 5</h2></article>
</section>
<section id="special-offer-radar"><h2>시장 특판 Radar</h2></section>
<section id="market-funding-competition"><h2>수신시장 · 기관별 자금조달 경쟁</h2></section>
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

    assert 'market-first-v2' in html
    assert '01","시장현황"' in html
    assert '02","금리설계"' in html
    assert '03","상세 판단요소"' in html
    assert 'moveAfter(kpis,cursor)' in html
    assert 'moveAfter(planning,cursor)' in html
    assert 'moveAfter(primary,cursor)' in html
    assert '기존 우대조건 트렌드 요약' in html
    assert '민감도 범위 · 예측모형 상세' in html
    assert 'body.appendChild(predictionResults)' in html
    assert 'predictInflow' not in html.split(SCRIPT_MARKER, 1)[1]


def test_desktop_left_navigation_uses_real_feature_names() -> None:
    html = inject_strategy_workspace_presentation(_full_strategy_fixture())

    for label in (
        "시장 요약",
        "금리 움직임",
        "당사 시장 위치",
        "신상품 금리 시뮬레이션",
        "경쟁사 · Peer 분석",
        "지역별 금리",
        "우대조건 · 상품구조",
        "특판 · 시장기회",
        "외부 자금환경",
        "데이터 근거 · 품질",
    ):
        assert label in html
    assert 'left:18px' in html
    assert '@media(max-width:1280px){.strategy-workspace-nav{display:none!important}}' in html
    assert 'aria-label=\"전략화면 바로가기\"' in html
    assert 'aria-current","location"' in html
    assert 'IntersectionObserver' in html


def test_detail_sections_default_to_disclosure_and_nav_reveals_targets() -> None:
    html = inject_strategy_workspace_presentation(_full_strategy_fixture())

    assert 'disclosure.id=\"workspace-detail-disclosure\"' in html
    assert 'className=\"workspace-detail-disclosure\"' in html
    assert 'wrapDetailDisclosure([detailLabel,primary,interpretation,pref,special,external' in html
    assert 'target.closest(\"details.workspace-detail-disclosure\")' in html
    assert 'disclosure.open=true' in html
    assert 'window.addEventListener(\"hashchange\",activateHash)' in html
    assert '<details id="workspace-detail-disclosure" open' not in html


def test_market_direction_and_change_event_contracts_are_visually_separated() -> None:
    html = inject_strategy_workspace_presentation(_full_strategy_fixture())

    assert "최근 30일 금리 변경 이벤트" in html
    assert "실제 금리가 바뀐 상품 이벤트만 집계합니다" in html
    assert "전체 비교상품의 인상·유지·인하 비중" in html
    assert 'changes.removeAttribute("open")' in html


def test_mobile_density_and_detail_compaction_are_explicit() -> None:
    html = inject_strategy_workspace_presentation(_full_strategy_fixture())

    assert '.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}' in html
    assert '.evidence-strip{grid-template-columns:repeat(2,minmax(0,1fr))}' in html
    assert '.workspace-detail.primary:not(.busan-focus) .mapstage{height:270px}' in html
    assert '.primary.busan-focus' not in html
    assert 'external-context-rates,.external-context-flows{display:flex;overflow-x:auto' in html
    assert '.workspace-model-detail>summary' in html
    assert '.workspace-detail-disclosure>summary span{display:none}' in html


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


def test_workspace_spec_preserves_market_first_and_release_boundaries() -> None:
    spec = (ROOT / "docs/specs/20260917-strategy-market-first-ia-v2.md").read_text(
        encoding="utf-8"
    )

    assert "시장현황 → 금리설계 → 상세 판단요소" in spec
    assert "왼쪽 floating navigation" in spec
    assert "최근 30일 금리 변경 이벤트" in spec
    assert "대표 시장방향" in spec
    assert "계산 계약을 변경하지 않는다" in spec
    assert "Production Strategy Release Gate" in spec


def test_injection_fails_closed_without_existing_layout_contract() -> None:
    with pytest.raises(DashboardBuildError, match="기존 레이아웃 계약"):
        inject_strategy_workspace_presentation("<html><head></head><body></body></html>")


def test_partial_injection_fails_closed() -> None:
    partial = _full_strategy_fixture().replace(
        "</head>", f'<style {STYLE_MARKER}></style></head>'
    )
    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_strategy_workspace_presentation(partial)
