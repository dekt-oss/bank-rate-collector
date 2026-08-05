#!/usr/bin/env python3
"""P0: 새마을금고 공식 페이지 원본 HTML 확보 + 구조 정찰.

명세서 v3 §22 원칙: 실물 표본 없이 HTML 파서를 추정 구현하지 않는다.
이 스크립트는 파서가 아니라 **정찰**이다. 원본 HTML을 그대로 저장하고,
목표 원천값(gmgoCd/divCd 등)이 문서 안에 어떤 형태로 존재하는지만 보고한다.
구조를 단정하지 않고 발견한 사실만 기록한다.

기본 대상은 부산 중구(참고 데이터 기준 금고 6개)로, 요청 수를 최소화한 표본이다.

사용법:
    python scripts/p0_kfcc_capture.py [시도] [시군구]
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

BASE = "https://www.kfcc.co.kr"
RAW_DIR = Path("data/raw/p0/kfcc")
FIXTURE_DIR = Path("tests/fixtures/kfcc")
REPORT_PATH = Path("docs/source-recon/kfcc-capture.json")
UA = "rate-monitor-p0-recon/1"

# 명세서 v3 §7.3.8 요청 제어
INTERVAL_SECONDS = 1.0

# 정찰 대상 원천값 (명세서 v3 §7.3.4)
TOKENS = ["gmgoCd", "divCd", "gmgoNm", "divNm", "OPEN_TRMID", "gubuncode"]


def get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def save(content: bytes, name: str, also_fixture: bool = False) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    digest = sha256(content).hexdigest()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"{name}_{stamp}.html"
    path.write_bytes(content)
    if also_fixture:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        (FIXTURE_DIR / f"{name}.html").write_bytes(content)
    return {"path": str(path), "sha256": digest, "bytes": len(content)}


# 2026-08-05 실측: 목록 페이지는 원천값을 아래 형태의 숨김 span으로 노출한다.
#   <span hidden="true" style="display: none;" title="gmgoCd">1203</span>
SPAN_RE = re.compile(r'<span[^>]*title="([a-zA-Z_0-9]+)"[^>]*>([^<]*)</span>')


def extract_rows(text: str) -> list[dict]:
    """숨김 span 묶음을 행 단위로 복원한다.

    같은 title이 다시 나오면 새 행이 시작된 것으로 본다.
    """
    rows: list[dict] = []
    current: dict = {}
    for title, value in SPAN_RE.findall(text):
        if title in current:
            rows.append(current)
            current = {}
        current[title] = value.strip()
    if current:
        rows.append(current)
    return [r for r in rows if "gmgoCd" in r and r.get("gmgoCd")]


def inspect(content: bytes) -> dict:
    """구조를 단정하지 않고 관측 사실만 보고한다."""
    text = content.decode("utf-8", "ignore")
    found = {t: text.count(t) for t in TOKENS if t in text}
    rows = extract_rows(text)

    return {
        "token_counts": found,
        "hidden_span_titles": sorted({t for t, _ in SPAN_RE.findall(text)}),
        "row_count": len(rows),
        "distinct_gmgoCd": len({r["gmgoCd"] for r in rows}),
        "gmgoCd_sample": sorted({r["gmgoCd"] for r in rows})[:10],
        "first_row": rows[0] if rows else {},
        "table_tag_count": text.count("<table"),
        "has_tblWrap": "tblWrap" in text,
        "has_tbl_tit": "tbl-tit" in text,
        "has_divTmp": bool(re.search(r"divTmp\d", text)),
        "divTmp_ids": sorted(set(re.findall(r"divTmp\d+", text))),
        "title": (re.search(r"<title[^>]*>(.*?)</title>", text, re.S).group(1).strip()
                  if re.search(r"<title[^>]*>(.*?)</title>", text, re.S) else ""),
    }


def main() -> int:
    sido = sys.argv[1] if len(sys.argv) > 1 else "부산"
    sigungu = sys.argv[2] if len(sys.argv) > 2 else "중구"

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "captured_at": datetime.now(UTC).isoformat(),
        "target": {"r1": sido, "r2": sigungu},
        "note": "정찰 전용. 구조를 단정하지 않고 관측값만 기록한다.",
        "steps": {},
    }

    # 1. 지역 목록 페이지
    q = urllib.parse.urlencode({"r1": sido, "r2": sigungu})
    url = f"{BASE}/map/list.do?{q}"
    status, content = get(url)
    print(f"[1] map/list.do?{q} -> {status}, {len(content)} bytes")
    step: dict = {"url": url, "status": status}
    if status == 200 and content:
        step["artifact"] = save(content, f"list_{sido}_{sigungu}", also_fixture=True)
        step["observed"] = inspect(content)
    else:
        step["blocked_or_error"] = True
        step["snippet"] = content.decode("utf-8", "ignore")[:300]
    report["steps"]["region_list"] = step

    if status != 200:
        print("목록 페이지 실패. 후속 요청을 중단한다.")
        report["conclusion"] = {"list_parsable": False, "reason": f"status={status}"}
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    time.sleep(INTERVAL_SECONDS)

    # 2. 금리 페이지
    #    2026-08-05 실측: 목록의 "금리" 버튼은 view_rate() → _view()를 거쳐
    #    GET /map/view.do 로 행의 span 값 전부와 tab=sub_tab_rate 를 보낸다.
    #    명세서 v3 §7.3.3이 가정한 goods_19.do?OPEN_TRMID&gubuncode 가 아니다.
    list_obs = report["steps"]["region_list"].get("observed", {})
    rows = extract_rows(content.decode("utf-8", "ignore"))
    detail_results = []
    seen: set[str] = set()
    for row in rows:
        code = row.get("gmgoCd", "")
        if not code or code in seen:
            continue  # 금리는 gmgoCd 당 1회만 (명세서 v3 §7.3.4)
        seen.add(code)
        params = {k: v for k, v in row.items() if k != "pageNo"}
        params["tab"] = "sub_tab_rate"
        durl = f"{BASE}/map/view.do?{urllib.parse.urlencode(params)}"
        dstatus, dcontent = get(durl)
        print(f"[2] view.do gmgoCd={code} -> {dstatus}, {len(dcontent)} bytes")
        entry: dict = {"gmgoCd": code, "gmgoNm": row.get("gmgoNm"), "status": dstatus}
        if dstatus == 200 and dcontent:
            entry["artifact"] = save(
                dcontent, f"rate_{code}", also_fixture=len(detail_results) == 0
            )
            entry["observed"] = inspect(dcontent)
        else:
            entry["blocked_or_error"] = True
            entry["snippet"] = dcontent.decode("utf-8", "ignore")[:300]
        detail_results.append(entry)
        time.sleep(INTERVAL_SECONDS)
        if len(detail_results) >= 2:
            break  # 정찰이므로 표본 2건만
    report["steps"]["rate_detail"] = detail_results

    # 판정 — 관측 사실만 기록한다. 표본이 없으면 가능하다고 단정하지 않는다.
    parsed_rows = list_obs.get("row_count", 0)
    detail_ok = [d for d in detail_results if d.get("status") == 200]
    report["conclusion"] = {
        "list_page_reachable": True,
        "list_rows_parsed": parsed_rows,
        "distinct_gmgoCd": list_obs.get("distinct_gmgoCd", 0),
        "rate_page_endpoint": "/map/view.do (GET, tab=sub_tab_rate)",
        "rate_page_sampled": len(detail_results),
        "rate_page_ok": len(detail_ok),
        "next_step": (
            "목록 파싱과 금리 페이지 표본 모두 확보. 금리표 파서 설계 착수 가능"
            if parsed_rows and detail_ok
            else "목록은 파싱되나 금리 페이지 표본 미확보. 요청 파라미터 재조사 필요"
            if parsed_rows
            else "목록 파싱 실패. 요청 방식(POST/AJAX) 재조사 필요"
        ),
    }

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n판정:")
    print(json.dumps(report["conclusion"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
