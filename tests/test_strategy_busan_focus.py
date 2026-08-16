"""부산 drill-down은 전국보다 넓은 지도 영역과 큰 라벨을 사용한다."""

from pathlib import Path

from rate_monitor.services.site_service import adapt_strategy_korea_map_template
from rate_monitor.services.strategy_contract_service import adapt_strategy_template

TEMPLATE = Path("web/templates/strategy.html")


def _html() -> str:
    text = adapt_strategy_template(TEMPLATE.read_text(encoding="utf-8"))
    return adapt_strategy_korea_map_template(text)


def test_busan_mode_expands_map_without_changing_compact_national_default() -> None:
    html = _html()

    assert ".primary{grid-template-columns:minmax(360px,.64fr) minmax(620px,1.36fr)}" in html
    assert (
        ".primary.busan-focus{grid-template-columns:minmax(720px,1.45fr) "
        "minmax(420px,.55fr)}" in html
    )
    assert ".primary.busan-focus .mapcard{min-height:650px}" in html
    assert ".primary.busan-focus .mapstage{height:560px}" in html
    assert 'classList.add("busan-focus")' in html
    assert 'classList.remove("busan-focus")' in html


def test_busan_mode_uses_larger_district_labels_and_spacing() -> None:
    html = _html()

    assert ".primary.busan-focus .district-name{font-size:15px;stroke-width:4px}" in html
    assert ".primary.busan-focus .district-rate{font-size:14px;stroke-width:4px}" in html
    assert 'nameText.setAttribute("y",(y-(has?7:0)).toFixed(1));' in html
    assert 'rateText.setAttribute("y",(y+12).toFixed(1));' in html
