from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from rate_monitor.db.models import Base, Product, ProductVariant, RateObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.special_offer_models import OfficialSpecialOfferCatalogEvidence
from rate_monitor.services.special_offer_catalog_service import (
    CONFIRMED_SPECIAL,
    OfficialSpecialOfferCatalogError,
    OfficialSpecialOfferCatalogInput,
    append_official_catalog_evidence,
    import_capture_payload,
)
from rate_monitor.services.special_offer_radar_service import build_special_offer_radar

NOW = datetime(2026, 9, 27, 1, 0, tzinfo=UTC).replace(tzinfo=None)
HASH = "sha256:" + "a" * 64


def _db(tmp_path: Path):
    path = tmp_path / "catalog.sqlite3"
    engine = create_db_engine(path)
    Base.metadata.create_all(engine)
    return path, make_session_factory(engine)


def _item(
    *,
    key: str = "P1",
    availability: str = "confirmed_ended",
) -> OfficialSpecialOfferCatalogInput:
    assertion = "판매 종료" if availability == "confirmed_ended" else None
    if availability == "confirmed_active":
        assertion = "현재 판매 중"
    return OfficialSpecialOfferCatalogInput(
        institution_name="테스트저축은행",
        official_product_key=key,
        product_name=f"특판 {key}",
        classification=CONFIRMED_SPECIAL,
        availability_status=availability,
        snapshot_as_of=date(2026, 9, 27),
        observed_at=NOW,
        source_locator=f"https://bank.example/products/{key}",
        content_hash=HASH,
        source_effective_from=date(2026, 1, 1),
        source_effective_to=(
            date(2026, 6, 30) if availability == "confirmed_ended" else None
        ),
        evidence={
            "identity_marker_present": True,
            "explicit_phrases_present": True,
            "special_offer_terms": {
                "special_rate": "4.10",
                "sale_start": "2026-01-01",
                "sale_end": (
                    "2026-06-30" if availability == "confirmed_ended" else None
                ),
                "quota_text": "100억원 한도",
                "eligibility_text": "개인",
                "early_termination_text": "한도 소진 시 조기종료",
            },
            "availability": {
                "status": availability,
                "assertion_text": assertion,
                "observed_at": NOW.isoformat(),
                "source_locator": f"https://bank.example/products/{key}",
            },
        },
    )


def test_catalog_append_is_idempotent_without_creating_canonical_products(
    tmp_path: Path,
) -> None:
    db_path, factory = _db(tmp_path)
    with session_scope(factory) as session:
        first = append_official_catalog_evidence(session, _item())
        second = append_official_catalog_evidence(session, _item())
        assert first.id == second.id
        assert session.scalar(select(func.count()).select_from(Product)) == 0
        assert session.scalar(select(func.count()).select_from(ProductVariant)) == 0
        assert session.scalar(select(func.count()).select_from(RateObservation)) == 0
        assert (
            session.scalar(
                select(func.count()).select_from(OfficialSpecialOfferCatalogEvidence)
            )
            == 1
        )

    radar = build_special_offer_radar(db_path)
    assert radar["current_offers"] == []
    assert len(radar["past_offers"]) == 1
    assert radar["past_offers"][0]["evidence_source"] == "bank_direct_catalog"
    assert radar["official_catalog_counts"]["confirmed_ended"] == 1
    assert radar["policy"]["official_catalog_changes_rate_population"] is False


def test_unknown_availability_stays_out_of_current_and_history(tmp_path: Path) -> None:
    db_path, factory = _db(tmp_path)
    with session_scope(factory) as session:
        append_official_catalog_evidence(session, _item(availability="unknown"))

    radar = build_special_offer_radar(db_path)
    assert radar["current_offers"] == []
    assert radar["past_offers"] == []
    assert radar["availability_counts"]["unknown"] == 1
    assert radar["official_catalog_counts"]["unknown"] == 1


def test_confirmed_active_requires_explicit_availability_assertion(tmp_path: Path) -> None:
    _, factory = _db(tmp_path)
    item = _item(availability="confirmed_active")
    evidence = dict(item.evidence or {})
    evidence["availability"] = {
        "status": "confirmed_active",
        "assertion_text": None,
    }
    broken = OfficialSpecialOfferCatalogInput(
        **{**item.__dict__, "evidence": evidence}
    )
    with session_scope(factory) as session:
        with pytest.raises(OfficialSpecialOfferCatalogError, match="assertion"):
            append_official_catalog_evidence(session, broken)


def test_import_capture_payload_only_appends_explicit_special_candidates(
    tmp_path: Path,
) -> None:
    _, factory = _db(tmp_path)
    base_capture = {
        "institution": "웰컴저축은행",
        "official_product_key": "1130313564",
        "product_name": "웰컴 디지로카 100일적금",
        "source_locator": "https://www.welcomebank.co.kr/product?prdCd=1130313564",
        "content_sha256": HASH,
        "identity_marker_present": True,
        "explicit_phrases_present": True,
        "special_offer_terms": {
            "special_rate": None,
            "sale_start": "2024-07-22",
            "sale_end": "2024-12-31",
            "quota_text": "1만좌 한도",
            "eligibility_text": "실명의 개인",
            "early_termination_text": "특판소진 시 조기 종료",
        },
        "availability": {
            "status": "confirmed_ended",
            "assertion_text": "explicit sale period ended on 2024-12-31",
            "observed_at": "2026-09-27T01:00:00+00:00",
            "source_locator": None,
        },
    }
    payload = {
        "observed_at": "2026-09-27T01:00:00+00:00",
        "captures": [
            {**base_capture, "classification_candidate": "confirmed_special_candidate"},
            {
                **base_capture,
                "official_product_key": "UNVERIFIED",
                "classification_candidate": "unverified",
            },
        ],
    }
    with session_scope(factory) as session:
        rows = import_capture_payload(session, payload)
        assert len(rows) == 1
        assert rows[0].official_product_key == "1130313564"
        assert rows[0].canonical_product_id is None
        assert rows[0].binding_status == "unbound"
        assert session.scalar(select(func.count()).select_from(Product)) == 0
