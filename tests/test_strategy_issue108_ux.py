"""Issue #108 요구 1·2의 전략 대시보드 계약."""

from tests.strategy_output_helper import built_strategy_html


def test_other_preference_drilldown_uses_published_raw_source_text() -> None:
    html = built_strategy_html()

    assert 'prefRaw:look("preference",r[c.preference])||""' in html
    assert 'otherSamples:new Map' in html
    assert 'codes.includes("OTHER")&&r.prefRaw' in html
    assert 'class="pref-other"' in html
    assert "기타 원문 보기" in html
    assert "원천 우대조건 원문 예시" in html
    assert "원문은 여러 조건을 함께 포함할 수 있습니다." in html


def test_market_insight_is_before_national_map_and_top5() -> None:
    html = built_strategy_html()

    insight = html.index("시장 인사이트")
    map_title = html.index("전국 본점 소재지별 금리 분포")
    top5 = html.index("경쟁사 TOP 5")
    planning = html.index("신상품 기획 시뮬레이터")

    assert insight < map_title < planning
    assert insight < top5 < planning


def test_national_map_is_compact_without_regressing_busan_focus() -> None:
    html = built_strategy_html()

    assert '.primary:not(.busan-focus) .mapcard{min-height:440px}' in html
    assert '.primary:not(.busan-focus) .mapstage{height:350px}' in html
    assert '.primary:not(.busan-focus)>article:last-child{min-height:440px}' in html
    assert '.primary.busan-focus .mapcard{min-height:650px}' in html
    assert '.primary.busan-focus .mapstage{height:560px}' in html
    assert 'const busanLabelOffsets=' in html
    assert 'id="busan-rate-list"' in html
