from __future__ import annotations

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.public_structural_v2_cockpit_presentation import (
    ENGINE_MARKER,
    SCRIPT_MARKER,
    STYLE_MARKER,
    _JS,
    inject_public_structural_v2_cockpit,
)
from tests.strategy_output_helper import built_strategy_html


def test_built_strategy_contains_public_structural_v2_cockpit_and_engines() -> None:
    html = built_strategy_html()

    assert STYLE_MARKER in html
    assert ENGINE_MARKER in html
    assert SCRIPT_MARKER in html
    assert "PublicStructuralV2Inflow=api" in html
    assert "PublicStructuralV2MarketPosition=api" in html
    assert "PublicStructuralV2DecisionContract=api" in html
    assert "PublicStructuralV2Surface=api" in html
    assert "PublicStructuralV2Marginal=api" in html
    assert "Public Structural v2 금리결정 Cockpit" in html


def test_cockpit_consumes_surface_and_marginal_not_raw_structural_formula() -> None:
    assert "PublicStructuralV2Surface.buildSurface" in _JS
    assert "PublicStructuralV2Marginal.buildFixed5bpMarginals" in _JS
    assert "PublicStructuralV2MarketPosition.marketPosition" in _JS
    assert "PublicStructuralV2Inflow.predictScenario" not in _JS
    assert "new_money_log_change_per_10bp" not in _JS
    assert "rollover_log_odds_change_per_10bp" not in _JS


def test_cockpit_keeps_factual_and_uncalibrated_scenario_language_separate() -> None:
    html = built_strategy_html()

    required = (
        "실제 시장 위치",
        "미보정 구조 시나리오",
        "시장 사실과 구조 시나리오는 별도 정보입니다",
        "시장 사실 ≠ 수신금액의 직접 원인",
        "Market Position Ladder",
        "Response Surface",
        "후보금리 비교",
        "직전 5bp 표면비용",
        "공동순위 범위",
        "동률",
        "FTP/ALM 경제원가가 아닙니다",
    )
    for phrase in required:
        assert phrase in html

    assert "추천금리" not in _JS
    assert "최적금리" not in _JS
    assert "달성확률" not in _JS


def test_cockpit_mobile_contract_preserves_reading_order_without_single_row_squeeze() -> None:
    html = built_strategy_html()

    assert "@media(max-width:520px)" in html
    assert ".psv2-decision{grid-template-columns:1fr}" in html
    assert "제안금리" in _JS
    assert _JS.index("실제 시장 위치") < _JS.index("미보정 구조 시나리오")


def test_cockpit_injection_is_idempotent_on_built_strategy() -> None:
    html = built_strategy_html()
    assert inject_public_structural_v2_cockpit(html) == html


def test_cockpit_partial_marker_state_fails_closed() -> None:
    html = (
        '<html><head><style id="public-structural-v2-cockpit-style"></style></head>'
        '<body><section id="planning-zone"><div id="prediction-panel"></div>'
        '<script id="rate-monitor-data" type="application/json">{}</script>'
        '<div id="term-segment"></div></section></body></html>'
    )
    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_public_structural_v2_cockpit(html)
