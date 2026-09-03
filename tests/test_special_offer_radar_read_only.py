"""Regression coverage for byte-stable Strategy Radar reads."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime
from pathlib import Path

from rate_monitor.db.models import Base, Institution, Product, Source, SourceEntityLink
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.services.special_offer_evidence_service import (
    SOURCE_SNAPSHOT,
    UNKNOWN,
    SpecialOfferEvidenceInput,
    append_special_offer_evidence,
)
from rate_monitor.services.special_offer_radar_service import build_special_offer_radar

DAY = date(2026, 9, 3)
T0 = datetime(2026, 9, 3, 1, 0, 0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_radar_read_does_not_change_publish_snapshot_bytes(tmp_path: Path) -> None:
    db_path = tmp_path / "publish.sqlite3"
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
                created_at=T0,
                updated_at=T0,
            )
        )
        institution = Institution(
            id="institution-1",
            sector="savings_bank",
            canonical_name="테스트저축은행",
            normalized_name="테스트저축은행",
            first_seen_at=T0,
            last_seen_at=T0,
        )
        product = Product(
            id="product-1",
            institution_id=institution.id,
            product_type="term_deposit",
            name="정기예금",
            normalized_name="정기예금",
            first_seen_at=T0,
            last_seen_at=T0,
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
                created_at=T0,
                updated_at=T0,
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
                observed_at=T0,
                source_locator="$.REC[0]",
                evidence_ref="https://bank.example/products/1",
                content_hash="sha256:unknown",
                evidence={"identity_scope": "exact_product"},
            ),
        )

    engine.dispose()

    # A publish snapshot is expected to remain byte-stable after its manifest hash
    # is recorded. Normalize this fixture to DELETE mode so a reader that switches
    # it back to WAL reproduces the production failure caught by verify_gate.py.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    finally:
        conn.close()

    before = _sha256(db_path)
    payload = build_special_offer_radar(db_path)
    after = _sha256(db_path)

    assert payload["counts"][UNKNOWN] == 1
    assert payload["offers"] == []
    assert before == after

    check = sqlite3.connect(db_path)
    try:
        assert check.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        check.close()
