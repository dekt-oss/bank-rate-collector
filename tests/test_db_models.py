"""DB 계약 검증.

제약을 선언만 하고 실제로는 안 걸리는 경우가 흔하다. 위반을 실제로
일으켜 IntegrityError가 나는지 확인한다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from rate_monitor.db import institution_funding_models  # noqa: F401
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, pragma

NOW = datetime(2026, 8, 5, 0, 0, tzinfo=UTC).replace(tzinfo=None)

EXPECTED_TABLES = {
    "collection_run_stats",
    "collection_runs",
    "entity_aliases",
    "institution_funding_observations",
    "institutions",
    "manual_overrides",
    "market_indicators",
    "outlets",
    "preference_conditions",
    "product_variants",
    "products",
    "rate_observations",
    "raw_artifacts",
    "review_items",
    "source_entity_links",
    "sources",
}


@pytest.fixture()
def engine(tmp_path):
    eng = create_db_engine(tmp_path / "test.sqlite3")
    m.Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    factory = make_session_factory(engine)
    with factory() as s:
        yield s


def _seed_run(session) -> tuple[m.Source, m.CollectionRun, m.RawArtifact]:
    source = m.Source(
        id="finlife", name="금융감독원 오픈API", sector="savings_bank", mode="api",
        source_role="secondary_official", trust_level="official_direct", priority=20,
        created_at=NOW, updated_at=NOW,
    )
    run = m.CollectionRun(
        id="run-1", source_id="finlife", mode="api", started_at=NOW, status="running"
    )
    artifact = m.RawArtifact(
        id="art-1", run_id="run-1", artifact_type="json",
        relative_path="data/raw/2026/08/05/run-1/p1.json", sha256="a" * 64,
        content_length=100, captured_at=NOW,
    )
    session.add_all([source, run, artifact])
    session.commit()
    return source, run, artifact


def _seed_variant(session) -> m.ProductVariant:
    inst = m.Institution(
        id="inst-1", sector="savings_bank", canonical_name="애큐온저축은행",
        normalized_name="애큐온저축은행", first_seen_at=NOW, last_seen_at=NOW,
    )
    prod = m.Product(
        id="prod-1", institution_id="inst-1", product_type="term_deposit",
        name="정기예금", normalized_name="정기예금", first_seen_at=NOW, last_seen_at=NOW,
    )
    variant = m.ProductVariant(
        id="var-1", product_id="prod-1", term_months=12, join_channel="any",
        interest_method="simple", rate_scope="head_office_reference",
        variant_key="key-abc",
    )
    session.add_all([inst, prod, variant])
    session.commit()
    return variant


# ── 스키마 ──────────────────────────────────────────────────────────────

def test_the_models_declare_exactly_these_tables(engine) -> None:
    """**이름**으로 묻는다. 개수를 못 박으면 표를 더할 때마다 여기가 빨개진다.

    2026-08-06까지 `== 13`, `== 14` 같은 숫자를 네 곳에서 고쳤다. 목록은
    남긴다 — 실수로 늘어난 표를 잡는 건 개수가 아니라 이름이다.
    """
    assert set(m.Base.metadata.tables) == EXPECTED_TABLES


def test_rate_observation_has_v31_tracking_columns() -> None:
    cols = set(m.RateObservation.__table__.columns.keys())
    assert {
        "base_source_locator",
        "option_source_locator",
        "source_record_hash",
        "source_effective_at",
    } <= cols


# ── PRAGMA ──────────────────────────────────────────────────────────────

def test_wal_mode_enabled(engine) -> None:
    assert str(pragma(engine, "journal_mode")).lower() == "wal"


def test_foreign_keys_enforced(engine) -> None:
    assert pragma(engine, "foreign_keys") == 1


def test_foreign_key_violation_actually_raises(session) -> None:
    session.add(m.Product(id="p-bad", institution_id="does-not-exist", product_type="term_deposit", name="x", normalized_name="x", first_seen_at=NOW, last_seen_at=NOW))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_source_entity_link_active_unique_constraint(session) -> None:
    _seed_run(session)
    inst = m.Institution(
        id="inst-link", sector="savings_bank", canonical_name="테스트",
        normalized_name="테스트", first_seen_at=NOW, last_seen_at=NOW,
    )
    session.add(inst)
    session.commit()
    kwargs = dict(
        source_id="finlife", entity_type="institution", source_entity_key="savings_bank:001",
        entity_id="inst-link", created_at=NOW, updated_at=NOW,
    )
    session.add(m.SourceEntityLink(id="link-1", **kwargs))
    session.commit()
    session.add(m.SourceEntityLink(id="link-2", **kwargs))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_product_variant_key_unique(session) -> None:
    _seed_run(session)
    _seed_variant(session)
    duplicate = m.ProductVariant(
        id="var-2", product_id="prod-1", term_months=24, join_channel="any",
        interest_method="compound", rate_scope="head_office_reference",
        variant_key="key-abc",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_market_indicator_unique_point(session) -> None:
    _seed_run(session)
    kwargs = dict(
        indicator_code="bok_base_rate",
        indicator_name="한국은행 기준금리",
        source_id="finlife",
        observed_at=NOW,
        source_effective_at=date(2026, 8, 5),
        value=Decimal("2.500000"),
        unit="percent",
        raw_artifact_id="art-1",
        content_hash="sha256:" + "c" * 64,
    )
    session.add(m.MarketIndicator(id="mi-1", **kwargs))
    session.commit()
    session.add(m.MarketIndicator(id="mi-2", **kwargs))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
