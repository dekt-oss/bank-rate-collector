"""Strategy special-offer Radar fail-closed contract."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from rate_monitor.db.models import (
    Base,
    CollectionRun,
    Institution,
    Product,
    ProductVariant,
    RateObservation,
    RawArtifact,
    Source,
    SourceEntityLink,
)
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.services.special_offer_evidence_service import (
    CONFIRMED_NORMAL,
    CONFIRMED_SPECIAL,
    EXPLICIT_SOURCE_FIELD,
    SOURCE_SNAPSHOT,
    UNKNOWN,
    SpecialOfferEvidenceInput,
    append_special_offer_evidence,
)
from rate_monitor.services.special_offer_radar_presentation import (
    SCRIPT_MARKER,
    STYLE_MARKER,
    inject_special_offer_radar_presentation,
)
from rate_monitor.services.special_offer_radar_service import (
    RADAR_ACTIVATION,
    build_special_offer_radar,
)

DAY = date(2026, 9, 3)
T0 = datetime(2026, 9, 3, 1, 0, 0)


def _db(tmp_path: Path) -> tuple[Path, object]:
    db_path = tmp_path / "radar.sqlite3"
    engine = create_db_engine(db_path)
    Base.metadata.create_all(engine)
    return db_path, make_session_factory(engine)


def _seed(session) -> None:
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


def _seed_current_fsb_rate(session, *, rate: Decimal = Decimal("4.25")) -> None:
    run = CollectionRun(
        id="run-1",
        source_id="fsb",
        mode="http",
        started_at=T0,
        finished_at=T0,
        status="success",
    )
    artifact = RawArtifact(
        id="artifact-1",
        run_id=run.id,
        artifact_type="json",
        relative_path="fsb/test.json",
        sha256="a" * 64,
        content_length=2,
        captured_at=T0,
    )
    variant = ProductVariant(
        id="variant-1",
        product_id="product-1",
        term_months=12,
        join_channel="online",
        interest_method="simple",
        rate_scope="published",
        variant_key="variant-1",
    )
    observation = RateObservation(
        id="observation-1",
        variant_id=variant.id,
        run_id=run.id,
        last_run_id=run.id,
        raw_artifact_id=artifact.id,
        as_of=DAY,
        observed_at=T0,
        base_rate=Decimal("4.00"),
        max_rate=rate,
        source_detail_json={},
        raw_preference_text="",
        validation_status="valid",
        content_hash="sha256:rate",
        base_source_locator="$.REC[0]",
        source_record_hash="sha256:source-rate",
        source_effective_at=DAY,
    )
    session.add_all([run, artifact, variant, observation])
    session.flush()


def _evidence(
    classification: str,
    *,
    observed_at: datetime = T0,
    content_hash: str,
) -> SpecialOfferEvidenceInput:
    confirming = classification != UNKNOWN
    return SpecialOfferEvidenceInput(
        source_id="fsb",
        product_id="product-1",
        source_product_key="source-product-1",
        classification=classification,
        evidence_kind=EXPLICIT_SOURCE_FIELD if confirming else SOURCE_SNAPSHOT,
        snapshot_as_of=DAY,
        observed_at=observed_at,
        source_locator="$.REC[0]",
        evidence_ref="https://bank.example/products/1",
        content_hash=content_hash,
        evidence={
            "identity_scope": "exact_product",
            **({"explicit_assertion": classification} if confirming else {}),
        },
    )


def _seed_other_source_special(session) -> None:
    session.add(
        Source(
            id="other_official",
            name="다른 공식 원천",
            sector="savings_bank",
            mode="http",
            source_role="secondary_official",
            trust_level="official_direct",
            created_at=T0,
            updated_at=T0,
        )
    )
    session.add(
        SourceEntityLink(
            source_id="other_official",
            entity_type="product",
            source_entity_key="institution-1:other-product-1",
            entity_id="product-1",
            source_name="정기예금",
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
            source_id="other_official",
            product_id="product-1",
            source_product_key="other-product-1",
            classification=CONFIRMED_SPECIAL,
            evidence_kind=EXPLICIT_SOURCE_FIELD,
            snapshot_as_of=DAY,
            observed_at=T0,
            source_locator="$.other[0]",
            evidence_ref="https://other.example/products/1",
            content_hash="sha256:other-source",
            evidence={
                "identity_scope": "exact_product",
                "explicit_assertion": CONFIRMED_SPECIAL,
            },
        ),
    )


def test_missing_registry_is_safe_unavailable(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    engine = create_db_engine(db_path)
    # Simulate a legacy/partial Strategy fixture without special-offer tables.
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE institutions (id TEXT PRIMARY KEY)")
    engine.dispose()

    payload = build_special_offer_radar(db_path)
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "evidence_registry_missing"
    assert payload["offers"] == []
    assert payload["policy"]["unknown_is_special"] is False


def test_unknown_snapshot_never_becomes_radar_offer(tmp_path: Path) -> None:
    db_path, factory = _db(tmp_path)
    with session_scope(factory) as session:
        _seed(session)
        append_special_offer_evidence(
            session,
            _evidence(UNKNOWN, content_hash="sha256:unknown"),
        )

    payload = build_special_offer_radar(db_path)
    assert payload["status"] == "collecting_confirmed_evidence"
    assert payload["counts"][UNKNOWN] == 1
    assert payload["counts"][CONFIRMED_SPECIAL] == 0
    assert payload["offers"] == []
    assert payload["activation"] == RADAR_ACTIVATION


def test_other_source_confirmation_cannot_promote_fsb_unknown(tmp_path: Path) -> None:
    db_path, factory = _db(tmp_path)
    with session_scope(factory) as session:
        _seed(session)
        append_special_offer_evidence(
            session,
            _evidence(UNKNOWN, content_hash="sha256:unknown"),
        )
        _seed_other_source_special(session)

    payload = build_special_offer_radar(db_path)
    assert payload["source_id"] == "fsb"
    assert payload["counts"][UNKNOWN] == 1
    assert payload["counts"][CONFIRMED_SPECIAL] == 0
    assert payload["offers"] == []


def test_only_explicit_confirmed_special_enters_radar_with_current_fsb_rate(
    tmp_path: Path,
) -> None:
    db_path, factory = _db(tmp_path)
    reviewed_at = T0 + timedelta(hours=1)
    with session_scope(factory) as session:
        _seed(session)
        _seed_current_fsb_rate(session)
        append_special_offer_evidence(
            session,
            _evidence(UNKNOWN, content_hash="sha256:unknown"),
        )
        append_special_offer_evidence(
            session,
            _evidence(
                CONFIRMED_SPECIAL,
                observed_at=reviewed_at,
                content_hash="sha256:special",
            ),
        )

    payload = build_special_offer_radar(db_path)
    assert payload["status"] == "confirmed_evidence_available"
    assert payload["counts"][CONFIRMED_SPECIAL] == 1
    assert payload["counts"][UNKNOWN] == 0
    assert len(payload["offers"]) == 1
    assert payload["offers"][0]["institution_name"] == "테스트저축은행"
    assert payload["offers"][0]["product_name"] == "정기예금"
    assert payload["offers"][0]["representative_rate"] == 4.25
    assert payload["offers"][0]["term_months"] == 12
    assert payload["offers"][0]["join_channel"] == "online"
    assert payload["policy"]["ranking_population_changed"] is False


def test_confirmed_normal_and_conflict_are_excluded(tmp_path: Path) -> None:
    db_path, factory = _db(tmp_path)
    with session_scope(factory) as session:
        _seed(session)
        append_special_offer_evidence(
            session,
            _evidence(CONFIRMED_NORMAL, content_hash="sha256:normal"),
        )

    normal = build_special_offer_radar(db_path)
    assert normal["counts"][CONFIRMED_NORMAL] == 1
    assert normal["offers"] == []

    # A same-time contradictory assertion must close to unknown/conflict, not pick one.
    with session_scope(factory) as session:
        append_special_offer_evidence(
            session,
            _evidence(CONFIRMED_SPECIAL, content_hash="sha256:special"),
        )
    conflict = build_special_offer_radar(db_path)
    assert conflict["counts"]["conflict"] == 1
    assert conflict["counts"][UNKNOWN] == 1
    assert conflict["offers"] == []


def test_radar_presentation_is_read_only_and_idempotent() -> None:
    html = (
        '<html><head></head><body><script id="rate-monitor-data" type="application/json">'
        '{"strategy":{"special_offer_radar":{"counts":{"unknown":3,'
        '"confirmed_special":0,"confirmed_normal":0,"conflict":0},"offers":[]}}}'
        '</script><section id="market-flow"></section></body></html>'
    )
    rendered = inject_special_offer_radar_presentation(html)
    assert STYLE_MARKER in rendered
    assert SCRIPT_MARKER in rendered
    assert "시장 특판 Radar" in rendered
    assert "unknown" in rendered
    assert "<form" not in rendered.lower()
    assert 'type="submit"' not in rendered.lower()
    assert "append_operator_confirmation" not in rendered
    assert "^https?:" in rendered
    assert inject_special_offer_radar_presentation(rendered) == rendered
