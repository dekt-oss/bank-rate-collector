from __future__ import annotations

import re

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.public_structural_v2_cockpit_presentation import (
    _CSS as COCKPIT_CSS,
)
from rate_monitor.services.public_structural_v2_cockpit_visual_refinement import (
    _CSS,
    _SCRIPT,
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_public_structural_v2_cockpit_visual_refinement,
)
from rate_monitor.services.public_structural_v2_factual_rate_finder_presentation import (
    _CSS as FACTUAL_FINDER_CSS,
)
from tests.strategy_output_helper import built_strategy_html


def _absolute_font_sizes(css: str) -> list[float]:
    return [
        float(match)
        for match in re.findall(
            r"(?:font-size:|font:(?:[^;{}]*?\s)?)([0-9]+(?:\.[0-9]+)?)px",
            css,
        )
    ]


def test_built_strategy_wires_visual_refinement_after_public_structural_cockpit() -> None:
    html = built_strategy_html()

    assert STYLE_MARKER in html
    assert SCRIPT_MARKER in html
    assert html.index('id="public-structural-v2-cockpit-script"') < html.index(SCRIPT_MARKER)


def test_visual_refinement_merges_same_rate_ladder_markers() -> None:
    assert "mergeSameRateRungs" in _SCRIPT
    assert 'const rate=rung.querySelector("strong")?.textContent?.trim();' in _SCRIPT
    assert 'rung.classList.contains("proposal")' in _SCRIPT
    assert 'rung.classList.contains("current")' in _SCRIPT
    assert 'mergedLabels.push("현재 · 제안금리")' in _SCRIPT
    assert "primary.dataset.mergedRateMarkers=String(group.length)" in _SCRIPT
    assert "if(rung!==primary)rung.remove();" in _SCRIPT
    assert 'content:" · 동일금리"!important' in _CSS


def test_visual_refinement_deconflicts_enlarged_chart_x_axis_labels() -> None:
    assert "deconflictChartAxisLabels" in _SCRIPT
    assert '.psv2-chart text.axis[text-anchor="middle"]' in _SCRIPT
    assert 'for(const tick of ticks)tick.style.visibility="";' in _SCRIPT
    assert "rect.left<previousRight" in _SCRIPT
    assert 'tick.style.visibility="hidden"' in _SCRIPT
    assert 'window.addEventListener("resize",refine,{passive:true})' in _SCRIPT


def test_visual_refinement_keeps_mobile_charts_inside_local_scroll_regions() -> None:
    assert "@media(max-width:640px)" in _CSS
    assert (
        ".psv2-chart-wrap,.chartwrap{overflow-x:auto!important;overflow-y:hidden!important"
        in _CSS
    )
    assert (
        ".psv2-chart{width:620px!important;min-width:620px!important;"
        "max-width:none!important;height:220px!important}"
        in _CSS
    )
    assert (
        "#trend-chart.chart{width:786px!important;min-width:786px!important;"
        "max-width:none!important;height:220px!important}"
        in _CSS
    )
    assert "annotateMobileChartScroll" in _SCRIPT
    assert 'window.matchMedia("(max-width:640px)").matches' in _SCRIPT
    assert 'wrap.setAttribute("tabindex","0")' in _SCRIPT
    assert 'wrap.setAttribute("role","region")' in _SCRIPT
    assert "가로 스크롤로 전체 구간 확인" in _SCRIPT


def test_visual_refinement_deconflicts_legacy_trend_date_labels() -> None:
    assert "deconflictLegacyTrendAxisLabels" in _SCRIPT
    assert 'document.querySelectorAll("#trend-chart text.trenddate")' in _SCRIPT
    assert 'document.getElementById("trend-chart")' in _SCRIPT
    assert "new MutationObserver(refine).observe(legacyTrend" in _SCRIPT


def test_public_structural_base_css_enforces_brand_microcopy_floor() -> None:
    sizes = _absolute_font_sizes(COCKPIT_CSS + FACTUAL_FINDER_CSS + _CSS)

    assert sizes, "Public Structural v2 font contract를 검사할 CSS가 없습니다"
    too_small = sorted({size for size in sizes if size < 10.5})
    assert not too_small, f"Public Structural v2 10.5px 미만 font가 남아 있습니다: {too_small}"
    assert ".psv2-chart .axis" in COCKPIT_CSS
    assert ".psv2-chart .label" in COCKPIT_CSS
    assert ".psv2-finder-item small" in FACTUAL_FINDER_CSS
    assert "font-size:7.8px" not in FACTUAL_FINDER_CSS
    assert "font:700 10.5px/1.25 var(--sans)" in _CSS


def test_visual_refinement_uses_mobile_candidate_card_grid_without_overlap() -> None:
    assert ".psv2>div" in _CSS
    assert "@media(max-width:520px)" in _CSS
    assert ".psv2-table{display:block!important;width:100%!important;min-width:0!important" in _CSS
    assert ".psv2-table thead{display:none!important}" in _CSS
    assert ".psv2-table tbody{display:grid!important;gap:8px}" in _CSS
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in _CSS
    assert ".psv2-table td{display:block!important;min-width:0!important" in _CSS
    assert '.psv2-table td:nth-child(2):before{content:"공동순위 범위"}' in _CSS
    assert ".psv2-table td:nth-child(6){grid-column:1/-1}" in _CSS
    assert '.psv2-table td:nth-child(8):before{content:"직전 5bp 표면비용"}' in _CSS


def test_visual_refinement_is_idempotent() -> None:
    html = built_strategy_html()
    assert inject_public_structural_v2_cockpit_visual_refinement(html) == html


def test_visual_refinement_fails_closed_without_parent_cockpit() -> None:
    html = "<html><head></head><body></body></html>"
    with pytest.raises(DashboardBuildError, match="선행 script"):
        inject_public_structural_v2_cockpit_visual_refinement(html)
