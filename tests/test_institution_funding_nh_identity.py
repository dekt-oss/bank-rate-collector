from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from rate_monitor.collectors.data_go_funding.identity_reconciliation import (
    MAPPED_STATUS,
    FundingIdentityConflict,
    reconcile_agri_funding_identity,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope


def _source(source_id: str, *, sector: str, now: datetime) -> m.Source:
    return m.Source(
        id=source_id,
        name=source_id,
        sector=sector,
        mode="api",
        source_role="secondary_official",
        trust_level="official_direct",
        priority=40,
        enabled=True,
        policy_status="approved",
        coverage_status="partial",
        parser_version="1",
        created_at=now,
        updated_at=now,
    )


def _seed_base(tmp_path):
    db_path = tmp_path / "funding.sqlite3"
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 29, 3, 0, 0)

    with session_scope(factory) as session:
        session.add(_source("nh_local", sector="nh_local", now=now))
        session.add(
            _source(
                "data_go_agri_coop_funding",
                sector="nh_local",
                now=now,
            )
        )
        institution = m.Institution(
            sector="nh_local",
            canonical_name="남부산농협",
            normalized_name="남부산농협",
            availability_scope="unknown",
            active=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(institution)
        session.flush()
        session.add(
            m.SourceEntityLink(
                source_id="nh_local",
                entity_type="institution",
                source_entity_key="nh_local:121020",
                entity_id=institution.id,
                source_name="남부산농협",
                confidence=1.0,
                match_method="exact_code",
                valid_from=date(2026, 8, 17),
                valid_to=None,
                created_at=now,
                updated_at=now,
            )
        )
        run = m.CollectionRun(
            source_id="data_go_agri_coop_funding",
            mode="api",
            started_at=now,
            status="success",
        )
        session.add(run)
        session.flush()
        raw = m.RawArtifact(
            run_id=run.id,
            artifact_type="json",
            relative_path="data/raw/agri.json",
            sha256="a" * 64,
            content_length=2,
            encoding="utf-8",
            request_meta_json={},
            captured_at=now,
        )
        session.add(raw)
        session.flush()
        return db_path, factory, institution.id, raw.id, now


def _observation(
    *,
    raw_id: str,
    now: datetime,
    source_name: str,
    institution_id: str | None = None,
) -> InstitutionFundingObservation:
    return InstitutionFundingObservation(
        institution_id=institution_id,
        source_id="data_go_agri_coop_funding",
        source_institution_key="0010027121020",
        source_institution_name=source_name,
        source_crno="1146360000000",
        sector="nh_local",
        metric_code="deposit_liabilities_total",
        metric_name="예수부채",
        source_effective_month="2025-12",
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 31),
        value=Decimal("123.000000"),
        unit="million_krw",
        source_value_text="123000000",
        source_unit="krw",
        observation_basis="reported_period_end",
        statement_basis="source_reported_unconsolidated_unspecified",
        population_scope="agri_coops_local_units_source_reported",
        identity_status="unmapped_no_exact_cross_source_code",
        observed_at=now,
        source_locator="https://example.test/agri",
        raw_artifact_id=raw_id,
        content_hash="sha256:" + "b" * 64,
        revision=1,
        valid_from=now,
        valid_to=None,
        created_at=now,
    )


def test_exact_brc_and_source_name_maps_observation_idempotently(tmp_path) -> None:
    db_path, factory, institution_id, raw_id, now = _seed_base(tmp_path)
    with session_scope(factory) as session:
        session.add(
            _observation(
                raw_id=raw_id,
                now=now,
                source_name="남부산농협",
            )
        )

    first = reconcile_agri_funding_identity(db_path)
    second = reconcile_agri_funding_identity(db_path)

    assert first.scanned == 1
    assert first.eligible == 1
    assert first.mapped == 1
    assert first.name_mismatch == 0
    assert second.mapped == 0
    assert second.unchanged == 1

    with session_scope(factory) as session:
        row = session.scalar(select(InstitutionFundingObservation))
        assert row is not None
        assert row.institution_id == institution_id
        assert row.identity_status == MAPPED_STATUS
        assert row.value == Decimal("123.000000")
        assert row.revision == 1
        assert row.raw_artifact_id == raw_id


def test_same_brc_with_different_name_stays_unmapped(tmp_path) -> None:
    db_path, factory, _institution_id, raw_id, now = _seed_base(tmp_path)
    with session_scope(factory) as session:
        session.add(
            _observation(
                raw_id=raw_id,
                now=now,
                source_name="옛남부산농협",
            )
        )

    result = reconcile_agri_funding_identity(db_path)

    assert result.mapped == 0
    assert result.name_mismatch == 1
    with session_scope(factory) as session:
        row = session.scalar(select(InstitutionFundingObservation))
        assert row is not None
        assert row.institution_id is None
        assert row.identity_status == "unmapped_no_exact_cross_source_code"


def test_missing_brc_link_stays_unmapped(tmp_path) -> None:
    db_path, factory, _institution_id, raw_id, now = _seed_base(tmp_path)
    with session_scope(factory) as session:
        link = session.scalar(
            select(m.SourceEntityLink).where(m.SourceEntityLink.source_id == "nh_local")
        )
        assert link is not None
        session.delete(link)
        session.add(
            _observation(
                raw_id=raw_id,
                now=now,
                source_name="남부산농협",
            )
        )

    result = reconcile_agri_funding_identity(db_path)

    assert result.mapped == 0
    assert result.no_brc_link == 1


def test_existing_different_mapping_fails_closed(tmp_path) -> None:
    db_path, factory, _institution_id, raw_id, now = _seed_base(tmp_path)
    with session_scope(factory) as session:
        other = m.Institution(
            sector="nh_local",
            canonical_name="다른농협",
            normalized_name="다른농협",
            availability_scope="unknown",
            active=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(other)
        session.flush()
        session.add(
            _observation(
                raw_id=raw_id,
                now=now,
                source_name="남부산농협",
                institution_id=other.id,
            )
        )

    with pytest.raises(FundingIdentityConflict):
        reconcile_agri_funding_identity(db_path)

    with session_scope(factory) as session:
        row = session.scalar(select(InstitutionFundingObservation))
        assert row is not None
        assert row.identity_status == "unmapped_no_exact_cross_source_code"


def test_non_real_key_is_ignored(tmp_path) -> None:
    db_path, factory, _institution_id, raw_id, now = _seed_base(tmp_path)
    with session_scope(factory) as session:
        row = _observation(
            raw_id=raw_id,
            now=now,
            source_name="농협단위조합",
        )
        row.source_institution_key = "030801S"
        session.add(row)

    result = reconcile_agri_funding_identity(db_path)

    assert result.scanned == 1
    assert result.eligible == 0
    assert result.mapped == 0
