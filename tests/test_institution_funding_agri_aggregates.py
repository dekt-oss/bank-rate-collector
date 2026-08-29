from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from rate_monitor.collectors.data_go_funding.aggregate_guard import (
    retire_validated_agri_coop_aggregates,
)
from rate_monitor.collectors.data_go_funding.aggregate_policy import (
    AGRI_COOP_REGION_TOTALS,
    AggregateValidationError,
    partition_validated_agri_coop_rows,
)
from rate_monitor.collectors.data_go_funding.collector import CONTRACTS, parse_points
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope


@dataclass(frozen=True)
class _Row:
    source_institution_key: str
    source_institution_name: str
    source_crno: str | None
    source_effective_month: str
    value: Decimal
    population_scope: str = "agri_coops_local_units_source_reported"


def _current_rows(*, sector_total: Decimal = Decimal("200")) -> list[_Row]:
    institutions = [
        _Row("0010027000001", "가농협", None, "2025-12", Decimal("40")),
        _Row("0010027000002", "나농협", None, "2025-12", Decimal("60")),
    ]
    regions = [
        _Row(
            key,
            name,
            None,
            "2025-12",
            Decimal("100") if index == 0 else Decimal("0"),
        )
        for index, (key, name) in enumerate(AGRI_COOP_REGION_TOTALS.items())
    ]
    sector = _Row("030801S", "농협단위조합", None, "2025-12", sector_total)
    return [*institutions, *regions, sector]


def test_current_hierarchy_is_validated_and_partitioned() -> None:
    institutions, aggregates = partition_validated_agri_coop_rows(_current_rows())

    assert [row.source_institution_key for row in institutions] == [
        "0010027000001",
        "0010027000002",
    ]
    assert len(aggregates) == 17
    assert sum((row.value for row in institutions), Decimal("0")) == Decimal("100")


def test_current_hierarchy_missing_region_fails_closed() -> None:
    rows = _current_rows()
    rows = [row for row in rows if row.source_institution_key != "0321302S"]

    with pytest.raises(AggregateValidationError, match="hierarchy 불완전"):
        partition_validated_agri_coop_rows(rows)


def test_current_hierarchy_wrong_sector_total_fails_closed() -> None:
    with pytest.raises(AggregateValidationError, match="sector total hierarchy 불일치"):
        partition_validated_agri_coop_rows(_current_rows(sector_total=Decimal("201")))


def test_legacy_total_is_validated_and_partitioned() -> None:
    rows = [
        _Row("0010027000001", "가농협", None, "2020-12", Decimal("40")),
        _Row("0010027000002", "나농협", None, "2020-12", Decimal("60")),
        _Row("032120S", "농업협동조합", None, "2020-12", Decimal("100")),
    ]

    institutions, aggregates = partition_validated_agri_coop_rows(rows)

    assert len(institutions) == 2
    assert [row.source_institution_key for row in aggregates] == ["032120S"]


def test_institution_only_month_is_not_filtered() -> None:
    rows = [
        _Row("0010027000001", "가농협", None, "2026-06", Decimal("40")),
        _Row("0010027000002", "나농협", None, "2026-06", Decimal("60")),
    ]

    institutions, aggregates = partition_validated_agri_coop_rows(rows)

    assert institutions == rows
    assert aggregates == []


def test_unknown_aggregate_like_key_fails_closed() -> None:
    rows = [*_current_rows(), _Row("039999S", "미확정합계", None, "2025-12", Decimal("1"))]

    with pytest.raises(AggregateValidationError, match="미확정 aggregate key"):
        partition_validated_agri_coop_rows(rows)


def _source_row(key: str, name: str, amount_krw: int) -> dict[str, str]:
    return {
        "basYm": "202512",
        "fncoCd": key,
        "fncoNm": name,
        "crno": "",
        "astDebtSmryBlnshDcd": "A1",
        "astDebtSmryBlnshDcdNm": "예수부채",
        "astDebtSmryBlnshClsfAmt": str(amount_krw),
    }


def test_parser_excludes_validated_agri_aggregate_rows_before_persistence() -> None:
    rows = [
        _source_row("0010027000001", "가농협", 40_000_000),
        _source_row("0010027000002", "나농협", 60_000_000),
    ]
    rows.extend(
        _source_row(key, name, 100_000_000 if index == 0 else 0)
        for index, (key, name) in enumerate(AGRI_COOP_REGION_TOTALS.items())
    )
    rows.append(_source_row("030801S", "농협단위조합", 200_000_000))
    contract = next(contract for contract in CONTRACTS if contract.sector == "nh_local")

    points = parse_points(contract, rows, endpoint="https://example.test/agri")

    assert [point.source_institution_key for point in points] == [
        "0010027000001",
        "0010027000002",
    ]
    assert sum((point.value for point in points), Decimal("0")) == Decimal("100.000000")


def _source(source_id: str, now: datetime) -> m.Source:
    return m.Source(
        id=source_id,
        name=source_id,
        sector="nh_local",
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


def _observation(*, key: str, name: str, value: Decimal, raw_id: str, now: datetime):
    return InstitutionFundingObservation(
        institution_id=None,
        source_id="data_go_agri_coop_funding",
        source_institution_key=key,
        source_institution_name=name,
        source_crno=None,
        sector="nh_local",
        metric_code="deposit_liabilities_total",
        metric_name="예수부채",
        source_effective_month="2025-12",
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 31),
        value=value,
        unit="million_krw",
        source_value_text=str(value * Decimal("1000000")),
        source_unit="krw",
        observation_basis="reported_period_end",
        statement_basis="source_reported_unconsolidated_unspecified",
        population_scope="agri_coops_local_units_source_reported",
        identity_status="unmapped_no_exact_cross_source_code",
        observed_at=now,
        source_locator="https://example.test/agri",
        raw_artifact_id=raw_id,
        content_hash=f"sha256:{key:0<64}"[:71],
        revision=1,
        valid_from=now,
        valid_to=None,
        created_at=now,
    )


def test_legacy_active_aggregates_are_retired_idempotently(tmp_path) -> None:
    db_path = tmp_path / "funding.sqlite3"
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 29, 1, 0, 0)
    retired_at = datetime(2026, 8, 29, 2, 0, 0)

    with session_scope(factory) as session:
        session.add(_source("data_go_agri_coop_funding", now))
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
        raw_id = raw.id

        session.add(
            _observation(
                key="0010027000001",
                name="가농협",
                value=Decimal("40"),
                raw_id=raw_id,
                now=now,
            )
        )
        session.add(
            _observation(
                key="0010027000002",
                name="나농협",
                value=Decimal("60"),
                raw_id=raw_id,
                now=now,
            )
        )
        for index, (key, name) in enumerate(AGRI_COOP_REGION_TOTALS.items()):
            session.add(
                _observation(
                    key=key,
                    name=name,
                    value=Decimal("100") if index == 0 else Decimal("0"),
                    raw_id=raw_id,
                    now=now,
                )
            )
        session.add(
            _observation(
                key="030801S",
                name="농협단위조합",
                value=Decimal("200"),
                raw_id=raw_id,
                now=now,
            )
        )

    first = retire_validated_agri_coop_aggregates(db_path, now=retired_at)
    second = retire_validated_agri_coop_aggregates(db_path, now=retired_at)

    assert first.checked_months == 1
    assert first.retired_observations == 17
    assert second.checked_months == 0
    assert second.retired_observations == 0

    with session_scope(factory) as session:
        active = session.scalar(
            select(func.count())
            .select_from(InstitutionFundingObservation)
            .where(InstitutionFundingObservation.valid_to.is_(None))
        )
        retired = session.scalar(
            select(func.count())
            .select_from(InstitutionFundingObservation)
            .where(InstitutionFundingObservation.valid_to == retired_at)
        )
    assert active == 2
    assert retired == 17
