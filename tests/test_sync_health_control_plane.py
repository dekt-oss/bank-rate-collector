"""health control-plane 동기화가 데이터 파일을 건드리지 않는지 검증한다."""

from __future__ import annotations

from pathlib import Path

from rate_monitor.services.collection_health_live_presentation import (
    LIVE_HEALTH_SIGNAL_SCRIPT,
    MARKER,
)
from scripts.sync_health_control_plane import sync_control_plane, sync_html_text


def _page(script: str = "") -> str:
    return (
        '<html><body><button id="health-open">'
        '<span id="health-head-dot" class="health-dot green"></span>'
        '<span id="health-head-label">수집 정상</span></button>'
        f"{script}</body></html>"
    )


def test_sync_html_injects_once_when_old_deploy_has_no_live_script() -> None:
    rendered, changed = sync_html_text(_page(), LIVE_HEALTH_SIGNAL_SCRIPT)
    assert changed is True
    assert MARKER in rendered
    assert rendered.count(MARKER) == 1

    rerendered, changed_again = sync_html_text(rendered, LIVE_HEALTH_SIGNAL_SCRIPT)
    assert changed_again is False
    assert rerendered == rendered


def test_sync_html_replaces_stale_live_script_without_duplication() -> None:
    old = '<script id="collection-health-live-signal-script">old()</script>'
    rendered, changed = sync_html_text(_page(old), LIVE_HEALTH_SIGNAL_SCRIPT)
    assert changed is True
    assert "old()" not in rendered
    assert rendered.count(MARKER) == 1
    assert "apply(body.signal || body.sla)" in rendered


def test_sync_html_without_health_badge_is_left_untouched() -> None:
    html = "<html><body>plain</body></html>"
    rendered, changed = sync_html_text(html, LIVE_HEALTH_SIGNAL_SCRIPT)
    assert changed is False
    assert rendered == html


def test_sync_control_plane_changes_only_api_and_health_scripts(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "api").mkdir(parents=True)
    (deploy / "site-public").mkdir(parents=True)
    (deploy / "latest").mkdir(parents=True)

    (deploy / "api/health.js").write_text("old api", encoding="utf-8")
    (deploy / "site-public/index.html").write_text(_page(), encoding="utf-8")
    (deploy / "site-public/strategy.html").write_text(_page(), encoding="utf-8")
    sentinel = deploy / "latest/summary.json"
    sentinel.write_text('{"keep":true}', encoding="utf-8")

    changed = sync_control_plane(deploy)
    assert changed == [
        "api/health.js",
        "site-public/index.html",
        "site-public/strategy.html",
    ]
    assert sentinel.read_text(encoding="utf-8") == '{"keep":true}'
    assert "operationalSignal" in (deploy / "api/health.js").read_text(encoding="utf-8")
    assert MARKER in (deploy / "site-public/index.html").read_text(encoding="utf-8")

    assert sync_control_plane(deploy) == []
