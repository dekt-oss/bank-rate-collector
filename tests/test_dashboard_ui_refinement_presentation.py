from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.dashboard_ui_refinement_presentation import (
    DASHBOARD_UI_SCRIPT,
    DASHBOARD_UI_STYLE,
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_dashboard_ui_refinement,
)

ROOT = Path(__file__).resolve().parents[1]
SITE_SERVICE = ROOT / "src" / "rate_monitor" / "services" / "site_service.py"


def test_dashboard_ui_refinement_injects_once() -> None:
    html = "<html><head></head><body><header class=\"top\"></header></body></html>"

    rendered = inject_dashboard_ui_refinement(html)
    rendered_twice = inject_dashboard_ui_refinement(rendered)

    assert rendered.count(STYLE_MARKER) == 1
    assert rendered.count(SCRIPT_MARKER) == 1
    assert rendered_twice == rendered


def test_dashboard_ui_refinement_fails_closed_without_injection_points() -> None:
    with pytest.raises(DashboardBuildError, match="head"):
        inject_dashboard_ui_refinement("<html><body></body></html>")
    with pytest.raises(DashboardBuildError, match="body"):
        inject_dashboard_ui_refinement("<html><head></head></html>")


def test_shared_header_contract_moves_search_only_controls_below_header() -> None:
    assert "shared-dashboard-header" in DASHBOARD_UI_STYLE
    assert "shared-header-identity" in DASHBOARD_UI_SCRIPT
    assert "SB 인사이트" in DASHBOARD_UI_SCRIPT
    assert "shared-page-context-main" in DASHBOARD_UI_STYLE
    assert 'for(const selector of [".mine-pick",".stamp",".collect-box"])' in DASHBOARD_UI_SCRIPT
    assert "header.top.shared-dashboard-header>.page-nav" in DASHBOARD_UI_STYLE
    assert "header.topbar.shared-dashboard-header>.nav" in DASHBOARD_UI_STYLE
    assert ".main-report-button" in DASHBOARD_UI_STYLE
    assert ".ux-report-button" in DASHBOARD_UI_STYLE


def test_search_map_keeps_heatmap_and_adds_one_direct_label_per_region() -> None:
    for region in (
        "서울",
        "인천·경기",
        "강원",
        "충청",
        "전라",
        "경북",
        "경남",
        "부산",
        "제주",
    ):
        assert f'"{region}"' in DASHBOARD_UI_SCRIPT

    assert "path[data-region-key]" in DASHBOARD_UI_SCRIPT
    assert "values.has(key)" in DASHBOARD_UI_SCRIPT
    assert "main-map-label-layer" in DASHBOARD_UI_SCRIPT
    assert "main-map-label-name" in DASHBOARD_UI_STYLE
    assert "main-map-label-rate" in DASHBOARD_UI_STYLE
    assert "표본 부족" in DASHBOARD_UI_SCRIPT
    assert "data-has-rate" not in DASHBOARD_UI_SCRIPT
    assert "path.dataset.hasRate" in DASHBOARD_UI_SCRIPT
    assert "MutationObserver" in DASHBOARD_UI_SCRIPT
    assert "mainMapDirectLabels" in DASHBOARD_UI_SCRIPT
    assert "main-map-shell" in DASHBOARD_UI_STYLE
    assert "minmax(190px,225px)" in DASHBOARD_UI_STYLE


def test_site_build_applies_refinement_to_search_and_strategy() -> None:
    text = SITE_SERVICE.read_text(encoding="utf-8")

    assert "inject_dashboard_ui_refinement" in text
    assert text.count("inject_dashboard_ui_refinement(html)") == 1
    assert text.count("inject_dashboard_ui_refinement(strategy_html)") == 1
    assert "DASHBOARD_UI_MARKER" in text
