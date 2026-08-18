"""Stage B 금리→수신반응 Decision Cockpit의 presentation 계약."""

from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_decision_cockpit import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_decision_cockpit,
)

ROOT = Path(__file__).resolve().parents[1]


def _minimal_strategy_html() -> str:
    return """<!doctype html>
<html>
<head><title>strategy</title></head>
<body>
<section id="prediction-panel"></section>
<script>function predictInflow(args){return args}</script>
</body>
</html>"""


def test_injection_is_idempotent() -> None:
    once = inject_strategy_decision_cockpit(_minimal_strategy_html())
    twice = inject_strategy_decision_cockpit(once)

    assert once == twice
    assert once.count(STYLE_MARKER) == 1
    assert once.count(SCRIPT_MARKER) == 1


def test_cockpit_centres_rate_to_inflow_and_keeps_rank_secondary() -> None:
    html = inject_strategy_decision_cockpit(_minimal_strategy_html())

    assert "금리 결정 · 수신반응 시나리오" in html
    assert "금리별 수신반응 비교" in html
    assert "현재 대비 +0.05%p" in html
    assert "현재 대비 +0.10%p" in html
    assert "현재 대비 +0.15%p" in html
    assert "예상 신규자금" in html
    assert "예상 재예치" in html
    assert "예상 총수신" in html
    assert "시장 위치 참고 · 순위/상위 10%/포지션" in html


def test_uncalibrated_and_cost_boundaries_are_explicit() -> None:
    html = inject_strategy_decision_cockpit(_minimal_strategy_html())

    assert "내부 실적 미보정 스트레스 시나리오" in html
    assert "실제 forecast가 아닙니다" in html
    assert "총수신 = 신규자금 + 재예치이며 순수신이 아닙니다" in html
    assert "FTP 미반영" in html
    assert "window.predictInflow" in html


def test_injection_fails_closed_without_existing_prediction_contract() -> None:
    with pytest.raises(DashboardBuildError, match="기존 Strategy 수신예측 계약"):
        inject_strategy_decision_cockpit("<html><head></head><body></body></html>")


def test_partial_injection_fails_closed() -> None:
    partial = _minimal_strategy_html().replace(
        "</head>", f'<style {STYLE_MARKER}></style></head>'
    )
    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_strategy_decision_cockpit(partial)


def test_site_build_wires_cockpit_only_in_strategy_render_path() -> None:
    source = (ROOT / "src/rate_monitor/services/site_service.py").read_text(encoding="utf-8")
    render_line = "strategy_html = render(strategy_template_text, strategy_page_data)"
    inject_line = "strategy_html = inject_strategy_decision_cockpit(strategy_html)"
    verify_line = "_verify_strategy(strategy_html, strategy_page_data)"

    assert render_line in source
    assert inject_line in source
    assert verify_line in source
    assert source.index(render_line) < source.index(inject_line) < source.index(verify_line)
