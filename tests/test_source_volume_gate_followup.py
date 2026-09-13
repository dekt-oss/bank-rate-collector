"""저장 전 volume gate의 운영 안전장치 두 가지.

1. preflight 파싱 캐시는 메모리 상한이 있다. 실측 행당 2,601 bytes이므로 농·축협
   전국 310,157행을 그대로 들고 있으면 약 769 MB다. 상한을 넘으면 캐시를 버리고
   저장 단계가 다시 파싱한다 — 건수 판정과 저장 결과는 캐시와 무관해야 한다.
2. 어댑터가 응답 되풀이를 봤으면 물량 실패 경로에서도 그 검수항목을 남긴다.
   이 경로는 `_process`를 건너뛰므로, 안 남기면 물량 판정이 되풀이 진단을 덮어
   `REPEATED_RESPONSE`가 상태 화면에서 사라진다.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import func, select

from rate_monitor.collectors.cu.adapter import CuAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.enums import RunStatus, SourceRole, TrustLevel
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services import collection_service as cs
from rate_monitor.services import source_volume_contract as contract
from rate_monitor.services.collection_service import collect_source
from rate_monitor.services.source_health_service import build_collection_health

FIXTURES = Path(__file__).parent / "fixtures" / "cu"
ROWS_PER_ARTIFACT = 50


def _artifact(index: int) -> RawArtifactData:
    # 바이트가 서로 달라야 원본 행이 합쳐지지 않는다. JSON 뒤 공백은 파싱에 영향이 없다.
    return RawArtifactData(
        artifact_type="json",
        content=(FIXTURES / "findInrst15_busan.json").read_bytes() + b" " * index,
        filename=f"findInrst15_{index}.json",
        request_meta={
            "screen": "findInrst15",
            "sido": "04",
            "sido_name": "부산",
            "page_offset": index * ROWS_PER_ARTIFACT,
        },
        schema_fingerprint="cu-fixture-v1",
        source_role=SourceRole.PRIMARY_OFFICIAL,
        trust_level=TrustLevel.OFFICIAL_DIRECT,
    )


class CountingAdapter(CuAdapter):
    """원본 장수를 정하고 파싱 횟수를 세는 신협 어댑터."""

    def __init__(self, artifact_count: int) -> None:
        super().__init__()
        self._artifact_count = artifact_count
        self.parse_calls = 0
        self.fetch_note = f"응답 {artifact_count}장"

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [_artifact(i) for i in range(self._artifact_count)]

    def parse_with_warnings(self, artifact: RawArtifactData):  # noqa: ANN201
        self.parse_calls += 1
        return super().parse_with_warnings(artifact)


@pytest.fixture()
def db(tmp_path: Path):
    path = tmp_path / "gate.sqlite3"
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)
    return path, make_session_factory(engine)


def _collect(adapter, factory, raw_root: Path):
    return asyncio.run(
        collect_source(
            adapter,
            CollectionRequest(source_id="cu"),
            factory,
            raw_root=raw_root,
        )
    )


def test_small_source_parses_once_and_reuses_the_cache(db, tmp_path, monkeypatch):
    _, factory = db
    monkeypatch.setattr(cs, "PARSED_CACHE_MAX_ROWS", 500)
    monkeypatch.setitem(contract.POLICIES, "cu", contract.SourceVolumePolicy("cu", 10))
    adapter = CountingAdapter(artifact_count=2)  # 100행

    result = _collect(adapter, factory, tmp_path / "raw")

    assert result.status == RunStatus.SUCCESS
    assert result.parsed_count == 100
    # 원본 2장을 딱 한 번씩만 파싱했다.
    assert adapter.parse_calls == 2
    with session_scope(factory) as session:
        # 두 장이 같은 상품 50개를 담은 fixture라 관측은 50건으로 합쳐진다.
        assert session.scalar(select(func.count()).select_from(m.RateObservation)) == 50


def test_large_source_drops_the_cache_and_still_stores_every_row(db, tmp_path, monkeypatch):
    _, factory = db
    monkeypatch.setattr(cs, "PARSED_CACHE_MAX_ROWS", 50)
    monkeypatch.setitem(contract.POLICIES, "cu", contract.SourceVolumePolicy("cu", 10))
    adapter = CountingAdapter(artifact_count=2)  # 100행 > 상한 50

    result = _collect(adapter, factory, tmp_path / "raw")

    # 캐시를 버려도 판정과 저장 결과는 같다. 파싱만 두 번 한다.
    assert result.status == RunStatus.SUCCESS
    assert result.parsed_count == 100
    assert adapter.parse_calls == 4
    with session_scope(factory) as session:
        # 캐시를 쓴 실행과 같은 결과다 (위 시험의 50건).
        assert session.scalar(select(func.count()).select_from(m.RateObservation)) == 50


def test_cache_cap_is_grounded_in_the_measured_row_size():
    # 실측 2,601 bytes/행 (2026-09-13, CU fixture 10,000행 tracemalloc).
    # 상한이 농·축협 전국(310,157행)을 통과시키면 약 769 MB를 들게 된다.
    assert cs.PARSED_CACHE_MAX_ROWS < 310_157
    # 신협 전국(약 30,500행)은 캐시 이득을 그대로 받아야 한다.
    assert cs.PARSED_CACHE_MAX_ROWS > 30_500
    assert cs.PARSED_CACHE_MAX_ROWS * 2_601 < 200 * 1024 * 1024


def test_repeated_response_alert_survives_a_volume_failure(db, tmp_path, monkeypatch):
    path, factory = db
    # 100행을 받지만 하한이 200이라 물량 실패로 끝난다.
    monkeypatch.setitem(contract.POLICIES, "cu", contract.SourceVolumePolicy("cu", 200))
    monkeypatch.delenv(contract.ACCEPT_VOLUME_DROP_ENV, raising=False)

    adapter = CountingAdapter(artifact_count=2)
    adapter.fetch_alert = "같은 응답이 41장 연속으로 왔다"
    adapter.fetch_note = "응답 2장 · 되풀이 1장 · 최장 연속 41"

    result = _collect(adapter, factory, tmp_path / "raw")

    assert result.status == RunStatus.FAILED
    assert contract.CODE_BELOW_MINIMUM in result.message
    # 물량 판정과 되풀이 요약이 같은 메시지에 함께 남는다.
    assert "최장 연속 41" in result.message

    with session_scope(factory) as session:
        issues = {
            item.issue_type: item for item in session.scalars(select(m.ReviewItem)).all()
        }
        assert issues.keys() == {"repeated_response", "source_volume_below_minimum"}
        assert issues["repeated_response"].severity == "error"
        assert issues["repeated_response"].message == "같은 응답이 41장 연속으로 왔다"
        assert issues["repeated_response"].payload_json["source_id"] == "cu"
        # 실패 실행은 관측을 하나도 쓰지 않는다.
        assert session.scalar(select(func.count()).select_from(m.RateObservation)) == 0

    # 상태 화면이 되풀이 신호와 물량 원인을 함께 읽는다.
    conn = sqlite3.connect(path)
    try:
        health = build_collection_health(conn)
    finally:
        conn.close()
    card = next(c for c in health["sources"] if c["source_id"] == "cu")
    assert card["signal"] == "red"
    assert "REPEATED_RESPONSE" in {r["code"] for r in card["reasons"]}
    assert contract.CODE_BELOW_MINIMUM in (card["failure_message"] or "")


def test_no_alert_means_no_repeated_response_item(db, tmp_path, monkeypatch):
    _, factory = db
    monkeypatch.setitem(contract.POLICIES, "cu", contract.SourceVolumePolicy("cu", 200))
    adapter = CountingAdapter(artifact_count=2)

    result = _collect(adapter, factory, tmp_path / "raw")

    assert result.status == RunStatus.FAILED
    with session_scope(factory) as session:
        types = {item.issue_type for item in session.scalars(select(m.ReviewItem)).all()}
        assert types == {"source_volume_below_minimum"}
