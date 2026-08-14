"""전국 전략 지도의 presentation viewport 계약."""

from pathlib import Path

from rate_monitor.services.site_service import adapt_strategy_korea_map_template

TEMPLATE = Path("web/templates/strategy.html")


def test_national_map_crops_remote_islands_but_keeps_mainland_and_jeju() -> None:
    html = adapt_strategy_korea_map_template(TEMPLATE.read_text(encoding="utf-8"))

    assert 'setAttribute("viewBox","0 0 800 759")' in html
    interim = 'setAttribute("viewBox","120 0 500 759")'
    final = 'setAttribute("viewBox","120 0 500 785")'
    assert interim in html
    assert final in html
    assert html.rfind(final) > html.rfind(interim)
    assert '"제주":[207,723]' in html
    assert 'href="assets/korea-sido.svg"' in html
    assert '$("map-mode-label").style.left="auto"' in html
    assert '$("map-mode-label").style.right="16px"' in html
    assert "function showBusanMap()" in html
