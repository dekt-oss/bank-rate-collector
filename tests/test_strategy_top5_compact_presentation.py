# ruff: noqa: E501
from __future__ import annotations

import inspect

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)
from rate_monitor.services.strategy_top5_compact_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_top5_compact,
)


def _strategy_html() -> str:
    return (
        "<html><head></head><body><main>"
        '<div id="market-scope"></div>'
        '<article class="top5-card"><table><thead><tr>'
        '<th>순위</th><th>금융사 / 상품</th><th>기본금리</th><th>우대폭</th><th>최고금리</th>'
        '</tr></thead><tbody id="top5"><tr><td colspan="5">loading</td></tr></tbody></table></article>'
        "</main></body></html>"
    )


def test_top5_compact_injection_is_idempotent() -> None:
    rendered = inject_strategy_top5_compact(_strategy_html())

    assert STYLE_MARKER in rendered
    assert SCRIPT_MARKER in rendered
    assert rendered.count(STYLE_MARKER) == 1
    assert rendered.count(SCRIPT_MARKER) == 1
    assert inject_strategy_top5_compact(rendered) == rendered


def test_top5_compact_adds_sector_column_without_recomputing_ranking() -> None:
    rendered = inject_strategy_top5_compact(_strategy_html())

    assert 'th.textContent="업권"' in rendered
    assert "products12.slice(0,5)" in rendered
    assert "sectorLabel(sector" in rendered
    assert 'row.querySelector(".rank")' in rendered
    assert 'row.querySelector(".our-rank")' in rendered
    assert "OUR_INSTITUTION" in rendered
    assert "sort(" not in rendered
    assert "aggregateProducts(" not in rendered
    assert "ratesStats(" not in rendered


def test_top5_compact_handles_six_column_empty_and_mobile_layout() -> None:
    rendered = inject_strategy_top5_compact(_strategy_html())

    assert "cell.colSpan=6" in rendered
    assert 'td:nth-child(1){grid-area:r!important}' in rendered
    assert 'td:nth-child(2){grid-area:s!important}' in rendered
    assert 'td:nth-child(3){grid-area:n!important}' in rendered
    assert 'td:nth-child(4){grid-area:b!important}' in rendered
    assert 'td:nth-child(5){grid-area:u!important}' in rendered
    assert 'td:nth-child(6){grid-area:m!important' in rendered


def test_top5_compact_wraps_existing_render_market_once() -> None:
    rendered = inject_strategy_top5_compact(_strategy_html())

    assert "const priorRenderMarket=renderMarket" in rendered
    assert "renderMarket=function(){priorRenderMarket();decorate()}" in rendered
    assert "decorate();" in rendered


def test_top5_compact_partial_injection_fails_closed() -> None:
    html = _strategy_html().replace(
        "</head>",
        '<style id="strategy-top5-compact-style"></style></head>',
        1,
    )

    with pytest.raises(DashboardBuildError, match="TOP5 compact"):
        inject_strategy_top5_compact(html)


def test_top5_compact_is_noop_outside_strategy() -> None:
    html = "<html><head></head><body><main>search</main></body></html>"
    assert inject_strategy_top5_compact(html) == html


def test_top5_compact_composes_after_decision_navigation() -> None:
    source = inspect.getsource(inject_dashboard_ui_refinement)
    nav = source.index("inject_strategy_decision_scope_compact(rendered)")
    top5 = source.index("inject_strategy_top5_compact(rendered)")

    assert nav < top5
