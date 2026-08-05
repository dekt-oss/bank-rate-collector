#!/usr/bin/env python3
"""P0: 새마을금고 공식 사이트 직접수집 가능성 프로브.

명세서 v3는 `kfcc_official`(공식 직접수집)을 주 수집원으로 두고
`kfcc_reference`(공개 JSON)를 검증용 보조로 둔다. 이 스크립트는
주 수집원이 현재 네트워크 경로에서 실제로 도달 가능한지 판정한다.

수집이 아니라 도달성 확인이므로 요청은 최소 횟수만 보내고,
차단 응답을 받으면 즉시 중단한다. 우회 시도는 하지 않는다.

사용법:
    python scripts/p0_kfcc_probe.py
"""

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPORT_PATH = Path("docs/source-recon/kfcc-probe.json")
UA = "rate-monitor-p0-probe/1 (+official public page reachability check)"

TARGETS = [
    ("robots", "https://www.kfcc.co.kr/robots.txt"),
    ("map_main", "https://www.kfcc.co.kr/map/main.do"),
    ("map_list", "https://www.kfcc.co.kr/map/list.do?r1=%EB%B6%80%EC%82%B0&r2=%EC%A4%91%EA%B5%AC"),
]


def probe(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read(4096)
            return {
                "status": resp.status,
                "content_length": len(body),
                "blocked_marker": "Request Blocked" in body.decode("utf-8", "ignore"),
                "snippet": body.decode("utf-8", "ignore")[:200],
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", "ignore")
        return {
            "status": exc.code,
            "blocked_marker": "Request Blocked" in body,
            "snippet": body[:200],
        }
    except Exception as exc:  # noqa: BLE001 - 프로브는 모든 실패를 기록한다
        return {"status": None, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "note": "도달성 확인 전용. 차단 시 우회하지 않고 그대로 기록한다.",
        "results": {},
    }

    for name, url in TARGETS:
        result = probe(url)
        report["results"][name] = {"url": url, **result}
        print(f"{name}: status={result.get('status')} blocked={result.get('blocked_marker')}")
        if result.get("blocked_marker") or result.get("status") in (403, 429):
            report["results"][name]["stopped_early"] = True
            print("  -> 차단 응답. 추가 요청을 중단한다.")
            break
        time.sleep(1.0)

    reachable = any(
        r.get("status") == 200 and not r.get("blocked_marker")
        for r in report["results"].values()
    )
    report["conclusion"] = {
        "kfcc_official_reachable": reachable,
        "verdict": (
            "공식 직접수집 가능 — kfcc_official을 주 수집원으로 구현 진행"
            if reachable
            else "현재 네트워크 경로에서 차단 — kfcc_official 구현 전 실행 환경 결정 필요"
        ),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n판정 -> {REPORT_PATH}")
    print(json.dumps(report["conclusion"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
