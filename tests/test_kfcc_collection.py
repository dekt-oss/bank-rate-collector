"""새마을금고 저장 경로 검증 — fixture로 전 구간을 관통한다.

어댑터의 fetch만 fixture로 대체하고 그 아래 파싱·정규화·엔터티 해석·저장은
실제 코드를 그대로 쓴다. 네트워크를 호출하지 않는다.
"""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.kfcc.adapter import KfccAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.enums import RateScope, RunStatus, Sector
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_source

FIXTURES = Path(__file__).parent / "fixtures" / "kfcc"

# tests/test_kfcc_parser.py가 고정한 실측값
EXPECTED_DEPOSIT_ROWS = 49
EXPECTED_SAVINGS_ROWS = 29
EXPECTED_TOTAL = EXPECTED_DEPOSIT_ROWS + EXPECTED_SAVINGS_ROWS

_OUTLET = {
    "gmgoCd": "1203",
    "gmgoNm": "대청",
    "name": "대청",
    "divCd": "001",
    "divNm": "본점",
    "gmgoType": "지역",
    "addr": "부산 중구 대청로 101-1",
    "r1": "부산",
    "r2": "중구",
    "telephone": "051-463-2166",
}


def _rate_artifact(group: str) -> RawArtifactData:
    path = FIXTURES / f"rate_1203_{group}.html"
    return RawArtifactData(
        artifact_type="html",
        content=path.read_bytes(),
        filename=path.name,
        request_meta={
            "kind": "rate",
            "gmgoCd": "1203",
            "gubuncode": group,
            "r1": "부산",
            "r2": "중구",
            "outlet": _OUTLET,
        },
        schema_fingerprint=f"fp-{group}",
        source_role=KfccAdapter.source_role,
        trust_level=KfccAdapter.trust_level,
    )


def _list_artifact() -> RawArtifactData:
    path = FIXTURES / "list_busan_junggu.html"
    return RawArtifactData(
        artifact_type="html",
        content=path.read_bytes(),
        filename=path.name,
        request_meta={"kind": "list", "r1": "부산", "r2": "중구"},
        schema_fingerprint="list",
        source_role=KfccAdapter.source_role,
        trust_level=KfccAdapter.trust_level,
    )


class FixtureAdapter(KfccAdapter):
    """fetch만 fixture로 대체한다. 파싱 이하는 실제 코드."""

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [_list_artifact(), _rate_artifact("13"), _rate_artifact("14")]


class BlockedAdapter(KfccAdapter):
    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        raise SourceBlockedError("400 Request Blocked")


@pytest.fixture
def factory(tmp_path: Path):
    engine = create_db_engine(tmp_path / "kfcc.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def run_collect(factory, raw_root: Path, adapter=None):
    return asyncio.run(
        collect_source(
            adapter or FixtureAdapter(),
            CollectionRequest(source_id="kfcc", regions=("중구",)),
            factory,
            raw_root=raw_root,
        )
    )


def _counts(session) -> dict[str, int]:
    return {
        name: session.scalar(select(func.count()).select_from(table))
        for name, table in (
            ("institutions", m.Institution),
            ("outlets", m.Outlet),
            ("products", m.Product),
            ("variants", m.ProductVariant),
            ("observations", m.RateObservation),
            ("runs", m.CollectionRun),
        )
    }


# ── 1차 수집 ────────────────────────────────────────────────────────────


def test_collect_stores_every_parsed_row(factory, tmp_path) -> None:
    result = run_collect(factory, tmp_path / "raw")
    assert result.status == RunStatus.SUCCESS
    assert result.parsed_count == EXPECTED_TOTAL
    assert result.error_count == 0

    with session_scope(factory) as session:
        counts = _counts(session)
        assert counts["observations"] == EXPECTED_TOTAL
        assert counts["runs"] == 1
        # 목록 아티팩트도 저장되지만 금리 행은 만들지 않는다.
        assert session.scalar(select(func.count()).select_from(m.RawArtifact)) == 3


def test_source_row_uses_kfcc_metadata(factory, tmp_path) -> None:
    """finlife 값이 새어 들어오면 안 된다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        source = session.get(m.Source, "kfcc")
        assert source.name == "새마을금고 금고위치안내"
        assert source.sector == Sector.KFCC
        # 약관 미확인이므로 allowed가 아니다.
        assert source.policy_status == "review"


def test_institution_key_is_not_polluted_by_a_guessed_sector(factory, tmp_path) -> None:
    """권역을 rate_scope로 추측하면 "bank:1203"이 된다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        link = session.scalars(
            select(m.SourceEntityLink).where(
                m.SourceEntityLink.entity_type == "institution"
            )
        ).one()
        assert link.source_entity_key == "kfcc:1203"

        institution = session.get(m.Institution, link.entity_id)
        assert institution.sector == Sector.KFCC
        assert institution.canonical_name == "대청"
        assert institution.address == "부산 중구 대청로 101-1"
        # 화면 파라미터를 행정구역 공식 코드로 쓰지 않는다.
        assert institution.sido_code is None
        assert institution.sigungu_code is None


def test_every_observation_is_traceable_to_its_source(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        rows = session.scalars(select(m.RateObservation)).all()
        assert len(rows) == EXPECTED_TOTAL
        assert all(r.raw_artifact_id is not None for r in rows)
        assert all(r.base_source_locator for r in rows)
        assert all(r.source_record_hash for r in rows)
        # 기준일이 페이지에 있으므로 전부 채워져야 한다.
        assert all(r.source_effective_at is not None for r in rows)


def test_max_rate_is_null_in_storage(factory, tmp_path) -> None:
    """공식 화면에 우대금리 열이 없다. base_rate로 메우면 안 된다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        filled = session.scalar(
            select(func.count())
            .select_from(m.RateObservation)
            .where(m.RateObservation.max_rate.is_not(None))
        )
        assert filled == 0


def test_rate_scope_is_institution_not_outlet(factory, tmp_path) -> None:
    """금리는 금고 단위 공시다. 점포별 적용금리가 아니다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        scopes = {v.rate_scope for v in session.scalars(select(m.ProductVariant)).all()}
        assert scopes == {RateScope.INSTITUTION}


# ── 구·군 집계 — 이 절단의 목적 ────────────────────────────────────────


def test_dashboard_aggregates_by_district(factory, tmp_path) -> None:
    """구별 보기가 실제로 나오는지. 이게 안 되면 이 절단의 의미가 없다."""
    from rate_monitor.services.dashboard_service import build_summary

    run_collect(factory, tmp_path / "raw")
    summary = build_summary(tmp_path / "kfcc.sqlite3")

    districts = summary["by_district"]
    assert len(districts) == 1
    assert districts[0]["sigungu"] == "중구"
    assert districts[0]["sector"] == Sector.KFCC
    assert districts[0]["institutions"] == 1
    assert districts[0]["observations"] == EXPECTED_TOTAL

    top = summary["district_top"]
    assert [t["sigungu"] for t in top] == ["중구"]
    assert top[0]["term_months"] == 12


def test_district_is_derived_from_the_address(factory, tmp_path) -> None:
    """주소가 없으면 구 집계에 나타나지 않는다.

    저축은행이 그 경우다. finlife는 주소를 주지 않으므로 구 단위로 말할 수
    없고, 조용히 '미상' 같은 칸에 몰아넣지도 않는다.
    """
    from rate_monitor.services.dashboard_service import build_summary

    class NoAddressAdapter(FixtureAdapter):
        def parse_with_warnings(self, artifact):
            rows, warnings = super().parse_with_warnings(artifact)
            return [
                __import__("dataclasses").replace(r, address=None) for r in rows
            ], warnings

    run_collect(factory, tmp_path / "raw", adapter=NoAddressAdapter())
    summary = build_summary(tmp_path / "kfcc.sqlite3")
    assert summary["by_district"] == []


# ── 재수집 ──────────────────────────────────────────────────────────────


def test_recollect_does_not_duplicate_canonical_entities(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        first = _counts(session)

    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        second = _counts(session)

    for key in ("institutions", "outlets", "products", "variants"):
        assert second[key] == first[key], key
    assert second["runs"] == first["runs"] + 1
    assert second["observations"] == first["observations"] * 2


# ── 실패 경로 ───────────────────────────────────────────────────────────


def test_blocked_writes_no_observations(factory, tmp_path) -> None:
    """차단은 우회하지 않고 상태만 남긴다 (v3 §0.2)."""
    result = run_collect(factory, tmp_path / "raw", adapter=BlockedAdapter())
    assert result.status == RunStatus.BLOCKED
    with session_scope(factory) as session:
        assert _counts(session)["observations"] == 0


# ── 어댑터 계약 ─────────────────────────────────────────────────────────


def test_list_artifact_produces_no_rate_rows() -> None:
    adapter = KfccAdapter()
    rows, warnings = adapter.parse_with_warnings(_list_artifact())
    assert rows == []
    assert warnings == []


def test_adapter_rejects_unknown_district(tmp_path) -> None:
    adapter = KfccAdapter()
    with pytest.raises(ValueError, match="config에 없는"):
        adapter._load_regions(CollectionRequest(source_id="kfcc", regions=("서울중구",)))


def test_adapter_defaults_to_all_busan_districts() -> None:
    adapter = KfccAdapter()
    sido, districts = adapter._load_regions(CollectionRequest(source_id="kfcc"))
    assert sido == "부산"
    assert len(districts) == 16
    assert "기장군" in districts
