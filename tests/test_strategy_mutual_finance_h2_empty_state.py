def _html() -> str:
    with open("web/templates/strategy.html", encoding="utf-8") as handle:
        return handle.read()


def test_h2_empty_market_scope_resets_kpis_before_return() -> None:
    html = _html()

    start = html.index('if(!products12.length){')
    leader = html.index("const stats=ratesStats(products12),lead=products12[0]", start)
    block = html[start:leader]

    assert '$("market-max").textContent="—"' in block
    assert '$("leader").textContent="비교 가능한 최고금리 없음"' in block
    assert '$("mean").textContent="—"' in block
    assert '$("count").textContent="0"' in block
    assert '$("institutions").textContent=`${rankingEntityLabel()} 0곳`' in block
    assert '$("median").textContent="중앙값 —"' in block
    assert '$("top10").textContent="—"' in block
    assert '$("top10-note").textContent="비교상품 0개"' in block
    assert "현재 범위에 비교 가능한 최고금리가 없습니다." in block
    assert block.index("return") > block.index('$("top5").innerHTML=')


def test_h2_non_savings_modes_do_not_show_savings_history_as_current_scope_delta() -> None:
    html = _html()

    assert 'savingsOnly=marketMode==="savings_bank"' in html
    assert '$("trend-delta").hidden=!savingsOnly' in html
    assert 'tag:"저축은행 시장 방향"' in html
