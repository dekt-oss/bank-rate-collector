from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    FundingContractError,
    FundingPoint,
    _upsert_point,
    candidate_months,
    parse_points,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope


def _contract(sector: str):
    return next(contract for contract in CONTRACTS if contract.sector == sector)


def test_savings_bank_total_deposit_liability_deduplicates_subrows():
    contract = _contract("savings_bank")
    base = {
        "basYm": "202603",
        "fncoCd": "0010345",
        "fncoNm": "애큐온저축은행",
        "crno": "1101110126014",
        "dpsdbtDcd": "A11",
        "dpsdbtDcdNm": "예수부채",
        "dpsdbtClsfAmt": "13969690776494",
    }
    rows = [
        {**base, "tmsvdpDcdNm": "요구불예금"},
        {**base, "tmsvdpDcdNm": "저축성예금"},
    ]
    points = parse_points(contract, rows, endpoint="https://example.test/fina")
    assert len(points) == 1
    assert points[0].source_effective_month == "2026-03"
    assert points[0].period_end == date(2026, 3, 31)
    assert points[0].source_value_text == "13969690776494"
    assert points[0].value == Decimal("13969690.776494")


def test_savings_bank_conflicting_duplicate_fails_closed():
    contract = _contract("savings_bank")
    rows = [
        {
            "basYm": "202603",
            "fncoCd": "0010345",
            "fncoNm": "애큐온저축은행",
            "dpsdbtDcd": "A11",
            "dpsdbtDcdNm": "예수부채",
            "dpsdbtClsfAmt": "1000000",
        },
        {
            "basYm": "202603",
            "fncoCd": "0010345",
            "fncoNm": "애큐온저축은행",
            "dpsdbtDcd": "A11",
            "dpsdbtDcdNm": "예수부채",
            "dpsdbtClsfAmt": "2000000",
        },
    ]
    with pytest.raises(FundingContractError, match="서로 다르다"):
        parse_points(contract, rows, endpoint="https://example.test/fina")


def test_agri_central_is_excluded_from_local_population():
    contract = _contract("nh_local")
    rows = [
        {
            "basYm": "202506",
            "fncoCd": "0212450",
            "fncoNm": "농협중앙회",
            "crno": "",
            "astDebtSmryBlnshDcd": "A1",
            "astDebtSmryBlnshDcdNm": "예수부채",
            "astDebtSmryBlnshClsfAmt": "69865638868802",
        }
    ]
    point = parse_points(contract, rows, endpoint="https://example.test/fina")[0]
    assert point.population_scope == "agri_coop_central_excluded_from_local_sum"
    assert point.value == Decimal("69865638.868802")


def test_candidate_months_follow_source_cadence():
    savings = candidate_months(
        _contract("savings_bank"), 4, today=date(2026, 8, 27)
    )
    agri = candidate_months(_contract("nh_local"), 4, today=date(2026, 8, 27))
    assert savings == ["202606", "202603", "202512", "202509"]
    assert agri == ["202606", "202512", "202506", "202412"]


def _source(source_id: str, sector: str, now: datetime) -> m.Source:
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


def test_persistence_is_idempotent_and_revisioned():
    engine = create_db_engine(":memory:")
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 27, 12, 0, 0)

    with session_scope(factory) as session:
        session.add(_source("finlife_savings_bank", "savings_bank", now))
        session.add(_source("data_go_savings_bank_funding", "savings_bank", now))
        institution = m.Institution(
            sector="savings_bank",
            canonical_name="애큐온저축은행",
            normalized_name="애큐온저축은행",
            availability_scope="unknown",
            active=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(institution)
        session.flush()
        session.add(
            m.SourceEntityLink(
                source_id="finlife_savings_bank",
                entity_type="institution",
                source_entity_key="savings_bank:0010345",
                entity_id=institution.id,
                source_name="애큐온저축은행",
                confidence=1.0,
                match_method="exact_code",
                created_at=now,
                updated_at=now,
            )
        )
        run = m.CollectionRun(
            source_id="data_go_savings_bank_funding",
            mode="api",
            started_at=now,
            status="running",
        )
        session.add(run)
        session.flush()
        raw = m.RawArtifact(
            run_id=run.id,
            artifact_type="json",
            relative_path="data/raw/test.json",
            sha256="a" * 64,
            content_length=2,
            encoding="utf-8",
            request_meta_json={},
            captured_at=now,
        )
        session.add(raw)
        session.flush()
        raw_id = raw.id
        institution_id = institution.id

    point = FundingPoint(
        source_id="data_go_savings_bank_funding",
        sector="savings_bank",
        dataset_id="15061316",
        source_institution_key="0010345",
        source_institution_name="애큐온저축은행",
        source_crno="1101110126014",
        source_effective_month="2026-03",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        source_value_text="13969690776494",
        value=Decimal("13969690.776494"),
        population_scope="savings_banks_all_source_reported",
        source_locator="https://example.test/fina",
    )

    with session_scope(factory) as session:
        action, mapped = _upsert_point(
            session, point, raw_artifact_id=raw_id, now=now
        )
        assert action == "stored"
        assert mapped is True

    with session_scope(factory) as session:
        action, mapped = _upsert_point(
            session, point, raw_artifact_id=raw_id, now=now
        )
        assert action == "unchanged"
        assert mapped is True

    changed = FundingPoint(
        **{
            **point.__dict__,
            "source_value_text": "14000000000000",
            "value": Decimal("14000000.000000"),
        }
    )
    later = datetime(2026, 8, 28, 12, 0, 0)
    with session_scope(factory) as session:
        action, mapped = _upsert_point(
            session, changed, raw_artifact_id=raw_id, now=later
        )
        assert action == "revision"
        assert mapped is True

    with session_scope(factory) as session:
        rows = list(
            session.scalars(
                select(InstitutionFundingObservation).order_by(
                    InstitutionFundingObservation.revision
                )
            )
        )
        assert len(rows) == 2
        assert rows[0].valid_to == later
        assert rows[1].valid_to is None
        assert rows[1].revision == 2
        assert rows[1].institution_id == institution_id
        links = list(
            session.scalars(
                select(m.SourceEntityLink).where(
                    m.SourceEntityLink.source_id
                    == "data_go_savings_bank_funding"
                )
            )
        )
        assert len(links) == 1
        assert links[0].valid_from is None
        assert links[0].source_payload_json["crno"] == "1101110126014"


def test_name_only_does_not_auto_merge_identity():
    engine = create_db_engine(":memory:")
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 27, 12, 0, 0)

    with session_scope(factory) as session:
        session.add(_source("data_go_credit_union_funding", "cu", now))
        institution = m.Institution(
            sector="cu",
            canonical_name="대구태영",
            normalized_name="대구태영",
            availability_scope="unknown",
            active=True,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(institution)
        run = m.CollectionRun(
            source_id="data_go_credit_union_funding",
            mode="api",
            started_at=now,
            status="running",
        )
        session.add(run)
        session.flush()
        raw = m.RawArtifact(
            run_id=run.id,
            artifact_type="json",
            relative_path="data/raw/cu.json",
            sha256="b" * 64,
            content_length=2,
            captured_at=now,
        )
        session.add(raw)
        session.flush()
        raw_id = raw.id

    point = FundingPoint(
        source_id="data_go_credit_union_funding",
        sector="cu",
        dataset_id="15061337",
        source_institution_key="00106569130",
        source_institution_name="대구태영",
        source_crno="1101111441685",
        source_effective_month="2026-03",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        source_value_text="1000000",
        value=Decimal("1.000000"),
        population_scope="credit_unions_all_source_reported",
        source_locator="https://example.test/fina",
    )
    with session_scope(factory) as session:
        action, mapped = _upsert_point(
            session, point, raw_artifact_id=raw_id, now=now
        )
        assert action == "stored"
        assert mapped is False

    with session_scope(factory) as session:
        row = session.scalar(select(InstitutionFundingObservation))
        assert row.institution_id is None
        assert row.identity_status == "unmapped_no_exact_cross_source_code"
