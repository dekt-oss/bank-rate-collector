"""저축은행중앙회 저장 경로 검증 — fixture로 전 구간을 관통한다.

어댑터의 fetch만 fixture로 대체하고 그 아래 파싱·정규화·엔터티 해석·저장은
실제 코드를 그대로 쓴다. 네트워크를 호출하지 않는다.
"""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from rate_monitor.collectors.fsb.adapter import FsbAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.special_offer_models import ProductSpecialOfferEvidence
from rate_monitor.domain.enums import RateScope, RunStatus, Sector
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_source

FIXTURES = Path(__file__).parent / "fixtures" / "fsb"


def _artifact(name: str, meta: dict) -> RawArtifactData:
    return RawArtifactData(
        artifact_type="json",
        content=(FIXTURES / name).read_bytes(),
        filename=name,
        request_meta=meta,
        schema_fingerprint=f"fp-{name}",
        source_role=FsbAdapter.source_role,
        trust_level=FsbAdapter.trust_level,
    )


class FixtureAdapter(FsbAdapter):
    """fetch만 fixture로 대체한다. 파싱 이하는 실제 코드.

    명부 아티팩트를 먼저 둔다. 실제 fetch도 같은 순서다 — 주소를 붙이려면
    금리 행보다 명부가 먼저 읽혀야 한다.
    """

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [
            _artifact("sabfindquic_0100.json", {"kind": "branches", "area": "03"}),
            _artifact(
                "ratedepo_0100_01.json",
                {"kind": "rate", "screen": "ratedepo", "area": "YN_Busan",
                 "query_date": "2026-08-05", "page_offset": 0, "only_terms": []},
            ),
            _artifact(
                "rateinst_0100_01.json",
                {"kind": "rate", "screen": "rateinst", "area": "YN_Busan",
                 "query_date": "2026-08-05", "page_offset": 0, "only_terms": []},
            ),
        ]


@pytest.fixture
def factory(tmp_path: Path):
    engine = create_db_engine(tmp_path / "fsb.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def run_collect(factory, raw_root: Path, adapter=None):
    return asyncio.run(
        collect_source(
            adapter or FixtureAdapter(),
            CollectionRequest(source_id="fsb"),
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


def test_collect_stores_rows_from_both_screens(factory, tmp_path) -> None:
    result = run_collect(factory, tmp_path / "raw")
    assert result.status == RunStatus.SUCCESS
    assert result.parsed_count > 0
    assert result.error_count == 0

    with session_scope(factory) as session:
        products = session.scalars(select(m.Product)).all()
        types = {p.product_type for p in products}
        assert types == {"term_deposit", "installment_savings"}
        evidence = session.scalars(select(ProductSpecialOfferEvidence)).all()
        assert len(evidence) == len(products)
        assert {row.classification for row in evidence} == {"unknown"}
        assert {row.snapshot_as_of.isoformat() for row in evidence} == {"2026-08-05"}
        assert all(row.raw_artifact_id for row in evidence)
        assert all(product.is_special_sale is False for product in products)


def test_source_row_uses_fsb_metadata(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        source = session.get(m.Source, "fsb")
        assert source.name == "저축은행중앙회 소비자포털"
        assert source.sector == Sector.SAVINGS_BANK
        # 사이트 이용약관 자체가 없어 확인하지 못했다. allowed가 아니다.
        assert source.policy_status == "unknown"


def test_rate_scope_is_head_office_reference(factory, tmp_path) -> None:
    """저축은행 금리는 본점 기준이다. 지점 금리로 저장되면 안 된다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        scopes = {v.rate_scope for v in session.scalars(select(m.ProductVariant)).all()}
        assert scopes == {RateScope.HEAD_OFFICE_REFERENCE}


def test_head_office_address_reaches_the_institution(factory, tmp_path) -> None:
    """금리 화면에 소재지가 없다. 저축은행 찾기 화면 값이 실제로 붙는지."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        with_address = [
            i for i in session.scalars(select(m.Institution)).all() if i.address
        ]
        assert with_address, "본점 주소가 하나도 안 붙었다"
        bnk = next(i for i in with_address if i.canonical_name == "BNK")
        assert bnk.address.startswith("부산광역시 동구")
        # 화면 파라미터를 행정구역 공식 코드로 쓰지 않는다.
        assert bnk.sido_code is None and bnk.sigungu_code is None


def test_branch_outlets_are_stored(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        outlets = session.scalars(select(m.Outlet)).all()
        assert outlets
        assert any(o.name == "본점" for o in outlets)


def test_every_observation_is_traceable(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        rows = session.scalars(select(m.RateObservation)).all()
        assert rows
        assert all(r.raw_artifact_id is not None for r in rows)
        assert all(r.base_source_locator for r in rows)
        assert all(r.source_record_hash for r in rows)
        assert all(r.source_effective_at is not None for r in rows)


def test_no_duplicate_observations_within_one_run(factory, tmp_path) -> None:
    """같은 비교단위를 한 실행에서 두 번 저장하면 게이트가 깨진다.

    기간마다 요청을 나누던 설계에서 실제로 났던 문제다 — 한 행이 모든
    기간을 갖고 있어서 6번 요청하면 같은 관측이 6번 쌓였다.
    """
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        dupes = session.execute(
            select(m.RateObservation.run_id, m.RateObservation.variant_id, func.count())
            .group_by(m.RateObservation.run_id, m.RateObservation.variant_id)
            .having(func.count() > 1)
        ).all()
        assert dupes == []


def test_contact_details_are_not_stored(factory, tmp_path) -> None:
    """`OWNER`에 담당 부서명과 전화번호가 들어온다. 저장하지 않는다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        rows = session.scalars(select(m.RateObservation)).all()
        blob = json.dumps(
            [r.source_detail_json for r in rows], ensure_ascii=False
        )
        assert "경영기획부" not in blob
        # 검사가 성립하는지 — 원본에는 실제로 들어 있다.
        assert "경영기획부" in (FIXTURES / "ratedepo_0100_01.json").read_text(
            encoding="utf-8"
        )


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
    # 값이 그대로이므로 관측이 늘지 않는다 (선행 수정안 §3.2). 예전에는
    # 실행마다 두 배가 됐고, 그대로 두면 1년에 약 19 GB가 된다.
    assert second["observations"] == first["observations"]


# ── 어댑터 계약 ─────────────────────────────────────────────────────────


def test_branch_artifact_produces_no_rate_rows() -> None:
    adapter = FsbAdapter()
    rows, warnings = adapter.parse_with_warnings(
        _artifact("sabfindquic_0100.json", {"kind": "branches", "area": "03"})
    )
    assert rows == []
    assert warnings == []
    # 명부는 어댑터에 남아 뒤이은 금리 행에 주소를 붙인다.
    assert "BNK" in adapter._directory


def test_rate_rows_get_no_address_without_the_directory() -> None:
    """명부를 먼저 읽지 않으면 주소가 없다. 조용히 지어내지 않는다."""
    adapter = FsbAdapter()
    rows, _ = adapter.parse_with_warnings(
        _artifact(
            "ratedepo_0100_01.json",
            {"kind": "rate", "screen": "ratedepo", "area": "", "page_offset": 0},
        )
    )
    assert rows
    assert all(r.address is None for r in rows)
