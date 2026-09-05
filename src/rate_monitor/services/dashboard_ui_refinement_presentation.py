"""기존 공통 UI refinement에 상품군/기간 계약을 합성하는 호환 entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rate_monitor.services import dashboard_ui_refinement_base as _base
from rate_monitor.services.collection_health_live_presentation import (
    inject_collection_health_live_signal,
)
from rate_monitor.services.dashboard_filter_decision_ux_presentation import (
    inject_dashboard_filter_decision_ux,
)
from rate_monitor.services.dashboard_product_scope_followup_presentation import (
    inject_dashboard_product_scope_followup,
)
from rate_monitor.services.dashboard_product_scope_insight_presentation import (
    inject_dashboard_product_scope_insight,
)
from rate_monitor.services.dashboard_product_scope_presentation import (
    inject_dashboard_product_scope,
)
from rate_monitor.services.dashboard_product_scope_readability_presentation import (
    inject_dashboard_product_scope_readability,
)
from rate_monitor.services.dashboard_product_scope_runtime_repair import (
    repair_strategy_product_scope_runtime,
)
from rate_monitor.services.dashboard_search_performance_presentation import (
    inject_dashboard_search_performance,
)
from rate_monitor.services.dashboard_strategy_decision_clarity_presentation import (
    inject_dashboard_strategy_decision_clarity,
)
from rate_monitor.services.institution_funding_position_presentation import (
    inject_institution_funding_position,
)
from rate_monitor.services.main_map_drilldown_refinement import (
    inject_main_map_drilldown_refinement,
)
from rate_monitor.services.rate_funding_matrix_presentation import (
    inject_rate_funding_matrix,
)
from rate_monitor.services.relative_pricing_presentation import (
    inject_relative_pricing_presentation,
)
from rate_monitor.services.strategy_decision_scope_compact_presentation import (
    inject_strategy_decision_scope_compact,
)
from rate_monitor.services.strategy_first_screen_ux_presentation import (
    inject_strategy_first_screen_ux,
)
from rate_monitor.services.strategy_market_direction_presentation import (
    inject_strategy_market_direction,
)
from rate_monitor.services.strategy_mobile_responsive_presentation import (
    inject_strategy_mobile_responsive,
)
from rate_monitor.services.strategy_top5_compact_presentation import (
    inject_strategy_top5_compact,
)
from rate_monitor.services.strategy_unfinished_collapse_presentation import (
    inject_strategy_unfinished_collapse,
)

STYLE_MARKER = _base.STYLE_MARKER
SCRIPT_MARKER = _base.SCRIPT_MARKER
DASHBOARD_UI_STYLE = _base.DASHBOARD_UI_STYLE
DASHBOARD_UI_SCRIPT = _base.DASHBOARD_UI_SCRIPT
_STRATEGY_TEMPLATE = Path("web/templates/strategy.html")
# Exact-source evidence trigger only. Functional source equals PR #306 HEAD.


def __getattr__(name: str) -> Any:
    return getattr(_base, name)


def inject_dashboard_ui_refinement(html: str) -> str:
    rendered = inject_dashboard_product_scope(_base.inject_dashboard_ui_refinement(html))
    if 'id="reg"' in rendered:
        rendered = inject_main_map_drilldown_refinement(
            rendered,
            _STRATEGY_TEMPLATE.read_text(encoding="utf-8"),
        )
    rendered = inject_dashboard_product_scope_followup(rendered)
    rendered = inject_dashboard_product_scope_insight(rendered)
    rendered = inject_dashboard_product_scope_readability(rendered)
    rendered = inject_dashboard_strategy_decision_clarity(rendered)
    rendered = inject_dashboard_search_performance(rendered)
    # Search는 공통 entrypoint만으로 완결된다. Strategy의 상세 복원은
    # decision cockpit이 먼저 합성된 실제 site build에서만 적용한다.
    if 'id="market-scope"' not in rendered or 'id="rate-response-cockpit-script"' in rendered:
        rendered = inject_dashboard_filter_decision_ux(rendered)
    if 'id="market-scope"' in rendered:
        rendered = inject_institution_funding_position(rendered)
        rendered = inject_rate_funding_matrix(rendered)
    rendered = repair_strategy_product_scope_runtime(rendered)
    rendered = inject_collection_health_live_signal(rendered)
    rendered = inject_strategy_unfinished_collapse(rendered)
    # Relative Pricing R1은 Strategy decision cockpit 이후에만 합성한다. Search
    # 화면이나 bare template에는 주입하지 않아 기존 화면 계약을 건드리지 않는다.
    if 'id="rate-response-cockpit-script"' in rendered:
        rendered = inject_relative_pricing_presentation(rendered)
    # fixed-width 회귀를 정리한 뒤 첫 화면 UX → factual 시장방향 → 4단계
    # 의사결정 메뉴 → sector-aware TOP5 순으로 합성해 최종 정보 위계를 고정한다.
    rendered = inject_strategy_mobile_responsive(rendered)
    rendered = inject_strategy_first_screen_ux(rendered)
    rendered = inject_strategy_market_direction(rendered)
    rendered = inject_strategy_decision_scope_compact(rendered)
    return inject_strategy_top5_compact(rendered)
