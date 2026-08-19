"""Strategy branded theme presentation 계약."""

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_brand_theme_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_brand_theme,
)


def _workspace_fixture() -> str:
    return """<!doctype html>
<html>
<head><style id="strategy-workspace-style"></style></head>
<body><main class="card"><div class="kvalue">3.25%</div></main></body>
</html>"""


def test_brand_theme_is_idempotent_and_keeps_light_foundation() -> None:
    once = inject_strategy_brand_theme(_workspace_fixture())
    twice = inject_strategy_brand_theme(once)

    assert once == twice
    assert once.count(STYLE_MARKER) == 1
    assert once.count(SCRIPT_MARKER) == 1
    assert 'id="strategy-light-theme-style"' in once
    assert 'id="strategy-light-theme-script"' in once


def test_brand_theme_reuses_general_dashboard_palette() -> None:
    html = inject_strategy_brand_theme(_workspace_fixture())

    for token in (
        "--bg:#F7F4F8",
        "--ink:#251D27",
        "--brand-plum:#4D2D58",
        "--brand-plum-2:#5B2F64",
        "--brand-violet:#734A7E",
        "--brand-rose:#B34A77",
        "--accent:#D33A7C",
        "--accent-soft:#F8EAF1",
    ):
        assert token in html
    assert "linear-gradient(130deg,#4D2D58 0%,#784060 54%,#B34A77 118%)" in html
    assert 'dataset.strategyPalette="main-brand-v2"' in html


def test_brand_theme_uses_variable_ui_typography_without_remote_font_dependency() -> None:
    html = inject_strategy_brand_theme(_workspace_fixture())

    assert '"Pretendard Variable","Pretendard","SUIT Variable"' in html
    assert "font-optical-sizing:auto" in html
    assert 'font-variation-settings:"wght" 760' in html
    assert "font-size:clamp(28px,2.45vw,36px)" in html
    assert "font-size:10.5px!important" in html
    assert "@import" not in html
    assert "fonts.googleapis" not in html
    assert "cdn" not in html.lower()


def test_brand_theme_lightens_map_and_limits_semantic_colors() -> None:
    html = inject_strategy_brand_theme(_workspace_fixture())

    assert ".land,.island{fill:#EFE7F0!important" in html
    assert ".node-core{fill:#734A7E}" in html
    assert ".node.top .node-core{fill:#D33A7C}" in html
    assert "--green:#2E7D5B" in html
    assert "--red:#AC4238" in html


def test_partial_brand_theme_injection_fails_closed() -> None:
    complete = inject_strategy_brand_theme(_workspace_fixture())
    partial = complete.replace(
        '<script id="strategy-brand-theme-script">',
        '<script id="removed-brand-theme-script">',
    )

    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_strategy_brand_theme(partial)
