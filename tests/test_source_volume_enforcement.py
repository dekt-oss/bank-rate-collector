"""Canonical source-volume floors must fail closed before observations commit."""

import asyncio
from pathlib import Path

from sqlalchemy import func, select

from rate_monitor.collectors.finlife.adapter import FinlifeAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.enums import RunStatus
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_source

FIXTURE = Path(__file__).parent / "fixtures" / "finlife" / "deposit_savings_bank_page1.json"


class GuardedCuFixtureAdapter(FinlifeAdapter):
    """Use the real Finlife parser but exercise CU's nationwide volume contract."""

    source_id = "cu"
    source_name = "CU volume-contract fixture"

    def __init__(self) -> None:
        super().__init__(api_key="offline-test")

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [
            RawArtifactData(
                artifact_type="json",
                content=FIXTURE.read_bytes(),
                filename="cu-volume-contract-fixture.json",
                request_meta={"fixture": True},
                schema_fingerprint="fp-volume-guard",
                source_role=self.source_role,
                trust_level=self.trust_level,
            )
        ]


def test_nationwide_under_minimum_keeps_raw_evidence_but_rolls_back_observations(tmp_path):
    engine = create_db_engine(tmp_path / "volume.sqlite3")
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    result = asyncio.run(
        collect_source(
            GuardedCuFixtureAdapter(),
            CollectionRequest(source_id="cu"),
            factory,
            raw_root=tmp_path / "raw",
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.parsed_count > 0
    assert "SOURCE_VOLUME_BELOW_MINIMUM" in result.message

    with factory() as session:
        run = session.scalars(select(m.CollectionRun)).one()
        assert run.status == RunStatus.FAILED
        assert run.parsed_count == result.parsed_count
        assert session.scalar(select(func.count()).select_from(m.RawArtifact)) == 1
        assert session.scalar(select(func.count()).select_from(m.RateObservation)) == 0
        assert session.scalar(select(func.count()).select_from(m.ProductVariant)) == 0

        issue = session.scalars(
            select(m.ReviewItem).where(m.ReviewItem.issue_type == "source_volume")
        ).one()
        assert issue.severity == "error"
        assert issue.payload_json["source_id"] == "cu"
        assert issue.payload_json["parsed_count"] == result.parsed_count
        assert issue.payload_json["minimum"] == 7_500
