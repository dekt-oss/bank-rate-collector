"""발행 전 물량 급감 검사 (v4 §12.4).

2026-08-06에 실제로 일어난 일이다.

    finlife 원본 7개 → 2개, 파싱 4,010 → 1,075 (73% 손실)
    수집 상태          success
    validate           12/12 통과
    P1-A 게이트        15/15 통과
    발행               성공
    공개 사이트        132,502 → 129,567행

**아무것도 이상을 알리지 않았다.** 기존 검사는 전부 "이 실행 안에서 앞뒤가
맞는가"만 본다. 절반이 사라져도 남은 절반끼리는 완벽하게 맞으므로 다
통과한다.

빠진 관점은 **같은 수집원의 직전 실행과 비교하는 것**이다. 물량은 하루아침에
4분의 1이 되지 않는다. 그렇게 되면 원천이 바뀌었거나 우리가 덜 받아온 것이고,
둘 다 사람이 봐야 한다.

무엇을 비교하느냐가 중요하다. 처음에는 `sources[].observation_count`를 썼는데
**그 값은 누적이라 나쁜 실행에서도 늘어난다.** 실제 사고 데이터로 시험해 보니
finlife가 24,060 → 25,135로 **증가**해 그냥 통과했다. 화면 행 수도 97.8%라
걸리지 않았다 — finlife가 전체의 3%뿐이라 묻힌다.

그래서 `runs`의 실행별 `parsed_count`를 본다. 한 수집원이 무너지면 그 수집원
안에서는 73% 손실로 또렷하게 드러난다.

발행을 막는 쪽을 고른다. 막으면 어제 사이트가 그대로 남는다 — 틀린 것을
새로 올리는 것보다 낫다.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# 이 비율 아래로 떨어지면 멈춘다.
#
# 0.75는 "한 수집원의 4분의 1이 사라졌다"는 뜻이다. 정상 변동으로 보기
# 어렵다. 2026-08-06 실측 손실은 26.8%로 남았으므로 이 선에 걸린다.
#
# 늘어나는 것은 막지 않는다. 수집 범위를 넓히면 물량은 뛴다.
MIN_RATIO = 0.75

# 이 아래에서는 비율을 따지지 않는다. 3건이 2건이 되면 33% 감소지만
# 그건 그냥 작은 수다.
MIN_BASELINE = 100


@dataclass(frozen=True)
class Change:
    source_id: str
    before: int
    after: int

    @property
    def ratio(self) -> float:
        return self.after / self.before if self.before else 1.0

    @property
    def collapsed(self) -> bool:
        return self.before >= MIN_BASELINE and self.ratio < MIN_RATIO


def last_two_runs(summary: dict) -> dict[str, list[dict]]:
    """수집원마다 최근 실행 두 개. 최신이 앞이다.

    실패한 실행은 빼고 본다. 실패는 이미 다른 검사가 잡고, 여기 넣으면
    0건과 비교해 늘 급감으로 나온다.

    >>> s = {"runs": [
    ...   {"source_id": "a", "status": "success", "parsed_count": 10},
    ...   {"source_id": "a", "status": "failed",  "parsed_count": 0},
    ...   {"source_id": "a", "status": "success", "parsed_count": 40}]}
    >>> [r["parsed_count"] for r in last_two_runs(s)["a"]]
    [10, 40]
    """
    counted = ("success", "partial", "no_change")
    grouped: dict[str, list[dict]] = {}
    for run in summary.get("runs") or []:
        if run.get("status") not in counted:
            continue
        grouped.setdefault(run.get("source_id", "?"), []).append(run)
    return {k: v[:2] for k, v in grouped.items()}


def compare(summary: dict) -> list[Change]:
    """각 수집원의 최신 실행을 그 직전 실행과 견준다.

    비교할 직전 실행이 없으면 건너뛴다 — 첫 수집은 급감이 아니다.
    """
    changes = []
    for source_id, runs in sorted(last_two_runs(summary).items()):
        if len(runs) < 2:
            continue
        changes.append(
            Change(
                source_id,
                int(runs[1].get("parsed_count") or 0),
                int(runs[0].get("parsed_count") or 0),
            )
        )
    return changes


def report(changes: list[Change]) -> int:
    if not changes:
        print("  비교할 직전 실행이 없다. 건너뛴다")
        return 0

    for c in changes:
        mark = "급감" if c.collapsed else "    "
        print(
            f"  [{mark}] {c.source_id:10s} {c.before:>8,} → {c.after:>8,}"
            f"  ({c.ratio:6.1%})"
        )

    collapsed = [c for c in changes if c.collapsed]
    if collapsed:
        print(f"\n  물량이 급감했다. 발행하지 않는다 ({len(collapsed)}건):")
        for c in collapsed:
            print(f"    {c.source_id} — {c.before:,} → {c.after:,} ({c.ratio:.1%})")
        print(
            f"\n  기준: 같은 수집원의 직전 실행 대비 {MIN_RATIO:.0%} 미만.\n"
            "  원천이 정말 줄었다면 --accept로 한 번 통과시킨다."
        )
        return 1

    print(f"\n  통과 — 모든 수집원이 직전 실행 대비 {MIN_RATIO:.0%} 이상")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="발행 전 물량 급감 검사")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--accept", action="store_true",
        help="급감을 알고도 발행한다. 원천이 정말 줄었을 때만 쓴다",
    )
    args = parser.parse_args(argv)

    if not args.summary.is_file():
        print(f"summary가 없다: {args.summary}", file=sys.stderr)
        return 2

    print("물량 급감 검사 — 수집원별 직전 실행 대비")
    code = report(compare(json.loads(args.summary.read_text(encoding="utf-8"))))
    if code and args.accept:
        print("\n  --accept — 급감을 알고 발행한다")
        return 0
    return code


if __name__ == "__main__":
    raise SystemExit(main())
