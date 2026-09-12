"""저장 전 source volume gate — 직전 정상 전국 실행 대비 급감(75%) 계약.

2026-09-09 04:01 KST 신협 실행은 550장/22,257행(직전 30,502행의 73%)으로 잘렸는데
절대 하한 7,500은 넘었으므로 success로 저장·발행됐다. 이제 같은 원천의 직전
정상 전국 실행과 견줘 75% 미만이면 FAILED로 끝내고, 이전 정상 관측은 화면에
그대로 남긴다.
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
from rate_monitor.services import source_volume_contract as contract
from rate_monitor.services.collection_service import collect_source
from rate_monitor.services.dashboard_service import _stale_sources, latest_run_ids

FIXTURES = Path(__file__).parent / "fixtures" / "cu"
DEPOSIT = "findInrst15_busan.json"
SAVINGS = "findInrst17_busan.json"


def _artifact(name: str, screen: str) -> RawArtifactData:
    return RawArtifactData(
        artifact_type="json",
        content=(FIXTURES / name).read_bytes(),
        filename=name,
        request_meta={"screen": screen, "sido": "04", "sido_name": "부산", "page_offset": 0},
        schema_fingerprint="cu-fixture-v1",
        source_role=SourceRole.PRIMARY_OFFICIAL,
        trust_level=TrustLevel.OFFICIAL_DIRECT,
    )


class VolumeAdapter(CuAdapter):
    def __init__(self, names: tuple[tuple[str, str], ...]) -> None:
        super().__init__()
        self._names = names

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [_artifact(name, screen) for name, screen in self._names]


FULL = ((DEPOSIT, "findInrst15"), (SAVINGS, "findInrst17"))
HALF = ((DEPOSIT, "findInrst15"),)


@pytest.fixture()
def db(tmp_path: Path):
    path = tmp_path / "cu.sqlite3"
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)
    return path, make_session_factory(engine)


@pytest.fixture(autouse=True)
def _small_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    # fixture는 100행뿐이다. 절대 하한이 아니라 급감 계약을 시험한다.
    monkeypatch.setitem(contract.POLICIES, "cu", contract.SourceVolumePolicy("cu", 10))
    monkeypatch.delenv(contract.ACCEPT_VOLUME_DROP_ENV, raising=False)


def _collect(factory, raw_root: Path, names, request: CollectionRequest | None = None):
    return asyncio.run(
        collect_source(
            VolumeAdapter(names),
            request or CollectionRequest(source_id="cu"),
            factory,
            raw_root=raw_root,
        )
    )


def _current_observations(factory) -> int:
    with session_scope(factory) as session:
        return session.scalar(
            select(func.count()).select_from(m.RateObservation)
            .where(m.RateObservation.valid_to.is_(None))
        )


def test_truncated_nationwide_run_fails_and_keeps_previous_observations(db, tmp_path):
    path, factory = db
    first = _collect(factory, tmp_path / "raw", FULL)
    assert first.status == RunStatus.SUCCESS
    assert first.parsed_count == 100

    second = _collect(factory, tmp_path / "raw", HALF)

    assert second.status == RunStatus.FAILED
    assert second.raw_count == 1
    assert second.parsed_count == 50
    assert contract.CODE_DROP in second.message
    assert "50.0%" in second.message
    assert "직전 정상 실행 100건" in second.message

    with session_scope(factory) as session:
        failed = session.get(m.CollectionRun, second.run_id)
        assert failed.status == RunStatus.FAILED
        assert failed.parsed_count == 50
        review = session.scalars(
            select(m.ReviewItem).where(m.ReviewItem.run_id == second.run_id)
        ).one()
        assert review.issue_type == "source_volume_drop"
        assert review.payload_json["previous_parsed"] == 100
        # 실패 실행은 관측을 하나도 쓰지 않는다.
        assert session.scalar(
            select(func.count()).select_from(m.RateObservation)
            .where(m.RateObservation.run_id == second.run_id)
        ) == 0
    # 이전 정상 관측 100건은 닫히지 않고 그대로 현재값이다.
    assert _current_observations(factory) == 100

    # 화면은 직전 정상 실행을 계속 보여주고, 실패 사실과 원인을 함께 낸다.
    conn = sqlite3.connect(path)
    try:
        assert latest_run_ids(conn) == [first.run_id]
        stale = _stale_sources(conn)
        assert [s["source_id"] for s in stale] == ["cu"]
        assert contract.CODE_DROP in stale[0]["message"]
    finally:
        conn.close()


def test_operator_acceptance_relaxes_only_the_drop_comparison(db, tmp_path, monkeypatch):
    _, factory = db
    assert _collect(factory, tmp_path / "raw", FULL).status == RunStatus.SUCCESS

    monkeypatch.setenv(contract.ACCEPT_VOLUME_DROP_ENV, "true")
    accepted = _collect(factory, tmp_path / "raw", HALF)
    assert accepted.status == RunStatus.SUCCESS
    assert accepted.parsed_count == 50

    # 승인해도 0건은 절대 성공이 아니다.
    empty = _collect(factory, tmp_path / "raw", ())
    assert empty.status == RunStatus.FAILED
    assert contract.CODE_EMPTY in empty.message


def test_scoped_run_is_never_the_baseline_for_a_nationwide_run(db, tmp_path):
    _, factory = db
    scoped = _collect(
        factory, tmp_path / "raw", FULL, CollectionRequest(source_id="cu", regions=("부산",))
    )
    assert scoped.status == RunStatus.SUCCESS

    nationwide = _collect(factory, tmp_path / "raw", HALF)

    # 부산만 돌린 100건과 전국 50건은 비교 대상이 아니다.
    assert nationwide.status == RunStatus.SUCCESS
    assert nationwide.parsed_count == 50


def test_failed_run_is_not_the_baseline_either(db, tmp_path):
    _, factory = db
    assert _collect(factory, tmp_path / "raw", FULL).status == RunStatus.SUCCESS
    assert _collect(factory, tmp_path / "raw", ()).status == RunStatus.FAILED

    # 기준선은 마지막 *정상* 전국 실행(100건)이다. 0건 실패 뒤 50건도 급감이다.
    third = _collect(factory, tmp_path / "raw", HALF)
    assert third.status == RunStatus.FAILED
    assert contract.CODE_DROP in third.message


def test_stored_query_context_scope_matches_request_scope():
    assert contract.is_full_scope_context("cu", {"regions": [], "options": {}})
    assert not contract.is_full_scope_context("cu", {"regions": ["부산"], "options": {}})
    assert contract.is_full_scope_context("kfcc", {"regions": [], "options": {"scope": "전국"}})
    assert not contract.is_full_scope_context(
        "kfcc", {"regions": ["부산"], "options": {"scope": "전국"}}
    )
    assert not contract.is_full_scope_context(
        "nh_local", {"regions": [], "options": {"scope": "부산"}}
    )
    assert contract.is_full_scope_context("nh_local", None)


def test_drop_decision_message_carries_the_numbers():
    decision = contract.evaluate_source_volume(
        "cu", CollectionRequest(source_id="cu"), 22_257, previous_parsed=30_502
    )
    assert decision is not None and not decision.ok
    assert decision.code == contract.CODE_DROP
    assert "22,257" in decision.message and "30,502" in decision.message
    assert "73.0%" in decision.message

    ok = contract.evaluate_source_volume(
        "cu", CollectionRequest(source_id="cu"), 30_482, previous_parsed=30_502
    )
    assert ok is not None and ok.ok and ok.code == contract.CODE_OK

    # 직전 실행이 아주 작으면 비율을 따지지 않는다.
    tiny = contract.evaluate_source_volume(
        "cu", CollectionRequest(source_id="cu"), 8_000, previous_parsed=50
    )
    assert tiny is not None and tiny.ok
