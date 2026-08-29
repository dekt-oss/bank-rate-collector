from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from rate_monitor.collectors.cu.funding import (
    IDENTITY_STATUS,
    SOURCE_ID,
    SOURCE_UNIT,
    CuFundingContractError,
    CuFundingPoint,
    DisclosureRecord,
    _ensure_source,
    _targets,
    _upsert_point,
    parse_summary_point,
    select_latest_disclosures,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope


def _disclosure(
    *,
    year: int = 2025,
    disclosure_no: int = 22820,
    disclosure_type: str = "1",
) -> DisclosureRecord:
    return DisclosureRecord(
        cu_ingno="02002",
        disclosure_no=disclosure_no,
        disclosure_type=disclosure_type,
        disclosure_name=(
            f"{year}년도 결산정기공시"
            if disclosure_type == "1"
            else f"{year}년도 상반기 경영공시"
        ),
        reg_date="2026-02-10",
        short_file_name="summary.pdf",
        year=year,
        month=12 if disclosure_type == "1" else 6,
    )


def _summary_html(
    *,
    year: int = 2025,
    prior: int = 2024,
    label: str = "예 수 부 채",
    amount: str = "1,720,194",
    unit: str = "백만원",
) -> str:
    return f"""
    <html><body>
      <div>단위 : {unit}</div>
      <table>
        <tr>
          <th>구분</th><th>{year}년도</th><th>{prior}년도</th><th>증감</th>
        </tr>
        <tr>
          <th></th><th>금액</th><th>구성비</th><th>금액</th>
          <th>구성비</th><th>금액</th><th>증감율</th>
        </tr>
        <tr>
          <td>현금및예치금</td><td>227,264</td><td>11.74</td><td>188,554</td>
          <td>12.59</td><td>38,710</td><td>20.53</td>
        </tr>
        <tr>
          <td>{label}</td><td>{amount}</td><td>88.85</td><td>1,313,185</td>
          <td>87.66</td><td>407,009</td><td>30.99</td>
        </tr>
        <tr>
          <td>부 채 계</td><td>1,761,416</td><td>90.98</td><td>1,341,937</td>
          <td>89.57</td><td>419,479</td><td>31.26</td>
        </tr>
      </table>
    </body></html>
    """


def test_summary_parser_accepts_source_spacing_but_exact_account_semantics() -> None:
    point = parse_summary_point(
        _summary_html(),
        disclosure=_disclosure(),
        institution_id="inst-1",
        institution_name="광안",
        source_locator="https://example.test/summary",
    )

    assert point.cu_ingno == "02002"
    assert point.source_effective_month == "2025-12"
    assert point.value == Decimal("1720194.000000")
    assert point.source_value_text == "1,720,194"
    assert point.period_end.isoformat() == "2025-12-31"


def test_summary_parser_half_year_uses_june_period() -> None:
    point = parse_summary_point(
        _summary_html(year=2026, prior=2025, amount="6,460"),
        disclosure=_disclosure(
            year=2026,
            disclosure_no=25111,
            disclosure_type="2",
        ),
        institution_id="inst-2",
        institution_name="HJ중공업",
        source_locator="https://example.test/summary",
    )

    assert point.source_effective_month == "2026-06"
    assert point.period_end.isoformat() == "2026-06-30"
    assert point.value == Decimal("6460.000000")


def test_summary_parser_rejects_wrong_unit() -> None:
    with pytest.raises(CuFundingContractError, match="백만원"):
        parse_summary_point(
            _summary_html(unit="억원"),
            disclosure=_disclosure(),
            institution_id="inst-1",
            institution_name="광안",
            source_locator="https://example.test/summary",
        )


def test_summary_parser_rejects_non_exact_deposit_account() -> None:
    with pytest.raises(CuFundingContractError, match="정확히 1개"):
        parse_summary_point(
            _summary_html(label="부 채 계"),
            disclosure=_disclosure(),
            institution_id="inst-1",
            institution_name="광안",
            source_locator="https://example.test/summary",
        )


def test_summary_parser_rejects_header_year_mismatch() -> None:
    with pytest.raises(CuFundingContractError, match="header 불일치"):
        parse_summary_point(
            _summary_html(year=2024, prior=2023),
            disclosure=_disclosure(year=2025),
            institution_id="inst-1",
            institution_name="광안",
            source_locator="https://example.test/summary",
        )


def _list_row(
    *,
    disclosure_no: int,
    disclosure_type: str,
    disclosure_name: str,
    bogo_ty: str = "Y",
) -> dict[str, object]:
    return {
        "cuIngno": "02002",
        "disclosureNo": disclosure_no,
        "disclosureTy": disclosure_type,
        "disclosureName": disclosure_name,
        "regDate": "2026-02-01",
        "shortFileName": "summary.pdf",
        "bogoTy": bogo_ty,
        "chkYn3": "Y",
    }


def test_disclosure_selection_uses_reporting_period_and_latest_correction() -> None:
    rows = [
        _list_row(
            disclosure_no=100,
            disclosure_type="1",
            disclosure_name="2025년도 결산정기공시",
        ),
        _list_row(
            disclosure_no=101,
            disclosure_type="1",
            disclosure_name="2025년도 결산정기공시",
        ),
        _list_row(
            disclosure_no=90,
            disclosure_type="2",
            disclosure_name="2025년도 상반기 경영공시",
        ),
        _list_row(
            disclosure_no=999,
            disclosure_type="3",
            disclosure_name="2025년도 수시공시",
        ),
    ]

    selected = select_latest_disclosures(rows, cu_ingno="02002", periods=2)

    assert [(item.source_effective_month, item.disclosure_no) for item in selected] == [
        ("2025-12", 101),
        ("2025-06", 90),
    ]


def test_non_report_summary_is_not_selected() -> None:
    rows = [
        _list_row(
            disclosure_no=24856,
            disclosure_type="2",
            disclosure_name="2026년도 상반기 결산공시",
            bogo_ty="N",
        ),
        _list_row(
            disclosure_no=22820,
            disclosure_type="1",
            disclosure_name="2025년도 결산정기공시",
        ),
    ]

    selected = select_latest_disclosures(rows, cu_ingno="02002", periods=1)

    assert selected[0].source_effective_month == "2025-12"
    assert selected[0].disclosure_no == 22820


def _source(source_id: str, now: datetime) -> m.Source:
    return m.Source(
        id=source_id,
        name=source_id,
        sector="cu",
        mode="http",
        source_role="primary_official",
        trust_level="official_direct",
        priority=10,
        enabled=True,
        policy_status="review",
        coverage_status="partial",
        parser_version="1",
        created_at=now,
        updated_at=now,
    )


def _seed_exact_cu_link(factory, now: datetime) -> tuple[str, str]:
    with session_scope(factory) as session:
        session.add(_source("cu", now))
        institution = m.Institution(
            sector="cu",
            canonical_name="광안신협",
            normalized_name="광안신협",
            active=True,
            availability_scope="local_members",
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(institution)
        session.flush()
        institution_id = institution.id
        session.add(
            m.SourceEntityLink(
                source_id="cu",
                entity_type="institution",
                source_entity_key="cu:02002",
                entity_id=institution.id,
                source_name="광안",
                confidence=1.0,
                match_method="exact_code",
                valid_from=None,
                valid_to=None,
                created_at=now,
                updated_at=now,
            )
        )
    return institution_id, "02002"


def _raw(factory, now: datetime) -> str:
    with session_scope(factory) as session:
        _ensure_source(session, now)
        run = m.CollectionRun(
            source_id=SOURCE_ID,
            mode="http",
            started_at=now,
            status="success",
        )
        session.add(run)
        session.flush()
        raw = m.RawArtifact(
            run_id=run.id,
            artifact_type="html",
            relative_path="data/raw/cu-summary.html",
            sha256="a" * 64,
            content_length=10,
            encoding="utf-8",
            request_meta_json={},
            captured_at=now,
        )
        session.add(raw)
        session.flush()
        return raw.id


def _point(
    institution_id: str,
    value: Decimal = Decimal("1720194"),
) -> CuFundingPoint:
    return CuFundingPoint(
        institution_id=institution_id,
        cu_ingno="02002",
        institution_name="광안",
        source_effective_month="2025-12",
        period_start=datetime(2025, 12, 1).date(),
        period_end=datetime(2025, 12, 31).date(),
        value=value,
        source_value_text=f"{value}",
        disclosure_no=22820,
        disclosure_type="1",
        source_locator="https://example.test/summary",
    )


def test_exact_link_target_and_funding_revision_are_idempotent(tmp_path) -> None:
    db_path = tmp_path / "funding.sqlite3"
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 29, 2, 0, 0)
    institution_id, cu_ingno = _seed_exact_cu_link(factory, now)
    raw_id = _raw(factory, now)

    assert _targets(factory, {cu_ingno}) == [("02002", institution_id, "광안")]

    with session_scope(factory) as session:
        action = _upsert_point(
            session,
            _point(institution_id),
            raw_artifact_id=raw_id,
            now=now,
        )
        assert action == "stored"
    with session_scope(factory) as session:
        action = _upsert_point(
            session,
            _point(institution_id),
            raw_artifact_id=raw_id,
            now=now,
        )
        assert action == "unchanged"
    with session_scope(factory) as session:
        action = _upsert_point(
            session,
            _point(institution_id, Decimal("1720200")),
            raw_artifact_id=raw_id,
            now=datetime(2026, 8, 29, 3, 0, 0),
        )
        assert action == "revision"

    with session_scope(factory) as session:
        observations = list(
            session.scalars(
                select(InstitutionFundingObservation).order_by(
                    InstitutionFundingObservation.revision
                )
            )
        )
        active = session.scalar(
            select(func.count())
            .select_from(InstitutionFundingObservation)
            .where(InstitutionFundingObservation.valid_to.is_(None))
        )
    assert len(observations) == 2
    assert active == 1
    assert observations[0].valid_to is not None
    assert observations[1].revision == 2
    assert observations[1].institution_id == institution_id
    assert observations[1].identity_status == IDENTITY_STATUS
    assert observations[1].source_unit == SOURCE_UNIT
    assert observations[1].unit == "million_krw"


def test_target_resolution_fails_when_requested_exact_link_is_missing(tmp_path) -> None:
    db_path = tmp_path / "funding.sqlite3"
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 29, 2, 0, 0)
    _seed_exact_cu_link(factory, now)

    with pytest.raises(CuFundingContractError, match="active CU source link가 없다"):
        _targets(factory, {"99999"})
