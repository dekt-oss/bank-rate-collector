"""R2 체크포인트 보관 기간 정리 (docs/ops/20261016-r2-storage-audit.md §4).

체크포인트는 NH·KFCC 수집이 중간에 끊겼을 때 **같은 수집일 안에서** 이어받기
위한 임시 저장이다 (`resumable_acquisition`). 이어받기는 같은 cycle date에서만
하므로, 지난 날짜의 체크포인트는 복구에 쓰이지 않는다. 그런데 지우는 단계가
없어서 2026-08-12부터 계속 쌓였다 (실측 13.4 GB, run 38909801780).

여기서는 수집일(cycle date) 폴더 단위로 지운다. 세션 상태(manifest)를 읽지
않고 날짜와 운영 포인터만 본다. 성공한 세션이 `complete` 상태로 남아 기존
`session_gc_eligible`로는 지워지지 않기 때문이다.

지우는 조건 (둘 다 맞아야 한다):

1. 수집일이 오늘(KST)보다 보관 기간 넘게 지났다.
2. 운영 DB 포인터(`state/current.json`)의 스냅샷이 그 수집일보다 **나중**에
   만들어졌다. 발행이 며칠째 멈춰 있으면 체크포인트가 유일한 수집 결과일 수
   있으므로, 그동안의 날짜는 지우지 않는다.

`checkpoints/v1/` 밖의 키는 어떤 경우에도 지우지 않는다. 포인터가 없거나 읽을
수 없으면 아무것도 지우지 않고 실패한다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Protocol

from rate_monitor.domain.timeutil import to_kst
from rate_monitor.services.resumable_acquisition import CHECKPOINT_PREFIX
from rate_monitor.services.storage_service import CURRENT_KEY, SnapshotRef, StorageError

CHECKPOINT_RETENTION_DAYS = 7
_ROOT = f"{CHECKPOINT_PREFIX}/"


class _Store(Protocol):
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def list_sizes(self, prefix: str = "") -> list[tuple[str, int]]: ...


def _cycle_of(key: str) -> tuple[str, date] | None:
    """`checkpoints/v1/<source>/<YYYY-MM-DD>/...` → (source, 날짜).

    >>> _cycle_of("checkpoints/v1/nh_local/2026-10-01/sessions/s/chunks/000001-a.tar.gz")
    ('nh_local', datetime.date(2026, 10, 1))
    >>> _cycle_of("checkpoints/v1/nh_local/not-a-date/active.json") is None
    True
    """
    parts = key[len(_ROOT):].split("/") if key.startswith(_ROOT) else []
    if len(parts) < 3:
        return None
    try:
        return parts[0], date.fromisoformat(parts[1])
    except ValueError:
        return None


def _canonical_date(store: _Store) -> date:
    if not store.exists(CURRENT_KEY):
        raise StorageError(f"{CURRENT_KEY}가 없다. 운영 DB 반영을 확인할 수 없어 지우지 않는다")
    ref = SnapshotRef.from_json(store.get(CURRENT_KEY))
    generated = to_kst(ref.generated_at)
    if generated is None:
        raise StorageError(f"{CURRENT_KEY}의 generated_at을 읽을 수 없다")
    return generated.date()


def cleanup_checkpoints(
    store: _Store,
    *,
    today_kst: date,
    retention_days: int = CHECKPOINT_RETENTION_DAYS,
    dry_run: bool = True,
) -> dict[str, Any]:
    """오래된 수집일 폴더를 고른다. `dry_run=False`일 때만 지운다."""
    if retention_days < 1:
        raise ValueError("retention_days는 1 이상이어야 한다")
    cutoff = today_kst - timedelta(days=retention_days)
    canonical = _canonical_date(store)

    groups: dict[tuple[str, date], dict[str, Any]] = defaultdict(
        lambda: {"keys": [], "bytes": 0}
    )
    kept_bytes = 0
    unparseable: list[str] = []
    for key, size in store.list_sizes(_ROOT):
        cycle = _cycle_of(key)
        if cycle is None:
            unparseable.append(key)
            continue
        if cycle[1] < cutoff:
            group = groups[cycle]
            group["keys"].append(key)
            group["bytes"] += size
        else:
            kept_bytes += size

    candidates: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for (source, cycle_date), group in sorted(groups.items()):
        row = {
            "source": source,
            "cycle_date": cycle_date.isoformat(),
            "objects": len(group["keys"]),
            "bytes": group["bytes"],
        }
        # 운영 DB가 그 수집일 뒤에 갱신된 적이 없으면 체크포인트가 유일한 결과일 수 있다.
        (candidates if cycle_date < canonical else held).append(row)

    deleted_objects = 0
    if not dry_run:
        for row in candidates:
            for key in groups[(row["source"], date.fromisoformat(row["cycle_date"]))]["keys"]:
                if not key.startswith(_ROOT):  # pragma: no cover - list prefix가 보장한다
                    raise StorageError(f"checkpoint 밖의 키 삭제 시도: {key}")
                store.delete(key)
                deleted_objects += 1

    return {
        "today_kst": today_kst.isoformat(),
        "retention_days": retention_days,
        "cutoff_kst": cutoff.isoformat(),
        "canonical_snapshot_date_kst": canonical.isoformat(),
        "dry_run": dry_run,
        "candidate_cycles": candidates,
        "candidate_objects": sum(r["objects"] for r in candidates),
        "candidate_bytes": sum(r["bytes"] for r in candidates),
        "held_uncommitted_cycles": held,
        "kept_recent_bytes": kept_bytes,
        "deleted_objects": deleted_objects,
        "skipped_unparseable": unparseable,
    }
