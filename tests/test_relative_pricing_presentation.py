from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)
from rate_monitor.services.relative_pricing_presentation import (
    SCRIPT_MARKER,
    SECTION_MARKER,
    STYLE_MARKER,
    inject_relative_pricing_presentation,
)


def _strategy_html() -> str:
    return """
    <html><head></head><body>
      <div id="market-scope"></div>
      <div id="reg"></div>
      <script id="rate-response-cockpit-script"></script>
      <script id="rate-monitor-data" type="application/json">{"strategy": {}}</script>
      <footer class="foot"></footer>
    </body></html>
    """


def test_relative_pricing_injector_adds_exactly_one_r1_surface() -> None:
    rendered = inject_relative_pricing_presentation(_strategy_html())
    rendered = inject_relative_pricing_presentation(rendered)

    assert rendered.count(STYLE_MARKER) == 1
    assert rendered.count(SCRIPT_MARKER) == 1
    assert rendered.count(SECTION_MARKER) == 1
    assert "상대금리 · 주요 경쟁기관" in rendered
    assert "전체 상품시장 위치 · 현재 기준" in rendered
    assert "주요 경쟁기관 위치 · 검토금리 반영" in rendered


def test_r1_surface_keeps_review_rate_and_cost_inputs_factual() -> None:
    rendered = inject_relative_pricing_presentation(_strategy_html())

    assert 'id="rp-review-slider" type="range" min="1.50" max="6.00" step="0.01"' in rendered
    assert "기존 Strategy 제안금리 slider 계약 · 1bp" in rendered
    assert "비용 계산 기준금액(수신 목표 아님)" in rendered
    assert 'id="rp-cost-notional" type="number" min="0"' in rendered
    assert "고정 원금 · 단리 표면이자 차이" in rendered

    # R1 must not introduce goal/recommendation inputs or prediction outputs.
    forbidden_ids = (
        'id="target-balance"',
        'id="target-net-inflow"',
        'id="target-horizon"',
        'id="recommended-rate"',
        'id="predicted-inflow"',
    )
    assert all(item not in rendered for item in forbidden_ids)


def test_r1_competitor_table_keeps_rate_and_funding_dates_separate() -> None:
    rendered = inject_relative_pricing_presentation(_strategy_html())

    assert "금리 기준일" in rendered
    assert "수신 기준월" in rendered
    assert "funding 상태" in rendered
    assert "자료없음은 0이 아닙니다." in rendered
    assert "funding_balance_million_krw" in rendered
    assert "funding_as_of" in rendered
    assert "rate_as_of" in rendered


def test_r1_blocked_state_exposes_fail_closed_reason_without_fake_values() -> None:
    rendered = inject_relative_pricing_presentation(_strategy_html())

    assert "상대금리 비교를 아직 열지 않습니다." in rendered
    assert "availability_match_key_ambiguous" in rendered
    assert "matrix_representative_rate_temporal_mismatch" in rendered
    assert 'id="rp-ready" hidden' in rendered


def test_common_dashboard_composition_only_adds_r1_after_strategy_cockpit() -> None:
    strategy = inject_dashboard_ui_refinement(_strategy_html())
    search = inject_dashboard_ui_refinement(
        "<html><head></head><body><div id=\"reg\"></div></body></html>"
    )

    assert SECTION_MARKER in strategy
    assert SECTION_MARKER not in search
