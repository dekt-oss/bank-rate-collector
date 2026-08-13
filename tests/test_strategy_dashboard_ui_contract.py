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
    assert ".kpi{min-height:128px" in html


def test_strategy_dashboard_keeps_readable_desktop_density() -> None:
    html = _html()

    assert ".shell{width:min(1280px,calc(100% - 28px))" in html
    assert ".head h2{margin:0;font-size:15px" in html
    assert ".simrow label{color:#cad5d7;font-size:10.5px" in html
    assert ".segment button{border:1px solid var(--line)" in html
    assert "padding:7px 10px;font-size:10px" in html
    assert ".simresult b{display:block;margin-top:3px" in html
    assert "font:790 18px var(--mono)" in html
    assert ".chartwrap{height:300px" in html
    assert ".node-label{fill:#d0dcdd;font:700 10px" in html


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


def test_strategy_dashboard_uses_region_average_and_busan_district_drilldown() -> None:
    html = _html()

    assert "지역별 상품 대표 최고금리의 평균" in html
    assert "function regionAverages(rows)" in html
    assert 'data-region="${esc(x.region)}"' in html
    assert 'x.region==="부산"?"busan clickable"' in html
    assert "function showBusanDistricts()" in html
    assert 'region(x.region)==="부산"&&x.district' in html
    assert 'id="district-panel"' in html
    assert 'id="district-grid"' in html
    assert 'id="map-back"' in html
    assert "canonical district" in html


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


def test_condition_selector_is_data_linked_but_does_not_change_rate_rank() -> None:
    html = _html()

    assert "function conditionStats(products,selected)" in html
    assert "p.prefKnown" in html
    assert "p.tagCount" in html
    assert 'id="condition-match"' in html
    assert 'id="condition-note"' in html
    assert "simConditionCount=Number(btn.dataset.condition)" in html
    assert "시장 중앙" in html
    assert "금리순위에는 미반영" in html
    assert "조건 수는 금리순위를 임의 조정하지 않습니다" in html


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
