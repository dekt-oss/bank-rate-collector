from __future__ import annotations

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.rate_decision_simulator_presentation import (
    inject_rate_decision_simulator,
)

BASE_HTML = """<!doctype html>
<html>
<head></head>
<body>
<section id="prediction-panel"></section>
<div id="term-segment"></div>
<script id="rate-monitor-data" type="application/json">{}</script>
<script id="public-structural-v2-engine-bundle"></script>
<script id="public-structural-v2-cockpit-script"></script>
</body>
</html>
"""


def test_injects_style_and_runtime_bundle_once() -> None:
    rendered = inject_rate_decision_simulator(BASE_HTML)

    assert rendered.count('id="rate-decision-simulator-v1-style"') == 1
    assert rendered.count('id="rate-decision-simulator-v1-bundle"') == 1
    assert "StrategyTargetCandidate" in rendered
    assert "strategy-rate-decision-simulator" in rendered
    assert inject_rate_decision_simulator(rendered) == rendered


def test_runtime_bundle_keeps_nearby_sector_and_fail_closed_state_contract() -> None:
    rendered = inject_rate_decision_simulator(BASE_HTML)

    assert "SECTOR_LABELS" in rendered
    assert "<th>업권</th>" in rendered
    assert "clearDecisionState" in rendered
    assert "현재 계산이 차단되어 주변 상품을 표시하지 않습니다." in rendered
    assert "현재 계산이 차단되어 pricing peer gap을 표시하지 않습니다." in rendered
    assert "가장 낮은 existing candidate도 목표 이상" in rendered
    assert "더 낮은 금리는 지원범위 밖" in rendered


def test_rejects_partial_injection_state() -> None:
    partial = BASE_HTML.replace(
        "</head>", '<style id="rate-decision-simulator-v1-style"></style></head>'
    )

    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_rate_decision_simulator(partial)


def test_requires_public_structural_v2_contract() -> None:
    missing_engine = BASE_HTML.replace(
        '<script id="public-structural-v2-engine-bundle"></script>', ""
    )

    with pytest.raises(DashboardBuildError, match="선행 계약이 없다"):
        inject_rate_decision_simulator(missing_engine)
