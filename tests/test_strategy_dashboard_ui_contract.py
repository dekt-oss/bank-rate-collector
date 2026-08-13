"""전략 대시보드 HTML 초안의 핵심 의사결정 UI 계약."""

from pathlib import Path

TEMPLATE = Path("web/templates/strategy.html")


def _html() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_strategy_dashboard_keeps_briefing_and_market_position_ui() -> None:
    html = _html()

    assert "핵심 시장 브리핑" in html
    assert 'id="brief-leader-rate"' in html
    assert 'id="brief-change-rate"' in html
    assert 'id="brief-top10-rate"' in html
    assert "상위 10% 진입선" in html

    assert "시장 포지션" in html
    assert 'id="marker-mean"' in html
    assert 'id="marker-median"' in html
    assert 'id="marker-proposed"' in html
    assert 'id="position-copy"' in html


def test_strategy_dashboard_explains_product_event_deduplication() -> None:
    html = _html()

    assert "상품 변경 이벤트" in html
    assert 'id="change-note"' in html
    assert "affected_variant_count" in html
    assert "variant_count" in html
    assert "세부 관측" in html


def test_strategy_dashboard_keeps_scenario_safety_language() -> None:
    html = _html()

    assert "가정 기반 예상 월 수신액" in html
    assert "내부 실적 기반 예측모형이 아닙니다" in html
    assert "실제 유입을 보장하지 않습니다" in html
    assert 'baselineRaw!==""' in html
    assert 'sensitivityRaw!==""' in html
