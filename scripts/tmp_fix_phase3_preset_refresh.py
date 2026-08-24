from pathlib import Path

path = Path("web/templates/site.html")
text = path.read_text(encoding="utf-8")
old = "  const redrawSoon = afterTyping(redraw);\n"
new = """  const redrawSoon = afterTyping(() => {\n    // 프리셋 count/active도 q·금리·기간 scalar의 현재 상태를 따른다.\n    // 결과만 다시 그리면 버튼의 aria-pressed와 건수가 이전 값으로 남는다.\n    renderPresets();\n    redraw();\n  });\n"""
if text.count(old) != 1:
    raise SystemExit("redrawSoon anchor not found exactly once")
path.write_text(text.replace(old, new), encoding="utf-8")
print("patched", path)
