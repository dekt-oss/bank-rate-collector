"""발행 전 파일 크기 검사 (선행 수정안 v1 §10).

GitHub의 100 MB 한도는 저장소 전체가 아니라 **개별 blob 기준**이다. 한 번
넘으면 push 자체가 거부되고, 그 시점에는 이미 커밋이 쌓여 있어 되돌리기가
번거롭다. 그래서 한도 근처가 아니라 한참 앞에서 멈춘다.

2026-08-06 실측이 이 검사를 만든 이유다. rate-data가 이미 이랬다.

    51.53 MiB  latest/rate_monitor.sqlite3.gz
    50.67 MiB  latest/export/rates_20260806.json
    24.37 MiB  latest/summary.json
    16.57 MiB  site-public/data/rates.csv
    16.57 MiB  latest/export/rates_20260806.csv   ← 위와 같은 내용이 두 벌
     5.51 MiB  site/index.html
     5.51 MiB  site/public.html                   ← 아티팩트 시절 화면

경고만 하고 넘어가지 않는다. 넘으면 발행을 멈춘다 — 발행이 멈추면 어제
사이트가 그대로 남고, 그건 push가 거부되어 실행이 통째로 실패하는 것보다
낫다.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

MIB = 1024 * 1024

# 선행 수정안 v1 §10. GitHub 100 MB 직전까지 쓰지 않는다.
GIT_FILE_WARN = 20 * MIB
GIT_FILE_FAIL = 40 * MIB

# 화면이 **자동으로** 받아 가는 조각. 페이지를 열면 무조건 따라오므로
# 파일 크기가 곧 대기 시간이다. 그래서 한도가 더 빡빡하다.
SHARD_WARN = 10 * MIB
SHARD_FAIL = 20 * MIB

# 브랜치 전체. 한 커밋으로 재작성하므로 이 값이 곧 브랜치 크기다.
TOTAL_WARN = 100 * MIB
TOTAL_FAIL = 200 * MIB

# 다음 수집이 이어받는 운영 상태 DB. **한시적 예외다.**
#
# 2026-08-06 현재 50.75 MiB로 일반 한도(40 MiB)를 넘는다. 그런데 지금은
# 지울 수 없다 — 워크플로우의 Restore previous database 단계가 이 파일에서
# DB를 복원한다. 없애면 다음 실행이 빈 DB로 시작해 이력이 통째로 사라진다.
#
# 선행 수정안 v1 PR 2가 이 파일을 R2로 옮긴다. 그때 이 예외를 지운다.
# 그 전까지는 GitHub의 진짜 벽(100 MB)만 막는다 — 80 MiB에서 멈추면
# push가 거부되기 전에 손쓸 시간이 있다.
STATE_DB = "latest/rate_monitor.sqlite3.gz"
STATE_DB_WARN = 40 * MIB
STATE_DB_FAIL = 80 * MIB

SHARD_PREFIX = "site-public/data/"
# 사람이 눌러야 받아지는 파일. 같은 폴더에 있지만 성격이 다르다 — 페이지를
# 여는 사람 전부가 아니라 받겠다고 누른 사람만 기다린다. 화면이 크기를 미리
# 적어 주므로 눌러 보기 전에 알 수 있다. 여기에 화면 조각 한도를 들이대면
# 아무도 못 받는 크기로 잘라야 한다.
DOWNLOAD_STEMS = ("rates",)


@dataclass(frozen=True)
class Finding:
    """한 항목의 판정. `level`은 ok / warn / fail 셋 중 하나다."""

    level: str
    path: str
    size: int
    limit: int

    @property
    def failed(self) -> bool:
        return self.level == "fail"


def limits_for(relative: str) -> tuple[int, int]:
    """그 파일에 적용할 (경고, 실패) 한도.

    화면이 자동으로 받는 조각만 조각 한도를 쓴다. 같은 폴더에 있어도
    사람이 눌러야 받아지는 파일은 일반 Git 파일로 본다.

    >>> limits_for(STATE_DB) == (STATE_DB_WARN, STATE_DB_FAIL)
    True
    >>> limits_for("site-public/data/table.json") == (SHARD_WARN, SHARD_FAIL)
    True
    >>> limits_for("site-public/data/rates.csv") == (GIT_FILE_WARN, GIT_FILE_FAIL)
    True
    >>> limits_for("site-public/data/rates.json.gz") == (GIT_FILE_WARN, GIT_FILE_FAIL)
    True
    >>> limits_for("latest/summary.json") == (GIT_FILE_WARN, GIT_FILE_FAIL)
    True
    """
    if relative == STATE_DB:
        return STATE_DB_WARN, STATE_DB_FAIL
    if relative.startswith(SHARD_PREFIX):
        name = relative[len(SHARD_PREFIX) :]
        stem = name.split(".", 1)[0]
        if stem not in DOWNLOAD_STEMS:
            return SHARD_WARN, SHARD_FAIL
    return GIT_FILE_WARN, GIT_FILE_FAIL


def classify(size: int, warn: int, fail: int) -> str:
    """한 파일의 판정.

    >>> classify(5, 10, 20), classify(15, 10, 20), classify(25, 10, 20)
    ('ok', 'warn', 'fail')
    """
    if size >= fail:
        return "fail"
    if size >= warn:
        return "warn"
    return "ok"


def inspect(root: Path) -> list[Finding]:
    """트리 전체를 재고 판정한다. 합계도 한 항목으로 넣는다."""
    findings: list[Finding] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        size = path.stat().st_size
        total += size
        relative = path.relative_to(root).as_posix()
        warn, fail = limits_for(relative)
        findings.append(Finding(classify(size, warn, fail), relative, size, fail))

    findings.sort(key=lambda f: -f.size)
    findings.append(
        Finding(classify(total, TOTAL_WARN, TOTAL_FAIL), "(전체)", total, TOTAL_FAIL)
    )
    return findings


def report(findings: list[Finding]) -> int:
    """사람이 읽을 표를 찍고 종료코드를 돌려준다."""
    mark = {"ok": "    ", "warn": "경고", "fail": "실패"}
    shown = [f for f in findings if f.level != "ok" or f.size >= MIB]
    for f in shown:
        print(f"  [{mark[f.level]}] {f.size / MIB:9.2f} MiB  {f.path}")

    hidden = len(findings) - len(shown)
    if hidden:
        print(f"  ... 1 MiB 미만 {hidden}개 생략")

    failures = [f for f in findings if f.failed]
    if failures:
        print(f"\n  한도를 넘었다. 발행하지 않는다 ({len(failures)}건):")
        for f in failures:
            print(f"    {f.path} — {f.size / MIB:.2f} MiB > {f.limit / MIB:.0f} MiB")
        return 1

    # 예외를 조용히 두지 않는다. 통과할 때마다 적어야 잊히지 않는다.
    state = next((f for f in findings if f.path == STATE_DB), None)
    if state is not None:
        print(
            f"\n  ※ {STATE_DB}는 한시 예외다 ({state.size / MIB:.2f} MiB, "
            f"한도 {STATE_DB_FAIL / MIB:.0f} MiB).\n"
            "    지금 지우면 다음 실행이 빈 DB로 시작한다. R2로 옮긴 뒤"
            " 이 예외를 없앤다 (선행 수정안 v1 PR 2)."
        )

    warned = [f for f in findings if f.level == "warn"]
    print(f"\n  통과 — 파일 {len(findings) - 1}개, 경고 {len(warned)}건")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="발행 전 파일 크기 검사")
    parser.add_argument("root", type=Path, help="검사할 트리 (발행 직전 스테이지)")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"디렉터리가 아니다: {args.root}", file=sys.stderr)
        return 2
    print(f"파일 크기 검사 — {args.root}")
    return report(inspect(args.root))


if __name__ == "__main__":
    raise SystemExit(main())
