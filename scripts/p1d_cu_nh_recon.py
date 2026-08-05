#!/usr/bin/env python3
"""세로 절단 3·4 선행: 신협·지역농축협 원천 정찰.

명세서 v3 §22 — **실물 표본 없이 파서를 추정 구현하지 않는다.** 이 스크립트는
파서가 아니라 정찰이다. 어떤 화면이 있고 무엇을 돌려주는지만 기록한다.

확인한 것과 확인하지 못한 것을 구분해 남긴다. 상태코드 200이 곧 성공이
아니라는 것은 FSB 정찰에서 이미 겪었다 (소프트 404).

차단 우회는 하지 않는다 (명세서 v3 §0.2). 우리를 밝히는 User-Agent를 쓰고
1초 간격으로 보낸다.

사용법:
    python scripts/p1d_cu_nh_recon.py
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

RAW_DIR = Path("data/raw/p1d")
REPORT_PATH = Path("docs/source-recon/cu-nh-recon.json")

UA = "rate-monitor/1 (+public rate disclosure collector; 1 req/s)"
INTERVAL_SECONDS = 1.0
TIMEOUT = 25

# 소프트 404 판정. FSB에서 200을 돌려주면서 "찾을 수 없습니다"를 실어 보낸
# 사례가 있었다. 상태코드만 보고 성공으로 적으면 안 된다.
NOT_FOUND_MARKERS = (
    "요청하신 페이지를 찾을 수 없",
    "페이지를 찾을 수 없습니다",
    "Page Not Found",
    "잘못된 접근",
)
BLOCK_MARKERS = ("Request Blocked", "Access Denied", "접속이 차단")

# 정찰 대상. 각 항목은 "이 URL이 존재하는가"만 묻는다.
TARGETS = [
    # ── 신협 (CU) ────────────────────────────────────────────────────
    ("cu", "메인", "https://www.cu.co.kr/"),
    ("cu", "금리비교공시", "https://www.cu.co.kr/cu/deposit/rateDisclosure.do"),
    ("cu", "예적금금리", "https://www.cu.co.kr/cu/main/rate.do"),
    ("cu", "조합찾기", "https://www.cu.co.kr/cu/intro/branchSearch.do"),
    ("cu", "robots.txt", "https://www.cu.co.kr/robots.txt"),
    # ── 지역농축협 (NH) ──────────────────────────────────────────────
    ("nh", "농협 상호금융", "https://www.nonghyup.com/"),
    ("nh", "인터넷뱅킹", "https://banking.nonghyup.com/nhbank.html"),
    ("nh", "robots.txt", "https://www.nonghyup.com/robots.txt"),
    # ── 공통 비교공시 (금감원 외 통합 창구가 있는지) ─────────────────
    ("etc", "금융상품한눈에", "https://finlife.fss.or.kr/finlife/main/main.do"),
]

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_SCRIPT_SRC = re.compile(r'<script[^>]+src="([^"]+)"', re.I)
_FORM = re.compile(r'<form[^>]*\bid="([^"]+)"[^>]*\baction="([^"]+)"', re.I)
_LINK = re.compile(r'<a[^>]+href="([^"#][^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
_TAG = re.compile(r"<[^>]+>")

# 금리 화면일 법한 링크만 추린다. 사이트 전체를 긁지 않는다.
RATE_WORDS = ("금리", "이율", "예금", "적금", "수신", "공시", "상품")


def get(url: str) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})
    except Exception as exc:  # 네트워크 자체가 막힌 경우도 기록한다
        return 0, str(exc).encode(), {}


def text_of(html: str) -> str:
    return _TAG.sub(" ", html)


def probe(sector: str, label: str, url: str) -> dict:
    status, content, headers = get(url)
    entry: dict = {
        "sector": sector,
        "label": label,
        "url": url,
        "status": status,
        "bytes": len(content),
        "content_type": headers.get("Content-Type"),
    }
    if status == 0:
        entry["error"] = content.decode("utf-8", "ignore")[:200]
        return entry
    if not content:
        entry["empty"] = True
        return entry

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", f"{sector}_{label}")[:60]
    path = RAW_DIR / f"{safe}_{stamp}.html"
    path.write_bytes(content)
    entry["artifact"] = {"path": str(path), "sha256": sha256(content).hexdigest()}

    html = content.decode("utf-8", "replace")
    title = _TITLE.search(html)
    entry["title"] = _TAG.sub("", title.group(1)).strip()[:120] if title else None

    body = text_of(html)
    # 상태코드 200이어도 내용이 "없는 페이지"일 수 있다.
    entry["soft_404"] = any(m in body for m in NOT_FOUND_MARKERS)
    entry["blocked"] = any(m in body for m in BLOCK_MARKERS)

    # 금리 숫자가 화면 HTML에 실제로 들어 있는가. 없으면 AJAX다.
    entry["rate_like_numbers"] = len(re.findall(r"\b\d\.\d{1,2}\s*%", body))

    entry["scripts"] = sorted({s for s in _SCRIPT_SRC.findall(html)})[:20]
    entry["forms"] = [{"id": i, "action": a} for i, a in _FORM.findall(html)][:20]

    links = []
    for href, inner in _LINK.findall(html):
        label_text = " ".join(_TAG.sub(" ", inner).split())[:60]
        if not label_text:
            continue
        if any(w in label_text for w in RATE_WORDS):
            links.append({"text": label_text, "href": urllib.parse.urljoin(url, href)})
    # 같은 곳을 가리키는 링크가 많아 중복을 걷는다.
    seen: set[str] = set()
    entry["rate_links"] = [
        link for link in links
        if not (link["href"] in seen or seen.add(link["href"]))
    ][:30]
    return entry


def main() -> int:
    report: dict = {
        "captured_at": datetime.now(UTC).isoformat(),
        "note": (
            "정찰 기록이다. 파서 설계가 아니다. 상태코드 200이 곧 성공이"
            " 아니므로 soft_404를 함께 본다."
        ),
        "user_agent": UA,
        "probes": [],
    }

    for sector, label, url in TARGETS:
        entry = probe(sector, label, url)
        report["probes"].append(entry)
        print(
            f"  [{sector:3s}] {label:16s} status={entry['status']:3d} "
            f"bytes={entry['bytes']:7d} "
            f"soft404={entry.get('soft_404')} "
            f"금리숫자={entry.get('rate_like_numbers', 0)} "
            f"금리링크={len(entry.get('rate_links') or [])}"
        )
        time.sleep(INTERVAL_SECONDS)

    ok = [p for p in report["probes"] if p["status"] == 200 and not p.get("soft_404")]
    report["totals"] = {
        "probed": len(report["probes"]),
        "reachable": len(ok),
        "blocked": len([p for p in report["probes"] if p.get("blocked")]),
        "with_inline_rates": len([p for p in ok if p.get("rate_like_numbers", 0) > 0]),
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n정찰 보고서: {REPORT_PATH}")
    print(f"  {report['totals']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
