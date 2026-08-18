from pathlib import Path

from rate_monitor.services import site_service
from rate_monitor.services.main_map_presentation import (
    MAIN_MAP_MARKER,
    MAIN_MAP_TEMPLATE_ID,
    inject_main_map_presentation,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "web" / "templates" / "site.html"


def test_main_map_injection_is_idempotent() -> None:
    html = "<html><head></head><body><div id=\"reg\"></div></body></html>"
    svg = '<svg viewBox="0 0 10 10"><path id="부산광역시" d="M0 0h1v1z"/></svg>'

    once = inject_main_map_presentation(html, svg)
    twice = inject_main_map_presentation(once, svg)

    assert once == twice
    assert once.count(MAIN_MAP_MARKER) == 3  # style + template + script
    assert f'id="{MAIN_MAP_TEMPLATE_ID}"' in once
    assert "부산광역시" in once
    assert "REGION_BY_SVG_ID" in once


def test_main_map_injection_rejects_invalid_svg() -> None:
    html = "<html><head></head><body></body></html>"
    try:
        inject_main_map_presentation(html, "not-svg")
    except site_service.DashboardBuildError as exc:
        assert "source SVG" in str(exc)
    else:
        raise AssertionError("invalid SVG must fail closed")


def test_main_map_is_inlined_when_strategy_gate_is_off(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv(site_service.STRATEGY_ENABLED_ENV, raising=False)
    monkeypatch.setattr(
        site_service,
        "build_summary",
        lambda _path: {
            "totals": {},
            "table": {"columns": [], "lookups": {}, "rows": []},
        },
    )

    out = tmp_path / "site-public"
    manifest = site_service.build_site(tmp_path / "unused.sqlite3", TEMPLATE, out)
    html = (out / "index.html").read_text(encoding="utf-8")

    assert MAIN_MAP_MARKER in html
    assert f'id="{MAIN_MAP_TEMPLATE_ID}"' in html
    assert "부산광역시" in html
    assert "권역별 최고금리 중앙값 대한민국 지도" in html

    # Strategy Release Gate OFF에서는 기존 strategy 산출물은 계속 없어야 한다.
    assert not (out / site_service.STRATEGY_MAP_FILE).exists()
    assert not (out / site_service.STRATEGY_FILE).exists()
    assert site_service.STRATEGY_MAP_FILE not in manifest.files


def test_main_map_keeps_existing_region_calculation_contract_in_template() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")

    # Stage A는 regionRows()/regionBasis() 계산을 바꾸지 않고 presentation만 바꾼다.
    assert "const regionBasis = () =>" in text
    assert "const regionRows = () =>" in text
    assert "const regionBars = (stats) =>" in text
    assert "최고금리 <b>중앙값</b>" in text
    assert 'data-drill="1"' in text
