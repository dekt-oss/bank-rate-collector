"""Strategy 최종 IA의 Search 지역 상세 handoff 계약."""

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_decision_cockpit import inject_strategy_decision_cockpit
from rate_monitor.services.strategy_decision_handoff_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_strategy_decision_handoff,
)


def _fixture() -> str:
    return """<!doctype html>
<html>
<head></head>
<body>
<div class="ux-region-handoff" hidden><span>지역 상세</span><a href="./">지역 상세 보기</a></div>
</body>
</html>"""


def test_handoff_injection_is_idempotent_and_restores_visibility() -> None:
    once = inject_strategy_decision_handoff(_fixture())
    twice = inject_strategy_decision_handoff(once)

    assert once == twice
    assert once.count(STYLE_MARKER) == 1
    assert once.count(SCRIPT_MARKER) == 1
    assert 'handoff.hidden=false' in once
    assert 'handoff.dataset.decisionHandoff="1"' in once
    assert '.ux-region-handoff[data-decision-handoff="1"]{display:flex!important}' in once


def test_handoff_injection_fails_closed_without_contract() -> None:
    with pytest.raises(DashboardBuildError, match="Search handoff 선행 계약"):
        inject_strategy_decision_handoff("<html><head></head><body></body></html>")


def test_full_cockpit_composes_handoff_after_decision_refinement() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / "web/templates/strategy.html").read_text(encoding="utf-8")
    html = inject_strategy_decision_cockpit(template)

    refinement = 'id="strategy-decision-evidence-refinement-script"'
    handoff = 'id="strategy-decision-handoff-script"'
    assert refinement in html
    assert handoff in html
    assert html.index(refinement) < html.index(handoff)
