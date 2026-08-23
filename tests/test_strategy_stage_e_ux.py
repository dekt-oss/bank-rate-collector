"""Stage E 기획 흐름·표현 계약을 실제 build 산출물로 검증한다."""

from tests.strategy_output_helper import built_strategy_html


def test_kpis_are_explicitly_fixed_to_12_month_basis() -> None:
    html = built_strategy_html()

    assert html.count('class="basis-label">12개월</span>') == 4
    assert '시장 최고 금리 <span class="basis-label">12개월</span>' in html
    assert '시장 평균 금리 <span class="basis-label">12개월</span>' in html
    assert '현재 비교군 <span class="basis-label">12개월</span>' in html
    assert '상위 10% 진입선 <span class="basis-label">12개월</span>' in html


def test_planning_period_is_visibly_distinct_from_fixed_kpis() -> None:
    html = built_strategy_html()

    assert 'id="planning-basis"' in html
    assert '<span>선택기간</span><b>12개월</b><span>· 상단 KPI는 12개월 고정</span>' in html
    assert (
        '$("planning-basis").innerHTML=`<span>선택기간</span><b>${simTerm}개월</b>'
        '<span>· 상단 KPI는 12개월 고정</span>`' in html
    )


def test_prediction_summary_stays_visible_while_detail_panel_is_collapsed() -> None:
    html = built_strategy_html()

    summary = (
        '<div class="engine-summary" id="prediction-summary">내부 실적 미보정 · '
        '신규수신·만기·재예치율 3개 입력으로 총수신 범위 계산</div>'
    )
    assert summary in html
    assert '<div id="prediction-panel" class="prediction-panel" hidden>' in html
    assert html.index(summary) < html.index('<div id="prediction-panel"')


def test_simulator_resolves_initial_default_from_own_current_max_rate_once() -> None:
    html = built_strategy_html()

    assert 'let simDefaultsResolved=false;' in html
    assert 'function initializeSimulatorDefault(own)' in html
    assert 'simDefaultsResolved=true;if(!own||!Number.isFinite(own.max))return' in html
    assert 'const value=own.max.toFixed(2)' in html
    assert '$("base-n").value=value;$("base-r").value=value' in html
    assert '$("bonus-n").value="0.00";$("bonus-r").value="0.00"' in html
    assert 'initializeSimulatorDefault(own);const base=' in html
    # 당사 12개월 상품이 없으면 JS가 손대지 않는 기존 fallback을 그대로 보존한다.
    assert 'id="base-n" type="number" min="0" max="10" step="0.01" value="3.20"' in html
    assert 'id="bonus-n" type="number" min="0" max="3" step="0.01" value="0.50"' in html


def test_market_high_trend_note_includes_comparison_product_count_change() -> None:
    html = built_strategy_html()

    assert 'const firstProductCount=Number(first.product_count)' in html
    assert 'lastProductCount=Number(last.product_count)' in html
    assert 'productCountDelta=lastProductCount-firstProductCount' in html
    assert '비교상품 ${fmt.format(firstProductCount)}→${fmt.format(lastProductCount)}개' in html
    assert (
        '$("trend-max-note").textContent=`현재 '
        '${Number(last.market_max_rate).toFixed(2)}%${productCountNote}`' in html
    )


def test_mixed_term_and_history_card_has_truthful_title() -> None:
    html = built_strategy_html()

    assert '<h2>기간별 현재금리 · 12개월 시장 추이</h2>' in html
    assert (
        "현재 평균은 선택 업권 기준 · 이력 추이는 저축은행 정상 수집일 기준"
        in html
    )
    assert '<h2>기간별 금리 추이</h2>' not in html


def test_final_public_structural_layer_enforces_brand_microcopy_floor() -> None:
    html = built_strategy_html()

    brand_marker = 'id="strategy-brand-theme-style"'
    final_marker = 'id="public-structural-v2-cockpit-visual-refinement-style"'
    assert brand_marker in html
    assert final_marker in html
    assert html.index(brand_marker) < html.index(final_marker)

    start = html.index(final_marker)
    end = html.index("</style>", start)
    final_style = html[start:end]
    assert ".psv2-head p" in final_style
    assert ".psv2-chart .axis" in final_style
    assert ".psv2-table td:before" in final_style
    assert "font-size:10.5px!important" in final_style
