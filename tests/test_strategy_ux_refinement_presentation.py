from pathlib import Path

from rate_monitor.services.strategy_decision_cockpit import inject_strategy_decision_cockpit
from rate_monitor.services.strategy_ux_refinement_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_ux_refinement,
)


def _render_strategy() -> str:
    template = Path("web/templates/strategy.html").read_text(encoding="utf-8")
    return inject_strategy_decision_cockpit(template)


def test_strategy_ux_refinement_uses_combined_scope_by_default() -> None:
    html = _render_strategy()

    combined = html.index('data-market-mode="combined"')
    savings = html.index('data-market-mode="savings_bank"')
    mutual = html.index('data-market-mode="mutual_finance"')
    assert combined < savings < mutual
    assert '<button class="mode-tab active" type="button" data-market-mode="combined">' in html
    assert 'marketMode="combined",strategyUniverse=null;' in html
    assert '<span class="pill active" id="scope-pill">저축은행 + 상호금융</span>' in html


def test_strategy_ux_refinement_defaults_available_mutual_sectors_to_checked() -> None:
    html = _render_strategy()

    assert '<input type="checkbox" data-sector="cu" checked>' in html
    assert '<input type="checkbox" data-sector="kfcc" checked>' in html
    assert '<input type="checkbox" data-sector="nh_local" checked>' in html
    assert "상호금융 세부업권 · 기본 전체" in html
    assert 'host.dataset.savingsOnly=String(activeMode()==="savings_bank")' in html


def test_strategy_ux_refinement_demotes_evidence_and_hands_region_map_to_search() -> None:
    html = _render_strategy()

    assert "ux-evidence-panel" in html
    assert "데이터 기준 · ${sectors} · 업권별 수집률/기준일은 필요할 때 확인" in html
    assert ".workspace-detail.primary .mapcard{display:none!important}" in html
    assert ".workspace-detail.primary{grid-template-columns:1fr!important}" in html
    assert "지역·지도 상세는 검색 조회로 통합했습니다." in html
    assert "경쟁상단·금리결정 근거만 남깁니다." in html
    assert "지역 상세 보기" in html
    assert ".maplegend{display:none!important}" in html
    assert "height:435px" not in html


def test_strategy_ux_refinement_preference_follows_top_scope_and_uses_top_n() -> None:
    html = _render_strategy()

    assert "activeSectorKeys()" in html
    assert 'sectorControl.dataset.uxSectorControl="true"' in html
    assert "상단 선택 연동" in html
    assert "categories.slice(0,5)" in html
    assert "나머지 조건 ${rest.length}개 보기" in html
    assert "sectors.map(k=>sectorPreferenceCard" in html


def test_strategy_ux_refinement_increases_readability_after_light_theme() -> None:
    html = _render_strategy()

    light_style = html.index('id="strategy-light-theme-style"')
    ux_style = html.index(STYLE_MARKER)
    assert light_style < ux_style
    assert "body{font-size:16px;line-height:1.6}" in html
    assert ".tablewrap td{font-size:11.5px}" in html
    assert ".workspace-section-label strong{font-size:14px}" in html


def test_strategy_ux_refinement_is_idempotent() -> None:
    html = _render_strategy()
    again = inject_strategy_ux_refinement(html)

    assert again == html
    assert html.count(STYLE_MARKER) == 1
    assert html.count(SCRIPT_MARKER) == 1
