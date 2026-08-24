from pathlib import Path

path = Path("tests/test_site_ui_v4.py")
text = path.read_text(encoding="utf-8")
old = '''    assert "const TYPING_PAUSE_MS = 200;" in SOURCE
    assert "const redrawSoon = afterTyping(redraw);" in SOURCE
    # 체크박스는 지연을 걸지 않는다. 한 번 누르는 것이라 바로 반응해야 한다.
'''
new = '''    assert "const TYPING_PAUSE_MS = 200;" in SOURCE
    assert "const redrawSoon = afterTyping(() => {" in SOURCE
    redraw = SOURCE[SOURCE.index("const redrawSoon = afterTyping(() => {"):]
    redraw = redraw[:redraw.index("});") + 3]
    assert "renderPresets();" in redraw
    assert "redraw();" in redraw
    # 체크박스는 지연을 걸지 않는다. 한 번 누르는 것이라 바로 반응해야 한다.
'''
if text.count(old) != 1:
    raise SystemExit("typing contract block not found exactly once")
path.write_text(text.replace(old, new), encoding="utf-8")
print("patched", path)
