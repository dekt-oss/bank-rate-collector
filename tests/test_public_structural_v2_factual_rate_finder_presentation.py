from __future__ import annotations

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.public_structural_v2_factual_rate_finder_presentation import (
    ENGINE_MARKER,
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_public_structural_v2_factual_rate_finder,
)


def _html() -> str:
    return """<!doctype html>
<html><head></head><body>
<script id="rate-monitor-data" type="application/json">{"table_url":"strategy-table.json"}</script>
<section id="public-structural-v2-cockpit"></section>
<script id="public-structural-v2-cockpit-script"></script>
<script id="public-structural-v2-cockpit-visual-refinement-script"></script>
</body></html>"""


def test_stage_g_presentation_injects_independent_engine_and_factual_copy() -> None:
    rendered = inject_public_structural_v2_factual_rate_finder(_html())

    assert STYLE_MARKER in rendered
    assert ENGINE_MARKER in rendered
    assert SCRIPT_MARKER in rendered
    assert "시장조건 충족 금리" in rendered
    assert "조건충족 값 · 자동 결정 아님" in rendered
    assert "competitor_only_anchor_removed" in rendered
    assert "selection_step_pp:SELECTION_STEP_PP" in rendered
    assert "baseline_new_money" not in rendered
    assert "maturity_amount" not in rendered
    assert "current_rollover_rate_pct" not in rendered
    assert "추천금리" not in rendered
    assert "최적금리" not in rendered
    assert "달성확률" not in rendered


def test_stage_g_presentation_is_idempotent() -> None:
    once = inject_public_structural_v2_factual_rate_finder(_html())
    twice = inject_public_structural_v2_factual_rate_finder(once)

    assert twice == once
    assert twice.count(STYLE_MARKER) == 1
    assert twice.count(ENGINE_MARKER) == 1
    assert twice.count(SCRIPT_MARKER) == 1


def test_stage_g_presentation_requires_stage_f_contract() -> None:
    with pytest.raises(DashboardBuildError, match="선행 계약"):
        inject_public_structural_v2_factual_rate_finder(
            "<html><head></head><body><script id=\"rate-monitor-data\"></script></body></html>"
        )


def test_stage_g_partial_injection_fails_closed() -> None:
    partial = _html().replace("</head>", f"<style {STYLE_MARKER}></style></head>")
    with pytest.raises(DashboardBuildError, match="불완전"):
        inject_public_structural_v2_factual_rate_finder(partial)
