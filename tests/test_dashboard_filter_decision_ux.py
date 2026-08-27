from pathlib import Path

from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)
from rate_monitor.services.strategy_decision_cockpit import inject_strategy_decision_cockpit

SEARCH_TEMPLATE = Path("web/templates/site.html")
STRATEGY_TEMPLATE = Path("web/templates/strategy.html")


def _search_html() -> str:
    return inject_dashboard_ui_refinement(SEARCH_TEMPLATE.read_text(encoding="utf-8"))


def _strategy_html() -> str:
    cockpit = inject_strategy_decision_cockpit(
        STRATEGY_TEMPLATE.read_text(encoding="utf-8")
    )
    return inject_dashboard_ui_refinement(cockpit)


def test_search_product_families_are_multi_select_and_shareable() -> None:
    html = _search_html()

    assert 'data-product-family-toggle="deposit"' in html
    assert 'data-product-family-toggle="savings"' in html
    assert 'return deposit && savings ? "combined"' in html
    assert 'family === "savings" || family === "combined"' in html
    assert 'family === "combined" ? [PRODUCT_DEPOSIT_TYPE, ...selected]' in html
    assert 'if (family !== "deposit") {' in html
    assert "예금 + 적금" in html
    assert 'class="search-family-checks"' in html


def test_strategy_sector_controls_expose_parent_child_hierarchy() -> None:
    html = _strategy_html()

    assert 'id="dashboard-filter-decision-ux-style"' in html
    assert 'data-sector-family-toggle="savings_bank"' in html
    assert 'data-sector-family-toggle="mutual_finance"' in html
    assert 'class="strategy-mutual-children"' in html
    assert "const order={cu:0,nh_local:1,kfcc:2}" in html
    assert 'data-market-mode="combined"' in html
    assert "modes.querySelector(`[data-market-mode=\"${mode}\"]`)?.click()" in html


def test_strategy_decision_details_default_open_without_cross_family_prediction() -> None:
    html = _strategy_html()

    # Product-scope boot no longer closes the detail panel unconditionally.
    prediction_visibility = (
        '$("prediction-toggle").hidden=mutualOnly;'
        '$("prediction-panel").hidden=mutualOnly;'
    )
    assert prediction_visibility in html
    assert 'if(toggle)toggle.hidden=false;if(panel)panel.hidden=false;' in html
    assert 'marketReference.open=true' in html
    assert 'modelDetail.open=true' in html
    assert 'modelEvidence.open=true' in html

    # The prediction formulas and sensitivity coefficients remain present, but
    # non-deposit product scopes fail closed instead of using combined TOP10 data.
    assert "수신금액 예측 계산은 예금 단독 전용입니다" in html
    assert "수신예측 민감도 계산은 예금 단독 전용입니다" in html
    assert 'data-product-family-toggle="deposit"' in html
    assert 'data-product-family-toggle="savings"' in html
    assert "function predictInflow" in html
    assert "new_money_log_change_per_10bp" in html


def test_release_policy_records_strategy_as_existing_production_surface() -> None:
    instructions = Path("AGENTS.md").read_text(encoding="utf-8")

    assert 'RATE_MONITOR_STRATEGY_DASHBOARD: "1"' in instructions
    assert "Do not describe Strategy production release as OFF" in instructions
    assert "no second, separate \"Release Gate ON\" approval" in instructions
