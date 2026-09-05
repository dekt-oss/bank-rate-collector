from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from rate_monitor.collectors.data_go_funding import total_assets_persistence as persistence
from rate_monitor.collectors.data_go_funding.total_assets_evidence import (
    SAVINGS_BANK_SOURCE_ID,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.schemas import RawArtifactData


def _rows() -> list[dict[str, str]]:
    return [
        {
            "fncoCd": "001",
            "fncoNm": "A저축은행",
            "crno": "1101111234567",
            "basYm": "202512",
            "astSmryStfnpsAcitCd": "A",
            "astSmryStfnpsAcitCdNm": "자산총계",
            "astSmryStfnpsAcitCdAmt": "1000000",
        },
        {
            "fncoCd": "002",
            "fncoNm": "B저축은행",
            "crno": "1101117654321",
            "basYm": "202512",
            "astSmryStfnpsAcitCd": "A",
            "astSmryStfnpsAcitCdNm": "자산총계",
            "astSmryStfnpsAcitCdAmt": "2000000",
        },
        {
            "fncoCd": "030350S",
            "fncoNm": "저축은행",
            "basYm": "202512",
            "astSmryStfnpsAcitCd": "A",
            "astSmryStfnpsAcitCdNm": "자산총계",
            "astSmryStfnpsAcitCdAmt": "3000000",
        },
    ]


def _artifact() -> RawArtifactData:
    return RawArtifactData(
        artifact_type="json",
        content=b'{"asset":"fixture"}',
        filename="asset-fixture.json",
        request_meta={"metric": "total_assets", "basYm": "202512"},
        schema_fingerprint="fixture",
        source_role="secondary_official",
        trust_level="official_direct",
    )


def _prepare_db(path: Path) -> None:
    # Importing InstitutionFundingObservation above registers it on the shared Base.
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)


def test_asset_write_is_idempotent_and_does_not_supersede_funding(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "rate_monitor.sqlite3"
    raw_root = tmp_path / "raw"
    _prepare_db(db_path)

    monkeypatch.setattr(persistence, "_service_key", lambda contract: "secret")
    monkeypatch.setattr(
        persistence,
        "fetch_month",
        lambda client, *, contract, endpoint, key, bas_ym: (_rows(), [_artifact()]),
    )

    first = persistence.collect_total_assets_source(
        SAVINGS_BANK_SOURCE_ID,
        bas_ym="202512",
        db_path=db_path,
        raw_root=raw_root,
    )
    assert first.stored == 2
    assert first.revisions == 0
    assert first.aggregate_rows_validated == 1
    assert first.institution_rows == 2

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope(factory) as session:
        asset = session.scalar(
            select(InstitutionFundingObservation).where(
                InstitutionFundingObservation.metric_code == "total_assets",
                InstitutionFundingObservation.source_institution_key == "001",
                InstitutionFundingObservation.valid_to.is_(None),
            )
        )
        assert asset is not None
        session.add(
            InstitutionFundingObservation(
                institution_id=None,
                source_id=asset.source_id,
                source_institution_key=asset.source_institution_key,
                source_institution_name=asset.source_institution_name,
                source_crno=asset.source_crno,
                sector=asset.sector,
                metric_code="deposit_liabilities_total",
                metric_name="예수부채",
                source_effective_month=asset.source_effective_month,
                period_start=date(2025, 12, 1),
                period_end=date(2025, 12, 31),
                value=Decimal("0.500000"),
                unit="million_krw",
                source_value_text="500000",
                source_unit="krw",
                observation_basis="reported_period_end",
                statement_basis="source_reported_unconsolidated_unspecified",
                population_scope=asset.population_scope,
                identity_status="unmapped_no_exact_cross_source_code",
                observed_at=now,
                source_locator=asset.source_locator,
                raw_artifact_id=asset.raw_artifact_id,
                content_hash="sha256:funding-fixture",
                revision=1,
                valid_from=now,
                valid_to=None,
                created_at=now,
            )
        )

    second = persistence.collect_total_assets_source(
        SAVINGS_BANK_SOURCE_ID,
        bas_ym="2025-12",
        db_path=db_path,
        raw_root=raw_root,
    )
    assert second.stored == 0
    assert second.revisions == 0
    assert second.unchanged == 2

    with session_scope(factory) as session:
        active = list(
            session.scalars(
                select(InstitutionFundingObservation).where(
                    InstitutionFundingObservation.source_id == SAVINGS_BANK_SOURCE_ID,
                    InstitutionFundingObservation.source_institution_key == "001",
                    InstitutionFundingObservation.source_effective_month == "2025-12",
                    InstitutionFundingObservation.valid_to.is_(None),
                )
            )
        )
        assert {row.metric_code for row in active} == {
            "deposit_liabilities_total",
            "total_assets",
        }
        funding = next(row for row in active if row.metric_code == "deposit_liabilities_total")
        assert funding.revision == 1
        assert funding.content_hash == "sha256:funding-fixture"


def test_changed_asset_value_revises_only_asset_metric(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "rate_monitor.sqlite3"
    raw_root = tmp_path / "raw"
    _prepare_db(db_path)
    monkeypatch.setattr(persistence, "_service_key", lambda contract: "secret")

    rows = _rows()
    monkeypatch.setattr(
        persistence,
        "fetch_month",
        lambda client, *, contract, endpoint, key, bas_ym: (rows, [_artifact()]),
    )
    persistence.collect_total_assets_source(
        SAVINGS_BANK_SOURCE_ID,
        bas_ym="202512",
        db_path=db_path,
        raw_root=raw_root,
    )

    changed = _rows()
    changed[0]["astSmryStfnpsAcitCdAmt"] = "1500000"
    changed[2]["astSmryStfnpsAcitCdAmt"] = "3500000"
    monkeypatch.setattr(
        persistence,
        "fetch_month",
        lambda client, *, contract, endpoint, key, bas_ym: (changed, [_artifact()]),
    )
    result = persistence.collect_total_assets_source(
        SAVINGS_BANK_SOURCE_ID,
        bas_ym="202512",
        db_path=db_path,
        raw_root=raw_root,
    )
    assert result.revisions == 1
    assert result.unchanged == 1

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        versions = list(
            session.scalars(
                select(InstitutionFundingObservation)
                .where(
                    InstitutionFundingObservation.metric_code == "total_assets",
                    InstitutionFundingObservation.source_institution_key == "001",
                )
                .order_by(InstitutionFundingObservation.revision)
            )
        )
        assert [row.revision for row in versions] == [1, 2]
        assert versions[0].valid_to is not None
        assert versions[1].valid_to is None
        assert versions[1].value == Decimal("1.500000")
