"""특판 evidence 운영 검수 서비스/CLI의 안전 계약."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from rate_monitor.db.models import Base, Institution, Product, Source, SourceEntityLink
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.services.special_offer_evidence_service import (
    CONFIRMED_SPECIAL,
    EXPLICIT_SOURCE_FIELD,
    SOURCE_SNAPSHOT,
    UNKNOWN,
    SpecialOfferEvidenceError,
    SpecialOfferEvidenceInput,
    append_special_offer_evidence,
    resolve_special_offer_state,
)
from rate_monitor.services.special_offer_review_service import (
    append_operator_confirmation,
    list_special_offer_evidence,
    summarize_special_offer_evidence,
)

DAY = date(2026, 9, 3)
T0 = datetime(2026, 9, 3, 1, 0, 0)


@pytest.fixture
def factory(tmp_path):
    engine = create_db_engine(tmp_path / "special-offer-review.sqlite3")
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
            content_hash="sha256:unknown-source-row",
            evidence={
                "identity_scope": "exact_product",
                "classification_basis": "not_provided_by_source_snapshot",
            },
        ),
    )
    return product.id


def test_summary_and_list_keep_unknown_distinct_from_confirmed(factory) -> None:
    with session_scope(factory) as session:
        _seed(session)
        summary = summarize_special_offer_evidence(session)
        assert summary["total_evidence_rows"] == 1
        assert summary["total_products"] == 1
        assert summary["by_classification"]["unknown"] == {
            "evidence_rows": 1,
            "products": 1,
        }
        assert summary["by_classification"]["confirmed_special"]["evidence_rows"] == 0
        assert summary["radar_activation"].startswith("off_")

        rows = list_special_offer_evidence(session, classification=UNKNOWN)
        assert len(rows) == 1
        assert rows[0].institution_name == "테스트저축은행"
        assert rows[0].product_name == "정기예금"
        assert rows[0].source_product_key == "source-product-1"


def test_operator_confirmation_derives_exact_source_key_and_is_append_only(factory) -> None:
    reviewed_at = T0 + timedelta(hours=1)
    with session_scope(factory) as session:
        product_id = _seed(session)
        first = append_operator_confirmation(
            session,
            source_id="fsb",
            product_id=product_id,
            classification=CONFIRMED_SPECIAL,
            evidence_kind=EXPLICIT_SOURCE_FIELD,
            snapshot_as_of=DAY,
            observed_at=reviewed_at,
            source_locator="https://bank.example/products/1",
            evidence_ref="상품 상세의 특판 구분 필드",
            content_sha256="A" * 64,
            note="공식 상품 상세에서 직접 확인",
        )
        second = append_operator_confirmation(
            session,
            source_id="fsb",
            product_id=product_id,
            classification=CONFIRMED_SPECIAL,
            evidence_kind=EXPLICIT_SOURCE_FIELD,
            snapshot_as_of=DAY,
            observed_at=reviewed_at + timedelta(minutes=1),
            source_locator="https://bank.example/products/1",
            evidence_ref="상품 상세의 특판 구분 필드",
            content_sha256="A" * 64,
            note="공식 상품 상세에서 직접 확인",
        )
        assert first.id == second.id
        assert first.source_product_key == "source-product-1"
        assert first.content_hash == "sha256:" + ("a" * 64)
        assert first.evidence_json["review_method"] == "manual_cli"

        state = resolve_special_offer_state(
            session,
            product_id=product_id,
            as_of=DAY,
            known_at=reviewed_at,
        )
        assert state.classification == CONFIRMED_SPECIAL
        assert state.special_offer_flag is True


def test_operator_confirmation_rejects_fake_hash_and_non_exact_identity(factory) -> None:
    with session_scope(factory) as session:
        product_id = _seed(session)
        with pytest.raises(SpecialOfferEvidenceError, match="64 hex"):
            append_operator_confirmation(
                session,
                source_id="fsb",
                product_id=product_id,
                classification=CONFIRMED_SPECIAL,
                evidence_kind=EXPLICIT_SOURCE_FIELD,
                snapshot_as_of=DAY,
                observed_at=T0,
                source_locator="https://bank.example/products/1",
                evidence_ref="field",
                content_sha256="not-a-hash",
            )

    engine = create_db_engine("file:non-exact?mode=memory&cache=shared&uri=true")
    non_exact_factory = make_session_factory(engine)
    Base.metadata.create_all(engine)
    with session_scope(non_exact_factory) as session:
        product_id = _seed(session, match_method="manual_name")
        with pytest.raises(SpecialOfferEvidenceError, match="exactly one active exact_code"):
            append_operator_confirmation(
                session,
                source_id="fsb",
                product_id=product_id,
                classification=CONFIRMED_SPECIAL,
                evidence_kind=EXPLICIT_SOURCE_FIELD,
                snapshot_as_of=DAY,
                observed_at=T0,
                source_locator="https://bank.example/products/1",
                evidence_ref="field",
                content_sha256="b" * 64,
            )


def test_operator_cannot_backdate_current_page_without_effective_period(factory) -> None:
    reviewed_at = T0 + timedelta(days=1)
    with session_scope(factory) as session:
        product_id = _seed(session)
        with pytest.raises(SpecialOfferEvidenceError, match="cannot be carried back"):
            append_operator_confirmation(
                session,
                source_id="fsb",
                product_id=product_id,
                classification=CONFIRMED_SPECIAL,
                evidence_kind=EXPLICIT_SOURCE_FIELD,
                snapshot_as_of=DAY,
                observed_at=reviewed_at,
                source_locator="https://bank.example/products/1",
                evidence_ref="field",
                content_sha256="c" * 64,
            )
