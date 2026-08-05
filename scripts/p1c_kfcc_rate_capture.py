#!/usr/bin/env python3
"""세로 절단 2 선행: 새마을금고 금리 페이지 표본 확보.

명세서 v3 §22 원칙: 실물 표본 없이 파서를 추정 구현하지 않는다.
이 스크립트는 파서가 아니라 **표본 채집**이다. 응답 원본을 그대로 저장하고
관측한 구조만 보고한다.

수집 경로 (docs/source-recon/kfcc.md §2.2 실측):

    GET /map/goods_19.do?OPEN_TRMID={gmgoCd}&gubuncode={12|13|14}

목록의 「금리」 버튼은 `view.do`를 부르지만 그 응답은 iframe 껍데기이고
금리 표가 없다. 금리는 iframe에 `goods_19.do`가 실린다. `goods_NN`은
상품군이 아니며 상품군은 `gubuncode` 값이다.

사용법:
    python scripts/p1c_kfcc_rate_capture.py [--gmgo-cd 1203] [--groups 13 14]
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape
from pathlib import Path

BASE = "https://www.kfcc.co.kr"
RAW_DIR = Path("data/raw/p1c/kfcc")
FIXTURE_DIR = Path("tests/fixtures/kfcc")
REPORT_PATH = Path("docs/source-recon/kfcc-rate-capture.json")
UA = "rate-monitor-recon/1"

# 명세서 v3 §7.3.8 요청 제어
INTERVAL_SECONDS = 1.0

# gubuncode → 화면이 스스로 붙인 이름. 우리가 지은 이름이 아니다.
GROUP_LABELS = {
    "12": "요구불예탁금",
    "13": "거치식예탁금",
    "14": "적립식예탁금",
}

_TAG_RE = re.compile(r"<[^>]+>")
_TBL_TIT_RE = re.compile(r'class="tbl-tit"[^>]*>(.*?)</', re.S)
_TABLE_RE = re.compile(r"<table.*?</table>", re.S)
_TH_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.S)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)


def _text(raw: str) -> str:
    return " ".join(unescape(_TAG_RE.sub(" ", raw)).split())


def get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def save(content: bytes, name: str) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (RAW_DIR / f"{name}_{stamp}.html").write_bytes(content)
    (FIXTURE_DIR / f"{name}.html").write_bytes(content)
    return {
        "fixture": str(FIXTURE_DIR / f"{name}.html"),
        "sha256": sha256(content).hexdigest(),
        "bytes": len(content),
    }


def inspect(html: str) -> dict:
    """구조를 단정하지 않고 관측 사실만 보고한다."""
    tables = _TABLE_RE.findall(html)
    observed: dict = {
        "h3": [_text(x) for x in _H3_RE.findall(html)],
        "product_titles": [_text(x) for x in _TBL_TIT_RE.findall(html)],
        "table_count": len(tables),
        "tbl_tit_count": html.count("tbl-tit"),
        # 명세서 §7.3.5가 가정한 선택자가 실제로 있는지 되짚는다.
        "divTmp_ids": sorted(set(re.findall(r"divTmp\d+", html))),
        "header_variants": [],
        "sample_rows": [],
    }
    seen_headers: set[tuple[str, ...]] = set()
    for table in tables:
        headers = tuple(_text(x) for x in _TH_RE.findall(table))
        if headers and headers not in seen_headers:
            seen_headers.add(headers)
            observed["header_variants"].append(list(headers))
    for table in tables[:2]:
        for tr in _TR_RE.findall(table)[1:4]:
            cells = [_text(x) for x in _TD_RE.findall(tr)]
            if cells:
                observed["sample_rows"].append(cells)

    # 기준일은 파서가 source_effective_at에 넣을 값이라 원문을 남긴다.
    basis = re.search(r"조회기준일\s*\(([^)]+)\)", html)
    observed["basis_date_raw"] = basis.group(1) if basis else None
    observed["tax_note"] = "세금공제전" in html
    return observed


def capture(gmgo_cd: str, gubuncode: str) -> dict:
    url = f"{BASE}/map/goods_19.do?OPEN_TRMID={gmgo_cd}&gubuncode={gubuncode}"
    status, content = get(url)
    entry: dict = {
        "gmgoCd": gmgo_cd,
        "gubuncode": gubuncode,
        "group_label": GROUP_LABELS.get(gubuncode, "미상"),
        "url": url,
        "status": status,
    }
    if status != 200 or not content:
        entry["blocked_or_error"] = True
        entry["snippet"] = content.decode("utf-8", "ignore")[:300]
        return entry
    entry["artifact"] = save(content, f"rate_{gmgo_cd}_{gubuncode}")
    entry["observed"] = inspect(content.decode("utf-8", "ignore"))
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description="새마을금고 금리 페이지 표본 확보")
    parser.add_argument("--gmgo-cd", default="1203", help="금고 코드 (기본: 부산 중구 대청)")
    parser.add_argument(
        "--groups", nargs="+", default=["13", "14"], help="gubuncode 목록"
    )
    args = parser.parse_args()

    report: dict = {
        "captured_at": datetime.now(UTC).isoformat(),
        "base": BASE,
        "endpoint": "/map/goods_19.do?OPEN_TRMID={gmgoCd}&gubuncode={12|13|14}",
        "note": "정찰 전용. 구조를 단정하지 않고 관측값만 기록한다.",
        "captures": [],
    }
    for gubuncode in args.groups:
        entry = capture(args.gmgo_cd, gubuncode)
        report["captures"].append(entry)
        obs = entry.get("observed", {})
        print(
            f"  gubuncode={gubuncode} ({entry['group_label']}) "
            f"status={entry['status']} "
            f"bytes={entry.get('artifact', {}).get('bytes', '-')} "
            f"상품={len(obs.get('product_titles') or [])} "
            f"기준일={obs.get('basis_date_raw')}"
        )
        for headers in obs.get("header_variants", []):
            print(f"      열: {headers}")
        time.sleep(INTERVAL_SECONDS)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n보고서: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
