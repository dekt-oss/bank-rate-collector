from __future__ import annotations

import pytest

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.rate_decision_simulator_presentation import (
    inject_rate_decision_simulator,
)

BASE_HTML = """<!doctype html>
<html>
<head></head>
<body>
<section id="prediction-panel"></section>
<div id="term-segment"></div>
<script id="rate-monitor-data" type="application/json">{}</script>
<script id="public-structural-v2-engine-bundle"></script>
<script id="public-structural-v2-cockpit-script"></script>
</body>
</html>
"""


def test_injects_style_and_runtime_bundle_once() -> None:
    rendered = inject_rate_decision_simulator(BASE_HTML)

    assert rendered.count('id="rate-decision-simulator-v1-style"') == 1
    assert rendered.count('id="rate-decision-simulator-v1-bundle"') == 1
    assert "StrategyTargetCandidate" in rendered
    assert "strategy-rate-decision-simulator" in rendered
    assert inject_rate_decision_simulator(rendered) == rendered


def test_runtime_bundle_keeps_nearby_sector_and_fail_closed_state_contract() -> None:
    rendered = inject_rate_decision_simulator(BASE_HTML)

    assert "SECTOR_LABELS" in rendered
    assert "<th>업권</th>" in rendered
    assert "clearDecisionState" in rendered
    assert "현재 계산이 차단되어 주변 상품을 표시하지 않습니다." in rendered
    assert "현재 계산이 차단되어 pricing peer gap을 표시하지 않습니다." in rendered
    assert "가장 낮은 existing candidate도 목표 이상" in rendered
    assert "더 낮은 금리는 지원범위 밖" in rendered


def test_runtime_bundle_separates_size_peer_from_relative_pricing() -> None:
    rendered = inject_rate_decision_simulator(BASE_HTML)

    assert "공식 가격 경쟁기관 <small>Relative Pricing R1</small>" in rendered
    assert "유사 규모 기관 <small>Size Peer</small>" in rendered
    assert 'data-size-peer-mode="remote"' in rendered
    assert 'data-size-peer-mode="branch_busan"' in rendered
    assert "가격 경쟁기관과 별도 기준" in rendered
    assert "재무 기준" in rendered
    assert "가입가능성 기준" in rendered
    assert "현재 총자산 비교 가능 업권: 저축은행 · 농·축협" not in rendered
    # The exact coverage string comes from the DB-backed payload, not hard-coded UI.
    assert "payload.coverage_note" in rendered
    assert "membership cutoff가 아닙니다" in rendered
    assert "selectedTerm()!==Number(payload.term_months||12)" in rendered


def test_mobile_size_peer_uses_card_layout_without_table_min_width() -> None:
    rendered = inject_rate_decision_simulator(BASE_HTML)

    assert "@media(max-width:620px)" in rendered
    assert ".rds-size-peer-table thead{display:none}" in rendered
    assert 'content:attr(data-label)' in rendered
    assert ".rds-size-peer-table,.rds-size-peer-table tbody" in rendered


def test_rejects_partial_injection_state() -> None:
    partial = BASE_HTML.replace(
        "</head>", '<style id="rate-decision-simulator-v1-style"></style></head>'
    )

    with pytest.raises(DashboardBuildError, match="주입 상태가 불완전"):
        inject_rate_decision_simulator(partial)


def test_requires_public_structural_v2_contract() -> None:
    missing_engine = BASE_HTML.replace(
        '<script id="public-structural-v2-engine-bundle"></script>', ""
    )

    with pytest.raises(DashboardBuildError, match="선행 계약이 없다"):
        inject_rate_decision_simulator(missing_engine)
