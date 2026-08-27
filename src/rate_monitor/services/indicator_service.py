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
from rate_monitor.db.types import canonical_quantity_text, quantize_quantity
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
                id=run_id,
                source_id=adapter.source_id,
                mode=adapter.mode,
                started_at=now,
                status=RunStatus.RUNNING,
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
                for note in notes:
                    _record_warning(
                        session,
                        run_id=run_id,
                        source_id=adapter.source_id,
                        artifact_id=record.id,
                        message=note,
                        now=now,
                    )
                parsed += len(points)
                for point in points:
                    if _upsert(
                        session,
                        point,
                        adapter.source_id,
                        record.id,
                        run_id,
                        now,
                    ):
                        stored += 1
                    else:
                        unchanged += 1
    except Exception as error:  # noqa: BLE001 - 무엇이든 실행에 기록하고 끝낸다
        # 파싱·저장 실패도 실행을 끝낸다. 실패 artifact transaction은 rollback돼
        # 구조가 틀린 contract의 일부 point만 DB에 남지 않는다.
        _finish(
            session_factory,
            run_id,
            RunStatus.FAILED,
            str(error),
            fetched,
            parsed,
            stored,
            len(warnings),
        )
        return IndicatorResult(
            run_id,
            RunStatus.FAILED,
            fetched,
            parsed,
            stored,
            unchanged,
            len(warnings),
            str(error),
        )

    if parsed == 0:
        status, message = RunStatus.FAILED, "지표를 하나도 읽지 못했다"
    elif stored == 0:
        status, message = RunStatus.NO_CHANGE, f"값이 그대로다 ({unchanged}개 시점)"
    else:
        message = f"새 시점 {stored}개, 그대로 {unchanged}개"

    _finish(
        session_factory,
        run_id,
        status,
        message,
        fetched,
        parsed,
        stored,
        len(warnings),
    )
    return IndicatorResult(
        run_id, status, fetched, parsed, stored, unchanged, len(warnings), message
    )


def _content_hash(point: Any) -> tuple[object, str]:
    """DB bind와 같은 normalized Decimal로 hash를 만든다."""
    normalized = quantize_quantity(point.value)
    canonical = canonical_quantity_text(normalized)
    payload = (
        f"{point.indicator_code}|{point.source_effective_at}|"
        f"{canonical}|{point.unit}"
    ).encode()
    return normalized, "sha256:" + hashlib.sha256(payload).hexdigest()


def _record_warning(
    session: Any,
    *,
    run_id: str,
    source_id: str,
    artifact_id: str,
    message: str,
    now: datetime,
) -> None:
    no_data = "no_data" in message.lower()
    session.add(
        m.ReviewItem(
            run_id=run_id,
            entity_type="market_indicator",
            issue_type=("market_indicator_no_data" if no_data else "market_indicator_warning"),
            severity=("info" if no_data else "warning"),
            message=message,
            payload_json={
                "source_id": source_id,
                "raw_artifact_id": artifact_id,
                "message": message,
            },
            created_at=now,
        )
    )


def _upsert(
    session: Any,
    point: Any,
    source_id: str,
    artifact_id: str,
    run_id: str,
    now: datetime,
) -> bool:
    """새 시점/원천 revision이면 저장하고 True, 완전히 같으면 False.

    동일 자연키의 값이 바뀌면 canonical row를 최신 원천값으로 갱신하되, 갱신
    전후 값·원본·시각을 같은 transaction의 review_items에 남긴다.
    """
    existing = session.scalar(
        select(m.MarketIndicator).where(
            m.MarketIndicator.indicator_code == point.indicator_code,
            m.MarketIndicator.source_effective_at == point.source_effective_at,
            m.MarketIndicator.source_id == source_id,
        )
    )
    normalized, content_hash = _content_hash(point)

    if existing is not None:
        if existing.unit != point.unit:
            raise CollectorError(
                "market indicator unit drift: "
                f"{point.indicator_code} {existing.unit!r} -> {point.unit!r}"
            )
        if existing.content_hash == content_hash:
            return False

        old_value = canonical_quantity_text(existing.value)
        new_value = canonical_quantity_text(normalized)
        session.add(
            m.ReviewItem(
                run_id=run_id,
                entity_type="market_indicator",
                entity_id=existing.id,
                issue_type="market_indicator_revision",
                severity="info",
                message=(
                    f"{point.indicator_code} {point.source_effective_at} "
                    f"원천 revision {old_value} -> {new_value}"
                ),
                payload_json={
                    "indicator_code": point.indicator_code,
                    "source_effective_at": (
                        point.source_effective_at.isoformat()
                        if point.source_effective_at
                        else None
                    ),
                    "unit": point.unit,
                    "old_value": old_value,
                    "new_value": new_value,
                    "old_content_hash": existing.content_hash,
                    "new_content_hash": content_hash,
                    "old_raw_artifact_id": existing.raw_artifact_id,
                    "new_raw_artifact_id": artifact_id,
                    "old_observed_at": existing.observed_at.isoformat(),
                    "new_observed_at": now.isoformat(),
                    "old_source_locator": existing.source_locator,
                    "new_source_locator": point.source_locator,
                },
                created_at=now,
            )
        )
        existing.value = normalized
        existing.content_hash = content_hash
        existing.observed_at = now
        existing.raw_artifact_id = artifact_id
        existing.source_locator = point.source_locator
        return True

    session.add(
        m.MarketIndicator(
            indicator_code=point.indicator_code,
            indicator_name=point.indicator_name,
            source_id=source_id,
            observed_at=now,
            source_effective_at=point.source_effective_at,
            value=normalized,
            unit=point.unit,
            raw_artifact_id=artifact_id,
            source_locator=point.source_locator,
            content_hash=content_hash,
        )
    )
    return True


def _finish(
    session_factory: Any,
    run_id: str,
    status: str,
    message: str,
    fetched: int,
    parsed: int,
    stored: int,
    warnings: int,
) -> None:
    with session_scope(session_factory) as session:
        run = session.get(m.CollectionRun, run_id)
        run.status = status
        run.message = message[:500] if message else None
        run.finished_at = _utcnow()
        run.raw_count = fetched
        run.parsed_count = parsed
        run.valid_count = stored
        run.warning_count = warnings
