#!/usr/bin/env python3
from pathlib import Path

PATH = Path("src/rate_monitor/collectors/nh_local/parser.py")
OLD = '''    options: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, entry in enumerate(parse_rate_table(html)):
'''
NEW = '''    options: list[dict[str, Any]] = []
    warnings: list[str] = []

    # fetch 단계의 e-joy 보조 추출이 raw capture 자체를 막아서는 안 된다.
    # 본 상세 artifact는 이후 parse_detail에서 기존 schema 계약대로 검증한다.
    if DETAIL_CAPTION not in html:
        return [], [f"e-joy 상세표 캡션 없음: brc={brc}"]

    for index, entry in enumerate(parse_rate_table(html)):
'''

text = PATH.read_text(encoding="utf-8")
count = text.count(OLD)
if count != 1:
    raise SystemExit(f"expected one insertion point, found {count}")
PATH.write_text(text.replace(OLD, NEW), encoding="utf-8")
