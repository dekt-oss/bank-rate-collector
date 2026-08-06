#!/usr/bin/env python3
"""한국은행 ECOS 오픈API 정찰 (v4 §7.2).

**통계표 코드를 추정해서 적지 않는다.** 명세서가 그걸 금지한다 — 확인하지
않은 코드를 하드코딩하면 그 값이 정말 기준금리인지 아무도 모른 채 화면에
뜬다. 그래서 이 스크립트는 **찾아낸다.**

    1. 100대 통계지표 목록에서 "기준금리"라는 이름을 찾는다
    2. 그 지표가 가리키는 통계표의 항목 목록을 받는다
    3. 그 항목으로 실제 시계열을 조회해 최신값을 본다

각 단계의 응답을 그대로 저장하므로, 나중에 이 JSON만 보고도 계약을 다시
읽을 수 있다.

인증키는 **어디에도 남기지 않는다.** URL에 키가 들어가는 API라 저장 전에
반드시 지운다 (v3 §16.1).

사용법:
    ECOS_API_KEY=... uv run python scripts/p2_bok_ecos_recon.py
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://ecos.bok.or.kr/api"
OUT = Path("docs/source-recon/bok-ecos-recon.json")
KEY_ENV = "ECOS_API_KEY"

# 이름으로 찾는다. 코드를 적지 않기 위해서다.
WANTED = "기준금리"

TIMEOUT = 20
INTERVAL = 0.5


def _mask(url: str, key: str) -> str:
    """주소에서 인증키를 지운다. 키가 경로에 들어가는 API다."""
    return url.replace(key, "[REDACTED]") if key else url


def probe(path: str, key: str) -> dict[str, Any]:
    """한 번 두드리고 응답을 그대로 담는다."""
    url = f"{BASE}/{path}"
    record: dict[str, Any] = {"url": _mask(url, key)}
    request = urllib.request.Request(
        url, headers={"User-Agent": "rate-monitor/1 (+public rate disclosure collector)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
            record["status"] = response.status
            record["bytes"] = len(body)
            try:
                record["payload"] = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                record["text"] = body.decode("utf-8", "replace")[:2000]
    except Exception as error:  # noqa: BLE001 - 정찰이므로 무엇이든 기록한다
        record["error"] = f"{type(error).__name__}: {_mask(str(error), key)}"
    time.sleep(INTERVAL)
    return record


def _rows(record: dict[str, Any], container: str) -> list[dict[str, Any]]:
    payload = record.get("payload") or {}
    block = payload.get(container) or {}
    return block.get("row") or []


def main() -> int:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"{KEY_ENV} 환경변수가 없다. 인증키는 환경변수로만 받는다.", file=sys.stderr)
        return 2

    report: dict[str, Any] = {"base": BASE, "wanted": WANTED, "steps": {}}

    # ── 1. 100대 통계지표에서 이름으로 찾는다 ────────────────────────
    key_stats = probe(f"KeyStatisticList/{key}/json/kr/1/100", key)
    report["steps"]["key_statistics"] = key_stats
    rows = _rows(key_stats, "KeyStatisticList")
    hits = [r for r in rows if WANTED in str(r.get("KEYSTAT_NAME", ""))]
    report["matched_key_statistics"] = hits
    print(f"100대 지표 {len(rows)}개 중 '{WANTED}' 포함 {len(hits)}개")
    for hit in hits:
        print(f"  {hit.get('KEYSTAT_NAME')} = {hit.get('DATA_VALUE')} "
              f"{hit.get('UNIT_NAME')} ({hit.get('CYCLE')})")

    # ── 2. 통계표 목록에서 정책금리를 찾는다 ─────────────────────────
    #
    # 100대 지표는 값만 주고 통계표 코드를 안 준다. 시계열을 받으려면
    # 통계표 코드가 필요하므로 목록에서 이름으로 찾는다.
    tables = probe(f"StatisticTableList/{key}/json/kr/1/1000", key)
    report["steps"]["table_list"] = tables
    table_rows = _rows(tables, "StatisticTableList")
    candidates = [
        r for r in table_rows
        if re.search(r"기준금리|정책금리|여수신금리", str(r.get("STAT_NAME", "")))
    ]
    report["candidate_tables"] = candidates
    print(f"\n통계표 {len(table_rows)}개 중 후보 {len(candidates)}개")
    for row in candidates[:12]:
        print(f"  {row.get('STAT_CODE')}  {row.get('STAT_NAME')}  주기={row.get('CYCLE')}")

    # ── 3. 후보마다 항목 목록과 실제 시계열 ──────────────────────────
    report["steps"]["items"] = {}
    report["steps"]["series"] = {}
    for row in candidates[:5]:
        code = str(row.get("STAT_CODE") or "")
        if not code:
            continue
        items = probe(f"StatisticItemList/{key}/json/kr/1/100/{code}", key)
        report["steps"]["items"][code] = items
        item_rows = _rows(items, "StatisticItemList")
        named = [r for r in item_rows if WANTED in str(r.get("ITEM_NAME", ""))]
        print(f"\n{code} 항목 {len(item_rows)}개 / '{WANTED}' 포함 {len(named)}개")
        for item in named[:5]:
            print(f"    {item.get('ITEM_CODE')}  {item.get('ITEM_NAME')}  "
                  f"주기={item.get('CYCLE')}")

        cycle = str(row.get("CYCLE") or "M")
        # 조회 구간은 주기가 정한다. 일별이면 8자리, 월별이면 6자리다.
        span = {"D": ("20240101", "20261231"), "M": ("202401", "202612"),
                "Q": ("2024Q1", "2026Q4"), "A": ("2024", "2026")}.get(cycle,
                                                                     ("202401", "202612"))
        for item in (named or item_rows)[:2]:
            item_code = str(item.get("ITEM_CODE") or "")
            if not item_code:
                continue
            series = probe(
                f"StatisticSearch/{key}/json/kr/1/10/{code}/{cycle}/"
                f"{span[0]}/{span[1]}/{item_code}",
                key,
            )
            report["steps"]["series"][f"{code}/{item_code}"] = series
            data = _rows(series, "StatisticSearch")
            print(f"    시계열 {code}/{item_code}: {len(data)}행")
            for point in data[-3:]:
                print(f"      {point.get('TIME')}  {point.get('DATA_VALUE')}"
                      f"  {point.get('UNIT_NAME')}  {point.get('ITEM_NAME1')}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    # 마지막 방어선. 키가 어딘가 남았으면 여기서 지운다.
    if key in blob:
        blob = blob.replace(key, "[REDACTED]")
        print("\n경고: 응답 어딘가에 인증키가 남아 있어 저장 전에 지웠다.")
    OUT.write_text(blob, encoding="utf-8")
    print(f"\n기록: {OUT} ({len(blob):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
