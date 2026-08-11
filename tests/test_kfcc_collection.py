"""새마을금고 collector의 저장·변경감지·중복안전 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from rate_monitor.collectors.kfcc.adapter import KfccAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.enums import CollectionMode, ProductType, RunStatus, Sector
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_once

FIXTURE_DIR = Path(__file__).parent / "fixtures/kfcc"

LIST_HTML = (FIXTURE_DIR / "list.html").read_text(encoding="utf-8")
RATE_13_HTML = (FIXTURE_DIR / "rate_13.html").read_text(encoding="utf-8")
RATE_14_HTML = (FIXTURE_DIR / "rate_14.html").read_text(encoding="utf-8")

# fixture는 목록 2점포/1금고, 정기예탁금 2행, 적립식 2행이다.
EXPECTED_TOTAL = 4


class FixtureKfccAdapter(KfccAdapter):
    """네트워크 없이 실제 KfccAdapter parser/storage 경로를 태운다."""

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [
            self._artifact(
                LIST_HTML.encode(),
                filename="list_부산.html",
                meta={"kind": "list", "r1": "부산", "r2": ""},
            ),
            self._artifact(
                RATE_13_HTML.encode(),
                filename="rate_1203_13.html",
                meta={
                    "kind": "rate",
                    "gmgoCd": "1203",
                    "gubuncode": "13",
                    "r1": "부산",
                    "r2": "해운대구",
                    "outlet": {
                        "gmgoCd": "1203",
                        "gmgoNm": "대청",
                        "divCd": "120301",
                        "divNm": "해운대",
                        "addr": "부산광역시 해운대구 우동 1",
                        "r1": "부산",
                        "r2": "해운대구",
                    },
                    "outlet_directory": [
                        {
                            "gmgoCd": "1203",
                            "gmgoNm": "대청",
                            "divCd": "120301",
                            "divNm": "해운대",
                            "addr": "부산광역시 해운대구 우동 1",
                            "r1": "부산",
                            "r2": "해운대구",
                        },
                        {
                            "gmgoCd": "1203",
                            "gmgoNm": "대청",
                            "divCd": "120302",
                            "divNm": "수영",
                            "addr": "부산광역시 수영구 광안동 2",
                            "r1": "부산",
                            "r2": "수영구",
                        },
                    ],
                },
            ),
            self._artifact(
                RATE_14_HTML.encode(),
                filename="rate_1203_14.html",
                meta={
                    "kind": "rate",
                    "gmgoCd": "1203",
                    "gubuncode": "14",
                    "r1": "부산",
                    "r2": "해운대구",
                    "outlet": {
                        "gmgoCd": "1203",
                        "gmgoNm": "대청",
                        "divCd": "120301",
                        "divNm": "해운대",
                        "addr": "부산광역시 해운대구 우동 1",
                        "r1": "부산",
                        "r2": "해운대구",
                    },
                    "outlet_directory": [
                        {
                            "gmgoCd": "1203",
                            "gmgoNm": "대청",
                            "divCd": "120301",
                            "divNm": "해운대",
                            "addr": "부산광역시 해운대구 우동 1",
                            "r1": "부산",
                            "r2": "해운대구",
                        },
                        {
                            "gmgoCd": "1203",
                            "gmgoNm": "대청",
                            "divCd": "120302",
                            "divNm": "수영",
                            "addr": "부산광역시 수영구 광안동 2",
                            "r1": "부산",
                            "r2": "수영구",
                        },
                    ],
                },
            ),
        ]


@pytest.fixture
def factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_db_engine(tmp_path / "kfcc.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def request() -> CollectionRequest:
    return CollectionRequest(
        source_id="kfcc",
        mode=CollectionMode.HTTP,
        requested_by="test",
        regions=["부산"],
        options={"groups": ["13", "14"]},
    )


def run_collect(factory, raw_dir: Path):
    return collect_once(
        FixtureKfccAdapter(), request(), factory, raw_dir=raw_dir
    )


def _counts(session: Session) -> dict[str, int]:
    return {
        "institutions": session.scalar(select(func.count()).select_from(m.Institution)),
        "outlets": session.scalar(select(func.count()).select_from(m.Outlet)),
        "products": session.scalar(select(func.count()).select_from(m.Product)),
        "variants": session.scalar(select(func.count()).select_from(m.ProductVariant)),
        "observations": session.scalar(select(func.count()).select_from(m.RateObservation)),
        "runs": session.scalar(select(func.count()).select_from(m.CollectionRun)),
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
    """finlife 값이나 기술 경로명이 사용자 표시명으로 새어 들어오면 안 된다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        source = session.get(m.Source, "kfcc")
        assert source.name == "새마을금고 예·적금 금리"
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


# ── 동일 재수집 ────────────────────────────────────────────────────────


def test_same_data_second_run_is_no_change(factory, tmp_path) -> None:
    first = run_collect(factory, tmp_path / "raw1")
    second = run_collect(factory, tmp_path / "raw2")
    assert first.status == RunStatus.SUCCESS
    assert second.status == RunStatus.NO_CHANGE
    assert second.parsed_count == EXPECTED_TOTAL

    with session_scope(factory) as session:
        counts = _counts(session)
        # 동일 데이터는 history observation을 늘리지 않는다.
        assert counts["observations"] == EXPECTED_TOTAL
        assert counts["runs"] == 2


def test_same_data_keeps_variant_identity(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw1")
    with session_scope(factory) as session:
        before = {
            row.id: row.variant_key
            for row in session.scalars(select(m.ProductVariant)).all()
        }

    run_collect(factory, tmp_path / "raw2")
    with session_scope(factory) as session:
        after = {
            row.id: row.variant_key
            for row in session.scalars(select(m.ProductVariant)).all()
        }

    assert before == after


# ── 변경 수집 ──────────────────────────────────────────────────────────


def test_changed_rate_creates_one_new_observation(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw1")

    class ChangedAdapter(FixtureKfccAdapter):
        async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
            artifacts = await super().fetch(request)
            changed = RATE_13_HTML.replace("3.10", "3.11", 1)
            artifacts[1] = self._artifact(
                changed.encode(),
                filename="rate_1203_13.html",
                meta=artifacts[1].request_meta,
            )
            return artifacts

    result = collect_once(
        ChangedAdapter(), request(), factory, raw_dir=tmp_path / "raw2"
    )
    assert result.status == RunStatus.SUCCESS

    with session_scope(factory) as session:
        counts = _counts(session)
        assert counts["observations"] == EXPECTED_TOTAL + 1


def test_changed_rate_keeps_product_and_variant_counts(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw1")
    with session_scope(factory) as session:
        before = _counts(session)

    class ChangedAdapter(FixtureKfccAdapter):
        async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
            artifacts = await super().fetch(request)
            changed = RATE_14_HTML.replace("3.20", "3.21", 1)
            artifacts[2] = self._artifact(
                changed.encode(),
                filename="rate_1203_14.html",
                meta=artifacts[2].request_meta,
            )
            return artifacts

    collect_once(ChangedAdapter(), request(), factory, raw_dir=tmp_path / "raw2")
    with session_scope(factory) as session:
        after = _counts(session)

    assert after["institutions"] == before["institutions"]
    assert after["outlets"] == before["outlets"]
    assert after["products"] == before["products"]
    assert after["variants"] == before["variants"]


# ── 점포/지역 ──────────────────────────────────────────────────────────


def test_one_institution_can_have_multiple_outlets(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        institution = session.scalars(select(m.Institution)).one()
        outlets = session.scalars(select(m.Outlet)).all()
        assert institution.canonical_name == "대청"
        assert {outlet.region_sigungu for outlet in outlets} == {"해운대구", "수영구"}


def test_outlet_addresses_are_preserved(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        addresses = {
            outlet.address for outlet in session.scalars(select(m.Outlet)).all()
        }
        assert addresses == {
            "부산광역시 해운대구 우동 1",
            "부산광역시 수영구 광안동 2",
        }


# ── raw/provenance ─────────────────────────────────────────────────────


def test_raw_artifacts_keep_request_context(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        raws = session.scalars(select(m.RawArtifact).order_by(m.RawArtifact.filename)).all()
        metas = [json.loads(raw.request_meta_json) for raw in raws]
        assert any(meta.get("kind") == "list" for meta in metas)
        assert any(meta.get("gubuncode") == "13" for meta in metas)
        assert any(meta.get("gubuncode") == "14" for meta in metas)


def test_rate_raw_keeps_outlet_directory(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        raws = session.scalars(
            select(m.RawArtifact).where(m.RawArtifact.filename.like("rate_%"))
        ).all()
        assert raws
        for raw in raws:
            meta = json.loads(raw.request_meta_json)
            assert {row["divCd"] for row in meta["outlet_directory"]} == {
                "120301",
                "120302",
            }


# ── product type ───────────────────────────────────────────────────────


def test_kfcc_product_types_are_preserved(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        types = {product.product_type for product in session.scalars(select(m.Product)).all()}
        assert types == {ProductType.TERM_DEPOSIT, ProductType.INSTALLMENT_SAVINGS}
