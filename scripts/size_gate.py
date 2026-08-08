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
import gzip
import sys
from dataclasses import dataclass
from pathlib import Path

MIB = 1024 * 1024

# 선행 수정안 v1 §10. GitHub 100 MB 직전까지 쓰지 않는다.
GIT_FILE_WARN = 20 * MIB
GIT_FILE_FAIL = 40 * MIB

# 화면이 **자동으로** 받아 가는 조각. 페이지를 열면 무조건 따라오므로
# 대기 시간이 곧 이 한도다.
#
# **압축한 크기로 잰다.** 예전에는 파일 크기로 쟀는데, 호스팅이 전송할 때
# 알아서 압축하므로 그 값은 아무도 기다리지 않는 숫자였다. 배포된 사이트에
# 브라우저와 같은 조건으로 요청해 실측한 값이다 (2026-08-08).
#
#   Accept-Encoding: br        →   611,320 bytes  (0.58 MiB)  ← 실제 브라우저
#   Accept-Encoding: gzip      →   664,512 bytes  (0.63 MiB)
#   Accept-Encoding: identity  → 8,319,675 bytes  (7.93 MiB)  ← 예전에 재던 값
#
# 13.6배 차이다. 그래서 게이트가 20.34 MiB에서 막았지만 그 화면의 실제
# 대기는 1.84 MiB였다 (run 31232386844). 막을 이유가 없는 것을 막았다.
#
# gzip으로 재는 이유는 위 실측에서 brotli보다 8.7% 크게 나오기 때문이다 —
# 틀리더라도 안전한 쪽으로 틀린다.
#
# 한도는 성능 목표가 아니라 **다음 배가 전에 경고가 뜨는 여유**다.
# 실측 1.84 MiB(327,599행)에 약 1.6배와 3.3배를 곱했다.
SHARD_WARN = 3 * MIB
SHARD_FAIL = 6 * MIB

# 압축 수준. 서버가 실제로 쓰는 값이 6 근처이고, 재는 비용도 여기가 맞다.
# 같은 20.34 MiB 파일 실측:
#
#   level 1  2.38 MiB  0.12초
#   level 6  1.84 MiB  0.47초   ← 여기
#   level 9  1.71 MiB  2.86초
#
# 9를 쓰면 게이트가 3초 가까이 멈추면서 정작 판정은 더 후해진다.
SHARD_GZIP_LEVEL = 6

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
    """한 항목의 판정. `level`은 ok / warn / fail 셋 중 하나다.

    `basis`는 **무엇을 재서 그 판정이 나왔는가**이다. 화면 조각은 압축한
    크기로도 재므로 `size`와 다를 수 있다. 둘을 한 칸에 뭉개면
    «20.34 MiB > 6 MiB»처럼 단위가 어긋난 실패 문구가 나온다.

    `transfer`는 조각일 때만 채운다. 통과할 때도 표에 적어야 무엇이
    커지고 있는지 다음 사람이 읽는다.
    """

    level: str
    path: str
    size: int
    limit: int
    transfer: int | None = None
    basis: str = "파일"

    @property
    def failed(self) -> bool:
        return self.level == "fail"

    @property
    def value(self) -> int:
        """판정에 실제로 쓴 값."""
        return self.transfer if self.basis == "전송" else self.size


def is_shard(relative: str) -> bool:
    """화면이 자동으로 받아 가는 조각인가.

    같은 폴더에 있어도 사람이 눌러야 받아지는 파일은 조각이 아니다 —
    페이지를 여는 사람 전부가 아니라 받겠다고 누른 사람만 기다린다.

    >>> is_shard("site-public/data/table.json")
    True
    >>> is_shard("site-public/data/rates.csv")
    False
    >>> is_shard("latest/summary.json")
    False
    """
    if not relative.startswith(SHARD_PREFIX):
        return False
    stem = relative[len(SHARD_PREFIX) :].split(".", 1)[0]
    return stem not in DOWNLOAD_STEMS


def transferred_bytes(path: Path) -> int:
    """이 파일을 받는 사람이 실제로 기다리는 양.

    호스팅이 전송할 때 압축한다. 파일 크기를 그대로 대기 시간으로 읽으면
    실측 기준 13.6배를 틀린다 (위 SHARD_WARN 주석의 실측표).

    **이미 압축된 파일은 그대로 간다.** 호스팅이 `.gz`를 한 번 더 누르지
    않는다. 여기서 다시 눌러 재면 1.71 MiB짜리가 1.65 MiB로 나와, 실제로
    오가지 않는 숫자를 판정에 쓰게 된다.
    """
    if path.suffix == ".gz":
        return path.stat().st_size
    with path.open("rb") as handle:
        return len(gzip.compress(handle.read(), compresslevel=SHARD_GZIP_LEVEL))


def limits_for(relative: str, backend: str = "github_legacy") -> tuple[int, int]:
    """그 파일의 **압축 전** 크기에 적용할 (경고, 실패) 한도.

    조각도 여기서는 일반 Git 파일과 같은 한도를 쓴다. GitHub의 100 MB 벽은
    압축 전 크기로 걸리기 때문이다. 조각의 대기 시간 한도는 압축한 값에
    따로 적용한다 (`SHARD_WARN`/`SHARD_FAIL`).

    상태 DB의 예외는 `backend`가 `r2`가 되는 순간 사라진다. 그 모드에서는
    이 파일이 아예 없어야 하므로, 있으면 일반 한도로 걸려 실패한다 —
    예외가 스스로 사라지는 구조라야 잊히지 않는다.

    >>> limits_for(STATE_DB) == (STATE_DB_WARN, STATE_DB_FAIL)
    True
    >>> limits_for(STATE_DB, backend="r2") == (GIT_FILE_WARN, GIT_FILE_FAIL)
    True
    >>> limits_for("site-public/data/table.json") == (GIT_FILE_WARN, GIT_FILE_FAIL)
    True
    >>> limits_for("latest/summary.json") == (GIT_FILE_WARN, GIT_FILE_FAIL)
    True
    """
    if relative == STATE_DB and backend != "r2":
        return STATE_DB_WARN, STATE_DB_FAIL
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


# 나쁜 쪽이 이긴다. 두 잣대 중 하나만 걸려도 발행하지 않는다.
_RANK = {"ok": 0, "warn": 1, "fail": 2}


def inspect(root: Path, backend: str = "github_legacy") -> list[Finding]:
    """트리 전체를 재고 판정한다. 합계도 한 항목으로 넣는다.

    화면 조각은 **두 잣대**를 다 통과해야 한다. 압축 후는 사람의 대기이고
    압축 전은 GitHub의 벽이라, 하나로 합칠 수 있는 값이 아니다.
    """
    findings: list[Finding] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        size = path.stat().st_size
        total += size
        relative = path.relative_to(root).as_posix()

        warn, fail = limits_for(relative, backend)
        level, limit, basis = classify(size, warn, fail), fail, "파일"

        sent = transferred_bytes(path) if is_shard(relative) else None
        if sent is not None:
            sent_level = classify(sent, SHARD_WARN, SHARD_FAIL)
            if _RANK[sent_level] >= _RANK[level]:
                level, limit, basis = sent_level, SHARD_FAIL, "전송"

        findings.append(Finding(level, relative, size, limit, sent, basis))

    findings.sort(key=lambda f: -f.size)
    findings.append(
        Finding(classify(total, TOTAL_WARN, TOTAL_FAIL), "(전체)", total, TOTAL_FAIL)
    )
    return findings


def report(findings: list[Finding], backend: str = "github_legacy") -> int:
    """사람이 읽을 표를 찍고 종료코드를 돌려준다."""
    mark = {"ok": "    ", "warn": "경고", "fail": "실패"}
    shown = [f for f in findings if f.level != "ok" or f.size >= MIB]
    for f in shown:
        # 조각은 전송량을 함께 적는다. 파일 크기만 보면 «20 MiB짜리를
        # 매번 받는다»고 읽히는데, 실제로 기다리는 것은 압축된 쪽이다.
        sent = "" if f.transfer is None else f"  (전송 {f.transfer / MIB:.2f} MiB)"
        print(f"  [{mark[f.level]}] {f.size / MIB:9.2f} MiB  {f.path}{sent}")

    hidden = len(findings) - len(shown)
    if hidden:
        print(f"  ... 1 MiB 미만 {hidden}개 생략")

    failures = [f for f in findings if f.failed]
    if failures:
        print(f"\n  한도를 넘었다. 발행하지 않는다 ({len(failures)}건):")
        for f in failures:
            # 어느 잣대에 걸렸는지 적는다. 안 적으면 20.34 MiB짜리 파일이
            # «6 MiB 초과»로 걸린 것처럼 보여 숫자가 안 맞는다.
            print(
                f"    {f.path} — {f.basis} {f.value / MIB:.2f} MiB"
                f" > {f.limit / MIB:.0f} MiB"
            )
        return 1

    # 예외를 조용히 두지 않는다. 통과할 때마다 적어야 잊히지 않는다.
    state = next((f for f in findings if f.path == STATE_DB), None)
    if state is not None and backend != "r2":
        print(
            f"\n  ※ {STATE_DB}는 한시 예외다 ({state.size / MIB:.2f} MiB, "
            f"한도 {STATE_DB_FAIL / MIB:.0f} MiB).\n"
            "    지금 지우면 다음 실행이 빈 DB로 시작한다. R2로 옮긴 뒤"
            " 이 예외를 없앤다 (docs/roadmap.md §4.2.1)."
        )

    warned = [f for f in findings if f.level == "warn"]
    print(f"\n  통과 — 파일 {len(findings) - 1}개, 경고 {len(warned)}건")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="발행 전 파일 크기 검사")
    parser.add_argument("root", type=Path, help="검사할 트리 (발행 직전 스테이지)")
    parser.add_argument(
        "--backend", default="github_legacy",
        help="상태 저장소. r2면 상태 DB 예외가 사라진다 (그 모드에선 파일이 없어야 한다)",
    )
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"디렉터리가 아니다: {args.root}", file=sys.stderr)
        return 2
    print(f"파일 크기 검사 — {args.root}  (backend={args.backend})")
    return report(inspect(args.root, args.backend), args.backend)


if __name__ == "__main__":
    raise SystemExit(main())
