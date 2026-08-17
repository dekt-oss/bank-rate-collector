def test_h2_empty_market_scope_does_not_dereference_missing_leader() -> None:
    with open("web/templates/strategy.html", encoding="utf-8") as handle:
        html = handle.read()

    guard = 'if(!products12.length){$("top5").innerHTML='
    leader = "const stats=ratesStats(products12),lead=products12[0]"

    assert guard in html
    assert leader in html
    assert html.index(guard) < html.index(leader)
    assert "현재 범위에 비교 가능한 최고금리가 없습니다." in html
