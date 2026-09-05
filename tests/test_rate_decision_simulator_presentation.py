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