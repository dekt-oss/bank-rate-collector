"""Stage D2 Preference Intelligence presentation / payload 계약."""

import json
from pathlib import Path

import pytest

from rate_monitor.services.dashboard_service import DATA_END, DATA_MARKER, DashboardBuildError
from rate_monitor.services.preference_intelligence_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_preference_intelligence_presentation,
)
from rate_monitor.services.site_service import DEFAULT_STRATEGY_TEMPLATE, build_site
from rate_monitor.services.strategy_decision_cockpit import inject_strategy_decision_cockpit
from tests.test_strategy_dashboard import collected_db  # noqa: F401


def _minimal_html() -> str:
    return """
    <html><head></head><body>
      <script id="rate-monitor-data" type="application/json">
      {"strategy":{"preference_intelligence":{"scopes":[],"mutual_finance_scopes":[]}}}
      </script>
      <section class="grid interpretation"></section>
    </body></html>
    """


def _inline(html: str) -> dict:
    start = html.index(DATA_MARKER) + len(DATA_MARKER)
    end = html.index(DATA_END, start)
    return json.loads(html[start:end].replace("<\\/", "</"))


def test_preference_intelligence_panel_is_injected_once() -> None:
    rendered = inject_preference_intelligence_presentation(_minimal_html())

    assert rendered.count(STYLE_MARKER) == 1
    assert rendered.count(SCRIPT_MARKER) == 1
    assert "상품 · 우대조건 전략" in rendered
    assert "침투율 분모는 우대조건 보유 상품입니다" in rendered
    assert 'savings_bank:"저축은행"' in rendered
    assert 'nh_local:"농·축협"' in rendered
    assert "[6,12,24,36]" in rendered
    assert "known_preference_share" in rendered
    assert "preference_bearing_share_among_known" in rendered
    assert "market_product_share" in rendered
    assert "top_tier_product_share" in rendered
    assert "전체 우대상품 침투율" in rendered
    assert "상위금리군 침투율" in rendered
    assert "침투율 차이" in rendered
    assert "미제공을 '조건 없음'으로 해석하지 않습니다" in rendered
    assert "당사 우대조건 원문 근거" in rendered
    assert inject_preference_intelligence_presentation(rendered) == rendered


def test_preference_intelligence_partial_injection_fails_closed() -> None:
    html = _minimal_html().replace("</head>", f"<style {STYLE_MARKER}></style></head>")

    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_preference_intelligence_presentation(html)


def test_full_strategy_composition_includes_c2_and_d2() -> None:
    html = """
    <html><head></head><body>
      <script id="rate-monitor-data" type="application/json">
      {"strategy":{"market_intelligence":{"scopes":[]},"preference_intelligence":{"scopes":[],"mutual_finance_scopes":[]}}}
      </script>
      <div id="prediction-panel"></div>
      <section id="market-flow"></section>
      <section class="grid interpretation"></section>
      <script>function predictInflow(){return {}}</script>
    </body></html>
    """

    rendered = inject_strategy_decision_cockpit(html)

    assert rendered.count('id="rate-response-cockpit-style"') == 1
    assert rendered.count('id="market-intelligence-briefing-style"') == 1
    assert rendered.count('id="preference-intelligence-style"') == 1
    assert rendered.count('id="preference-intelligence-script"') == 1


def test_strategy_build_attaches_d1_payload_and_d2_ui(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    fixture = request.getfixturevalue("collected_db")
    db, _, _ = fixture
    out = tmp_path / "site-public"

    build_site(db, out_dir=out, strategy_template_path=DEFAULT_STRATEGY_TEMPLATE)

    strategy_html = (out / "strategy.html").read_text(encoding="utf-8")
    payload = _inline(strategy_html)
    preference = payload["strategy"]["preference_intelligence"]

    assert preference["version"] == "preference-intelligence-v2"
    assert preference["effect_calibration"] == "not_available_without_internal_performance_data"
    assert preference["top_tier_definition"] == "top_ceil_10pct_by_strategy_max_rate"
    assert preference["category_denominator"] == "preference_bearing_products_present_only"
    assert preference["category_composition_denominator"] == (
        "normalized_preference_category_occurrences_present_only"
    )
    assert preference["mutual_finance_scope_policy"] == "pooled_selected_mutual_sectors"
    assert preference["scopes"]
    assert preference["mutual_finance_scopes"]
    assert len(preference["mutual_finance_scopes"]) == 16
    assert 'id="preference-intelligence-style"' in strategy_html
    assert 'id="preference-intelligence-script"' in strategy_html
    assert "침투율 분모는 우대조건 보유 상품입니다" in strategy_html
