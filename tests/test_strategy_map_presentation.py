"""전국 전략 지도의 presentation viewport 계약."""

from tests.strategy_output_helper import built_strategy_html


def test_national_map_crops_sea_and_keeps_jeju_as_compact_inset() -> None:
    html = built_strategy_html()

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
