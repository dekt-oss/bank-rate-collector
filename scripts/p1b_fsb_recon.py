#!/usr/bin/env python3
"""P1-B 선행: 저축은행중앙회(FSB) 소비자포털 구조 정찰.

명세서 v3 §22 원칙: 실물 표본 없이 파서를 추정 구현하지 않는다.
이 스크립트는 파서가 아니라 **정찰**이다. 응답 원본을 그대로 저장하고,
어떤 요청이 어떤 필드를 돌려주는지만 보고한다. 구조를 단정하지 않는다.

발견 경로 (2026-08-05 실측, 사이트 내비게이션에서 추출):
    ratedepo_0100.act   정기예금
    rateinst_0100.act   정기적금
    ratanym_0100.act    입출금자유예금

화면 HTML에는 금리 행이 없다. 전부 AJAX로 실린다. 실제 데이터 엔드포인트는
jexjs가 조립하며 확장자가 `.act`가 아니라 `.jct`다 (FSBcomm.js의
`ajaxSetup.suffix = ".jct"`). 즉 `<화면>_01.jct`에 JSON을 POST한다.

사용법:
    python scripts/p1b_fsb_recon.py [--date YYYY-MM-DD] [--area YN_Busan]
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from hashlib import sha256
from http.cookiejar import CookieJar
from pathlib import Path

BASE = "https://www.fsb.or.kr"
RAW_DIR = Path("data/raw/p1b/fsb")
FIXTURE_DIR = Path("tests/fixtures/fsb")
REPORT_PATH = Path("docs/source-recon/fsb-recon.json")

# 화면 HTML을 브라우저 UA로 받아야 정상 문서가 온다. 기본 UA로는 축약본이 온다.
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)

# 명세서 v3 §7.3.8 요청 제어. 정찰이라 요청 수 자체가 적다.
INTERVAL_SECONDS = 1.0

# 화면 이름 → 명세서 §7.2가 지정한 대상 화면.
#
# 세 화면이 같은 모양이 아니다. 실측으로 확인한 차이:
#   정기예금·정기적금 — `<화면>_01.jct`, 응답 키 REC, 가입기간·지역 차원 있음
#   입출금자유예금   — `<화면>.jct`,    응답 키 ANYM_REC/TOTAL_CNT,
#                      가입기간 없음, **지역 필터도 없음**
# 이 비대칭은 추측이 아니라 각 화면 전용 JS(ratedepo_0100.js / ratanym_0100.js)의
# sendData와 createAjaxUtil 인자를 읽어 확인한 것이다.
SCREENS = {
    "ratedepo_0100": ("정기예금", "term"),
    "rateinst_0100": ("정기적금", "term"),
    "ratanym_0100": ("입출금자유예금", "anytime"),
}

# 화면의 조회 차원. 라벨은 HTML에서 읽어 검증한다 (하드코딩 아님).
TERM_INPUT = "radio1"
JOIN_INPUT = "chkbox01"
AREA_SELECT = "areaSelect"

_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(CookieJar())
)


def _request(url: str, body: bytes | None = None, json_body: bool = False) -> tuple[int, bytes]:
    headers = {"User-Agent": UA, "Referer": f"{BASE}/ratedepo_0100.act"}
    if json_body:
        headers["Content-Type"] = "application/json; charset=UTF-8"
        headers["X-Requested-With"] = "XMLHttpRequest"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with _opener.open(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def save(content: bytes, name: str, suffix: str, also_fixture: bool = False) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"{name}_{stamp}.{suffix}"
    path.write_bytes(content)
    if also_fixture:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        (FIXTURE_DIR / f"{name}.{suffix}").write_bytes(content)
    return {
        "path": str(path),
        "sha256": sha256(content).hexdigest(),
        "bytes": len(content),
    }


_OPTION_RE = re.compile(r'<option[^>]*value=["\']([^"\']*)["\'][^>]*>(.*?)</option>', re.S)
_LABEL_RE = (
    r'<input[^>]*name="{name}"[^>]*value="([^"]+)"[^>]*>'
    r'(?:\s*</?\w+[^>]*>)*\s*<label[^>]*>(.*?)</label>'
)


def _text(raw: str) -> str:
    import html as _html

    return _html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def read_dimensions(html: str) -> dict:
    """조회 차원을 화면에서 읽는다. 값을 지어내지 않는다."""
    terms = [
        {"value": m.group(1), "label": _text(m.group(2))}
        for m in re.finditer(_LABEL_RE.format(name=TERM_INPUT), html, re.S)
    ]
    joins = [
        {"value": m.group(1), "label": _text(m.group(2))}
        for m in re.finditer(_LABEL_RE.format(name=JOIN_INPUT), html, re.S)
    ]
    # 입출금자유예금 화면은 가입방법 입력 이름이 chkbox01이 아니라 JOIN_LOCATION이다.
    joins_anytime = [
        {"value": m.group(1), "label": _text(m.group(2))}
        for m in re.finditer(_LABEL_RE.format(name="JOIN_LOCATION"), html, re.S)
    ]
    areas: list[dict] = []
    sel = re.search(
        rf'<select[^>]*id=["\']{AREA_SELECT}["\'][^>]*>(.*?)</select>', html, re.S
    )
    if sel:
        areas = [
            {"value": m.group(1), "label": _text(m.group(2))}
            for m in _OPTION_RE.finditer(sel.group(1))
        ]
    return {
        "terms": terms,
        "join_locations": joins,
        "join_locations_anytime": joins_anytime,
        "areas": areas,
    }


def read_notice(html: str) -> list[str]:
    """'정보 이용시 유의사항' 문구를 원문 그대로 남긴다.

    이 문구가 데이터의 성격(본점 기준 여부)을 규정하므로 요약하지 않는다.
    """
    body = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    flat = re.sub(r"\s+", " ", _text(body))
    idx = flat.find("정보 이용시 유의사항")
    if idx < 0:
        return []
    chunk = flat[idx : idx + 700]
    return [s.strip() for s in re.split(r"(?<=다\.)\s+", chunk) if s.strip()][:6]


def build_payload(*, on: str, area: str, term: str, joins: list[str], size: int) -> dict:
    """`depo_search()`가 조립하는 sendData를 그대로 재현한다.

    필드 이름과 순서는 ratedepo_0100.js에서 읽은 것이다. 의미를 모르는
    필드(TB_SEQ1~3, SEARCH_CODE 등)는 빈 값으로 둔다. 추측해서 채우지 않는다.
    """
    y, m, d = on.split("-")
    return {
        "REG_DATE": on,
        "CHG_DATE": on,
        "AREA": area,
        "SELECT_YEAR": y,
        "SELECT_MONTH": m,
        "SELECT_DAY": d,
        "TB_SEQ1": "",
        "TB_SEQ2": "",
        "TB_SEQ3": "",
        "ORDERBY": "",
        "JOIN_LOCATION": "|".join(joins),
        "CHK_MONTH": term,
        "END_NUM": str(size),
        "START_NUM": "1",
        "SEARCH_CODE": "",
        "SEARCH_SELECT_IN": "",
        "SEARCH_TEXT_IN": "",
    }


def build_anytime_payload(*, joins: list[str], size: int) -> dict:
    """`searchAnym()`의 sendData를 재현한다.

    가입기간과 지역이 없다. 대신 이자지급방식(DEPO_INTS_PRVS_MTHD_CD)과
    최고금리 기준(RATE_HIGH)이 차원이다. 의미를 모르는 값은 비워 둔다.
    """
    return {
        "ORDERBY": "",
        "RATE_HIGH": "",
        "RATE_HIGH_UPPER": "",
        "DEPO_INTS_PRVS_MTHD_CD": "",
        "JOIN_LOCATION": "|".join(joins),
        "END_NUM": str(size),
        "START_NUM": "1",
        "SEARCH_SELECT_IN": "",
        "SEARCH_TEXT_IN": "",
    }


def probe_screen(screen: str, label: str, shape: str, on: str, area: str, size: int) -> dict:
    """화면 HTML → 조회 차원 → 데이터 엔드포인트 순으로 확인한다."""
    result: dict = {"screen": screen, "label": label, "shape": shape}

    status, html_bytes = _request(f"{BASE}/{screen}.act")
    html = html_bytes.decode("utf-8", errors="replace")
    result["page"] = {"status": status, **save(html_bytes, screen, "html")}
    result["page_title"] = (
        _text(re.search(r"<title>(.*?)</title>", html, re.S).group(1))
        if "<title>" in html
        else None
    )
    result["dimensions"] = read_dimensions(html)
    result["notice"] = read_notice(html)
    time.sleep(INTERVAL_SECONDS)

    dims = result["dimensions"]
    if shape == "term":
        if not dims["terms"]:
            result["data"] = {"skipped": "가입기간 입력을 찾지 못해 데이터 요청을 보내지 않는다"}
            return result
        term = (
            "12"
            if any(t["value"] == "12" for t in dims["terms"])
            else dims["terms"][0]["value"]
        )
        joins = [j["value"] for j in dims["join_locations"]] or ["1"]
        payload = build_payload(on=on, area=area, term=term, joins=joins, size=size)
        url = f"{BASE}/{screen}_01.jct"
    else:
        joins = [j["value"] for j in dims["join_locations_anytime"]] or ["1"]
        payload = build_anytime_payload(joins=joins, size=size)
        url = f"{BASE}/{screen}.jct"
    status, raw = _request(url, json.dumps(payload).encode("utf-8"), json_body=True)
    entry: dict = {
        "endpoint": url,
        "status": status,
        "request": payload,
        # 저장 이름은 실제 호출한 엔드포인트에서 딴다. 화면마다 경로가 달라
        # 이름을 고정하면 파일과 요청이 어긋난다.
        **save(raw, url.rsplit("/", 1)[-1].removesuffix(".jct"), "json", also_fixture=True),
    }
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        entry["parse_error"] = str(exc)
        result["data"] = entry
        return result

    # 응답 키가 화면마다 다르다. REC(정기예금·정기적금) / ANYM_REC(입출금자유예금).
    rec = parsed.get("REC") or parsed.get("ANYM_REC") or []
    entry["top_level_keys"] = sorted(parsed)
    entry["record_count"] = len(rec)
    # 총건수도 위치가 다르다. 행 안의 CNT이거나 최상위 TOTAL_CNT다.
    entry["total_count"] = (rec[0].get("CNT") if rec else None) or parsed.get("TOTAL_CNT")
    entry["record_fields"] = sorted(rec[0]) if rec else []
    entry["sample"] = rec[0] if rec else None
    result["data"] = entry
    time.sleep(INTERVAL_SECONDS)
    return result


def probe_branches(area_code: str) -> dict:
    """저축은행 찾기 화면 — 점포 목록.

    금리 화면에는 소재지가 없다. 이 화면에만 있다. `BRANCH_NAME`이 '본점'인
    행이 본점이고 `ADDRESS`에 구·군까지 들어 있어, 금리를 **본점 소재지
    기준**으로 묶을 수 있다. 결합키는 금리 화면과 같은 `BANK_NAME`이다.

    AREA는 시도가 아니라 중앙회 지부 단위다(03 = 부산/경남). 부산만 보려면
    주소로 한 번 더 걸러야 한다.
    """
    screen = "sabfindquic_0100"
    status, html_bytes = _request(f"{BASE}/{screen}.act")
    time.sleep(INTERVAL_SECONDS)

    payload = {
        "AREA": area_code,
        "IBANK": "", "MBANK": "", "PLOAN": "", "N_FUNDS": "",
        "CD": "", "CDP": "", "ATM": "",
        "END_NUM": "500", "START_NUM": "1", "STR_SORT": "SEQ DESC",
        "ADDR": "", "SEARCHTEXT": "", "SEARCHVAL": "",
    }
    url = f"{BASE}/{screen}.jct"
    status, raw = _request(url, json.dumps(payload).encode("utf-8"), json_body=True)
    entry: dict = {
        "endpoint": url,
        "status": status,
        "request": payload,
        **save(raw, screen, "json", also_fixture=True),
    }
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        entry["parse_error"] = str(exc)
        return entry

    rec = parsed.get("REC") or []
    entry["area_codes"] = parsed.get("REC2") or []
    entry["record_count"] = len(rec)
    entry["record_fields"] = sorted(rec[0]) if rec else []
    entry["sample"] = rec[0] if rec else None

    busan = [r for r in rec if str(r.get("ADDRESS", "")).startswith("부산")]
    head_offices = [r for r in busan if r.get("BRANCH_NAME") == "본점"]
    entry["busan_outlets"] = len(busan)
    entry["busan_head_offices"] = sorted(
        {
            (r["BANK_NAME"].strip(), r["ADDRESS"].split()[1])
            for r in head_offices
            if len(r["ADDRESS"].split()) > 1
        }
    )
    districts: dict[str, int] = {}
    for r in busan:
        parts = r["ADDRESS"].split()
        if len(parts) > 1:
            districts[parts[1]] = districts.get(parts[1], 0) + 1
    entry["busan_districts"] = dict(sorted(districts.items(), key=lambda kv: -kv[1]))
    time.sleep(INTERVAL_SECONDS)
    return entry


def compare_areas(on: str, areas: list[str]) -> list[dict]:
    """AREA가 실제로 건수를 바꾸는지, 평균금리에도 반영되는지 확인한다."""
    out = []
    for area in areas:
        payload = build_payload(
            on=on, area=area, term="12", joins=["1", "2", "3", "4", "5", "9"], size=3
        )
        status, raw = _request(
            f"{BASE}/ratedepo_0100_01.jct",
            json.dumps(payload).encode("utf-8"),
            json_body=True,
        )
        row: dict = {"area": area or "(지역전체)", "status": status}
        try:
            parsed = json.loads(raw)
            rec = parsed.get("REC") or []
            row["total_count"] = rec[0].get("CNT") if rec else None
            row["avg_12m_simple"] = parsed.get("DAN12")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            row["parse_error"] = str(exc)
        out.append(row)
        time.sleep(INTERVAL_SECONDS)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="저축은행중앙회 구조 정찰")
    parser.add_argument("--date", default=date.today().isoformat(), help="조회일 YYYY-MM-DD")
    parser.add_argument("--area", default="YN_Busan", help="지역 코드 (빈 값이면 전체)")
    parser.add_argument("--size", type=int, default=10, help="표본으로 받을 행 수")
    parser.add_argument(
        "--branch-area", default="03", help="점포 조회 지부코드 (03=부산/경남)"
    )
    args = parser.parse_args()

    report = {
        "captured_at": datetime.now(UTC).isoformat(),
        "base": BASE,
        "query_date": args.date,
        "area": args.area,
        "screens": [],
    }
    for screen, (label, shape) in SCREENS.items():
        report["screens"].append(
            probe_screen(screen, label, shape, args.date, args.area, args.size)
        )

    report["area_comparison"] = compare_areas(args.date, ["", "YN_Busan", "YN_Seoul"])
    report["branches"] = probe_branches(args.branch_area)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"정찰 보고서: {REPORT_PATH}")
    for s in report["screens"]:
        data = s.get("data", {})
        print(
            f"  {s['screen']:16s} {s['label']:10s} "
            f"title={s.get('page_title')!r} "
            f"status={data.get('status')} "
            f"행={data.get('record_count')} 총={data.get('total_count')} "
            f"필드={len(data.get('record_fields') or [])}"
        )
    br = report["branches"]
    print(
        f"  점포: status={br.get('status')} 행={br.get('record_count')} "
        f"부산소재={br.get('busan_outlets')} 본점={len(br.get('busan_head_offices') or [])}"
    )
    print(f"    부산 구·군 분포: {br.get('busan_districts')}")
    print("  지역 비교:")
    for row in report["area_comparison"]:
        print(
            f"    {row['area']:12s} 총={row.get('total_count')} "
            f"평균12M단리={row.get('avg_12m_simple')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
