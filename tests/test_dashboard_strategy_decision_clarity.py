from pathlib import Path

from rate_monitor.services.dashboard_ui_refinement_presentation import (
    inject_dashboard_ui_refinement,
)

STRATEGY_TEMPLATE = Path("web/templates/strategy.html")


def _html() -> str:
    return inject_dashboard_ui_refinement(STRATEGY_TEMPLATE.read_text(encoding="utf-8"))


def test_strategy_decision_clarity_exposes_scope_contract_and_readable_controls() -> None:
    html = _html()

    assert 'id="dashboard-strategy-decision-clarity-style"' in html
    assert 'contract.id="strategy-scope-contract"' in html
    assert "통합 이력 미생성 · 상품군별 이력 유지" in html
    assert "예금 단독에서만 사용" in html
    assert "font-size:12.5px!important" in html
    assert ".strategy-product-scope .global-term-tabs button" in html
    assert "font-size:12px!important" in html


def test_strategy_decision_clarity_adds_own_position_without_changing_ranking_population() -> None:
    html = _html()

    assert "const decorateOwnPosition=()=>{" in html
    assert "products12.find(product=>product.institution===OUR_INSTITUTION)" in html
    assert "products12.filter(product=>product.max>own.max+1e-9).length+1" in html
    assert 'row.dataset.ownPosition="row"' in html
    assert 'row.dataset.ownPosition="empty"' in html
    assert "TOP5 평균 대비" in html
    assert "5위선까지" in html
    clarity_runtime = html.split(
        "dashboard-strategy-decision-clarity-runtime", 1
    )[-1]
    assert "aggregateProducts=" not in clarity_runtime


def test_strategy_decision_clarity_relabels_existing_insight_evidence_and_action() -> None:
    html = _html()

    assert "const decorateInsightActions=()=>{" in html
    assert 'evidence.classList.add("insight-evidence")' in html
    assert "판단 근거 ·" in html
    assert 'action.classList.add("insight-action")' in html
    assert "권고 행동 ·" in html
    assert ".insightcard .insight .insight-action" in html


def test_strategy_decision_clarity_runtime_stays_after_readability_inside_main_iife() -> None:
    html = _html()

    assert "dashboard-strategy-decision-clarity-runtime" in html
    assert '<script id="dashboard-strategy-decision-clarity-script">' not in html
    data_end = html.index("</script>", html.index('id="rate-monitor-data"'))
    main_start = html.index("<script>", data_end)
    main_end = html.index("</script>", main_start)
    readability = html.index("dashboard-strategy-scope-readability-runtime")
    clarity = html.index("dashboard-strategy-decision-clarity-runtime")
    assert main_start < readability < clarity < main_end
