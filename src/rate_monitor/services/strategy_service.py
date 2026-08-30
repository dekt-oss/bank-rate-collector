"""Strategy 요약 호환 wrapper + 상품군/기간 이력 확장."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rate_monitor.services import strategy_service_base as _base
from rate_monitor.services.institution_funding_position_service import (
    build_institution_funding_positions,
)
from rate_monitor.services.market_funding_strategy_service import (
    build_market_funding_strategy,
)
from rate_monitor.services.strategy_product_history_service import build_product_history
from rate_monitor.services.strategy_savings_trend_policy import (
    build_savings_trend_display_policy,
)
from rate_monitor.services.strategy_service_base import *  # noqa: F403


def __getattr__(name: str) -> Any:
    return getattr(_base, name)


def build_strategy_summary(db_path: Path) -> dict[str, Any]:
    summary = _base.build_strategy_summary(db_path)
    product_history = build_product_history(db_path)
    product_history["savings_trend_display_policy"] = (
        build_savings_trend_display_policy(product_history)
    )
    summary["product_history"] = product_history
    summary["market_funding"] = build_market_funding_strategy(db_path)
    summary["institution_funding_positions"] = build_institution_funding_positions(db_path)
    return summary
