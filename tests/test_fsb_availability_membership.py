"""FSB 가입가능지역 census/persistence 계약.

정기예금 금리축과 분리된 membership만 다루며 partial census는 기존 정상값을
건드리지 않는지 검증한다.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from rate_monitor.db.availability_models import InstitutionAvailabilityMembership
from rate_monitor.db.models import (
    Base,
    Institution,
    Product,
    ProductVariant,
    RateObservation,
    Source,
    SourceEntityLink,
)
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.enums import Sector
from rate_monitor.domain.identifiers import make_org_key
from rate_monitor.services.fsb_availability_service import (
    AREAS,
    AvailabilityCensus,
    AvailabilityCensusError,
    build_census_from_rows,
    reconcile_fsb_availability,
    sync_fsb_availability,
)

QUERY_DATE = date(2026, 9, 1)
T0 = datetime(2026, 9, 1, 9, 0, 0)


@pytest.fixture
def factory(tmp_path):
    engine = create_db_engine(tmp_path / "availability.sqlite3")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _source(session) -> None:
    session.add(
        Source(
            id="fsb",
            name="저축은행중앙회 소비자포털",
            sector=Sector.SAVINGS_BANK,
            mode="http",
            source_role="primary_official",
            trust_level="official_direct",
            priority=10,
            enabled=True,
            policy_status="unknown",
            coverage_status="partial",
            created_at=T0,
            updated_at=T0,
        )
    )


def _institution(session, source_code: str, *, match_method: str = "exact_code") -> str:
    institution = Institution(
        sector=Sector.SAVINGS_BANK,
        canonical_name=f"은행-{source_code}",
        normalized_name=f"은행-{source_code}",
        availability_scope="unknown",
        active=True,
        first_seen_at=T0,
        last_seen_at=T0,
    )
    session.add(institution)
    session.flush()
    session.add(
        SourceEntityLink(
            source_id="fsb",
            entity_type="institution",
            source_entity_key=make_org_key(Sector.SAVINGS_BANK, source_code),
            entity_id=institution.id,
            source_name=institution.canonical_name,
            confidence=1.0,
            match_method=match_method,
            valid_from=QUERY_DATE,
            valid_to=None,
            created_at=T0,
            updated_at=T0,
        )
    )
    return institution.id


def _census(mapping: dict[str, set[str]]) -> AvailabilityCensus:
    return AvailabilityCensus(
        query_date=QUERY_DATE,
        memberships={key: frozenset(value) for key, value in mapping.items()},
        institution_count=len(mapping),
        product_count=len(mapping),
    )


def _row(institution: str, product: str) -> dict[str, str]:
    return {"FINAN_COMP_CODE": institution, "FINAN_PROD_CODE": product}


def _complete_rows() -> dict[str, list[dict[str, str]]]:
    rows = {"": [_row("001", "p1"), _row("001", "p2"), _row("002", "p3")]}
    rows.update({code: [] for code, _label in AREAS})
    rows["YN_Busan"] = [_row("001", "p1"), _row("001", "p2")]
    rows["YN_Seoul"] = [_row("002", "p3")]
    return rows


def test_complete_17_area_census_collapses_only_when_products_agree() -> None:
    census = build_census_from_rows(QUERY_DATE, _complete_rows())
    assert census.institution_count == 2
    assert census.product_count == 3
    assert census.memberships == {
        "001": frozenset({"YN_Busan"}),
        "002": frozenset({"YN_Seoul"}),
    }


def test_missing_one_area_is_not_a_complete_census() -> None:
    rows = _complete_rows()
    rows.pop("YN_Jeju")
    with pytest.raises(AvailabilityCensusError, match=r"지역전체\+17 AREA"):
        build_census_from_rows(QUERY_DATE, rows)


def test_area_may_not_contain_product_outside_all_baseline() -> None:
    rows = _complete_rows()
    rows["YN_Busan"].append(_row("999", "outside"))
    with pytest.raises(AvailabilityCensusError, match="absent from 지역전체"):
        build_census_from_rows(QUERY_DATE, rows)


def test_product_level_divergence_fails_closed_instead_of_being_lost() -> None:
    rows = _complete_rows()
    rows["YN_Busan"] = [_row("001", "p1")]
    rows["YN_Seoul"].append(_row("001", "p2"))
    with pytest.raises(AvailabilityCensusError, match="상품별 AREA membership"):
        build_census_from_rows(QUERY_DATE, rows)


def test_new_membership_and_identical_rerun_are_idempotent(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        institution_id = _institution(session, "001")
        first = reconcile_fsb_availability(
            session, _census({"001": {"YN_Busan"}}), now=T0
        )
        assert first.created == 1
        assert first.unchanged == 0

    with session_scope(factory) as session:
        second = reconcile_fsb_availability(
            session, _census({"001": {"YN_Busan"}}), now=T0 + timedelta(days=1)
        )
        assert second.created == 0
        assert second.unchanged == 1

    with session_scope(factory) as session:
        rows = session.scalars(select(InstitutionAvailabilityMembership)).all()
        assert len(rows) == 1
        assert rows[0].institution_id == institution_id
        assert rows[0].seen_count == 2
        assert rows[0].valid_to is None
        assert rows[0].availability_match_key == "fsb:term_deposit:area:YN_Busan"


def test_new_region_added_and_missing_region_expires_without_delete(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001")
        reconcile_fsb_availability(
            session, _census({"001": {"YN_Busan"}}), now=T0
        )

    with session_scope(factory) as session:
        result = reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Busan", "YN_Seoul"}}),
            now=T0 + timedelta(days=1),
        )
        assert result.created == 1
        assert result.unchanged == 1
        assert result.expired == 0

    with session_scope(factory) as session:
        result = reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Seoul"}}),
            now=T0 + timedelta(days=2),
        )
        assert result.expired == 1

    with session_scope(factory) as session:
        rows = session.scalars(
            select(InstitutionAvailabilityMembership).order_by(
                InstitutionAvailabilityMembership.area_code
            )
        ).all()
        assert len(rows) == 2
        busan = next(row for row in rows if row.area_code == "YN_Busan")
        seoul = next(row for row in rows if row.area_code == "YN_Seoul")
        assert busan.valid_to == T0 + timedelta(days=2)
        assert seoul.valid_to is None


def test_reappearing_region_creates_new_temporal_row(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001")
        reconcile_fsb_availability(
            session, _census({"001": {"YN_Busan"}}), now=T0
        )
        reconcile_fsb_availability(
            session, _census({"001": {"YN_Seoul"}}), now=T0 + timedelta(days=1)
        )
        reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Busan", "YN_Seoul"}}),
            now=T0 + timedelta(days=2),
        )

    with session_scope(factory) as session:
        busan = session.scalars(
            select(InstitutionAvailabilityMembership).where(
                InstitutionAvailabilityMembership.area_code == "YN_Busan"
            )
        ).all()
        assert len(busan) == 2
        assert sum(row.valid_to is None for row in busan) == 1


def test_unresolved_institution_code_rolls_back_whole_reconciliation(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001")

    with (
        pytest.raises(AvailabilityCensusError, match="resolve exactly once"),
        session_scope(factory) as session,
    ):
        reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Busan"}, "999": {"YN_Seoul"}}),
            now=T0,
        )

    with session_scope(factory) as session:
        count = session.scalar(
            select(func.count()).select_from(InstitutionAvailabilityMembership)
        )
        assert count == 0


def test_inactive_or_non_exact_link_is_not_accepted(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001", match_method="manual_name")

    with (
        pytest.raises(AvailabilityCensusError, match="not exact_code"),
        session_scope(factory) as session,
    ):
        reconcile_fsb_availability(
            session, _census({"001": {"YN_Busan"}}), now=T0
        )

    with session_scope(factory) as session:
        link = session.scalar(select(SourceEntityLink))
        link.match_method = "exact_code"
        link.valid_to = QUERY_DATE

    with (
        pytest.raises(AvailabilityCensusError, match="active_links=0"),
        session_scope(factory) as session,
    ):
        reconcile_fsb_availability(
            session, _census({"001": {"YN_Busan"}}), now=T0
        )


def test_active_identity_link_is_unique_at_database_boundary(factory) -> None:
    session = factory()
    try:
        _source(session)
        first_id = _institution(session, "001")
        other = Institution(
            sector=Sector.SAVINGS_BANK,
            canonical_name="다른은행",
            normalized_name="다른은행",
            availability_scope="unknown",
            active=True,
            first_seen_at=T0,
            last_seen_at=T0,
        )
        session.add(other)
        session.flush()
        session.add(
            SourceEntityLink(
                source_id="fsb",
                entity_type="institution",
                source_entity_key=make_org_key(Sector.SAVINGS_BANK, "001"),
                entity_id=other.id,
                source_name="다른은행",
                confidence=1.0,
                match_method="exact_code",
                valid_from=QUERY_DATE,
                valid_to=None,
                created_at=T0,
                updated_at=T0,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert first_id != other.id
    finally:
        session.close()


def test_timeout_before_transaction_preserves_existing_membership(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001")
        reconcile_fsb_availability(
            session, _census({"001": {"YN_Busan"}}), now=T0
        )

    async def timeout(_query_date: date) -> AvailabilityCensus:
        raise httpx.ReadTimeout("one AREA timed out")

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(sync_fsb_availability(factory, as_of=QUERY_DATE, fetch_census=timeout))

    with session_scope(factory) as session:
        row = session.scalar(select(InstitutionAvailabilityMembership))
        assert row.valid_to is None
        assert row.seen_count == 1


def test_schema_failure_before_transaction_preserves_existing_membership(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001")
        reconcile_fsb_availability(
            session, _census({"001": {"YN_Busan"}}), now=T0
        )

    async def schema_error(_query_date: date) -> AvailabilityCensus:
        raise AvailabilityCensusError("REC schema changed")

    with pytest.raises(AvailabilityCensusError, match="schema changed"):
        asyncio.run(
            sync_fsb_availability(factory, as_of=QUERY_DATE, fetch_census=schema_error)
        )

    with session_scope(factory) as session:
        row = session.scalar(select(InstitutionAvailabilityMembership))
        assert row.valid_to is None
        assert row.seen_count == 1


def test_membership_sync_does_not_touch_rate_identity_axis(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        institution_id = _institution(session, "001")
        product = Product(
            institution_id=institution_id,
            product_type="term_deposit",
            name="기존예금",
            normalized_name="기존예금",
            active=True,
            first_seen_at=T0,
            last_seen_at=T0,
        )
        session.add(product)
        session.flush()
        session.add(
            ProductVariant(
                product_id=product.id,
                term_months=12,
                join_channel="any",
                interest_method="simple",
                rate_scope="head_office_reference",
                variant_key="legacy-rate-axis",
            )
        )

    with session_scope(factory) as session:
        before = (
            session.scalar(select(func.count()).select_from(Product)),
            session.scalar(select(func.count()).select_from(ProductVariant)),
            session.scalar(select(func.count()).select_from(RateObservation)),
        )
        reconcile_fsb_availability(
            session, _census({"001": {"YN_Busan"}}), now=T0
        )

    with session_scope(factory) as session:
        after = (
            session.scalar(select(func.count()).select_from(Product)),
            session.scalar(select(func.count()).select_from(ProductVariant)),
            session.scalar(select(func.count()).select_from(RateObservation)),
        )
        assert after == before == (1, 1, 0)
        variant = session.scalar(select(ProductVariant))
        assert variant.variant_key == "legacy-rate-axis"
