from pathlib import Path

from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)

SEARCH_TEMPLATE = Path("web/templates/site.html")
STRATEGY_TEMPLATE = Path("web/templates/strategy.html")


def test_search_product_family_allows_empty_savings_and_global_terms() -> None:
    html = inject_dashboard_ui_refinement(SEARCH_TEMPLATE.read_text(encoding="utf-8"))

    assert 'data-product-family="deposit"' in html
    assert 'data-product-family="savings"' in html
    assert 'value="installment_savings"' in html
    assert 'value="flexible_savings"' in html
    assert 'return "적금 · 선택 없음";' in html
    assert 'emptySavingsSelected = !PRODUCT_SAVINGS_TYPES.some' in html
    assert 'data-global-term="${value}"' in html
    for term in (6, 12, 24, 36):
        assert f'>{term}개월<' in html or str(term) in html
    assert 'state.tmin = value; state.tmax = value;' in html
    assert 'if (g.key === "term") return "";' in html
    assert "선택된 적금 유형이 없습니다" in html


def test_search_default_scope_is_deposit_12_months() -> None:
    html = inject_dashboard_ui_refinement(SEARCH_TEMPLATE.read_text(encoding="utf-8"))

    assert 'state.picked.type.add(PRODUCT_DEPOSIT_TYPE)' in html
    assert 'tmin: 12, tmax: 12' in html
    assert 'const basisLabel = () => `${activeGlobalTerm()}개월 ${productScopeLabel()}`;' in html
    assert html.count('type: ["installment_savings", "flexible_savings"]') >= 3


def test_search_url_preserves_family_savings_subtypes_and_term() -> None:
    html = inject_dashboard_ui_refinement(SEARCH_TEMPLATE.read_text(encoding="utf-8"))

    assert 'const normalizeProductScopeAliases = () => {' in html
    assert 'p.set("family", family);' in html
    assert 'p.set("term", String(activeGlobalTerm()));' in html
    assert 'p.set("savings", selected.length ? selected.join(",") : "none");' in html
    assert 'normalizeProductScopeAliases();\n  readUrl();\n  restoreProductScopeAliasState();' in html
    assert 'rawSavings === "none"' in html


def test_strategy_scope_links_product_term_kpi_map_history_and_simulator() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'data-product-mode="deposit"' in html
    assert 'data-product-mode="savings"' in html
    assert 'data-savings-type="installment_savings"' in html
    assert 'data-savings-type="flexible_savings"' in html
    for term in (6, 12, 24, 36):
        assert f'data-scope-term="{term}"' in html
    assert 'scopeTerm=12' in html
    assert 'products12=aggregateProducts(scopeTerm)' in html
    assert 'geoProducts(sector,scopeTerm)' in html
    assert 'prefData(scopeTerm)' in html
    assert 'activeRateTrend()' in html
    assert 'activeMarketChanges()' in html
    assert 'setScopeTerm(btn.dataset.term)' in html
    assert 'KPI·TOP·지도·추이·시뮬레이터 연동' in html


def test_strategy_savings_zero_selection_is_empty_not_forced() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'if(!savingsTypes.size)return"적금 · 선택 없음"' in html
    assert 'if(!savingsTypes.size)return null' in html
    assert 'else savingsTypes.delete(input.dataset.savingsType)' in html
    assert 'normalizeSavingsTypes' not in html
    assert '수신금액 예측은 정기예금 전용' in html
    assert 'id="strategy-product-empty"' not in html  # runtime-created to survive rerenders
    assert 'note.id="strategy-product-empty"' in html
    assert "선택된 적금 유형이 없습니다" in html


def test_strategy_url_restores_and_preserves_product_scope() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'p.set("family",productMode);' in html
    assert 'p.set("term",String(scopeTerm));' in html
    assert 'p.set("savings",savingsTypes.size?' in html
    assert 'raw==="none"?[]' in html
    assert 'allRows=q.family==="savings"?savingsRows:depositRows' in html
    assert 'strategyUniverse=q.family==="savings"?savingsUniverse:depositUniverse' in html


def test_strategy_savings_all_uses_adaptive_subtype_trend_panel() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'id="savings-subtype-trend"' in html
    assert 'savings_trend_display_policy?.terms?.[String(scopeTerm)]' in html
    assert 'policy.display_mode==="split"' in html
    assert 'pointMap("savings_installment")' in html
    assert 'pointMap("savings_flexible")' in html
    assert "두 추이를 분리 표시" in html
    assert "통합 추이 유지" in html
