from pathlib import Path

html_path = Path("web/templates/strategy.html")
html = html_path.read_text(encoding="utf-8")
replacements = {
    "font-size:8.5px": "font-size:9px",
    "font-size:8.6px": "font-size:9px",
    "font-size:8.7px": "font-size:9px",
    "font-size:8.8px": "font-size:9px",
}
for old, new in replacements.items():
    count = html.count(old)
    if count != 1:
        raise SystemExit(f"CSS font marker {old}: expected 1, got {count}")
    html = html.replace(old, new, 1)
html_path.write_text(html, encoding="utf-8")

ui_path = Path("tests/test_strategy_dashboard_ui_contract.py")
ui = ui_path.read_text(encoding="utf-8")
old = '''    assert 'x.region==="부산"?"busan clickable"' in html'''
new = '''    assert 'clickable=savings&&x.region==="부산"' in html'''
if ui.count(old) != 1:
    raise SystemExit("Busan layer-aware click contract marker mismatch")
ui_path.write_text(ui.replace(old, new, 1), encoding="utf-8")
