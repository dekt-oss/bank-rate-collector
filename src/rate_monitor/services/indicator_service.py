"""참고지표 수집·저장 (v4 §7).

금리 수집(`collection_service`)과 나란한 자리다. 다른 이유는 하나다 —
**지표는 금융상품이 아니다.** 기관·상품·가입기간이 없고, 비교표에 서지 않고,
옆에 놓고 보는 값이다.

그래서 저장 표가 다르고(`market_indicators`) 오케스트레이터도 다르다. 다만
실행 이력·원본 보존은 똑같이 남긴다 — 그 값이 언제 어디서 왔는지 못 대면
화면에 띄울 수 없다.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from rate_monitor.collectors.base import CollectorError, SourceBlockedError
from rate_monitor.db import models as m
from rate_monitor.db.session import session_scope
from rate_monitor.domain.enums import RunStatus
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.collection_service import (
    DEFAULT_RAW_ROOT,
    _utcnow,
    ensure_source,
    save_raw_artifacts,
)


@dataclass(frozen=True)
class IndicatorResult:
    run_id: str
    status: str
    fetched: int
    parsed: int
    stored: int
    unchanged: int
    warnings: int
    message: str


async def collect_indicator(
    adapter: Any,
    request: CollectionRequest,
    session_factory: Any,
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
) -> IndicatorResult:
    """지표 한 종류를 받아 저장한다.

    **값이 그대로면 행을 만들지 않는다** (§7.3). 기준금리는 몇 달씩 같으므로
    매일 한 줄씩 쌓으면 이력이 아니라 잡음이 된다. `UNIQUE` 제약이 마지막
    방어선이지만, 여기서 먼저 세어 `no_change`로 끝낸다 — 그래야 "받았는데
    안 바뀐 것"과 "못 받은 것"이 구별된다.
    """
    # 저장은 naive UTC다. 다른 수집원과 같은 자를 써야 `latest_run_ids`의
    # MAX(started_at) 비교가 성립하고, 화면의 KST 변환도 맞는다
    # (domain/timeutil). 로컬 시각을 넣으면 9시간 어긋난다.
    now = _utcnow()
    run_id = m.new_id()
    warnings: list[str] = []
    fetched = parsed = stored = unchanged = 0
    status = RunStatus.SUCCESS
    message = ""

    with session_scope(session_factory) as session:
        ensure_source(session, adapter, now)
        session.add(
            m.CollectionRun(
                id=run_id, source_id=adapter.source_id, mode=adapter.mode,
                started_at=now, status=RunStatus.RUNNING,
                query_context_json={"indicator": request.source_id},
            )
        )

    try:
        artifacts = await adapter.fetch(request)
    except SourceBlockedError as error:
        _finish(session_factory, run_id, RunStatus.BLOCKED, str(error), 0, 0, 0, 0)
        return IndicatorResult(run_id, RunStatus.BLOCKED, 0, 0, 0, 0, 0, str(error))
    except (CollectorError, Exception) as error:  # noqa: BLE001
        _finish(session_factory, run_id, RunStatus.FAILED, str(error), 0, 0, 0, 0)
        return IndicatorResult(run_id, RunStatus.FAILED, 0, 0, 0, 0, 0, str(error))

    fetched = len(artifacts)
    try:
        with session_scope(session_factory) as session:
            run = session.get(m.CollectionRun, run_id)
            records = save_raw_artifacts(session, run, artifacts, raw_root, now)
            for artifact, record in zip(artifacts, records, strict=True):
                points, notes = adapter.parse_points(artifact)
                warnings.extend(notes)
                parsed += len(points)
                for point in points:
                    if _upsert(session, point, adapter.source_id, record.id, now):
                        stored += 1
                    else:
                        unchanged += 1
    except Exception as error:  # noqa: BLE001 - 무엇이든 실행에 기록하고 끝낸다
        # **파싱·저장 실패도 실행을 끝내야 한다.**
        #
        # 2026-08-06 run 31101956888에서 실제로 걸렸다. ECOS가 오류 본문을
        # 200으로 줘서 `ParseError`가 났는데, 그때 이 구간이 try 밖이라
        # 예외가 그대로 올라갔다. 그 결과 `collection_runs` 행이 `running`
        # 상태로 영원히 남았다 — 그 원천이 "지금도 돌고 있다"로 보이고,
        # 다음 실행이 좀비 행을 하나씩 더 쌓는다.
        _finish(session_factory, run_id, RunStatus.FAILED, str(error),
                fetched, parsed, stored, len(warnings))
        return IndicatorResult(run_id, RunStatus.FAILED, fetched, parsed, stored,
                               unchanged, len(warnings), str(error))

    if parsed == 0:
        status, message = RunStatus.FAILED, "지표를 하나도 읽지 못했다"
    elif stored == 0:
        # 받았고 읽었는데 새 값이 없다. 실패가 아니다 (§7.3).
        status, message = RunStatus.NO_CHANGE, f"값이 그대로다 ({unchanged}개 시점)"
    else:
        message = f"새 시점 {stored}개, 그대로 {unchanged}개"

    _finish(session_factory, run_id, status, message, fetched, parsed, stored,
            len(warnings))
    return IndicatorResult(run_id, status, fetched, parsed, stored, unchanged,
                           len(warnings), message)


def _upsert(session, point, source_id: str, artifact_id: str, now: datetime) -> bool:
    """새 시점이면 저장하고 True. 이미 있으면 False.

    같은 날짜를 두 번 쌓지 않는다. 값이 바뀌었으면 그 날짜의 값을 고친다 —
    원천이 잠정치를 확정치로 바꾸는 경우가 있다.
    """
    existing = session.scalar(
        select(m.MarketIndicator).where(
            m.MarketIndicator.indicator_code == point.indicator_code,
            m.MarketIndicator.source_effective_at == point.source_effective_at,
            m.MarketIndicator.source_id == source_id,
        )
    )
    content_hash = "sha256:" + hashlib.sha256(
        f"{point.indicator_code}|{point.source_effective_at}|{point.value}".encode()
    ).hexdigest()

    if existing is not None:
        if existing.content_hash == content_hash:
            return False
        existing.value = point.value
        existing.content_hash = content_hash
        existing.observed_at = now
        existing.raw_artifact_id = artifact_id
        return True

    session.add(
        m.MarketIndicator(
            indicator_code=point.indicator_code,
            indicator_name=point.indicator_name,
            source_id=source_id,
            observed_at=now,
            source_effective_at=point.source_effective_at,
            value=point.value,
            unit=point.unit,
            raw_artifact_id=artifact_id,
            source_locator=point.source_locator,
            content_hash=content_hash,
        )
    )
    return True


def _finish(session_factory, run_id, status, message, fetched, parsed, stored,
            warnings) -> None:
    with session_scope(session_factory) as session:
        run = session.get(m.CollectionRun, run_id)
        run.status = status
        run.message = message[:500] if message else None
        run.finished_at = _utcnow()
        run.raw_count = fetched
        run.parsed_count = parsed
        run.valid_count = stored
        run.warning_count = warnings
