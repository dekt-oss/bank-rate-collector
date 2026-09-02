"""FSB 가입가능지역 census/persistence 계약."""

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
    resolve_active_institutions,
    sync_fsb_availability,
)

QUERY_DATE = date(2026, 9, 1)
T0 = datetime(2026, 9, 1, 9, 0, 0)


@pytest.fixture
def factory(tmp_path):
    engine = create_db_engine(tmp_path / "availability.sqlite3")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _org_key(code: str) -> str:
    return make_org_key(
        sector=Sector.SAVINGS_BANK,
        source_institution_key=code,
        institution_name="",
    )


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


def _institution(session, code: str, *, match_method: str = "exact_code") -> str:
    institution = Institution(
        sector=Sector.SAVINGS_BANK,
        canonical_name=f"은행-{code}",
        normalized_name=f"은행-{code}",
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
            source_entity_key=_org_key(code),
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


def _census(mapping: dict[str, set[str]], *, when: date = QUERY_DATE) -> AvailabilityCensus:
    return AvailabilityCensus(
        query_date=when,
        memberships={code: frozenset(areas) for code, areas in mapping.items()},
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


def test_complete_census_requires_all_17_areas_and_consistent_products() -> None:
    census = build_census_from_rows(QUERY_DATE, _complete_rows())
    assert census.memberships == {
        "001": frozenset({"YN_Busan"}),
        "002": frozenset({"YN_Seoul"}),
    }
    assert (census.institution_count, census.product_count) == (2, 3)

    missing = _complete_rows()
    missing.pop("YN_Jeju")
    with pytest.raises(AvailabilityCensusError, match=r"지역전체\+17 AREA"):
        build_census_from_rows(QUERY_DATE, missing)

    outside = _complete_rows()
    outside["YN_Busan"].append(_row("999", "outside"))
    with pytest.raises(AvailabilityCensusError, match="absent from 지역전체"):
        build_census_from_rows(QUERY_DATE, outside)

    divergent = _complete_rows()
    divergent["YN_Busan"] = [_row("001", "p1")]
    divergent["YN_Seoul"].append(_row("001", "p2"))
    with pytest.raises(AvailabilityCensusError, match="상품별 AREA membership"):
        build_census_from_rows(QUERY_DATE, divergent)


def test_new_membership_rerun_is_idempotent_and_resolvable(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        institution_id = _institution(session, "001")
        first = reconcile_fsb_availability(session, _census({"001": {"YN_Busan"}}), now=T0)
        assert (first.created, first.unchanged) == (1, 0)

    with session_scope(factory) as session:
        second = reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Busan"}}),
            now=T0 + timedelta(days=1),
        )
        assert (second.created, second.unchanged, second.expired) == (0, 1, 0)
        row = session.scalar(select(InstitutionAvailabilityMembership))
        assert row.seen_count == 2
        assert row.valid_to is None
        assert row.evidence_json["source_entity_keys"] == [_org_key("001")]
        assert resolve_active_institutions(
            session, "fsb:term_deposit:area:YN_Busan"
        ) == frozenset({institution_id})
        with pytest.raises(ValueError, match="지원하지 않는 availability_match_key"):
            resolve_active_institutions(session, "legacy:nationwide")


def test_region_add_expire_and_reappear_preserve_history(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001")
        reconcile_fsb_availability(session, _census({"001": {"YN_Busan"}}), now=T0)

    with session_scope(factory) as session:
        added = reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Busan", "YN_Seoul"}}),
            now=T0 + timedelta(days=1),
        )
        assert (added.created, added.unchanged, added.expired) == (1, 1, 0)

    with session_scope(factory) as session:
        removed = reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Seoul"}}),
            now=T0 + timedelta(days=2),
        )
        assert removed.expired == 1
        busan = session.scalar(
            select(InstitutionAvailabilityMembership).where(
                InstitutionAvailabilityMembership.area_code == "YN_Busan"
            )
        )
        assert busan.valid_to == T0 + timedelta(days=2)
        assert busan.evidence_json["expired_by_query_date"] == QUERY_DATE.isoformat()

    with session_scope(factory) as session:
        reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Busan", "YN_Seoul"}}),
            now=T0 + timedelta(days=3),
        )
        busan_rows = session.scalars(
            select(InstitutionAvailabilityMembership).where(
                InstitutionAvailabilityMembership.area_code == "YN_Busan"
            )
        ).all()
        assert len(busan_rows) == 2
        assert sum(row.valid_to is None for row in busan_rows) == 1


def test_older_census_cannot_rewind_current_membership(factory) -> None:
    newer = QUERY_DATE + timedelta(days=1)
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001")
        reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Busan"}}, when=newer),
            now=T0,
        )

    with (
        pytest.raises(AvailabilityCensusError, match="되감을 수 없다"),
        session_scope(factory) as session,
    ):
        reconcile_fsb_availability(
            session,
            _census({"001": {"YN_Seoul"}}, when=QUERY_DATE),
            now=T0 + timedelta(days=1),
        )

    with session_scope(factory) as session:
        row = session.scalar(
            select(InstitutionAvailabilityMembership).where(
                InstitutionAvailabilityMembership.valid_to.is_(None)
            )
        )
        assert row.area_code == "YN_Busan"
        assert row.source_effective_date == newer


def test_unresolved_nonexact_and_inactive_identity_fail_closed(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001", match_method="manual_name")

    with (
        pytest.raises(AvailabilityCensusError, match="not exact_code"),
        session_scope(factory) as session,
    ):
        reconcile_fsb_availability(session, _census({"001": {"YN_Busan"}}), now=T0)

    with session_scope(factory) as session:
        link = session.scalar(select(SourceEntityLink))
        link.match_method = "exact_code"
        link.valid_to = QUERY_DATE

    with (
        pytest.raises(AvailabilityCensusError, match="active_links=0"),
        session_scope(factory) as session,
    ):
        reconcile_fsb_availability(session, _census({"001": {"YN_Busan"}}), now=T0)

    with (
        pytest.raises(AvailabilityCensusError, match="active_links=0"),
        session_scope(factory) as session,
    ):
        reconcile_fsb_availability(session, _census({"999": {"YN_Seoul"}}), now=T0)


def test_source_identity_active_link_is_database_unique(factory) -> None:
    session = factory()
    try:
        _source(session)
        _institution(session, "001")
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
                source_entity_key=_org_key("001"),
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
    finally:
        session.close()


def test_fetch_failure_before_transaction_preserves_existing_membership(factory) -> None:
    with session_scope(factory) as session:
        _source(session)
        _institution(session, "001")
        reconcile_fsb_availability(session, _census({"001": {"YN_Busan"}}), now=T0)

    async def timeout(_when: date) -> AvailabilityCensus:
        raise httpx.ReadTimeout("one AREA timed out")

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(sync_fsb_availability(factory, as_of=QUERY_DATE, fetch_census=timeout))

    async def schema_error(_when: date) -> AvailabilityCensus:
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
        reconcile_fsb_availability(session, _census({"001": {"YN_Busan"}}), now=T0)

    with session_scope(factory) as session:
        after = (
            session.scalar(select(func.count()).select_from(Product)),
            session.scalar(select(func.count()).select_from(ProductVariant)),
            session.scalar(select(func.count()).select_from(RateObservation)),
        )
        assert after == before == (1, 1, 0)
        assert session.scalar(select(ProductVariant)).variant_key == "legacy-rate-axis"
