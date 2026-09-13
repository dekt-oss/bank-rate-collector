import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.enums import RunStatus
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_source


class GuardedAdapter:
    source_name = "guarded test source"
    sector = "mutual_finance"
    mode = "web"
    source_role = "primary_official"
    trust_level = "official_direct"
    priority = 10
    base_reference = "https://example.invalid"
    policy_status = "allowed"
    coverage_status = "active"

    def __init__(self, source_id: str, parsed_count: int) -> None:
        self.source_id = source_id
        self._parsed_count = parsed_count

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [
            RawArtifactData(
                artifact_type="json",
                content=b"[]",
                filename=f"{self.source_id}.json",
                request_meta={"scope": request.options.get("scope", "전국")},
                schema_fingerprint="guarded-test-v1",
                source_role=self.source_role,
                trust_level=self.trust_level,
            )
        ]

    def parse_with_warnings(self, artifact: RawArtifactData):  # noqa: ANN201
        # Runtime gate only needs aggregate count. A below-floor result must never
        # reach persist_rows, so deliberately opaque sentinels make that invariant
        # visible: if persistence is attempted this test fails loudly.
        return [object() for _ in range(self._parsed_count)], []


@pytest.fixture()
def factory(tmp_path):
    engine = create_db_engine(tmp_path / "guarded.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture()
def raw_root(tmp_path) -> Path:
    return tmp_path / "raw"


def _collect(factory, raw_root, source_id: str, parsed_count: int):
    return asyncio.run(
        collect_source(
            GuardedAdapter(source_id, parsed_count),
            CollectionRequest(source_id=source_id),
            factory,
            raw_root=raw_root,
        )
    )


def test_cu_empty_result_fails_before_canonical_persistence(factory, raw_root) -> None:
    result = _collect(factory, raw_root, "cu", 0)

    assert result.status == RunStatus.FAILED
    assert result.raw_count == 1
    assert result.parsed_count == 0
    assert result.error_count == 1
    assert "SOURCE_EMPTY_RESULT" in result.message

    with factory() as session:
        run = session.scalars(select(m.CollectionRun)).one()
        assert run.status == RunStatus.FAILED
        assert run.raw_count == 1
        assert run.parsed_count == 0
        assert run.valid_count == 0
        assert run.error_count == 1
        assert "SOURCE_EMPTY_RESULT" in (run.message or "")

        assert session.scalar(select(func.count()).select_from(m.RawArtifact)) == 1
        assert session.scalar(select(func.count()).select_from(m.RateObservation)) == 0
        review = session.scalars(select(m.ReviewItem)).one()
        assert review.issue_type == "source_empty_result"
        assert review.severity == "error"
        assert review.payload_json["minimum"] == 7_500
        stat = session.scalars(select(m.CollectionRunStat)).one()
        assert stat.parsed_count == 0
        assert stat.error_count == 1

    assert len(list(raw_root.rglob("*.json"))) == 1


def test_nh_truncated_result_fails_before_canonical_persistence(factory, raw_root) -> None:
    result = _collect(factory, raw_root, "nh_local", 999)

    assert result.status == RunStatus.FAILED
    assert result.parsed_count == 999
    assert "SOURCE_VOLUME_BELOW_MINIMUM" in result.message

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.RateObservation)) == 0
        review = session.scalars(select(m.ReviewItem)).one()
        assert review.issue_type == "source_volume_below_minimum"
        assert review.payload_json["parsed_count"] == 999
        assert review.payload_json["minimum"] == 1_000
