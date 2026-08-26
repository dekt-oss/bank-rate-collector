"""Stage E 기획 흐름·표현 계약을 실제 build 산출물로 검증한다."""

import re

from tests.strategy_output_helper import built_strategy_html


def test_kpis_default_to_12_months_but_follow_global_term_scope() -> None:
    html = built_strategy_html()

    assert html.count('class="basis-label">12개월</span>') == 4
    assert 'scopeTerm=12' in html
    assert 'products12=aggregateProducts(scopeTerm)' in html
    for term in (6, 12, 24, 36):
        assert f'data-scope-term="{term}"' in html


def test_planning_period_uses_same_global_term_as_kpis() -> None:
    html = built_strategy_html()

    assert 'id="planning-basis"' in html
    assert (
        '$("planning-basis").innerHTML=`<span>전역 가입기간</span>'
        '<b>${scopeTerm}개월</b><span>· KPI·TOP·지도·추이·시뮬레이터 연동</span>`'
        in html
    )
    assert 'setScopeTerm(btn.dataset.term)' in html


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
    # 당사 기본 12개월 상품이 없으면 JS가 손대지 않는 기존 fallback을 그대로 보존한다.
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


def test_absolute_css_fonts_are_never_below_9px() -> None:
    html = built_strategy_html()
    sizes = [
        float(match)
        for match in re.findall(
            r"(?:font-size:|font:(?:[^;{}]*?\s)?)([0-9]+(?:\.[0-9]+)?)px",
            html,
        )
    ]

    assert sizes, "absolute px font contract를 검사할 CSS가 없습니다"
    too_small = sorted({size for size in sizes if size < 9})
    assert not too_small, f"9px 미만 absolute font가 남아 있습니다: {too_small}"
