from pathlib import Path


def test_strategy_workspace_runtime_smoke_keeps_entrypoint() -> None:
    source = Path("scripts/strategy_workspace_smoke.js").read_text(encoding="utf-8")

    assert 'chromium.launch({ channel: "chrome", headless: true })' in source
    assert 'runViewport(browser, "desktop"' in source
    assert 'runViewport(browser, "mobile"' in source
    assert 'process.exit(1)' in source
