from rate_monitor.services.collection_health_live_presentation import (
    LIVE_HEALTH_SIGNAL_SCRIPT,
    inject_collection_health_live_signal,
)


def test_live_health_injection_surfaces_static_failure_message() -> None:
    html = '<html><body><i id="health-head-dot"></i></body></html>'

    rendered = inject_collection_health_live_signal(html)

    assert 'id="collection-health-live-signal-script"' in rendered
    assert "stale_sources" in LIVE_HEALTH_SIGNAL_SCRIPT
    assert "data-source-failure-causes" in LIVE_HEALTH_SIGNAL_SCRIPT
    assert "item.message" in LIVE_HEALTH_SIGNAL_SCRIPT
    assert 'detail.textContent = "원인 "' in LIVE_HEALTH_SIGNAL_SCRIPT


def test_static_failed_snapshot_cannot_be_downgraded_by_live_signal() -> None:
    assert 'staticFailurePending && baselineSignal === "red" && live !== "red"' in (
        LIVE_HEALTH_SIGNAL_SCRIPT
    )
    assert "restoreBaseline();" in LIVE_HEALTH_SIGNAL_SCRIPT


def test_live_health_injection_is_idempotent() -> None:
    html = '<html><body><i id="health-head-dot"></i></body></html>'

    once = inject_collection_health_live_signal(html)
    twice = inject_collection_health_live_signal(once)

    assert once == twice
    assert twice.count('id="collection-health-live-signal-script"') == 1
