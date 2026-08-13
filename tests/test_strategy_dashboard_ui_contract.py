"""전략 대시보드 HTML의 핵심 의사결정 UI 계약."""

from pathlib import Path

TEMPLATE = Path("web/templates/strategy.html")


def _html() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_strategy_dashboard_keeps_core_kpis_and_market_position_ui() -> None:
    html = _html()

    assert "시장 최고 금리" in html
    assert 'id="market-max"' in html
    assert "시장 평균 금리" in html
    assert 'id="mean"' in html
    assert "현재 비교군" in html
    assert 'id="count"' in html
    assert "상위 10% 진입선" in html
    assert 'id="top10"' in html

    assert "시장 포지션" in html
    assert 'id="marker-mean"' in html
    assert 'id="marker-median"' in html
    assert 'id="marker-proposed"' in html
    assert 'id="position-copy"' in html


def test_strategy_dashboard_keeps_trend_and_analysis_panels() -> None:
    html = _html()

    assert "우대조건 트렌드" in html
    assert "시장 인사이트" in html
    assert "기간별 금리 추이" in html
    assert 'id="trend-chart"' in html
    assert 'id="termstrip"' in html
    assert 'data-term="6"' in html
    assert 'data-term="12"' in html
    assert 'data-term="24"' in html
    assert 'data-term="36"' in html


def test_strategy_dashboard_compares_three_historical_rate_lines() -> None:
    html = _html()

    assert "시장 최고 / 시장 평균 / 고려저축은행 최고금리" in html
    assert "시장 최고</span>" in html
    assert "시장 평균</span>" in html
    assert "고려저축은행</span>" in html
    assert 'class="legendline max"' in html
    assert 'class="legendline mean"' in html
    assert 'class="legendline own"' in html
    assert 'build("market_max_rate","max")' in html
    assert 'build("mean_max_rate","mean",true)' in html
    assert 'build("our_company_max_rate","own")' in html


def test_strategy_dashboard_explains_product_event_deduplication() -> None:
    html = _html()

    assert "상품 변경 이벤트" in html
    assert "동일 상품 variant 동시 변경은 상품 이벤트 1건으로 집계" in html
    assert "affected_variant_count" in html
    assert "variant_count" in html
    assert "영향 세부 관측" in html


def test_strategy_dashboard_keeps_scenario_safety_language() -> None:
    html = _html()

    assert "가정 기반 예상 월 수신액" in html
    assert "내부 실적 기반 예측모형이 아닙니다" in html
    assert "실제 유입을 보장하지 않습니다" in html
    assert 'baselineRaw!==""' in html
    assert 'sensitivityRaw!==""' in html
