from __future__ import annotations

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.public_structural_v2_forecast_provider_presentation import (
    BRIDGE_MARKER,
    ENGINE_MARKER,
    inject_public_structural_v2_forecast_provider,
)
from tests.strategy_output_helper import built_strategy_html


def _minimal_parent() -> str:
    return """<!doctype html>
<html><head></head><body>
<script id="public-structural-v2-engine-bundle"></script>
<script id="public-structural-v2-cockpit-script"></script>
</body></html>"""


def test_built_strategy_wires_provider_before_cockpit_runtime() -> None:
    html = built_strategy_html()

    assert ENGINE_MARKER in html
    assert BRIDGE_MARKER in html
    assert html.index('id="public-structural-v2-engine-bundle"') < html.index(ENGINE_MARKER)
    assert html.index(ENGINE_MARKER) < html.index(BRIDGE_MARKER)
    assert html.index(BRIDGE_MARKER) < html.index('id="public-structural-v2-cockpit-script"')
    assert html.index(BRIDGE_MARKER) < html.index(
        'id="public-structural-v2-cockpit-visual-refinement-script"'
    )
    assert html.index(
        'id="public-structural-v2-cockpit-visual-refinement-script"'
    ) < html.index('id="public-structural-v2-factual-rate-finder-script"')


def test_provider_bridge_routes_existing_cockpit_through_sanitized_adapter() -> None:
    html = inject_public_structural_v2_forecast_provider(_minimal_parent())

    assert "buildSurfaceFrame" in html
    assert "createStructuralProvider" in html
    assert "validatePublicForecast" in html
    assert "attachForecast" in html
    assert "baseline_new_money:args.baseline_new_money" in html
    assert "current_rollover_rate_pct:args.current_rollover_rate_pct" in html
    assert "private_model" not in html
    assert "training_metric" not in html
    assert "feature_importance" not in html
    assert "source_file" not in html


def test_provider_presentation_is_idempotent() -> None:
    once = inject_public_structural_v2_forecast_provider(_minimal_parent())
    twice = inject_public_structural_v2_forecast_provider(once)

    assert twice == once
    assert twice.count(ENGINE_MARKER) == 1
    assert twice.count(BRIDGE_MARKER) == 1


def test_provider_presentation_fails_closed_without_parent_contract() -> None:
    html = "<html><head></head><body></body></html>"

    with pytest.raises(DashboardBuildError, match="선행 계약"):
        inject_public_structural_v2_forecast_provider(html)


def test_provider_presentation_fails_closed_on_partial_injection() -> None:
    html = _minimal_parent().replace(
        "</head>",
        '<script id="public-structural-v2-forecast-provider-engine"></script></head>',
    )

    with pytest.raises(DashboardBuildError, match="불완전"):
        inject_public_structural_v2_forecast_provider(html)
