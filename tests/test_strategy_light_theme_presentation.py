"""Strategy light theme presentation 계약."""

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_light_theme_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_light_theme,
)


def _workspace_fixture() -> str:
    return """<!doctype html>
<html>
<head><style id="strategy-workspace-style"></style></head>
<body><main class="card"><div class="kvalue">3.25%</div></main></body>
</html>"""


def test_light_theme_injection_is_idempotent() -> None:
    once = inject_strategy_light_theme(_workspace_fixture())
    twice = inject_strategy_light_theme(once)

    assert once == twice
    assert once.count(STYLE_MARKER) == 1
    assert once.count(SCRIPT_MARKER) == 1


def test_light_theme_uses_readable_local_font_stack_and_tabular_numbers() -> None:
    html = inject_strategy_light_theme(_workspace_fixture())

    assert '"Pretendard Variable","Pretendard","Noto Sans KR"' in html
    assert 'font-variant-numeric:tabular-nums lining-nums' in html
    assert 'font-feature-settings:"tnum" 1,"lnum" 1' in html
    assert "@import" not in html
    assert "fonts.googleapis" not in html
    assert "cdn" not in html.lower()


def test_light_theme_defines_neutral_canvas_white_surface_and_limited_accent() -> None:
    html = inject_strategy_light_theme(_workspace_fixture())

    assert "--bg:#eef2f5" in html
    assert "--panel:#ffffff" in html
    assert "--ink:#17232d" in html
    assert "--accent:#4f6f9f" in html
    assert ".card{border-color:rgba(42,61,78,.09);background:#fff" in html
    assert "color-scheme:light" in html


def test_light_theme_requires_workspace_to_be_present_first() -> None:
    with pytest.raises(DashboardBuildError, match="Workspace 이후"):
        inject_strategy_light_theme("<html><head></head><body></body></html>")


def test_partial_light_theme_injection_fails_closed() -> None:
    partial = _workspace_fixture().replace(
        "</head>", f'<style {STYLE_MARKER}></style></head>'
    )
    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_strategy_light_theme(partial)
