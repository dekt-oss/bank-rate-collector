from pathlib import Path

html_path = Path("web/templates/strategy.html")
html = html_path.read_text(encoding="utf-8")


def once(old: str, new: str, label: str) -> None:
    global html
    count = html.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    html = html.replace(old, new, 1)


old_empty = '''  if(!products12.length){$("top5").innerHTML='<tr><td colspan="5"><div class="empty">현재 범위에 비교 가능한 최고금리가 없습니다.</div></td></tr>';return}'''
new_empty = '''  if(!products12.length){
    $("market-max").textContent="—";$("leader").textContent="비교 가능한 최고금리 없음";$("leader-source").textContent="—";
    $("mean").textContent="—";$("count").textContent="0";$("institutions").textContent="기관 0곳";$("median").textContent="중앙값 —";
    $("top10").textContent="—";$("top10-note").textContent="비교상품 0개";
    $("top5").innerHTML='<tr><td colspan="5"><div class="empty">현재 범위에 비교 가능한 최고금리가 없습니다.</div></td></tr>';
    return
  }'''
once(old_empty, new_empty, "empty market KPI reset")

old_visibility = '''function applyModeVisibility(){const mutualOnly=marketMode==="mutual_finance";$("market-flow").hidden=mutualOnly;$("map-card").hidden=mutualOnly;$("sim-scope-warning").hidden=!mutualOnly;$("sim-form").hidden=mutualOnly;if(!mutualOnly&&mapMode==="korea")renderKoreaMap()}'''
new_visibility = '''function applyModeVisibility(){const mutualOnly=marketMode==="mutual_finance",savingsOnly=marketMode==="savings_bank";$("market-flow").hidden=mutualOnly;$("map-card").hidden=mutualOnly;$("trend-delta").hidden=!savingsOnly;$("sim-scope-warning").hidden=!mutualOnly;$("sim-form").hidden=mutualOnly;if(!mutualOnly&&mapMode==="korea")renderKoreaMap()}'''
once(old_visibility, new_visibility, "history delta scope")

once('{icon:"↕",tag:"시장 방향",title:`30일 ${flow.label}`', '{icon:"↕",tag:"저축은행 시장 방향",title:`30일 ${flow.label}`', "insight history label")

html_path.write_text(html, encoding="utf-8")

Path("tests/test_strategy_mutual_finance_h2_empty_state.py").write_text(
    '''def _html() -> str:\n    with open("web/templates/strategy.html", encoding="utf-8") as handle:\n        return handle.read()\n\n\ndef test_h2_empty_market_scope_resets_kpis_before_return() -> None:\n    html = _html()\n\n    start = html.index('if(!products12.length){')\n    leader = html.index("const stats=ratesStats(products12),lead=products12[0]", start)\n    block = html[start:leader]\n\n    assert '$("market-max").textContent="—"' in block\n    assert '$("leader").textContent="비교 가능한 최고금리 없음"' in block\n    assert '$("mean").textContent="—"' in block\n    assert '$("count").textContent="0"' in block\n    assert '$("institutions").textContent="기관 0곳"' in block\n    assert '$("median").textContent="중앙값 —"' in block\n    assert '$("top10").textContent="—"' in block\n    assert '$("top10-note").textContent="비교상품 0개"' in block\n    assert "현재 범위에 비교 가능한 최고금리가 없습니다." in block\n    assert block.index("return") > block.index('$("top5").innerHTML=')\n\n\ndef test_h2_non_savings_modes_do_not_show_savings_history_as_current_scope_delta() -> None:\n    html = _html()\n\n    assert 'savingsOnly=marketMode==="savings_bank"' in html\n    assert '$("trend-delta").hidden=!savingsOnly' in html\n    assert 'tag:"저축은행 시장 방향"' in html\n''',
    encoding="utf-8",
)
