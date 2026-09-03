"""Regression tests for immutable Strategy special-offer reads."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from rate_monitor.db.models import Base, Institution, Product, Source, SourceEntityLink
from rate_monitor.db.session import (
    create_db_engine,
    create_readonly_db_engine,
    make_session_factory,
    session_scope,
)
from rate_monitor.services.special_offer_evidence_service import (
    SOURCE_SNAPSHOT,
    UNKNOWN,
    SpecialOfferEvidenceInput,
    append_special_offer_evidence,
)
from rate_monitor.services.special_offer_radar_service import build_special_offer_radar

DAY = date(2026, 9, 4)
NOW = datetime(2026, 9, 4, 1, 0, 0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frozen_radar_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "radar-readonly.sqlite3"
    engine = create_db_engine(db_path)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        session.add(
            Source(
                id="fsb",
                name="저축은행중앙회",
                sector="savings_bank",
                mode="http",
                source_role="primary_official",
                trust_level="official_direct",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        institution = Institution(
            id="institution-1",
            sector="savings_bank",
            canonical_name="테스트저축은행",
            normalized_name="테스트저축은행",
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        product = Product(
            id="product-1",
            institution_id=institution.id,
            product_type="term_deposit",
            name="정기예금",
            normalized_name="정기예금",
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        session.add_all([institution, product])
        session.add(
            SourceEntityLink(
                source_id="fsb",
                entity_type="product",
                source_entity_key="institution-1:source-product-1",
                entity_id=product.id,
                source_name=product.name,
                match_method="exact_code",
                valid_from=DAY,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        append_special_offer_evidence(
            session,
            SpecialOfferEvidenceInput(
                source_id="fsb",
                product_id=product.id,
                source_product_key="source-product-1",
                classification=UNKNOWN,
                evidence_kind=SOURCE_SNAPSHOT,
                snapshot_as_of=DAY,
                observed_at=NOW,
                source_locator="$.REC[0]",
                evidence_ref="https://bank.example/products/1",
                content_hash="sha256:readonly-regression",
                evidence={"identity_scope": "exact_product"},
            ),
        )
    engine.dispose()

    # Mirror snapshot_service: the canonical deployable is a self-contained
    # DELETE-journal SQLite file whose bytes are locked by a manifest SHA.
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        conn.commit()
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    return db_path


def test_special_offer_radar_preserves_snapshot_bytes_and_journal_mode(
    tmp_path: Path,
) -> None:
    db_path = _frozen_radar_db(tmp_path)
    before = _sha256(db_path)

    payload = build_special_offer_radar(db_path)

    assert payload["counts"][UNKNOWN] == 1
    assert payload["offers"] == []
    assert _sha256(db_path) == before
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        conn.close()
    assert not db_path.with_name(db_path.name + "-wal").exists()
    assert not db_path.with_name(db_path.name + "-shm").exists()


def test_readonly_engine_rejects_writes_without_changing_bytes(tmp_path: Path) -> None:
    db_path = _frozen_radar_db(tmp_path)
    before = _sha256(db_path)
    engine = create_readonly_db_engine(db_path)
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM products").scalar_one() == 1
            with pytest.raises(OperationalError):
                conn.exec_driver_sql("DELETE FROM products")
    finally:
        engine.dispose()

    assert _sha256(db_path) == before
