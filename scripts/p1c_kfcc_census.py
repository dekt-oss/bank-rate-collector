#!/usr/bin/env python3
"""세로 절단 2 선행: 새마을금고 부산 모집단 확정.

명세서 v3 §13.4는 모집단이 미확정이면 "모집단 확인 중"으로 표시하라고 했다.
지금까지 부산 137금고/273점포는 **참고 저장소 집계**였을 뿐 공식 직접수집으로
확인한 값이 아니다. 이 스크립트가 그 확인을 한다.

파서가 아니라 **인구 조사**다. 목록 페이지만 읽고 금고·점포 수를 센다.
금리는 건드리지 않는다.

목록 페이지는 원천값을 숨김 span으로 노출한다 (docs/source-recon/kfcc.md §3).
그 추출 규칙은 scripts/p0_kfcc_capture.py에서 검증된 것을 그대로 쓴다.

사용법:
    python scripts/p1c_kfcc_census.py [--regions config/regions.yaml]
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


def survey_district(r1: str, r2: str) -> dict:
    query = urllib.parse.urlencode({"r1": r1, "r2": r2})
    url = f"{BASE}/map/list.do?{query}"
    status, content = get(url)

    entry: dict = {"sigungu": r2, "url": url, "status": status, "bytes": len(content)}
    if status != 200 or not content:
        entry["blocked_or_error"] = True
        entry["snippet"] = content.decode("utf-8", "ignore")[:200]
        return entry

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"list_{r1}_{r2}_{stamp}.html"
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

    # 주소가 정말 요청한 구·군인지 되짚는다. 화면 파라미터를 믿지 않는다.
    mismatched = [
        r.get("addr", "")
        for r in rows
        if r.get("addr") and f" {r2} " not in f" {r.get('addr', '')} "
    ]
    entry["address_mismatch"] = len(mismatched)
    entry["address_mismatch_sample"] = mismatched[:3]
    entry["codes"] = sorted(codes)
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description="새마을금고 부산 모집단 조사")
    parser.add_argument("--regions", default="config/regions.yaml")
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.regions).read_text(encoding="utf-8"))
    r1 = cfg["kfcc_r1"]

    report: dict = {
        "captured_at": datetime.now(UTC).isoformat(),
        "base": BASE,
        "sido": cfg["sido_name"],
        "note": "공식 목록 직접수집. 참고 저장소 집계와 독립적으로 센 값이다.",
        "districts": [],
    }

    for entry in cfg["sigungu"]:
        row = survey_district(r1, entry["kfcc_r2"])
        report["districts"].append(row)
        print(
            f"  {row['sigungu']:8s} status={row['status']} "
            f"금고={row.get('institutions', '-')} 점포={row.get('outlets', '-')} "
            f"주소불일치={row.get('address_mismatch', '-')}"
        )
        time.sleep(INTERVAL_SECONDS)

    ok = [d for d in report["districts"] if d.get("status") == 200]
    all_codes: set[str] = set()
    for d in ok:
        all_codes.update(d.get("codes") or [])
    report["totals"] = {
        "districts_queried": len(report["districts"]),
        "districts_ok": len(ok),
        # 같은 금고가 여러 구에 점포를 둘 수 있으므로 코드 합집합으로 센다.
        "institutions_distinct": len(all_codes),
        "institutions_sum_by_district": sum(d.get("institutions", 0) for d in ok),
        "outlets": sum(d.get("outlets", 0) for d in ok),
        "address_mismatch": sum(d.get("address_mismatch", 0) for d in ok),
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    t = report["totals"]
    print(f"\n조사 보고서: {REPORT_PATH}")
    print(f"  구·군 {t['districts_ok']}/{t['districts_queried']} 조회 성공")
    print(
        f"  고유 금고 {t['institutions_distinct']} "
        f"(구별 합계 {t['institutions_sum_by_district']})"
    )
    print(f"  점포 {t['outlets']}")
    print(f"  주소 불일치 {t['address_mismatch']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
