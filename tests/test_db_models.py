"""DB 계약 검증.

제약을 선언만 하고 실제로는 안 걸리는 경우가 흔하다. 위반을 실제로
일으켜 IntegrityError가 나는지 확인한다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from rate_monitor.db import availability_models  # noqa: F401
from rate_monitor.db import institution_funding_models  # noqa: F401
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, pragma

NOW = datetime(2026, 8, 5, 0, 0, tzinfo=UTC).replace(tzinfo=None)

EXPECTED_TABLES = {
    "collection_run_stats",
    "collection_runs",
    "entity_aliases",
    "institution_availability_memberships",
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
    # 정수부를 0으로 채워 사전순 == 수치순이 되게 한다 (db/types.Rate)
    assert raw[0] == "000.1000"
    assert raw[1] == "text"


def test_rate_ordering_is_numeric_not_lexicographic(session) -> None:
    """ORDER BY base_rate가 수치 순서여야 한다.

    0 패딩이 없으면 "10.0000" < "2.0000"이 참이 되어 금리 순위가 뒤집힌다.
    순위 비교는 핵심 기능이므로 저장 형식으로 보장한다.
    """
    from sqlalchemy import text as sql_text

    _seed_run(session)
    inst = m.Institution(
        id="i9", sector="savings_bank", canonical_name="A", normalized_name="A",
        first_seen_at=NOW, last_seen_at=NOW,
    )
    prod = m.Product(
        id="p9", institution_id="i9", product_type="term_deposit", name="P",
        normalized_name="p", first_seen_at=NOW, last_seen_at=NOW,
    )
    session.add_all([inst, prod])
    for idx, rate in enumerate(["2.0", "10.0", "3.5", "0.5"]):
        session.add(
            m.ProductVariant(
                id=f"v{idx}", product_id="p9", term_months=12, join_channel="any",
                interest_method="simple", rate_scope="head_office_reference",
                variant_key=f"k{idx}",
            )
        )
        session.add(
            m.RateObservation(
                id=f"ro{idx}", variant_id=f"v{idx}", run_id="run-1", raw_artifact_id="art-1",
                observed_at=NOW, base_rate=Decimal(rate), content_hash=f"c{idx}",
                base_source_locator="$.x", source_record_hash=f"sha256:{idx}",
            )
        )
    session.commit()

    ordered = [
        r[0]
        for r in session.execute(
            sql_text("SELECT base_rate FROM rate_observations ORDER BY base_rate")
        )
    ]
    assert [Decimal(v) for v in ordered] == [
        Decimal("0.5"), Decimal("2.0"), Decimal("3.5"), Decimal("10.0")
    ]


def test_negative_rate_is_rejected_not_silently_wrong(session) -> None:
    """음수는 0 패딩으로 정렬되지 않는다. 조용히 틀리게 두지 않고 막는다."""
    from sqlalchemy.exc import StatementError

    from rate_monitor.db.types import RateOutOfRangeError

    _seed_run(session)
    variant = _seed_variant(session)
    session.add(
        m.RateObservation(
            id="neg", variant_id=variant.id, run_id="run-1", raw_artifact_id="art-1",
            observed_at=NOW, base_rate=Decimal("-1.0"), content_hash="h",
            base_source_locator="$.x", source_record_hash="sha256:n",
        )
    )
    # SQLAlchemy가 바인딩 단계 예외를 StatementError로 감싼다
    with pytest.raises(StatementError) as excinfo:
        session.commit()
    assert isinstance(excinfo.value.orig, RateOutOfRangeError)


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


def test_only_one_live_observation_per_variant(session) -> None:
    """살아 있는 관측은 비교 단위마다 하나뿐이다 (선행 수정안 §3.2).

    예전에는 (variant_id, run_id) 유니크였다. 실행마다 행이 생길 때만 뜻이
    있던 제약이라, 값이 바뀔 때만 행을 만드는 지금은 다른 것을 지켜야 한다 —
    둘이 살아 있으면 화면에 같은 상품이 두 줄로 나온다.
    """
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


def test_a_closed_observation_leaves_room_for_the_next(session) -> None:
    """값이 바뀌면 옛 행에 valid_to를 찍고 새 행을 만든다. 이력이 남아야 하므로.

    부분 유니크가 `valid_to IS NULL`에만 걸리므로 닫힌 행은 얼마든지 쌓인다.
    """
    _seed_run(session)
    variant = _seed_variant(session)
    session.add(m.CollectionRun(id="run-2", source_id="finlife", mode="api",
                                started_at=NOW, status="running"))
    session.add(m.RawArtifact(id="art-2", run_id="run-2", artifact_type="json",
                              relative_path="p2.json", sha256="b" * 64,
                              content_length=1, captured_at=NOW))
    session.commit()

    common = dict(variant_id=variant.id, observed_at=NOW,
                  base_source_locator="$.x", source_record_hash="sha256:a")
    # 3.10 구간을 닫고 3.20 구간을 연다.
    session.add(m.RateObservation(id="o1", run_id="run-1", raw_artifact_id="art-1",
                                  content_hash="h1", valid_to=NOW, **common))
    session.add(m.RateObservation(id="o2", run_id="run-2", raw_artifact_id="art-2",
                                  content_hash="h2", **common))
    session.commit()
    assert session.query(m.RateObservation).count() == 2

    # 기본값이 스스로 채워졌는지. 호출부가 네 칸을 반복하지 않아도 된다.
    live = session.get(m.RateObservation, "o2")
    assert live.last_run_id == "run-2"
    assert live.first_seen_at == live.valid_from == NOW
    assert live.seen_count == 1


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
