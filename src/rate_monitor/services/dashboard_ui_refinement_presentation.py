"""기존 공통 UI refinement에 상품군/기간 계약을 합성하는 호환 entrypoint."""

from __future__ import annotations

from typing import Any

from rate_monitor.services import dashboard_ui_refinement_base as _base
from rate_monitor.services.dashboard_product_scope_presentation import (
    inject_dashboard_product_scope,
)

STYLE_MARKER = _base.STYLE_MARKER
SCRIPT_MARKER = _base.SCRIPT_MARKER
DASHBOARD_UI_STYLE = _base.DASHBOARD_UI_STYLE
DASHBOARD_UI_SCRIPT = _base.DASHBOARD_UI_SCRIPT


def __getattr__(name: str) -> Any:
    return getattr(_base, name)


def inject_dashboard_ui_refinement(html: str) -> str:
    return inject_dashboard_product_scope(_base.inject_dashboard_ui_refinement(html))
