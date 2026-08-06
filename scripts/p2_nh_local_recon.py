"""농·축협 원천 정찰 (v4 §5.2, PR 3).

**파서를 만들기 전에 무엇이 실재하는지부터 확인한다** (v4 §0.2). 이 스크립트는
아무것도 파싱하지 않는다. 호스트와 화면이 응답하는지만 두드려 보고 그 결과를
JSON으로 남긴다.

왜 스크립트인가: 2026-08-05 정찰은 "중앙 수집 불가"라는 틀린 결론을 냈고,
근거가 손으로 두드려 본 기억뿐이라 아무도 재확인하지 못했다. 여기서는 무엇을
두드렸고 무엇이 돌아왔는지가 파일로 남는다.

    uv run python scripts/p2_nh_local_recon.py --out docs/source-recon/nh-local-recon-v2.json

차단은 우회하지 않는다 (v3 §16.1). User-Agent를 브라우저로 위장하지 않고
우리를 밝힌다. 403/429가 오면 그 자리에서 멈춘다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

USER_AGENT = "rate-monitor/1 (+public rate disclosure collector; 1 req/s)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# 두드릴 곳. 명세서 v4 §5.1이 적은 화면 ID와, 그것이 있을 법한 호스트들.
#
# 첫 질문은 "그 화면이 어느 호스트에 있나"였고, 답은 wmall.nonghyup.com이다.
# 나머지 넷을 남겨 두는 이유는, 화면군이 호스트로 갈린다는 사실 자체가
# 결과이기 때문이다 — BF*는 smartmarket, SF*는 wmall/mmall이다.
HOSTS = (
    ("wmall.nonghyup.com", "NH웹 (농·축협) — 여기에 있다"),
    ("smartmarket.nonghyup.com", "농협은행 금융상품몰"),
    ("mmall.nonghyup.com", "NH모바일웹 (농·축협)"),
    ("banking.nonghyup.com", "NH뱅킹"),
    ("www.nonghyup.com", "농협 소개"),
)

SCREENS = (
    "SFDPW0160R",  # v4 §5.1: 농·축협별 예금금리 검색
    "SFDPW0161R",  # v4 §5.1: 검색 결과
    "SFDPW0162R",  # v4 §5.1: 점포별 금리 상세
    "SFDPM0130R",  # 실측으로 찾은 모바일 화면
    "SFDPM0100R",
    "BFBCW0001R",  # 농협은행 진입 화면 (대조군)
)

# 대출금리는 공개 페이지가 따로 있다. 예금 쪽 대응 페이지가 있는지 본다.
STATIC_PAGES = (
    "https://www.nonghyup.com/introduce/interest/loan1.do",
    "https://www.nonghyup.com/introduce/interest/loan2.do",
)


@dataclass
class Probe:
    """한 번 두드린 결과. 무엇을 봤는지가 다음 사람에게 남아야 한다."""

    url: str
    status: int | None
    bytes: int
    title: str | None = None
    note: str = ""
    screen_ids: list[str] = field(default_factory=list)


def _title(html: str) -> str | None:
    match = re.search(r"<title>(.*?)</title>", html, re.S)
    return match.group(1).strip()[:120] if match else None


def _screen_ids(html: str) -> list[str]:
    """화면 ID처럼 생긴 토큰. 어느 화면군이 사는 호스트인지 드러난다."""
    return sorted({m for m in re.findall(r"\b[A-Z]{4}[A-Z0-9]{5,6}\b", html)})[:40]


def probe(client: httpx.Client, url: str, note: str = "") -> Probe:
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        return Probe(url=url, status=None, bytes=0, note=f"{note} 연결 실패: {exc}".strip())

    if response.status_code in (403, 429):
        # 차단은 우회하지 않는다. 기록하고 멈춘다.
        return Probe(url=url, status=response.status_code, bytes=len(response.content),
                     note=f"{note} 차단 응답 — 우회하지 않는다".strip())

    text = response.text
    return Probe(
        url=url,
        status=response.status_code,
        bytes=len(response.content),
        title=_title(text),
        note=note,
        screen_ids=_screen_ids(text) if response.status_code == 200 else [],
    )


def run() -> dict[str, object]:
    probes: list[Probe] = []
    with httpx.Client(
        timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        for host, label in HOSTS:
            probes.append(probe(client, f"https://{host}/", label))
            for screen in SCREENS:
                probes.append(probe(client, f"https://{host}/servlet/{screen}.view", label))
        for url in STATIC_PAGES:
            probes.append(probe(client, url, "농·축협 대출금리 공개 페이지"))

    reachable = [p for p in probes if p.status == 200]
    return {
        "probes": [asdict(p) for p in probes],
        "summary": {
            "probed": len(probes),
            "http_200": len(reachable),
            "hosts_alive": sorted({p.url.split("/")[2] for p in reachable}),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="결과 JSON 경로")
    args = parser.parse_args(argv)

    report = run()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"기록: {args.out}")
    for entry in report["probes"]:  # type: ignore[index]
        mark = "OK " if entry["status"] == 200 else "   "
        print(f"  {mark}{entry['status']!s:>5}  {entry['bytes']:>8,}B  {entry['url']}")
    print(f"\n응답한 호스트: {report['summary']['hosts_alive']}")  # type: ignore[index]
    return 0


if __name__ == "__main__":
    sys.exit(main())
