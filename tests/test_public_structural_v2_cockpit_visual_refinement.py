from __future__ import annotations

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.public_structural_v2_cockpit_visual_refinement import (
    _CSS,
    _SCRIPT,
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_public_structural_v2_cockpit_visual_refinement,
)
from tests.strategy_output_helper import built_strategy_html


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


def test_visual_refinement_uses_mobile_candidate_card_grid_without_overlap() -> None:
    assert ".psv2>div{min-width:0}" in _CSS
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
