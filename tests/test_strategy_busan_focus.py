"""부산 drill-down은 지도·TOP5·구별 목록을 판독 가능한 구조로 전환한다."""

from tests.strategy_output_helper import built_strategy_html


def test_busan_mode_expands_map_without_changing_compact_national_default() -> None:
    html = built_strategy_html()

    assert ".primary{grid-template-columns:minmax(360px,.64fr) minmax(620px,1.36fr)}" in html
    assert (
        ".primary.busan-focus{grid-template-columns:minmax(720px,1.45fr) "
        "minmax(420px,.55fr)}" in html
    )
    assert ".primary.busan-focus .mapcard{min-height:650px}" in html
    assert ".primary.busan-focus .mapstage{height:560px}" in html
    assert 'classList.add("busan-focus")' in html
    assert 'classList.remove("busan-focus")' in html


def test_busan_mode_uses_preset_offsets_for_central_district_labels() -> None:
    html = built_strategy_html()

    assert ".primary.busan-focus .district-name{font-size:15px;stroke-width:4px}" in html
    assert ".primary.busan-focus .district-rate{font-size:14px;stroke-width:4px}" in html
    assert "const busanLabelOffsets=" in html
    for district in ("부산진구", "연제구", "수영구", "동구", "중구", "서구"):
        assert f'"{district}":[' in html
    assert 'preset=busanLabelOffsets[name]||[0,0,"middle"]' in html
    assert 'line.setAttribute("class","district-label-line")' in html
    assert 'nameText.setAttribute("text-anchor",anchor)' in html
    assert 'rateText.setAttribute("text-anchor",anchor)' in html


def test_busan_mode_compacts_top5_without_horizontal_scroll() -> None:
    html = built_strategy_html()

    assert 'id="top5-name-head"' in html
    assert ".primary.busan-focus .tablewrap{overflow:visible}" in html
    assert ".primary.busan-focus table{min-width:0;table-layout:fixed}" in html
    assert (
        ".primary.busan-focus th:nth-child(3),.primary.busan-focus th:nth-child(4),"
        ".primary.busan-focus td:nth-child(3),.primary.busan-focus td:nth-child(4){display:none}"
        in html
    )
    assert '.primary.busan-focus .product,.primary.busan-focus .sourcehint{display:none}' in html
    assert '$("top5-name-head").textContent="금융사"' in html
    assert '$("top5-name-head").textContent="금융사 / 상품"' in html


def test_busan_mode_lists_only_districts_with_canonical_rate_data() -> None:
    html = built_strategy_html()

    assert 'id="busan-rate-list"' in html
    assert 'class="busan-rate-list"' in html
    assert ".busan-rate-list[hidden]{display:none}" in html
    assert 'rateList.hidden=!list.length' in html
    assert 'rateList.innerHTML=list.map((x,i)=>' in html
    assert '${esc(x.district)}' in html
    assert '${x.rate.toFixed(2)}%' in html
    assert '${fmt.format(x.count)}개 상품' in html
    assert '$("busan-rate-list").hidden=true' in html
