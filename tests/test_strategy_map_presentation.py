"""전국 전략 지도의 presentation viewport 계약."""

from pathlib import Path

from rate_monitor.services.site_service import adapt_strategy_korea_map_template

TEMPLATE = Path("web/templates/strategy.html")


def test_national_map_crops_sea_and_keeps_jeju_as_compact_inset() -> None:
    html = adapt_strategy_korea_map_template(TEMPLATE.read_text(encoding="utf-8"))

    assert 'viewBox="130 -5 450 675" role="img"' in html
    assert 'setAttribute("viewBox","130 -5 450 675")' in html
    assert 'setAttribute("viewBox","120 0 500 759")' not in html
    assert '"제주":[207,633]' in html
    assert 'id="korea-jeju-clip"' in html
    assert 'transform="translate(0 -90)"' in html
    assert 'href="assets/korea-sido.svg"' in html
    assert '$("map-mode-label").style.left="auto"' in html
    assert '$("map-mode-label").style.right="16px"' in html
    assert "function showBusanMap()" in html
