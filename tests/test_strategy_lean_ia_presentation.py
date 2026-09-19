# ruff: noqa: E501
from __future__ import annotations

import inspect

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)
from rate_monitor.services.strategy_lean_ia_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_lean_ia,
)


def _strategy_html() -> str:
    return """<!doctype html>
<html>
<head>
<style id="strategy-workspace-style"></style>
<style id="strategy-top5-compact-style"></style>
</head>
<body>
<div id="market-scope"></div>
<script id="rate-monitor-data" type="application/json">{"strategy":{"market_changes":{"up_count":7,"down_count":3,"count":10}}}</script>
<section class="grid kpis"></section>
<section id="external-market-context"></section>
<section id="market-funding-competition"><div class="funding-market-strip"></div><div class="funding-sector-tabs"></div><div class="funding-analysis-grid"></div><div class="funding-caveat"></div></section>
<section id="market-intelligence"></section>
<section id="market-flow"><article class="chartcard"></article><details class="changes"></details></section>
<section id="planning-zone"><div class="planning-strip"><div><span>30일 변경 이벤트 방향</span><b id="plan-flow">—</b></div></div></section>
<section class="top5-card"><table><thead><tr><th>순위</th><th>업권</th><th>금융사 / 상품</th><th>기본금리</th><th>우대폭</th><th>최고금리</th></tr></thead><tbody id="top5"></tbody></table></section>
<section id="institution-funding-position"></section>
<section id="preference-intelligence"></section>
<section id="special-offer-radar"></section>
<section id="scope-evidence"></section>
<section id="relative-pricing-r1"></section>
<section id="rate-funding-matrix"></section>
<div class="ux-region-handoff"><a href="./">지역 상세 보기</a></div>
<details id="workspace-detail-disclosure"></details>
<script id="strategy-workspace-script"></script>
<script id="strategy-top5-compact-script"></script>
</body>
</html>"""


def test_lean_ia_injection_is_idempotent() -> None:
    once = inject_strategy_lean_ia(_strategy_html())
    twice = inject_strategy_lean_ia(once)

    assert once == twice
    assert once.count(STYLE_MARKER) == 1
    assert once.count(SCRIPT_MARKER) == 1


def test_non_strategy_and_minimal_strategy_are_noop() -> None:
    search = "<html><head></head><body><div id=\"reg\"></div></body></html>"
    bare = "<html><head></head><body><div id=\"market-scope\"></div></body></html>"

    assert inject_strategy_lean_ia(search) == search
    assert inject_strategy_lean_ia(bare) == bare


def test_partial_injection_fails_closed() -> None:
    partial = _strategy_html().replace(
        "</head>",
        '<style id="strategy-lean-ia-style"></style></head>',
        1,
    )
    with pytest.raises(DashboardBuildError, match="Lean IA 주입 상태가 불완전"):
        inject_strategy_lean_ia(partial)


def test_payload_contract_is_preserved_while_duplicate_surfaces_are_hidden() -> None:
    rendered = inject_strategy_lean_ia(_strategy_html())

    assert '"market_changes":{"up_count":7,"down_count":3,"count":10}' in rendered
    assert "#market-flow details.changes" in rendered
    assert ".strategy-market-direction" in rendered
    assert ".ux-decision-readiness" in rendered
    assert ".ux-decision-menu" in rendered
    assert ".decision-integrated-insight" in rendered
    assert "#workspace-detail-disclosure" in rendered
    assert "#relative-pricing-r1" in rendered
    assert "#rate-funding-matrix" in rendered
    assert 'hide($("relative-pricing-r1"))' in rendered
    assert 'hide($("rate-funding-matrix"))' in rendered


def test_external_context_and_market_funding_are_reconciled_before_market_status() -> None:
    rendered = inject_strategy_lean_ia(_strategy_html())

    assert '"01","시장 자금환경"' in rendered
    assert '"02","시장현황"' in rendered
    assert 'if(external)cursor=moveAfter(external,cursor)' in rendered
    assert 'if(funding)cursor=moveAfter(funding,cursor)' in rendered
    assert 'cursor=moveAfter(marketLabel,cursor);cursor=moveAfter(kpis,cursor)' in rendered
    assert 'funding.querySelectorAll(".funding-sector-tabs,.funding-analysis-grid,.funding-caveat").forEach(hide)' in rendered
    assert 'title.textContent="업권 수신 흐름"' in rendered


def test_competitor_wrapper_owns_top5_and_institution_position() -> None:
    rendered = inject_strategy_lean_ia(_strategy_html())

    assert 'wrapper.id="workspace-competitor-position"' in rendered
    assert "경쟁사 · 기관 포지션" in rendered
    assert 'wrapper.appendChild(top5)' in rendered
    assert 'wrapper.appendChild(institution)' in rendered
    assert '["경쟁사 · 기관 포지션","workspace-competitor-position"]' in rendered


def test_finalizer_guarantees_search_region_handoff_when_earlier_injector_misses_it() -> None:
    rendered = inject_strategy_lean_ia(_strategy_html())

    assert "function ensureRegionHandoff()" in rendered
    assert 'handoff.className="ux-region-handoff"' in rendered
    assert "지역·지도 상세는 검색 조회로 통합했습니다." in rendered
    assert '<a href="./">지역 상세 보기</a>' in rendered
    assert 'handoff:ensureRegionHandoff()' in rendered


def test_top5_visible_summary_is_reduced_and_readability_increased() -> None:
    rendered = inject_strategy_lean_ia(_strategy_html())

    assert 'th:nth-child(4)' in rendered
    assert 'th:nth-child(5)' in rendered
    assert '.bank{font-size:14px!important' in rendered
    assert '.product{font-size:12px!important' in rendered
    assert '.strongrate{font-size:16px!important' in rendered
    assert 'grid-template-areas:"r s n m"' in rendered


def test_planning_event_tile_is_hidden_but_owner_dom_is_preserved() -> None:
    rendered = inject_strategy_lean_ia(_strategy_html())

    assert 'const eventFlow=$("plan-flow")?.parentElement' in rendered
    assert 'eventFlow.dataset.leanEventDirection="1";eventFlow.hidden=true' in rendered
    assert 'id="plan-flow"' in rendered
    assert "#market-flow{grid-template-columns:minmax(0,1fr)!important}" in rendered
    assert ".workspace-decision .planning-strip{grid-template-columns:repeat(4,minmax(0,1fr))!important}" in rendered
    assert 'planning?.classList.add("workspace-decision")' in rendered
    assert 'const planningShell=planning?.closest(".workspace-decision")||planning' in rendered
    assert 'cursor=moveAfter(designLabel,cursor);cursor=moveAfter(planningShell,cursor)' in rendered
    assert "@media(max-width:480px){" in rendered
    assert ".workspace-decision .planning-strip{grid-template-columns:1fr!important}" in rendered
    assert "remove()" not in rendered.split(SCRIPT_MARKER, 1)[1].split("function buildNavigation", 1)[0]


def test_final_navigation_is_explicit_and_mobile_hidden() -> None:
    rendered = inject_strategy_lean_ia(_strategy_html())

    for label, target in (
        ("시장 자금환경", "external-market-context"),
        ("업권 수신 흐름", "market-funding-competition"),
        ("시장 금리 방향", "market-intelligence"),
        ("12개월 시장 추이", "workspace-market-trend"),
        ("신상품 금리 시뮬레이션", "planning-zone"),
        ("경쟁사 · 기관 포지션", "workspace-competitor-position"),
        ("우대조건 · 상품구조", "preference-intelligence"),
        ("특판 · 시장기회", "special-offer-radar"),
    ):
        assert f'["{label}","{target}"]' in rendered
    assert "지역별 금리" not in rendered
    assert "데이터 근거 · 품질" not in rendered
    assert '@media(max-width:1280px){.strategy-workspace-nav{display:none!important}}' in rendered
    assert 'window.addEventListener("hashchange",activateHash)' in rendered
    assert "IntersectionObserver" in rendered
    assert "Math.abs(hashNode.getBoundingClientRect().top)<=180" in rendered
    assert "hashActivationTimer=setTimeout" in rendered
    assert "},1200)" in rendered
    assert "navLinks().some(link=>link.dataset.workspaceTarget===hashId)" in rendered
    assert '"lean-planning-detail"' in rendered
    assert '"lean-institution-detail"' in rendered
    assert '"lean-preference-detail"' in rendered
    assert '"lean-special-detail"' in rendered
    assert "compactSecondarySurfaces();" in rendered
    assert 'const form=planning.querySelector(".simform"),panel=$("prediction-panel")' in rendered
    assert 'ensureDisclosure(form,"lean-planning-detail","수신예측·모형 상세",[panel])' in rendered
    assert 'toggle.addEventListener("click",()=>{if(detail)detail.open=true})' in rendered


def test_bounded_observer_handles_late_dom_and_reports_missing_contract() -> None:
    rendered = inject_strategy_lean_ia(_strategy_html())

    assert "[0,40,160,500,1200,3000,6000].forEach" in rendered
    assert "new MutationObserver" in rendered
    assert 'new MutationObserver(()=>{reconcile()})' in rendered
    assert 'anchor.nextElementSibling!==node' in rendered
    assert 'if(node.innerHTML!==markup)node.innerHTML=markup' in rendered
    assert 'title&&title.textContent!=="업권 수신 흐름"' in rendered
    assert 'trendAnchor.id="workspace-market-trend"' in rendered
    assert 'trend.prepend(trendAnchor)' in rendered
    assert 'dataset.strategyLeanIa==="v3")return true' not in rendered
    assert 'lateDomObserver.observe(document.body,{childList:true,subtree:true})' in rendered
    assert "setTimeout(()=>{lateDomObserver?.disconnect();lateDomObserver=null;lateDomTimer=null;reconcile()},10000)" in rendered
    assert 'document.documentElement.dataset.strategyLeanIaMissing=missing.join(",")' in rendered
    assert 'dataset.strategyWorkspace!=="market-first-v2"' in rendered
    assert 'missing.unshift("workspace")' in rendered
    assert 'document.documentElement.dataset.strategyLeanIa="v3"' in rendered
    assert 'document.documentElement.dataset.strategyLeanIaMissing=""' in rendered
    assert "handoff.hidden=false" in rendered


def test_compositor_skips_old_duplicate_injectors_and_runs_lean_ia_last() -> None:
    source = inspect.getsource(inject_dashboard_ui_refinement)

    assert "inject_strategy_market_direction(rendered)" not in source
    assert "inject_strategy_decision_scope_compact(rendered)" not in source
    top5 = source.index("inject_strategy_top5_compact(rendered)")
    lean = source.index("inject_strategy_lean_ia(rendered)")
    assert top5 < lean
