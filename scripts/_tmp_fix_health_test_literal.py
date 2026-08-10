from pathlib import Path

path = Path("tests/test_collection_health.py")
text = path.read_text(encoding="utf-8")
old = "('r1', 'warning', '계약기간을 읽지 못했다: -'),\n                ('r1', 'valid', NULL),\n                ('old', 'warning', '계약기간을 읽지 못했다: -');"
new = "('r1', 'warning', '계약기간을 읽지 못했다: ''-'''),\n                ('r1', 'valid', NULL),\n                ('old', 'warning', '계약기간을 읽지 못했다: ''-''');"
if text.count(old) != 1:
    raise RuntimeError(f"expected one generated fixture literal, got {text.count(old)}")
path.write_text(text.replace(old, new), encoding="utf-8")
print("health test fixture literal aligned with production")
