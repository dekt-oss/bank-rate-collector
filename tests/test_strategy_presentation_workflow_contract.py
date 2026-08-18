"""Strategy presentation-only 변경도 Preview/Browser Smoke를 실행해야 한다."""

WORKFLOW = ".github/workflows/strategy-presentation-checks.yml"


def test_strategy_presentation_dispatcher_covers_current_modules() -> None:
    with open(WORKFLOW, encoding="utf-8") as workflow:
        text = workflow.read()

    for path in (
        "src/rate_monitor/services/strategy_decision_cockpit.py",
        "src/rate_monitor/services/market_intelligence_service.py",
        "src/rate_monitor/services/market_intelligence_presentation.py",
        "src/rate_monitor/services/preference_intelligence_service.py",
        "src/rate_monitor/services/preference_intelligence_presentation.py",
    ):
        assert f'- "{path}"' in text

    assert 'gh workflow run strategy-preview.yml --ref "$SOURCE_REF"' in text
    assert 'gh workflow run strategy-browser-smoke.yml --ref "$SOURCE_REF"' in text
    assert "actions: write" in text
    assert "contents: read" in text
    assert "RATE_MONITOR_STRATEGY_DASHBOARD" not in text
