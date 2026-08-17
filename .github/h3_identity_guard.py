from pathlib import Path

html_path = Path("web/templates/strategy.html")
html = html_path.read_text(encoding="utf-8")

old = 'if(!allowed.has(r.sector)||r.type!=="term_deposit"||r.term!==term||!Number.isFinite(r.max))continue;'
new = 'if(!allowed.has(r.sector)||r.type!=="term_deposit"||r.term!==term||!Number.isFinite(r.max)||!r.productId)continue;'
if html.count(old) != 1:
    raise SystemExit(f"aggregate product identity marker mismatch: {html.count(old)}")
html_path.write_text(html.replace(old, new, 1), encoding="utf-8")

test_path = Path("tests/test_strategy_mutual_finance_h3.py")
test = test_path.read_text(encoding="utf-8")
test += '''\n\ndef test_h3_ranking_rejects_missing_stable_product_identity() -> None:\n    html = _html()\n\n    assert '||!r.productId)continue;' in html\n    assert 'const key=`${r.sector}\\\\0${r.productId}\\\\0${term}`' in html\n    assert 'r.productId||r.product' not in html\n'''
test_path.write_text(test, encoding="utf-8")
