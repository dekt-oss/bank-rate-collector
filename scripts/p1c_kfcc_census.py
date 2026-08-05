#!/usr/bin/env python3
"""새마을금고 모집단 조사.

명세서 v3 §13.4는 모집단이 미확정이면 "모집단 확인 중"으로 표시하라고 했다.
이 스크립트가 공식 목록을 직접 세어 그 표시를 걷어낸다.

파서가 아니라 **인구 조사**다. 목록 페이지만 읽고 금고·점포 수를 센다.
금리는 건드리지 않는다.

목록 페이지는 원천값을 숨김 span으로 노출한다 (docs/source-recon/kfcc.md §3).
그 추출 규칙은 scripts/p0_kfcc_capture.py에서 검증된 것을 그대로 쓴다.

`r2`를 비우면 지역 하나가 요청 한 번에 온다. 그래서 시군구 목록이 필요 없고,
수집 범위는 `config/regions.yaml`의 이름으로 고른다.

사용법:
    python scripts/p1c_kfcc_census.py [--scope 전국] [--regions config/regions.yaml]
"""

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import yaml

BASE = "https://www.kfcc.co.kr"
RAW_DIR = Path("data/raw/p1c/kfcc")
FIXTURE_DIR = Path("tests/fixtures/kfcc")
REPORT_PATH = Path("docs/source-recon/kfcc-census.json")
UA = "rate-monitor-census/1"

# 명세서 v3 §7.3.8 요청 제어
INTERVAL_SECONDS = 1.0

# docs/source-recon/kfcc.md §3 실측 구조
SPAN_RE = re.compile(r'<span[^>]*title="([a-zA-Z_0-9]+)"[^>]*>([^<]*)</span>')


def get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


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
    return [r for r in rows if r.get("gmgoCd")]


def survey_region(r1: str) -> dict:
    """지역 하나를 한 번에 센다.

    `r2`를 비우면 그 지역 전체가 한 응답에 온다. 예전에는 구·군을 하나씩
    돌았는데, 손으로 관리하는 구·군 목록이 필요했고 요청도 그만큼 늘었다.
    """
    query = urllib.parse.urlencode({"r1": r1, "r2": ""})
    url = f"{BASE}/map/list.do?{query}"
    status, content = get(url)

    entry: dict = {"r1": r1, "url": url, "status": status, "bytes": len(content)}
    if status != 200 or not content:
        entry["blocked_or_error"] = True
        entry["snippet"] = content.decode("utf-8", "ignore")[:200]
        return entry

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"list_{r1}_{stamp}.html"
    path.write_bytes(content)
    entry["artifact"] = {"path": str(path), "sha256": sha256(content).hexdigest()}

    text = content.decode("utf-8", "ignore")
    rows = extract_rows(text)
    codes = {r["gmgoCd"] for r in rows}
    entry["outlets"] = len(rows)
    entry["institutions"] = len(codes)

    # gmgoType은 직장금고 여부를 명칭 추측이 아니라 공식 값으로 준다
    # (명세서 v3 §7.3.4 item 7).
    entry["gmgo_types"] = dict(Counter(r.get("gmgoType", "") for r in rows))

    # 화면의 r1을 시도로 믿지 않는다. 주소 첫 토막이 실제로 무엇인지 센다.
    # r1=광주가 전남 주소를 함께 돌려주는 것이 여기서 드러난다.
    entry["address_sido"] = dict(
        Counter((r.get("addr") or " ").split()[0] for r in rows if r.get("addr"))
    )
    entry["address_sigungu"] = dict(
        Counter(
            (r.get("addr") or "").split()[1]
            for r in rows
            if len((r.get("addr") or "").split()) > 1
        )
    )
    entry["codes"] = sorted(codes)
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description="새마을금고 모집단 조사")
    parser.add_argument("--regions", default="config/regions.yaml")
    parser.add_argument(
        "--scope", default=None, help="config의 수집 범위 이름. 생략하면 default_scope"
    )
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.regions).read_text(encoding="utf-8"))
    scopes = {s["name"]: list(s["kfcc_r1"]) for s in cfg["scopes"]}
    scope_name = args.scope or cfg["default_scope"]
    if scope_name not in scopes:
        print(f"config에 없는 수집 범위: {scope_name!r} (가능: {sorted(scopes)})")
        return 2

    report: dict = {
        "captured_at": datetime.now(UTC).isoformat(),
        "base": BASE,
        "scope": scope_name,
        "note": (
            "공식 목록 직접수집. r1은 사이트의 지역 구분값이며 행정구역 시도가"
            " 아니다. 지역 판정은 address_sido/address_sigungu를 본다."
        ),
        "regions": [],
    }

    for r1 in scopes[scope_name]:
        row = survey_region(r1)
        report["regions"].append(row)
        print(
            f"  {r1:6s} status={row['status']} "
            f"금고={row.get('institutions', '-')} 점포={row.get('outlets', '-')} "
            f"주소시도={row.get('address_sido', '-')}"
        )
        time.sleep(INTERVAL_SECONDS)

    ok = [d for d in report["regions"] if d.get("status") == 200]
    all_codes: set[str] = set()
    sido_totals: Counter = Counter()
    for d in ok:
        all_codes.update(d.get("codes") or [])
        sido_totals.update(d.get("address_sido") or {})
    report["totals"] = {
        "regions_queried": len(report["regions"]),
        "regions_ok": len(ok),
        # 같은 금고가 여러 지역에 점포를 둘 수 있으므로 코드 합집합으로 센다.
        "institutions_distinct": len(all_codes),
        "institutions_sum_by_region": sum(d.get("institutions", 0) for d in ok),
        "outlets": sum(d.get("outlets", 0) for d in ok),
        "outlets_by_address_sido": dict(sorted(sido_totals.items())),
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    t = report["totals"]
    print(f"\n조사 보고서: {REPORT_PATH}")
    print(f"  지역 {t['regions_ok']}/{t['regions_queried']} 조회 성공")
    print(
        f"  고유 금고 {t['institutions_distinct']} "
        f"(지역별 합계 {t['institutions_sum_by_region']})"
    )
    print(f"  점포 {t['outlets']}")
    print(f"  주소 기준 시도 분포 {t['outlets_by_address_sido']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
