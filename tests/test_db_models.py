"""DB 계약 검증.

제약을 선언만 하고 실제로는 안 걸리는 경우가 흔하다. 위반을 실제로
일으켜 IntegrityError가 나는지 확인한다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, pragma

NOW = datetime(2026, 8, 5, 0, 0, tzinfo=UTC).replace(tzinfo=None)

EXPECTED_TABLES = {
    "collection_runs",
    "entity_aliases",
    "institutions",
    "manual_overrides",
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

def test_all_thirteen_tables_created(engine) -> None:
    assert set(m.Base.metadata.tables) == EXPECTED_TABLES
    assert len(EXPECTED_TABLES) == 13


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
    """PRAGMA가 켜져 있어야 실제로 막힌다."""
    session.add(
        m.CollectionRun(
            id="run-x", source_id="존재하지않는소스", mode="api",
            started_at=NOW, status="running",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


# ── 금리 정밀도 ─────────────────────────────────────────────────────────

def test_rate_roundtrip_preserves_four_decimals(session) -> None:
    """Decimal 왕복 손실 0. float 경유하면 여기서 깨진다 (명세서 v3 §8.4)."""
    _seed_run(session)
    variant = _seed_variant(session)
    session.add(
        m.RateObservation(
            id="obs-1", variant_id=variant.id, run_id="run-1", raw_artifact_id="art-1",
            observed_at=NOW, base_rate=Decimal("2.7500"), max_rate=Decimal("3.1234"),
            content_hash="h1", base_source_locator="$.result.baseList[0]",
            source_record_hash="sha256:x",
        )
    )
    session.commit()
    session.expunge_all()

    got = session.get(m.RateObservation, "obs-1")
    assert got.base_rate == Decimal("2.7500")
    assert got.max_rate == Decimal("3.1234")
    assert str(got.base_rate) == "2.7500"


def test_rate_stored_as_text_not_float(session) -> None:
    from sqlalchemy import text as sql_text

    _seed_run(session)
    variant = _seed_variant(session)
    session.add(
        m.RateObservation(
            id="obs-2", variant_id=variant.id, run_id="run-1", raw_artifact_id="art-1",
            observed_at=NOW, base_rate=Decimal("0.1"), content_hash="h2",
            base_source_locator="$.x", source_record_hash="sha256:y",
        )
    )
    session.commit()
    raw = session.execute(
        sql_text("SELECT base_rate, typeof(base_rate) FROM rate_observations WHERE id='obs-2'")
    ).one()
    assert raw[0] == "0.1000"
    assert raw[1] == "text"


def test_null_max_rate_stays_null(session) -> None:
    """max_rate NULL 규칙이 저장 계층에서도 유지되는지 (v3 §8.4)."""
    _seed_run(session)
    variant = _seed_variant(session)
    session.add(
        m.RateObservation(
            id="obs-3", variant_id=variant.id, run_id="run-1", raw_artifact_id="art-1",
            observed_at=NOW, base_rate=Decimal("2.5"), max_rate=None,
            content_hash="h3", base_source_locator="$.x", source_record_hash="sha256:z",
        )
    )
    session.commit()
    session.expunge_all()
    assert session.get(m.RateObservation, "obs-3").max_rate is None


# ── 유니크 제약 4종 ─────────────────────────────────────────────────────

def test_uq_raw_artifacts_run_sha(session) -> None:
    _seed_run(session)
    session.add(
        m.RawArtifact(
            id="art-dup", run_id="run-1", artifact_type="json",
            relative_path="other.json", sha256="a" * 64, content_length=1, captured_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_uq_product_variants_key(session) -> None:
    _seed_variant(session)
    session.add(
        m.ProductVariant(
            id="var-dup", product_id="prod-1", term_months=24, join_channel="any",
            interest_method="simple", rate_scope="head_office_reference",
            variant_key="key-abc",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_uq_rate_observations_variant_run(session) -> None:
    """같은 실행 안에서 같은 비교단위가 두 번 저장되면 안 된다 (v3.1 §12.2)."""
    _seed_run(session)
    variant = _seed_variant(session)
    common = dict(
        variant_id=variant.id, run_id="run-1", raw_artifact_id="art-1",
        observed_at=NOW, content_hash="h", base_source_locator="$.x",
        source_record_hash="sha256:a",
    )
    session.add(m.RateObservation(id="o1", **common))
    session.commit()
    session.add(m.RateObservation(id="o2", **common))
    with pytest.raises(IntegrityError):
        session.commit()


def test_rate_observations_allows_same_variant_across_runs(session) -> None:
    """다른 실행에서는 같은 비교단위를 다시 관측해야 한다. 이력이 남아야 하므로."""
    _seed_run(session)
    variant = _seed_variant(session)
    session.add(m.CollectionRun(id="run-2", source_id="finlife", mode="api",
                                started_at=NOW, status="running"))
    session.add(m.RawArtifact(id="art-2", run_id="run-2", artifact_type="json",
                              relative_path="p2.json", sha256="b" * 64,
                              content_length=1, captured_at=NOW))
    session.commit()
    common = dict(variant_id=variant.id, observed_at=NOW, content_hash="h",
                  base_source_locator="$.x", source_record_hash="sha256:a")
    session.add(m.RateObservation(id="o1", run_id="run-1", raw_artifact_id="art-1", **common))
    session.add(m.RateObservation(id="o2", run_id="run-2", raw_artifact_id="art-2", **common))
    session.commit()
    assert session.query(m.RateObservation).count() == 2


def test_source_entity_link_active_uniqueness(session) -> None:
    """활성 매핑(valid_to IS NULL)은 하나만 허용한다."""
    _seed_run(session)
    common = dict(
        source_id="finlife", entity_type="institution", source_entity_key="0010345",
        created_at=NOW, updated_at=NOW,
    )
    session.add(m.SourceEntityLink(id="l1", entity_id="inst-1", valid_to=None, **common))
    session.commit()
    session.add(m.SourceEntityLink(id="l2", entity_id="inst-2", valid_to=None, **common))
    with pytest.raises(IntegrityError):
        session.commit()


def test_source_entity_link_allows_superseded_row(session) -> None:
    """만료된(valid_to가 채워진) 매핑은 여러 건 남을 수 있다. 통폐합 이력이므로."""
    _seed_run(session)
    common = dict(
        source_id="finlife", entity_type="institution", source_entity_key="0010345",
        created_at=NOW, updated_at=NOW,
    )
    session.add(
        m.SourceEntityLink(id="l1", entity_id="old", valid_to=date(2026, 1, 1), **common)
    )
    session.add(
        m.SourceEntityLink(id="l2", entity_id="older", valid_to=date(2025, 1, 1), **common)
    )
    session.add(m.SourceEntityLink(id="l3", entity_id="current", valid_to=None, **common))
    session.commit()
    assert session.query(m.SourceEntityLink).count() == 3
