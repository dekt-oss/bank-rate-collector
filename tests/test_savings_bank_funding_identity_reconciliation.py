from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from rate_monitor.collectors.data_go_funding.savings_bank_identity import (
    MAPPED_DUAL_SOURCE_STATUS,
    resolve_savings_bank_dual_source_consensus,
)
from rate_monitor.collectors.data_go_funding.savings_bank_identity_reconciliation import (
    reconcile_latest_savings_bank_funding_identity,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

NOW = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)
FUNDING = "data_go_savings_bank_funding"
ORG_KEY = "savings_bank:0013002"
CRNO = "1801110786484"


def _source(source_id: str, sector: str = "savings_bank") -> m.Source:
    return m.Source(
        id=source_id,
        name=source_id,
        sector=sector,
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


def _institution(
    name: str = "BNK저축은행", *, active: bool = True, sector: str = "savings_bank"
) -> m.Institution:
    return m.Institution(
        sector=sector,
        canonical_name=name,
        normalized_name=name,
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
        active=active,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def _link(
    source_id: str,
    institution_id: str,
    *,
    match_method: str = "exact_code",
    crno: str | None = None,
) -> m.SourceEntityLink:
    return m.SourceEntityLink(
        source_id=source_id,
        entity_type="institution",
        source_entity_key=ORG_KEY,
        entity_id=institution_id,
        source_name="BNK저축은행",
        source_payload_json={"crno": crno} if crno else {},
        confidence=1.0,
        match_method=match_method,
        valid_from=None,
        valid_to=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _prepare_db(db_path: Path) -> tuple[object, object]:
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        session.add_all([_source(FUNDING), _source("fsb"), _source("finlife_savings_bank")])
        run = m.CollectionRun(
            source_id=FUNDING,
            mode="api",
            started_at=NOW,
            finished_at=NOW,
            status="success",
            query_context_json={},
            raw_count=1,
            parsed_count=1,
            valid_count=1,
            warning_count=0,
            error_count=0,
            message=None,
            schema_fingerprint=None,
            previous_run_id=None,
            fallback_used=False,
            blocked_until=None,
        )
        session.add(run)
        session.flush()
        raw = m.RawArtifact(
            run_id=run.id,
            artifact_type="json",
            relative_path="raw/test.json",
            sha256="a" * 64,
            content_length=2,
            encoding="utf-8",
            request_meta_json={},
            captured_at=NOW,
        )
        session.add(raw)
        session.flush()
        raw_id = raw.id
    return factory, raw_id


def _add_observation(
    session: object,
    *,
    raw_id: str,
    month: str = "2026-03",
    institution_id: str | None = None,
    source_key: str = "0013002",
) -> InstitutionFundingObservation:
    year, mon = (int(part) for part in month.split("-"))
    period_end = date(year, mon, calendar.monthrange(year, mon)[1])
    observation = InstitutionFundingObservation(
        institution_id=institution_id,
        source_id=FUNDING,
        source_institution_key=source_key,
        source_institution_name="비엔케이저축은행",
        source_crno=CRNO,
        sector="savings_bank",
        metric_code="deposit_liabilities_total",
        metric_name="예수부채",
        source_effective_month=month,
        period_start=date(year, mon, 1),
        period_end=period_end,
        value=Decimal("123456.000000"),
        unit="million_krw",
        source_value_text="123456000000",
        source_unit="krw",
        observation_basis="reported_period_end",
        statement_basis="source_reported_unconsolidated_unspecified",
        population_scope="all_savings_banks",
        identity_status="unmapped",
        observed_at=NOW,
        source_locator="https://example.invalid/data-go",
        raw_artifact_id=raw_id,
        content_hash="sha256:" + "b" * 64,
        revision=1,
        valid_from=NOW,
        valid_to=None,
        created_at=NOW,
    )
    session.add(observation)  # type: ignore[attr-defined]
    return observation


def test_dual_source_consensus_maps_only_same_exact_code_entity(tmp_path: Path) -> None:
    factory, _raw_id = _prepare_db(tmp_path / "test.sqlite3")
    with session_scope(factory) as session:
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

        result = resolve_savings_bank_dual_source_consensus(
            session,
            source_institution_key="0013002",
            source_institution_name="비엔케이저축은행",
            source_crno=CRNO,
        )

        assert result.institution_id == institution.id
        assert result.reason == "fsb_finlife_exact_code_consensus"


def test_dual_source_consensus_fails_closed_on_missing_or_divergent_reference(
    tmp_path: Path,
) -> None:
    factory, _raw_id = _prepare_db(tmp_path / "test.sqlite3")
    with session_scope(factory) as session:
        first = _institution("BNK저축은행")
        second = _institution("다른저축은행")
        session.add_all([first, second])
        session.flush()
        session.add(_link("fsb", first.id))
        session.flush()

        missing = resolve_savings_bank_dual_source_consensus(
            session,
            source_institution_key="0013002",
            source_institution_name="비엔케이저축은행",
            source_crno=CRNO,
        )
        assert missing.institution_id is None
        assert missing.reason == "reference_link_cardinality"

        session.add(_link("finlife_savings_bank", second.id))
        session.flush()
        divergent = resolve_savings_bank_dual_source_consensus(
            session,
            source_institution_key="0013002",
            source_institution_name="비엔케이저축은행",
            source_crno=CRNO,
        )
        assert divergent.institution_id is None
        assert divergent.reason == "reference_entity_conflict"


def test_dual_source_consensus_rejects_non_exact_inactive_wrong_sector_crno_and_aggregate(
    tmp_path: Path,
) -> None:
    for case in ("non_exact", "inactive", "wrong_sector", "crno"):
        db_path = tmp_path / f"{case}.sqlite3"
        factory, _raw_id = _prepare_db(db_path)
        with session_scope(factory) as session:
            institution = _institution(
                active=case != "inactive",
                sector="bank" if case == "wrong_sector" else "savings_bank",
            )
            session.add(institution)
            session.flush()
            session.add_all(
                [
                    _link(
                        "fsb",
                        institution.id,
                        match_method="manual" if case == "non_exact" else "exact_code",
                        crno="9999999999999" if case == "crno" else None,
                    ),
                    _link("finlife_savings_bank", institution.id),
                ]
            )
            session.flush()
            result = resolve_savings_bank_dual_source_consensus(
                session,
                source_institution_key="0013002",
                source_institution_name="비엔케이저축은행",
                source_crno=CRNO,
            )
            assert result.institution_id is None

    factory, _raw_id = _prepare_db(tmp_path / "aggregate.sqlite3")
    with session_scope(factory) as session:
        aggregate = resolve_savings_bank_dual_source_consensus(
            session,
            source_institution_key="030350S",
            source_institution_name="저축은행",
            source_crno=None,
        )
        assert aggregate.institution_id is None
        assert aggregate.reason == "sector_total_excluded"


def test_reconciliation_maps_latest_unmapped_only_and_preserves_financial_provenance(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.sqlite3"
    factory, raw_id = _prepare_db(db_path)
    with session_scope(factory) as session:
        institution = _institution()
        session.add(institution)
        session.flush()
        session.add_all(
            [
                _link("fsb", institution.id),
                _link("finlife_savings_bank", institution.id),
            ]
        )
        older = _add_observation(session, raw_id=raw_id, month="2026-02")
        latest = _add_observation(session, raw_id=raw_id, month="2026-03")
        session.flush()
        latest_id = latest.id
        older_id = older.id
        expected_institution_id = institution.id
        before = (
            latest.value,
            latest.source_value_text,
            latest.source_effective_month,
            latest.period_start,
            latest.period_end,
            latest.raw_artifact_id,
            latest.content_hash,
            latest.revision,
            latest.valid_from,
            latest.valid_to,
            latest.source_locator,
        )

    first = reconcile_latest_savings_bank_funding_identity(db_path)
    assert first.latest_month == "2026-03"
    assert first.scanned == 1
    assert first.eligible_unmapped == 1
    assert first.mapped == 1
    assert first.no_consensus == 0

    with session_scope(factory) as session:
        latest = session.get(InstitutionFundingObservation, latest_id)
        older = session.get(InstitutionFundingObservation, older_id)
        assert latest is not None
        assert older is not None
        assert latest.institution_id == expected_institution_id
        assert latest.identity_status == MAPPED_DUAL_SOURCE_STATUS
        assert older.institution_id is None
        after = (
            latest.value,
            latest.source_value_text,
            latest.source_effective_month,
            latest.period_start,
            latest.period_end,
            latest.raw_artifact_id,
            latest.content_hash,
            latest.revision,
            latest.valid_from,
            latest.valid_to,
            latest.source_locator,
        )
        assert after == before
        own_link = session.scalars(
            select(m.SourceEntityLink).where(m.SourceEntityLink.source_id == FUNDING)
        ).first()
        assert own_link is None

    second = reconcile_latest_savings_bank_funding_identity(db_path)
    assert second.mapped == 0
    assert second.eligible_unmapped == 0
    assert second.unchanged_mapped == 1
