from __future__ import annotations

from pathlib import Path

PATH = Path("tests/test_site_ui_v4.py")
OLD = '''    assert "if (!set.size) selectAllGroup(box.dataset.group);" in SOURCE
'''
NEW = '''    assert "if (!set.size) selectAllGroup(box.dataset.group);" not in SOURCE
    assert "const emptyMainGroup = () =>" in SOURCE
    assert 'allSelected ? "전체 해제" : "전체 선택"' in SOURCE
    assert "if (g && groupAllSelected(g)) {" in SOURCE
'''

text = PATH.read_text(encoding="utf-8")
count = text.count(OLD)
if count != 1:
    raise SystemExit(f"legacy all-selection assertion: expected 1 anchor, found {count}")
PATH.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
print("Search D1 legacy UI contract test updated")
