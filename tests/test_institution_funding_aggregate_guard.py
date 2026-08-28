from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from rate_monitor.collectors.data_go_funding.aggregate_guard import (
    SAVINGS_BANK_SECTOR_TOTAL_KEY,
    retire_validated_savings_bank_sector_totals,
)
from rate_monitor.collectors.data_go_funding.collector import (
    FundingContractError,
    FundingPoint,
    _upsert_point,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

SOURCE_ID = "data_go_savings_bank_funding"


def _point(*, key: str, name: str, value: str, month: str = "2026-03") -> FundingPoint:
    year, mon = (int(part) for part in month.split("-"))
    return FundingPoint(
        source_id=SOURCE_ID,
        sector="savings_bank",
        dataset_id="15061316",
        source_institution_key=key,
        source_institution_name=name,
        source_crno=None,
        source_effective_month=month,
        period_start=date(year, mon, 1),
        period_end=date(year, mon, 31),
        source_value_text=str(Decimal(value) * Decimal("1000000")),
        value=Decimal(value),
        population_scope="savings_banks_all_source_reported",
        source_locator="https://example.test/fina",
    )


def _seed(tmp_path, points: list[FundingPoint]):
    db_path = tmp_path / "funding.sqlite3"
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 29, 1, 0, 0)

    with session_scope(factory) as session:
        session.add(
            m.Source(
                id=SOURCE_ID,
                name="저축은행 재무현황",
                sector="savings_bank",
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
        )
        run = m.CollectionRun(
            source_id=SOURCE_ID,
            mode="api",
            started_at=now,
            status="running",
        )
        session.add(run)
        session.flush()
        raw = m.RawArtifact(
            run_id=run.id,
            artifact_type="json",
            relative_path="data/raw/funding.json",
            sha256="a" * 64,
            content_length=2,
            encoding="utf-8",
            request_meta_json={},
            captured_at=now,
        )
        session.add(raw)
        session.flush()
        for point in points:
            _upsert_point(session, point, raw_artifact_id=raw.id, now=now)

    return db_path, factory


def _active(factory):
    with session_scope(factory) as session:
        return list(
            session.scalars(
                select(InstitutionFundingObservation)
                .where(InstitutionFundingObservation.valid_to.is_(None))
                .order_by(InstitutionFundingObservation.source_institution_key)
            )
        )


def test_exact_sector_total_is_retired_and_history_is_preserved(tmp_path):
    db_path, factory = _seed(
        tmp_path,
        [
            _point(key="001", name="A저축은행", value="1.000000"),
            _point(key="002", name="B저축은행", value="2.000000"),
            _point(
                key=SAVINGS_BANK_SECTOR_TOTAL_KEY,
                name="저축은행",
                value="3.000000",
            ),
        ],
    )
    retired_at = datetime(2026, 8, 29, 2, 0, 0)

    result = retire_validated_savings_bank_sector_totals(db_path, now=retired_at)

    assert result.checked_months == 1
    assert result.retired_observations == 1
    assert [row.source_institution_key for row in _active(factory)] == ["001", "002"]
    with session_scope(factory) as session:
        aggregate = session.scalar(
            select(InstitutionFundingObservation).where(
                InstitutionFundingObservation.source_institution_key
                == SAVINGS_BANK_SECTOR_TOTAL_KEY
            )
        )
        assert aggregate is not None
        assert aggregate.valid_to == retired_at

    second = retire_validated_savings_bank_sector_totals(db_path, now=retired_at)
    assert second.checked_months == 0
    assert second.retired_observations == 0


def test_sector_total_mismatch_fails_closed_without_retirement(tmp_path):
    db_path, factory = _seed(
        tmp_path,
        [
            _point(key="001", name="A저축은행", value="1.000000"),
            _point(key="002", name="B저축은행", value="2.000000"),
            _point(
                key=SAVINGS_BANK_SECTOR_TOTAL_KEY,
                name="저축은행",
                value="4.000000",
            ),
        ],
    )

    with pytest.raises(FundingContractError, match="sector-total 합계 불일치"):
        retire_validated_savings_bank_sector_totals(db_path)

    assert {row.source_institution_key for row in _active(factory)} == {
        "001",
        "002",
        SAVINGS_BANK_SECTOR_TOTAL_KEY,
    }


def test_sector_total_key_with_changed_identity_fails_closed(tmp_path):
    db_path, factory = _seed(
        tmp_path,
        [
            _point(key="001", name="A저축은행", value="1.000000"),
            _point(
                key=SAVINGS_BANK_SECTOR_TOTAL_KEY,
                name="실제저축은행",
                value="1.000000",
            ),
        ],
    )

    with pytest.raises(FundingContractError, match="identity 계약 불일치"):
        retire_validated_savings_bank_sector_totals(db_path)

    assert len(_active(factory)) == 2


def test_same_name_with_different_key_is_not_treated_as_sector_total(tmp_path):
    db_path, factory = _seed(
        tmp_path,
        [_point(key="001", name="저축은행", value="1.000000")],
    )

    result = retire_validated_savings_bank_sector_totals(db_path)

    assert result.checked_months == 0
    assert result.retired_observations == 0
    assert [row.source_institution_key for row in _active(factory)] == ["001"]
