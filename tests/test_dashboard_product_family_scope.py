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
    restore_contract = (
        'normalizeProductScopeAliases();\n  readUrl();\n  '
        'restoreProductScopeAliasState();'
    )
    assert restore_contract in html
    assert 'rawSavings === "none"' in html


def test_strategy_scope_links_product_term_kpi_map_history_and_simulator() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'data-product-mode="deposit"' in html
    assert 'data-product-mode="savings"' in html
    assert 'data-product-family-toggle="deposit"' in html
    assert 'data-product-family-toggle="savings"' in html
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


def test_strategy_product_family_checkboxes_support_combined_current_scope() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'PRODUCT_FAMILY_MODES=new Set(["deposit","savings","combined"])' in html
    assert 'return new Set(["term_deposit",...savingsTypes])' in html
    assert 'return`combined:${savingsKey()}`' in html
    assert 'if(savingsTypes.size===2)return"예금 + 적금"' in html
    assert 'allRows=[...depositRows,...savingsRows]' in html
    assert 'strategyUniverse=buildCombinedUniverse()' in html
    assert 'metric_basis:"mixed_product_family_collected_best_rate"' in html
    assert 'evidence:"deposit_stable_plus_savings_canonical_current"' in html
    assert 'if(!checked.length){input.checked=true;renderProductScopeControls();return}' in html


def test_strategy_combined_scope_fails_closed_for_history_and_prediction() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'if(productMode==="combined")return null;' in html
    assert 'installmentMode=productMode!=="deposit"' in html
    assert 'if(productMode!=="deposit"){clearInflowPrediction(' in html
    assert '예금+적금 시장 비교 · 수신금액 예측은 예금 단독 전용' in html
    assert '상품군별 이력 계약이 달라 통합 이력은 재가공하지 않으며' in html


def test_strategy_scope_controls_and_key_sections_are_readable() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'id="dashboard-product-scope-readability-style"' in html
    assert '.strategy-family-checks label.active,.strategy-savings-types label.active' in html
    assert 'background:#123f32!important;color:#fff!important' in html
    assert '.strategy-product-scope .global-term-tabs button.active' in html
    assert '.top5-card .bank{color:var(--ink)!important;font-size:12px!important' in html
    assert '.top5-card .product{color:var(--ink)!important;opacity:.82!important' in html
    assert '.insightcard .insight b{color:var(--ink)!important;font-size:12px!important' in html
    assert 'grid-template-columns:repeat(3,minmax(0,1fr))!important' in html
    assert '.insightcard .insight:last-child{grid-column:auto!important}' in html


def test_strategy_savings_zero_selection_is_empty_not_forced() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'if(!savingsTypes.size)return"적금 · 선택 없음"' in html
    assert 'if(!savingsTypes.size)return null' in html
    assert 'else savingsTypes.delete(input.dataset.savingsType)' in html
    assert 'normalizeSavingsTypes' not in html
    assert '수신금액 예측은 정기예금 전용' in html
    assert '<div id="strategy-product-empty"' not in html
    assert 'note.id="strategy-product-empty"' in html
    assert "선택된 적금 유형이 없습니다" in html


def test_strategy_url_restores_and_preserves_product_scope() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'family==="deposit"||family==="savings"||family==="combined"' in html
    assert 'p.set("family",productMode);' in html
    assert 'p.set("term",String(scopeTerm));' in html
    assert 'if(productMode!=="deposit")p.set("savings",savingsTypes.size?' in html
    assert 'raw==="none"?[]' in html
    assert 'setProductMode(q.family)' in html
    assert 'p.set("family",productMode);p.set("term",String(scopeTerm));' in html


def test_strategy_followup_runtime_stays_inside_main_iife_scope() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert "dashboard-strategy-product-followup-runtime" in html
    assert "dashboard-strategy-savings-insight-runtime" in html
    assert "dashboard-strategy-scope-readability-runtime" in html
    assert '<script id="dashboard-strategy-product-followup-script">' not in html
    assert '<script id="dashboard-strategy-savings-insight-script">' not in html
    assert '<script id="dashboard-strategy-scope-readability-script">' not in html
    data_end = html.index("</script>", html.index('id="rate-monitor-data"'))
    main_start = html.index("<script>", data_end)
    main_end = html.index("</script>", main_start)
    followup = html.index("dashboard-strategy-product-followup-runtime")
    insight = html.index("dashboard-strategy-savings-insight-runtime")
    readability = html.index("dashboard-strategy-scope-readability-runtime")
    assert main_start < followup < insight < readability < main_end


def test_strategy_savings_all_uses_adaptive_subtype_trend_panel() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'id="savings-subtype-trend"' in html
    assert 'savings_trend_display_policy?.terms?.[String(scopeTerm)]' in html
    assert 'policy.display_mode==="split"' in html
    assert 'pointMap("savings_installment")' in html
    assert 'pointMap("savings_flexible")' in html
    assert "두 추이를 분리 표시" in html
    assert "통합 추이 유지" in html


def test_strategy_split_trend_shows_gap_badge_and_latest_spread_kpi() -> None:
    html = inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert "dashboard-strategy-savings-insight-runtime" in html
    assert 'id="savings-subtype-gap-badge"' in html
    assert "유형별 차이 확대" in html
    assert 'id="savings-subtype-spread-kpi"' in html
    assert "유형간 스프레드" in html
    assert 'const latestCommonSpread=()=>{' in html
    assert 'const spread=installmentRate-flexibleRate;' in html
    assert 'policy?.display_mode==="split"' in html
    assert "정기적금 우위" in html
    assert "자유적금 우위" in html
