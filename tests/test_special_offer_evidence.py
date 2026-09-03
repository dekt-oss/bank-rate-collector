"""Forward-only 상품 특판 evidence registry 계약."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from rate_monitor.db.models import Base, Institution, Product, Source, SourceEntityLink
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.special_offer_models import ProductSpecialOfferEvidence
from rate_monitor.services.special_offer_evidence_service import (
    CONFIRMED_NORMAL,
    CONFIRMED_SPECIAL,
    EXPLICIT_SOURCE_FIELD,
    SOURCE_SNAPSHOT,
    UNKNOWN,
    VERSIONED_PRODUCT_SCOPE,
    SpecialOfferEvidenceError,
    SpecialOfferEvidenceInput,
    append_special_offer_evidence,
    resolve_special_offer_state,
)

DAY = date(2026, 9, 3)
T0 = datetime(2026, 9, 3, 1, 0, 0)


@pytest.fixture
def factory(tmp_path):
    engine = create_db_engine(tmp_path / "special-offer.sqlite3")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _seed(session, *, match_method: str = "exact_code") -> str:
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
            match_method=match_method,
            valid_from=DAY,
            created_at=T0,
            updated_at=T0,
        )
    )
    session.flush()
    return product.id


def _item(
    *,
    classification: str = UNKNOWN,
    kind: str = SOURCE_SNAPSHOT,
    observed_at: datetime = T0,
    snapshot_as_of: date = DAY,
    effective_from: date | None = None,
    content_hash: str = "sha256:source-row",
) -> SpecialOfferEvidenceInput:
    evidence = {"identity_scope": "exact_product"}
    if classification != UNKNOWN:
        evidence["explicit_assertion"] = classification
    return SpecialOfferEvidenceInput(
        source_id="fsb",
        product_id="product-1",
        source_product_key="source-product-1",
        classification=classification,
        evidence_kind=kind,
        snapshot_as_of=snapshot_as_of,
        observed_at=observed_at,
        source_locator="$.REC[0]",
        evidence_ref="https://bank.example/products/1",
        content_hash=content_hash,
        source_effective_from=effective_from,
        evidence=evidence,
    )


def test_unknown_is_not_false_and_identical_append_is_idempotent(factory) -> None:
    with session_scope(factory) as session:
        _seed(session)
        first = append_special_offer_evidence(session, _item())
        second = append_special_offer_evidence(session, _item())
        assert first.id == second.id
        assert session.scalar(select(func.count()).select_from(ProductSpecialOfferEvidence)) == 1

        state = resolve_special_offer_state(session, product_id="product-1", as_of=DAY, known_at=T0)
        assert state.classification == UNKNOWN
        assert state.special_offer_flag is None
        assert state.evidence_kind is None


def test_later_explicit_product_evidence_promotes_only_that_snapshot(factory) -> None:
    reviewed_at = T0 + timedelta(hours=1)
    with session_scope(factory) as session:
        _seed(session)
        append_special_offer_evidence(session, _item())
        append_special_offer_evidence(
            session,
            _item(
                classification=CONFIRMED_SPECIAL,
                kind=VERSIONED_PRODUCT_SCOPE,
                observed_at=reviewed_at,
                content_hash="sha256:official-page",
            ),
        )

        before_review = resolve_special_offer_state(
            session, product_id="product-1", as_of=DAY, known_at=T0
        )
        after_review = resolve_special_offer_state(
            session, product_id="product-1", as_of=DAY, known_at=reviewed_at
        )
        next_day = resolve_special_offer_state(
            session,
            product_id="product-1",
            as_of=DAY + timedelta(days=1),
            known_at=reviewed_at,
        )
        assert before_review.special_offer_flag is None
        assert after_review.special_offer_flag is True
        assert after_review.evidence_kind == VERSIONED_PRODUCT_SCOPE
        assert next_day.special_offer_flag is None


def test_explicit_period_can_resolve_later_date_but_current_page_cannot_backdate(
    factory,
) -> None:
    later = T0 + timedelta(days=10)
    with session_scope(factory) as session:
        _seed(session)
        with pytest.raises(SpecialOfferEvidenceError, match="cannot be carried back"):
            append_special_offer_evidence(
                session,
                _item(
                    classification=CONFIRMED_NORMAL,
                    kind=VERSIONED_PRODUCT_SCOPE,
                    observed_at=later,
                ),
            )

        append_special_offer_evidence(
            session,
            _item(
                snapshot_as_of=DAY + timedelta(days=5),
                content_hash="sha256:unknown-snapshot",
            ),
        )
        append_special_offer_evidence(
            session,
            _item(
                classification=CONFIRMED_NORMAL,
                kind=EXPLICIT_SOURCE_FIELD,
                observed_at=later,
                effective_from=DAY,
                content_hash="sha256:dated-official-field",
            ),
        )
        state = resolve_special_offer_state(
            session,
            product_id="product-1",
            as_of=DAY + timedelta(days=5),
            known_at=later,
        )
        assert state.special_offer_flag is False


@pytest.mark.parametrize("kind", ["text_heuristic", "official_product_page"])
def test_heuristic_or_unapproved_kind_cannot_confirm(factory, kind: str) -> None:
    with session_scope(factory) as session:
        _seed(session)
        with pytest.raises(SpecialOfferEvidenceError, match="approved explicit"):
            append_special_offer_evidence(
                session,
                _item(classification=CONFIRMED_SPECIAL, kind=kind),
            )


def test_confirmation_requires_exact_product_identity(factory) -> None:
    with session_scope(factory) as session:
        _seed(session, match_method="manual_name")
        with pytest.raises(SpecialOfferEvidenceError, match="exact_code"):
            append_special_offer_evidence(session, _item())


def test_conflicting_latest_confirmations_fail_closed(factory) -> None:
    with session_scope(factory) as session:
        _seed(session)
        append_special_offer_evidence(
            session,
            _item(
                classification=CONFIRMED_SPECIAL,
                kind=EXPLICIT_SOURCE_FIELD,
                content_hash="sha256:special",
            ),
        )
        append_special_offer_evidence(
            session,
            _item(
                classification=CONFIRMED_NORMAL,
                kind=EXPLICIT_SOURCE_FIELD,
                content_hash="sha256:normal",
            ),
        )
        state = resolve_special_offer_state(session, product_id="product-1", as_of=DAY, known_at=T0)
        assert state.classification == UNKNOWN
        assert state.special_offer_flag is None
        assert state.conflict is True
        assert len(state.evidence_ids) == 2
