from pathlib import Path
from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)


SEARCH_TEMPLATE = Path("web/templates/site.html")
STRATEGY_TEMPLATE = Path("web/templates/strategy.html")


def test_search_product_family_scope_uses_existing_type_filter_as_single_state() -> None:
    html = inject_dashboard_ui_refinement(SEARCH_TEMPLATE.read_text(encoding="utf-8"))

    assert 'data-product-family="deposit"' in html
    assert 'data-product-family="savings"' in html
    assert 'value="installment_savings"' in html
    assert 'value="flexible_savings"' in html
    assert 'state.picked.type.add(PRODUCT_DEPOSIT_TYPE)' in html
    assert 'PRODUCT_SAVINGS_TYPES.forEach((type) => state.picked.type.add(type))' in html
    assert 'if (key === "type") { normalizeProductTypeSelection(); renderGroups(); }' in html
    assert 'if (key === "type") return `상품군 ${productScopeLabel()}`;' in html
    assert 'const basisLabel = () => productScopeLabel();' in html


def test_search_savings_presets_default_to_both_savings_subtypes() -> None:
    html = inject_dashboard_ui_refinement(SEARCH_TEMPLATE.read_text(encoding="utf-8"))

    assert html.count('type: ["installment_savings", "flexible_savings"]') >= 3
    assert 'installment_savings: "정기적금"' in html
    assert 'flexible_savings: "자유적금"' in html


def test_strategy_product_scope_links_kpis_and_blocks_deposit_only_prediction() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'data-product-mode="deposit"' in html
    assert 'data-product-mode="savings"' in html
    assert 'data-savings-type="installment_savings"' in html
    assert 'data-savings-type="flexible_savings"' in html
    assert 'fetch("data/table.json"' in html
    assert 'cacheKey=`${productScopeKey()}:${marketMode}' in html
    assert '!activeProductTypes().has(r.type)' in html
    assert '12개월 ${productScopeLabel()}' in html
    assert 'renderProductHistoryScope();renderInsightsEnhanced()' in html
    assert 'if(productMode==="savings"){clearInflowPrediction' in html
    assert '수신금액 예측은 예금 전용이라 비활성화' in html


def test_strategy_savings_history_is_fail_closed_not_relabelled_deposit_history() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert '적금 이력 미지원' in html
    assert '30일/63일 이력 계약은 예금과 분리해 아직 계산하지 않습니다.' in html
    assert '현재 적금 스냅샷 비교에는 포함되지 않는 예금 전용 이력 지표입니다.' in html
