from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from rate_monitor.collectors.data_go_funding import operations
from rate_monitor.collectors.data_go_funding.collector import FundingPoint, _resolve_identity
from rate_monitor.collectors.data_go_funding.resilient import ResilientSourceResult
from rate_monitor.collectors.data_go_funding.savings_bank_identity import (
    MAPPED_DUAL_SOURCE_STATUS,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation  # noqa: F401
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

NOW = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)
FUNDING_SOURCE_ID = "data_go_savings_bank_funding"
ORG_KEY = "savings_bank:0013002"


def _source(source_id: str) -> m.Source:
    return m.Source(
        id=source_id,
        name=source_id,
        sector="savings_bank",
        mode="api",
        source_role="primary_official",
        trust_level="official_direct",
        priority=10,
        base_reference=None,
        enabled=True,
        schedule_cron=None,
        policy_status="approved",
        coverage_status="partial",
        parser_version="1",
        created_at=NOW,
        updated_at=NOW,
    )


def _institution() -> m.Institution:
    return m.Institution(
        sector="savings_bank",
        canonical_name="BNK저축은행",
        normalized_name="bnk저축은행",
        institution_type=None,
        sido_code=None,
        sigungu_code=None,
        region_sido=None,
        region_sigungu=None,
        geo_basis="none",
        geo_confidence=None,
        address=None,
        phone=None,
        availability_scope="unknown",
        active=True,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def _link(source_id: str, institution_id: str) -> m.SourceEntityLink:
    return m.SourceEntityLink(
        source_id=source_id,
        entity_type="institution",
        source_entity_key=ORG_KEY,
        entity_id=institution_id,
        source_name="BNK저축은행",
        source_payload_json={},
        confidence=1.0,
        match_method="exact_code",
        valid_from=None,
        valid_to=None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_collector_name_mismatch_uses_consensus_without_persistent_funding_link(
    tmp_path: Path,
) -> None:
    engine = create_db_engine(tmp_path / "collector.sqlite3")
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        session.add_all(
            [
                _source(FUNDING_SOURCE_ID),
                _source("fsb"),
                _source("finlife_savings_bank"),
            ]
        )
        institution = _institution()
        session.add(institution)
        session.flush()
        session.add_all(
            [
                _link("fsb", institution.id),
                _link("finlife_savings_bank", institution.id),
            ]
        )
        session.flush()

        point = FundingPoint(
            source_id=FUNDING_SOURCE_ID,
            sector="savings_bank",
            dataset_id="15061316",
            source_institution_key="0013002",
            source_institution_name="비엔케이저축은행",
            source_crno="1801110786484",
            source_effective_month="2026-03",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            source_value_text="123456000000",
            value=Decimal("123456"),
            population_scope="savings_banks_all_source_reported",
            source_locator="https://example.invalid/data-go",
        )

        institution_id, status = _resolve_identity(session, point, NOW)
        session.flush()

        assert institution_id == institution.id
        assert status == MAPPED_DUAL_SOURCE_STATUS
        own_links = list(
            session.scalars(
                select(m.SourceEntityLink).where(
                    m.SourceEntityLink.source_id == FUNDING_SOURCE_ID
                )
            )
        )
        assert own_links == []


def _success_result() -> ResilientSourceResult:
    return ResilientSourceResult(
        source_id=FUNDING_SOURCE_ID,
        sector="savings_bank",
        required=True,
        status="success",
        requested_months=("2026-03",),
        completed_months=("2026-03",),
        failed_months=(),
        fetched_artifacts=1,
        parsed_points=79,
        stored=0,
        unchanged=79,
        revisions=0,
        mapped=66,
        unmapped=13,
        retry_recovered_months=(),
        message="ok",
    )


def test_operational_success_runs_aggregate_guard_before_identity_reconciliation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    savings_contract = next(
        contract for contract in operations.CONTRACTS if contract.sector == "savings_bank"
    )
    monkeypatch.setattr(operations, "CONTRACTS", (savings_contract,))
    monkeypatch.setattr(operations, "_transport_preflight", lambda _contract: (True, "ok"))

    def collect(*args, **kwargs):
        events.append("collect")
        return _success_result()

    def guard(_db_path):
        events.append("guard")
        return SimpleNamespace(checked_months=1, retired_observations=0)

    def reconcile(_db_path):
        events.append("identity")
        return SimpleNamespace(
            latest_month="2026-03",
            scanned=79,
            eligible_unmapped=13,
            mapped=13,
            unchanged_mapped=66,
            no_consensus=0,
            excluded_aggregate=0,
        )

    monkeypatch.setattr(operations, "collect_source_resilient", collect)
    monkeypatch.setattr(operations, "retire_validated_savings_bank_sector_totals", guard)
    monkeypatch.setattr(
        operations,
        "reconcile_latest_savings_bank_funding_identity",
        reconcile,
    )

    results = operations.collect_operational(
        db_path=tmp_path / "test.sqlite3",
        raw_root=tmp_path / "raw",
        mode="incremental",
    )

    assert [result.status for result in results] == ["success"]
    assert events == ["collect", "guard", "identity"]


def test_operational_failure_skips_guard_and_identity_reconciliation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    savings_contract = next(
        contract for contract in operations.CONTRACTS if contract.sector == "savings_bank"
    )
    monkeypatch.setattr(operations, "CONTRACTS", (savings_contract,))
    monkeypatch.setattr(operations, "_transport_preflight", lambda _contract: (True, "ok"))

    failed = _success_result()
    failed = ResilientSourceResult(**{**failed.__dict__, "status": "failed"})

    def collect(*args, **kwargs):
        events.append("collect")
        return failed

    def unexpected(*args, **kwargs):
        events.append("unexpected")
        raise AssertionError("post-collection identity path must not run after failure")

    monkeypatch.setattr(operations, "collect_source_resilient", collect)
    monkeypatch.setattr(
        operations,
        "retire_validated_savings_bank_sector_totals",
        unexpected,
    )
    monkeypatch.setattr(
        operations,
        "reconcile_latest_savings_bank_funding_identity",
        unexpected,
    )

    results = operations.collect_operational(
        db_path=tmp_path / "test.sqlite3",
        raw_root=tmp_path / "raw",
        mode="incremental",
    )

    assert [result.status for result in results] == ["failed"]
    assert events == ["collect"]
