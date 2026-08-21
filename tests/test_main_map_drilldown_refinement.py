from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.main_map_drilldown_refinement import (
    BUSAN_TEMPLATE_ID,
    MAIN_MAP_DRILLDOWN_MARKER,
    _extract_busan_boundary,
    inject_main_map_drilldown_refinement,
)

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_TEMPLATE = ROOT / "web" / "templates" / "strategy.html"
DASHBOARD_UI = (
    ROOT
    / "src"
    / "rate_monitor"
    / "services"
    / "dashboard_ui_refinement_presentation.py"
)
SITE_TEMPLATE = ROOT / "web" / "templates" / "site.html"


def test_busan_geometry_reuses_existing_strategy_16_district_boundary() -> None:
    markup = _extract_busan_boundary(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert markup.startswith('<g id="busan-boundaries">')
    assert markup.count("<path") == 16
    for district in ("강서구", "기장군", "부산진구", "중구", "해운대구"):
        assert f'id="{district}"' in markup


def test_busan_geometry_extraction_fails_closed() -> None:
    with pytest.raises(DashboardBuildError, match="SVG geometry"):
        _extract_busan_boundary("const BUSAN_BOUNDARY_SVG=`<g></g>`;")


def test_refinement_injects_once_and_uses_larger_readable_national_map() -> None:
    html = '<html><head></head><body><div id="reg"></div></body></html>'
    strategy = STRATEGY_TEMPLATE.read_text(encoding="utf-8")

    rendered = inject_main_map_drilldown_refinement(html, strategy)
    rendered_twice = inject_main_map_drilldown_refinement(rendered, strategy)

    assert rendered_twice == rendered
    assert rendered.count(MAIN_MAP_DRILLDOWN_MARKER) == 3  # style + template + script
    assert f'id="{BUSAN_TEMPLATE_ID}"' in rendered
    assert "main-national-map-card" in rendered
    assert "max-width: 740px" in rendered
    assert "minmax(0, 460px)" in rendered
    assert "min-height: 460px" in rendered
    assert "max-height: 490px" in rendered
    assert "minmax(0, 700px)" in rendered  # Busan remains wider
    assert "minmax(190px, 220px)" in rendered
    assert "@media (max-width: 1000px)" in rendered


def test_national_map_prunes_island_subpaths_and_refits_viewbox() -> None:
    strategy = STRATEGY_TEMPLATE.read_text(encoding="utf-8")
    rendered = inject_main_map_drilldown_refinement(
        '<html><head></head><body><div id="reg"></div></body></html>',
        strategy,
    )

    assert "keepLargestSubpath" in rendered
    assert 'd.match(/M[^M]+/g)' in rendered
    assert "omittedIslandSubpaths" in rendered
    assert "mainlandJejuCrop" in rendered
    assert '#전국_시도_경계 path[id]' in rendered
    assert 'svg.setAttribute("viewBox"' in rendered
    assert 'svg.setAttribute("preserveAspectRatio", "xMidYMid meet")' in rendered


def test_national_tooltip_flips_and_clamps_inside_map_stage() -> None:
    strategy = STRATEGY_TEMPLATE.read_text(encoding="utf-8")
    rendered = inject_main_map_drilldown_refinement(
        '<html><head></head><body><div id="reg"></div></body></html>',
        strategy,
    )

    assert "fitNationalTooltip" in rendered
    assert "bindNationalTooltipClamp" in rendered
    assert 'stage?.querySelector(".main-map-tooltip")' in rendered
    assert "top + height > sh - pad" in rendered
    assert 'tip.dataset.viewportFit = "1"' in rendered
    assert 'path.addEventListener("mouseenter"' in rendered
    assert 'path.addEventListener("focus"' in rendered


def test_busan_mode_is_transformed_from_existing_district_tiles_to_svg() -> None:
    strategy = STRATEGY_TEMPLATE.read_text(encoding="utf-8")
    rendered = inject_main_map_drilldown_refinement(
        '<html><head></head><body><div id="reg"></div></body></html>',
        strategy,
    )

    assert 'title.includes("부산 구·군별")' in rendered
    assert 'reg.querySelectorAll(":scope > .regtile")' in rendered
    assert 'svg.querySelectorAll("#busan-boundaries path[id]")' in rendered
    assert 'reg.replaceChildren(shell)' in rendered
    assert 'reg.classList.add("main-busan-map")' in rendered
    assert '"사하구": [-40,0,"end"]' in rendered
    assert "main-busan-label-name" in rendered
    assert "main-busan-label-rate" in rendered
    assert "전국으로 돌아가기" in rendered


def test_existing_core_busan_state_and_back_contract_remains_owner() -> None:
    text = SITE_TEMPLATE.read_text(encoding="utf-8")

    assert 'regionView = "busan"' in text
    assert 'regionView = "national"' in text
    assert 'id="reg-back"' in text
    assert 'e.target.closest("[data-drill]")' in text


def test_dashboard_ui_final_layer_wires_search_only_drilldown_refinement() -> None:
    text = DASHBOARD_UI.read_text(encoding="utf-8")

    assert "inject_main_map_drilldown_refinement" in text
    assert "_STRATEGY_TEMPLATE.read_text" in text
    assert "if 'id=\"reg\"' in rendered:" in text
