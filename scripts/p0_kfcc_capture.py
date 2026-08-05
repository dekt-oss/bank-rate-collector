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
from collections import Counter
from datetime import datetime, timezone
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"{name}_{stamp}.html"
    path.write_bytes(content)
    if also_fixture:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        (FIXTURE_DIR / f"{name}.html").write_bytes(content)
    return {"path": str(path), "sha256": digest, "bytes": len(content)}


def inspect(content: bytes) -> dict:
    """구조를 단정하지 않고 관측 사실만 보고한다."""
    text = content.decode("utf-8", "ignore")
    found = {t: text.count(t) for t in TOKENS if t in text}

    # gmgoCd 로 보이는 값의 실제 출현 형태를 그대로 수집 (추정 없이 원문 조각)
    samples: list[str] = []
    for m in re.finditer(r".{60}gmgoCd.{60}", text):
        snippet = " ".join(m.group(0).split())
        if snippet not in samples:
            samples.append(snippet)
        if len(samples) >= 5:
            break

    # 4자리 숫자 코드 후보 (참고 데이터의 gmgoCd 형태와 대조용)
    code_like = re.findall(r"['\"](\d{4})['\"]", text)

    return {
        "token_counts": found,
        "gmgoCd_context_samples": samples,
        "four_digit_code_candidates": len(code_like),
        "four_digit_code_distinct": len(set(code_like)),
        "four_digit_code_sample": sorted(set(code_like))[:10],
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
        "captured_at": datetime.now(timezone.utc).isoformat(),
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

    # 2. 금리 상세 페이지 — 명세서 v3 §7.3.3의 경로를 그대로 시험
    #    파라미터 의미가 미확인이므로, 관측된 코드 후보 1개로만 최소 시험한다.
    observed = report["steps"]["region_list"].get("observed", {})
    candidates = observed.get("four_digit_code_sample", [])
    detail_results = []
    if candidates:
        code = candidates[0]
        for category in (13, 14):  # 거치식, 적립식
            dq = urllib.parse.urlencode({"OPEN_TRMID": category, "gubuncode": code})
            durl = f"{BASE}/map/goods_19.do?{dq}"
            dstatus, dcontent = get(durl)
            print(f"[2] map/goods_19.do?{dq} -> {dstatus}, {len(dcontent)} bytes")
            entry: dict = {"url": durl, "status": dstatus, "tried_code": code,
                           "tried_category": category}
            if dstatus == 200 and dcontent:
                entry["artifact"] = save(dcontent, f"detail_{code}_{category}", also_fixture=True)
                entry["observed"] = inspect(dcontent)
            else:
                entry["blocked_or_error"] = True
                entry["snippet"] = dcontent.decode("utf-8", "ignore")[:300]
            detail_results.append(entry)
            time.sleep(INTERVAL_SECONDS)
    report["steps"]["rate_detail"] = detail_results

    # 판정 — 관측 사실만으로 다음 단계 가능 여부를 기록
    list_obs = report["steps"]["region_list"].get("observed", {})
    report["conclusion"] = {
        "list_page_reachable": True,
        "gmgoCd_token_present": "gmgoCd" in list_obs.get("token_counts", {}),
        "code_candidates_found": list_obs.get("four_digit_code_distinct", 0),
        "detail_page_reachable": any(d.get("status") == 200 for d in detail_results),
        "next_step": (
            "원본 HTML을 fixture로 고정했으므로 파서 설계 착수 가능"
            if list_obs.get("token_counts")
            else "목록 페이지에 목표 토큰이 없다. 요청 방식(POST/AJAX) 재조사 필요"
        ),
    }

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n판정:")
    print(json.dumps(report["conclusion"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
