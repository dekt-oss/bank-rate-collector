from pathlib import Path

from rate_monitor.services.market_funding_preview_presentation import (
    SEARCH_MARKER,
    STRATEGY_MARKER,
    inject_search_market_funding_preview,
    inject_strategy_market_funding_preview,
    load_preview_snapshot,
)


SNAPSHOT = Path("config/market-funding-preview-snapshot.json")


def test_verified_snapshot_keeps_separate_analysis_and_leading_clocks() -> None:
    snapshot = load_preview_snapshot(SNAPSHOT)

    assert snapshot["purpose"] == "preview_only_verified_d0_snapshot"
    assert snapshot["analysis_month"] == "202606"
    assert snapshot["leading_rate_month"] == "202607"
    assert snapshot["source_run"] == 33054355763
    assert snapshot["source_artifact_id"] == 9638970120


def test_search_preview_owns_full_macro_market_view() -> None:
    base = "<html><head></head><body><header>search</header><main></main></body></html>"
    rendered = inject_search_market_funding_preview(base, load_preview_snapshot(SNAPSHOT))

    assert SEARCH_MARKER in rendered
    assert STRATEGY_MARKER not in rendered
    assert "수신시장 현황" in rendered
    assert "업권별 수신잔액 추이" in rendered
    assert "예금은행 수신 구조" in rendered
    assert "정기예금 만기 구조" in rendered
    assert "2026.06" in rendered
    assert "2026.07" in rendered
    assert "4.21%" in rendered
    assert "2,281.49" in rendered
    assert "잔액 증감은 신규 순유입과 동일하지 않으며" in rendered
    assert rendered.count('class="mf-card"') == 4


def test_strategy_preview_is_compact_context_not_duplicate_macro_chart() -> None:
    base = "<html><head></head><body><header>strategy</header><main></main></body></html>"
    rendered = inject_strategy_market_funding_preview(base, load_preview_snapshot(SNAPSHOT))

    assert STRATEGY_MARKER in rendered
    assert SEARCH_MARKER not in rendered
    assert "시장 환경 요약" in rendered
    assert "수신시장 현황 전체 보기" in rendered
    assert "업권별 수신잔액 추이" not in rendered
    assert "정기예금 만기 구조" not in rendered
    assert rendered.count('class="smf-item"') == 4
    assert "최신 금리 2026.07는 선행신호로 분리" in rendered
    assert "인과관계는 단정하지 않음" in rendered


def test_preview_injection_is_idempotent() -> None:
    snapshot = load_preview_snapshot(SNAPSHOT)
    search = "<html><head></head><body><header>search</header></body></html>"
    strategy = "<html><head></head><body><header>strategy</header></body></html>"

    search_once = inject_search_market_funding_preview(search, snapshot)
    strategy_once = inject_strategy_market_funding_preview(strategy, snapshot)

    assert inject_search_market_funding_preview(search_once, snapshot) == search_once
    assert inject_strategy_market_funding_preview(strategy_once, snapshot) == strategy_once
