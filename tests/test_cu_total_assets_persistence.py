from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from rate_monitor.collectors.cu.funding import (
    IDENTITY_STATUS,
    SOURCE_ID,
    CuFundingContractError,
    CuFundingPoint,
    _ensure_source,
    _upsert_point,
)
from rate_monitor.collectors.cu.total_assets_evidence import CuSizePairEvidence
from rate_monitor.collectors.cu.total_assets_persistence import (
    TOTAL_ASSETS_METRIC_CODE,
    persist_cu_total_assets_pairs,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope


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


def _seed_exact_target(factory, now: datetime) -> str:
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
    return institution_id


def _raw_id(factory, now: datetime) -> str:
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
            relative_path="data/raw/cu-funding-summary.html",
            sha256="a" * 64,
            content_length=10,
            encoding="utf-8",
            request_meta_json={},
            captured_at=now,
        )
        session.add(raw)
        session.flush()
        return raw.id


def _seed_funding(factory, institution_id: str, now: datetime, *, value: Decimal) -> None:
    raw_id = _raw_id(factory, now)
    point = CuFundingPoint(
        institution_id=institution_id,
        cu_ingno="02002",
        institution_name="광안",
        source_effective_month="2025-12",
        period_start=datetime(2025, 12, 1).date(),
        period_end=datetime(2025, 12, 31).date(),
        value=value,
        source_value_text=str(value),
        disclosure_no=22820,
        disclosure_type="1",
        source_locator="https://example.test/summary",
    )
    with session_scope(factory) as session:
        assert (
            _upsert_point(
                session,
                point,
                raw_artifact_id=raw_id,
                now=now,
            )
            == "stored"
        )


def _pair(
    institution_id: str,
    *,
    deposit: Decimal = Decimal("1720194"),
    assets: Decimal = Decimal("1936132"),
    content: bytes = b"official-cu-summary",
) -> CuSizePairEvidence:
    return CuSizePairEvidence(
        institution_id=institution_id,
        cu_ingno="02002",
        institution_name="광안",
        source_effective_month="2025-12",
        disclosure_no=22820,
        disclosure_type="1",
        deposit_liabilities_total=deposit,
        total_assets=assets,
        deposit_source_text=str(deposit),
        total_assets_source_text=str(assets),
        source_locator="https://example.test/summary",
        raw_sha256=hashlib.sha256(content).hexdigest(),
    )


def _write_pair_raw(root, pair: CuSizePairEvidence, content: bytes) -> None:
    root.mkdir(parents=True, exist_ok=True)
    filename = (
        f"cu-size-pair-{pair.cu_ingno}-{pair.source_effective_month}-"
        f"{pair.disclosure_no}.html"
    )
    (root / filename).write_bytes(content)


def _db(tmp_path):
    path = tmp_path / "candidate.sqlite3"
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)
    return path, make_session_factory(engine)


def test_candidate_persistence_is_metric_isolated_and_idempotent(tmp_path) -> None:
    db_path, factory = _db(tmp_path)
    now = datetime(2026, 9, 7, 4, 0, 0)
    institution_id = _seed_exact_target(factory, now)
    _seed_funding(factory, institution_id, now, value=Decimal("1720194"))
    evidence_root = tmp_path / "evidence"
    artifact_root = tmp_path / "raw"
    content = b"official-cu-summary"
    pair = _pair(institution_id, content=content)
    _write_pair_raw(evidence_root, pair, content)

    first = persist_cu_total_assets_pairs(
        db_path=db_path,
        evidence_raw_root=evidence_root,
        artifact_root=artifact_root,
        pairs=[pair],
    )
    second = persist_cu_total_assets_pairs(
        db_path=db_path,
        evidence_raw_root=evidence_root,
        artifact_root=artifact_root,
        pairs=[pair],
    )

    assert first.status == "success"
    assert (first.stored, first.revisions, first.unchanged) == (1, 0, 0)
    assert (second.stored, second.revisions, second.unchanged) == (0, 0, 1)

    with session_scope(factory) as session:
        funding = list(
            session.scalars(
                select(InstitutionFundingObservation).where(
                    InstitutionFundingObservation.metric_code == "deposit_liabilities_total"
                )
            )
        )
        assets = list(
            session.scalars(
                select(InstitutionFundingObservation).where(
                    InstitutionFundingObservation.metric_code == TOTAL_ASSETS_METRIC_CODE
                )
            )
        )
        raw = session.get(m.RawArtifact, assets[0].raw_artifact_id)
    assert len(funding) == 1
    assert funding[0].value == Decimal("1720194.000000")
    assert len(assets) == 1
    assert assets[0].value == Decimal("1936132.000000")
    assert assets[0].institution_id == institution_id
    assert assets[0].identity_status == IDENTITY_STATUS
    assert assets[0].source_id == SOURCE_ID
    assert assets[0].source_effective_month == "2025-12"
    assert assets[0].period_end.isoformat() == "2025-12-31"
    assert raw is not None
    assert raw.sha256 == hashlib.sha256(content).hexdigest()


def test_candidate_persistence_revisions_only_total_assets(tmp_path) -> None:
    db_path, factory = _db(tmp_path)
    now = datetime(2026, 9, 7, 4, 0, 0)
    institution_id = _seed_exact_target(factory, now)
    _seed_funding(factory, institution_id, now, value=Decimal("1720194"))
    evidence_root = tmp_path / "evidence"
    artifact_root = tmp_path / "raw"

    first_content = b"official-cu-summary-v1"
    first_pair = _pair(institution_id, assets=Decimal("1936132"), content=first_content)
    _write_pair_raw(evidence_root, first_pair, first_content)
    persist_cu_total_assets_pairs(
        db_path=db_path,
        evidence_raw_root=evidence_root,
        artifact_root=artifact_root,
        pairs=[first_pair],
    )

    second_content = b"official-cu-summary-v2"
    second_pair = _pair(institution_id, assets=Decimal("1936200"), content=second_content)
    _write_pair_raw(evidence_root, second_pair, second_content)
    result = persist_cu_total_assets_pairs(
        db_path=db_path,
        evidence_raw_root=evidence_root,
        artifact_root=artifact_root,
        pairs=[second_pair],
    )

    assert (result.stored, result.revisions, result.unchanged) == (0, 1, 0)
    with session_scope(factory) as session:
        funding_count = session.scalar(
            select(func.count())
            .select_from(InstitutionFundingObservation)
            .where(InstitutionFundingObservation.metric_code == "deposit_liabilities_total")
        )
        asset_rows = list(
            session.scalars(
                select(InstitutionFundingObservation)
                .where(InstitutionFundingObservation.metric_code == TOTAL_ASSETS_METRIC_CODE)
                .order_by(InstitutionFundingObservation.revision)
            )
        )
    assert funding_count == 1
    assert len(asset_rows) == 2
    assert asset_rows[0].valid_to is not None
    assert asset_rows[1].valid_to is None
    assert asset_rows[1].revision == 2
    assert asset_rows[1].value == Decimal("1936200.000000")


def test_candidate_persistence_fails_when_same_period_funding_is_missing(tmp_path) -> None:
    db_path, factory = _db(tmp_path)
    institution_id = _seed_exact_target(factory, datetime(2026, 9, 7, 4, 0, 0))
    content = b"official-cu-summary"
    pair = _pair(institution_id, content=content)
    evidence_root = tmp_path / "evidence"
    _write_pair_raw(evidence_root, pair, content)

    with pytest.raises(CuFundingContractError, match="정확히 1개"):
        persist_cu_total_assets_pairs(
            db_path=db_path,
            evidence_raw_root=evidence_root,
            artifact_root=tmp_path / "raw",
            pairs=[pair],
        )


def test_candidate_persistence_fails_when_deposit_value_does_not_match_disclosure(tmp_path) -> None:
    db_path, factory = _db(tmp_path)
    now = datetime(2026, 9, 7, 4, 0, 0)
    institution_id = _seed_exact_target(factory, now)
    _seed_funding(factory, institution_id, now, value=Decimal("1720194"))
    content = b"official-cu-summary"
    pair = _pair(institution_id, deposit=Decimal("1720200"), content=content)
    evidence_root = tmp_path / "evidence"
    _write_pair_raw(evidence_root, pair, content)

    with pytest.raises(CuFundingContractError, match="deposit 값 불일치"):
        persist_cu_total_assets_pairs(
            db_path=db_path,
            evidence_raw_root=evidence_root,
            artifact_root=tmp_path / "raw",
            pairs=[pair],
        )


def test_candidate_persistence_fails_on_raw_hash_mismatch(tmp_path) -> None:
    db_path, factory = _db(tmp_path)
    now = datetime(2026, 9, 7, 4, 0, 0)
    institution_id = _seed_exact_target(factory, now)
    _seed_funding(factory, institution_id, now, value=Decimal("1720194"))
    pair = _pair(institution_id, content=b"expected")
    evidence_root = tmp_path / "evidence"
    _write_pair_raw(evidence_root, pair, b"tampered")

    with pytest.raises(CuFundingContractError, match="SHA256 불일치"):
        persist_cu_total_assets_pairs(
            db_path=db_path,
            evidence_raw_root=evidence_root,
            artifact_root=tmp_path / "raw",
            pairs=[pair],
        )


def test_candidate_persistence_fails_on_exact_link_identity_mismatch(tmp_path) -> None:
    db_path, factory = _db(tmp_path)
    now = datetime(2026, 9, 7, 4, 0, 0)
    institution_id = _seed_exact_target(factory, now)
    _seed_funding(factory, institution_id, now, value=Decimal("1720194"))
    content = b"official-cu-summary"
    pair = _pair("different-institution", content=content)
    evidence_root = tmp_path / "evidence"
    _write_pair_raw(evidence_root, pair, content)

    with pytest.raises(CuFundingContractError, match="exact link identity 불일치"):
        persist_cu_total_assets_pairs(
            db_path=db_path,
            evidence_raw_root=evidence_root,
            artifact_root=tmp_path / "raw",
            pairs=[pair],
        )
