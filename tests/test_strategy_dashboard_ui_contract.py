"""전략 대시보드 HTML의 핵심 의사결정·실데이터 UI 계약."""

from pathlib import Path

TEMPLATE = Path("web/templates/strategy.html")


def _html() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_strategy_dashboard_has_one_kpi_row_without_legacy_briefing() -> None:
    html = _html()

    assert "핵심 시장 브리핑" not in html
    assert "시장 선두 최고금리" not in html
    assert html.count('id="market-max"') == 1
    assert html.count('id="mean"') == 1
    assert html.count('id="count"') == 1
    assert html.count('id="top10"') == 1
    assert ".kpis{grid-template-columns:repeat(4,minmax(0,1fr))" in html
    assert ".kpi{min-height:132px" in html


def test_strategy_dashboard_keeps_readable_desktop_density() -> None:
    html = _html()

    assert ".shell{width:min(1380px,calc(100% - 32px))" in html
    assert ".head h2{margin:0;font-size:15px" in html
    assert ".simrow label{color:#cad5d0;font-size:10.5px" in html
    assert ".segment button{border:1px solid var(--line)" in html
    assert "padding:8px 12px;font-size:10px" in html
    assert ".simresult b{display:block;margin-top:4px" in html
    assert "font:790 19px var(--mono)" in html
    assert ".chartwrap{height:310px" in html
    assert ".node-label{fill:#d3dcd7;font:700 11px" in html


def test_strategy_dashboard_expands_canonical_source_and_district_fields() -> None:
    html = _html()

    assert 'district:look("district",r[c.district])' in html
    assert 'sourceId:look("source_id",r[c.source_id])' in html
    assert 'sourceEffectiveAt:look("source_effective_at",r[c.source_effective_at])' in html
    assert 'prefStatus:look("preference_status",r[c.preference_status])' in html
    assert 'prefTags:look("preference_tags",r[c.preference_tags])' in html
    assert 'id="leader-source"' in html
    assert "formatDate(r.sourceEffectiveAt)" in html


def test_strategy_dashboard_uses_product_representatives_for_market_metrics() -> None:
    html = _html()

    assert "function aggregateProducts(term)" in html
    assert 'const key=`${r.institution}\\0${r.product}\\0${term}`' in html
    assert "r.max>p.max" in html
    assert "products12=aggregateProducts(12)" in html
    assert "ratesStats(products12)" in html


def test_strategy_dashboard_uses_large_map_and_real_busan_boundaries() -> None:
    html = _html()

    assert ".primary{grid-template-columns:minmax(0,1.45fr)" in html
    assert ".mapcard{min-height:640px" in html
    assert ".mapstage{height:540px" in html
    assert 'id="geo-map"' in html
    assert "지역별 상품 대표 최고금리의 평균" in html
    assert "function regionAverages(rows)" in html
    assert 'data-region="${esc(x.region)}"' in html
    assert 'x.region==="부산"?"busan clickable"' in html
    assert "function renderKoreaMap()" in html
    assert "function showBusanMap()" in html
    assert "const BUSAN_BOUNDARY_SVG=" in html
    assert "const busanCoords=" not in html
    assert "부산을 누르면 부산 지도로 확대" in html
    assert "부산 구·군별 금리 지도" in html
    assert "부산 위치 개략도" not in html
    assert "통계청 SGIS 2020 행정경계" in html
    assert "StatGarten maps(MIT)" in html
    assert 'region(x.region)==="부산"&&x.district' in html
    assert "데이터 없음" in html
    assert 'id="map-back"' in html
    assert 'id="district-panel"' not in html
    assert 'id="district-grid"' not in html
    districts = (
        "강서구", "금정구", "기장군", "남구", "동구", "동래구", "부산진구", "북구",
        "사상구", "사하구", "서구", "수영구", "연제구", "영도구", "중구", "해운대구",
    )
    for district in districts:
        assert f'id="{district}"' in html


def test_busan_boundary_keeps_source_and_license_notice() -> None:
    notice = Path("docs/third-party/statgarten-maps.md").read_text(encoding="utf-8")

    assert "통계청 SGIS Open API" in notice
    assert "geometry 기준연도: **2020**" in notice
    assert "MIT License" in notice
    assert "Copyright (c) 2022 StatGarten" in notice
    assert "데이터 없음" in notice


def test_strategy_dashboard_places_map_before_top5() -> None:
    html = _html()

    assert html.index('id="geo-map"') < html.index("경쟁사 TOP 5")


def test_simulator_term_selector_changes_real_market_universe() -> None:
    html = _html()

    assert 'data-term="6"' in html
    assert 'data-term="12"' in html
    assert 'data-term="24"' in html
    assert 'data-term="36"' in html
    assert "comp=aggregateProducts(simTerm)" in html
    assert "higher=comp.filter" in html
    assert 'id="sim-top10"' in html
    assert "stats.top10.toFixed(2)" in html
    assert "stats.mean.toFixed(2)" in html
    assert "stats.median.toFixed(2)" in html


def test_simulator_compares_proposal_with_actual_our_bank_product() -> None:
    html = _html()

    assert 'const OUR_INSTITUTION="고려저축은행"' in html
    assert "p.institution===OUR_INSTITUTION" in html
    assert 'id="own-max"' in html
    assert 'id="own-delta"' in html
    assert 'id="marker-own"' in html
    assert "제안안 ${proposed-own.max" in html


def test_simulator_has_no_preference_condition_selector() -> None:
    html = _html()

    assert "우대조건 트렌드" in html
    assert 'prefStatus:look("preference_status",r[c.preference_status])' in html
    assert 'prefTags:look("preference_tags",r[c.preference_tags])' in html
    assert "기본금리·우대금리·가입기간만 입력" in html
    assert 'id="term-segment"' in html
    assert "우대조건 수" not in html
    assert 'id="condition-segment"' not in html
    assert 'id="condition-match"' not in html
    assert 'id="condition-note"' not in html
    assert "simConditionCount" not in html
    assert "conditionStats(products,selected)" not in html


def test_strategy_dashboard_keeps_three_historical_rate_lines() -> None:
    html = _html()

    assert "시장 최고 / 시장 평균 / 고려저축은행 최고금리" in html
    assert "시장 최고</span>" in html
    assert "시장 평균</span>" in html
    assert "고려저축은행</span>" in html
    assert 'build("market_max_rate","max")' in html
    assert 'build("mean_max_rate","mean",true)' in html
    assert 'build("our_company_max_rate","own")' in html


def test_strategy_dashboard_keeps_scenario_safety_language() -> None:
    html = _html()

    assert "가정 기반 예상 월 수신액" in html
    assert "내부 실적 기반 예측모형이 아닙니다" in html
    assert "실제 유입을 보장하지 않습니다" in html
    assert 'baselineRaw!==""' in html
    assert 'sensitivityRaw!==""' in html


def test_market_change_detail_stays_deduplicated_and_secondary() -> None:
    html = _html()

    assert "<details class=\"card changes\">" in html
    assert "동일 상품 variant 동시 변경은 상품 이벤트 1건으로 집계" in html
    assert "affected_variant_count" in html
    assert "variant_count" in html
