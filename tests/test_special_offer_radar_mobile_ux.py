from pathlib import Path

from rate_monitor.services import special_offer_radar_presentation

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "special_offer_radar_runtime_smoke.js"


def test_radar_mobile_metrics_are_two_column_grid_without_horizontal_carousel() -> None:
    css = special_offer_radar_presentation._CSS

    assert "@media(max-width:760px)" in css
    assert ".special-radar-metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}" in css
    assert "overflow-x:auto" not in css
    assert ".special-radar-metric{min-width:0" in css
    assert "@media(max-width:340px){.special-radar-metrics{grid-template-columns:1fr}}" in css


def test_radar_browser_smoke_rejects_clipped_mobile_metrics() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    assert "Radar metrics require horizontal scrolling" in text
    assert "Radar metric ${index + 1} clipped" in text
    assert "first Radar row is not two columns" in text
    assert "second Radar row is not two columns" in text
    assert "Radar grid columns are misaligned" in text
    assert 'viewport: { width: 390, height: 844 }' in text


def test_radar_browser_smoke_keeps_fail_closed_semantics() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    assert 'payload.source_id === "fsb"' in text
    assert "Radar activation unexpectedly changed" in text
    assert "unknown promotion policy changed" in text
    assert "ranking population changed" in text
    assert "unknown evidence leaked into Radar offers" in text
