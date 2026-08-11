from pathlib import Path

path = Path("tests/test_kfcc_collection.py")
text = path.read_text(encoding="utf-8")
old = '        assert source.name == "새마을금고 금고위치안내"'
new = '        assert source.name == "새마을금고 예·적금 금리"'
if text.count(old) != 1:
    raise SystemExit(f"expected one old KFCC source-name assertion, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
