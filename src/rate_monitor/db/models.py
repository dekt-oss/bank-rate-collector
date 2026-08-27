"""SQLAlchemy 모델 — 명세서 v3 §5 테이블 13종 + v3.1 §7.2 추가 컬럼.

이 파일은 DB 계약이다. 변경은 명세 갱신과 마이그레이션을 먼저 거친다.

PK는 SQLite에 native UUID가 없으므로 TEXT에 str(uuid4())를 넣는다.
sources.id만 사람이 읽는 문자열 키(`finlife` 등)다.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from rate_monitor.db.types import Quantity, Rate


def new_id() -> str:
    return str(uuid4())


def _same_as(column: str):
    """다른 칸의 값을 그대로 쓰는 기본값.

    INSERT 시점에 같은 행의 다른 칸을 본다. `last_run_id`처럼 "따로 안 주면
    이것과 같다"가 맞는 칸에 쓴다.
    """

    def default(context) -> object:
        return context.get_current_parameters()[column]

    return default


class Base(DeclarativeBase):
    pass


# ── 5.1 sources ────────────────────────────────────────────────────────
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    sector: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16))
    source_role: Mapped[str] = mapped_column(String(32))
    trust_level: Mapped[str] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    base_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule_cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_status: Mapped[str] = mapped_column(String(16), default="review")
    coverage_status: Mapped[str] = mapped_column(String(16), default="unknown")
    parser_version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


# ── 5.2 collection_runs ────────────────────────────────────────────────
class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    mode: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    query_context_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_count: Mapped[int] = mapped_column(Integer, default=0)
    parsed_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("collection_runs.id"), nullable=True
    )
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    source: Mapped["Source"] = relationship()


# ── 5.3 raw_artifacts ──────────────────────────────────────────────────
class RawArtifact(Base):
    """원본 파일은 DB BLOB이 아니라 파일로 저장하고 경로·해시만 담는다."""

    __tablename__ = "raw_artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "sha256", name="uq_raw_artifacts_run_sha"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("collection_runs.id"))
    artifact_type: Mapped[str] = mapped_column(String(16))
    relative_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    content_length: Mapped[int] = mapped_column(Integer)
    encoding: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 인증키는 저장 전에 마스킹한다 (v3.1 §7.4)
    request_meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime)

    run: Mapped["CollectionRun"] = relationship()


# ── 5.4 institutions ───────────────────────────────────────────────────
class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sector: Mapped[str] = mapped_column(String(32))
    canonical_name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text, index=True)
    institution_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 공식 행정구역 코드 확보 전까지 NULL (v3.1 §11)
    sido_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sigungu_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 주소에서 뽑은 지역 (v4 §4.2). 위 두 칸과 다른 것이다 — 저 둘은 행정구역
    # 공식 코드 자리이고 아직 비어 있다. 이 둘은 주소 문자열의 파생값이다.
    region_sido: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    region_sigungu: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # 그 지역이 무엇에서 왔는가. 기본값이 'none'인 이유는, 모르는 원천의 행이
    # 근거 있는 행처럼 보이면 안 되기 때문이다 (services/region_service.py).
    geo_basis: Mapped[str] = mapped_column(String(32), default="none", server_default="none")
    geo_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    availability_scope: Mapped[str] = mapped_column(String(32), default="unknown")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)


# ── 5.5 outlets ────────────────────────────────────────────────────────
class Outlet(Base):
    """P1-A에서는 행을 만들지 않는다. finlife는 점포 단위 금리를 주지 않는다."""

    __tablename__ = "outlets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"))
    name: Mapped[str] = mapped_column(Text)
    outlet_type: Mapped[str] = mapped_column(String(16), default="branch")
    sido_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sigungu_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 기관과 같은 네 칸. 구·군 집계는 이쪽을 먼저 본다 — 한 금고가 두 구에
    # 점포를 두면 두 구 모두에 잡혀야 한다 (부산 실측 3건).
    region_sido: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    region_sigungu: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    geo_basis: Mapped[str] = mapped_column(String(32), default="none", server_default="none")
    geo_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    institution: Mapped["Institution"] = relationship()


# ── 5.6 products ───────────────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"))
    product_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text, index=True)
    is_special_sale: Mapped[bool] = mapped_column(Boolean, default=False)
    sale_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    sale_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)

    institution: Mapped["Institution"] = relationship()


# ── 5.7 source_entity_links ────────────────────────────────────────────
class SourceEntityLink(Base):
    """공식 소스 키 ↔ 내부 표준 엔터티 매핑.

    한 내부 기관이 여러 소스 키를 가질 수 있고, 한 소스 키는 한 시점에
    하나의 내부 엔터티만 가리킨다. 활성(valid_to IS NULL) 매핑은 하나만
    허용하므로 부분 유니크 인덱스를 쓴다.
    """

    __tablename__ = "source_entity_links"
    __table_args__ = (
        Index(
            "uq_source_entity_links_active",
            "source_id",
            "entity_type",
            "source_entity_key",
            unique=True,
            sqlite_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    entity_type: Mapped[str] = mapped_column(String(16))
    source_entity_key: Mapped[str] = mapped_column(String(128))
    entity_id: Mapped[str] = mapped_column(String(36))
    source_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(default=1.0)
    match_method: Mapped[str] = mapped_column(String(32), default="exact_code")
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    source: Mapped["Source"] = relationship()


# ── 5.8 product_variants ───────────────────────────────────────────────
class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        UniqueConstraint("variant_key", name="uq_product_variants_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    outlet_id: Mapped[str | None] = mapped_column(ForeignKey("outlets.id"), nullable=True)
    term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    term_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    join_channel: Mapped[str] = mapped_column(String(16))
    interest_method: Mapped[str] = mapped_column(String(16))
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_scope: Mapped[str] = mapped_column(String(32))
    variant_key: Mapped[str] = mapped_column(String(64))

    product: Mapped["Product"] = relationship()
    outlet: Mapped["Outlet | None"] = relationship()


# ── 5.9 rate_observations (+ v3.1 §7.2) ────────────────────────────────
class RateObservation(Base):
    """금리 한 건. **값이 바뀔 때만 새 행이 생긴다** (선행 수정안 §3.2).

    예전에는 수집할 때마다 새 행을 만들었다. 같은 3.10%가 8월 6일·7일·8일에
    세 줄로 쌓였다. 실측으로 185,923행 중 43,116행이 그런 중복이었고, 평일
    수집으로 1년을 돌면 1,272만 행 — 약 19 GB가 된다.

    이제는 직전 값과 `content_hash`를 견줘 같으면 행을 만들지 않고
    `last_seen_at`·`seen_count`·`last_run_id`만 갱신한다.

    `run_id`와 `last_run_id`가 갈린다.

        run_id       이 값을 **처음** 본 실행. 원본 아티팩트가 거기 있다
        last_run_id  이 값을 **마지막으로 확인한** 실행

    화면은 `last_run_id`를 본다. 그래야 "이번 실행이 확인한 금리"라는 뜻이
    예전과 같게 유지된다 — `run_id`로 걸면 안 바뀐 금리가 화면에서 사라진다.
    """

    __tablename__ = "rate_observations"
    __table_args__ = (
        # 한 비교 단위에 **살아 있는 행은 하나뿐이다.** 예전의
        # (variant_id, run_id) 유니크는 실행마다 행이 생길 때만 뜻이 있었다.
        Index(
            "uq_rate_observations_current",
            "variant_id",
            unique=True,
            sqlite_where=text("valid_to IS NULL"),
        ),
        Index("ix_rate_observations_run_id", "run_id"),
        # 화면이 이 열로 건다.
        Index("ix_rate_observations_last_run_id", "last_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    variant_id: Mapped[str] = mapped_column(ForeignKey("product_variants.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("collection_runs.id"))
    last_run_id: Mapped[str] = mapped_column(
        ForeignKey("collection_runs.id"), default=_same_as("run_id")
    )
    raw_artifact_id: Mapped[str] = mapped_column(ForeignKey("raw_artifacts.id"))
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    # 언제부터 언제까지 이 값이었나. valid_to가 NULL이면 지금 값이다.
    #
    # 새 행은 "지금 처음 봤고 지금도 유효하다"가 기본이다. 안 그러면 호출부가
    # 네 칸을 매번 같은 값으로 채워야 하고, 한 곳만 빠뜨려도 NOT NULL로 죽는다.
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=_same_as("observed_at")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=_same_as("observed_at")
    )
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime, default=_same_as("observed_at")
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 금리는 문자열 고정소수로 저장한다 (db/types.Rate). float 왕복 손실 방지.
    base_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    max_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    rate_basis: Mapped[str] = mapped_column(String(32), default="annual_pre_tax")
    source_detail_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_preference_text: Mapped[str] = mapped_column(Text, default="")
    validation_status: Mapped[str] = mapped_column(String(16), default="valid")
    validation_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(80))

    # v3.1 §7 — 행 단위 원본 추적
    base_source_locator: Mapped[str] = mapped_column(Text)
    option_source_locator: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_record_hash: Mapped[str] = mapped_column(String(80))
    # v3.1 §7.3 — 원천 기준일. 없으면 NULL. collected_at으로 대체하지 않는다.
    source_effective_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    variant: Mapped["ProductVariant"] = relationship()
    run: Mapped["CollectionRun"] = relationship(foreign_keys=[run_id])
    last_run: Mapped["CollectionRun"] = relationship(foreign_keys=[last_run_id])
    raw_artifact: Mapped["RawArtifact"] = relationship()


# ── 5.10 preference_conditions (P1-A에서는 스키마만) ────────────────────
class PreferenceCondition(Base):
    __tablename__ = "preference_conditions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    observation_id: Mapped[str] = mapped_column(ForeignKey("rate_observations.id"))
    condition_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    add_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    mandatory: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    stackable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    parser_confidence: Mapped[float | None] = mapped_column(nullable=True)
    parse_status: Mapped[str] = mapped_column(String(16), default="raw_only")

    observation: Mapped["RateObservation"] = relationship()


# ── 5.11 manual_overrides (P1-A에서는 스키마만) ────────────────────────
class ManualOverride(Base):
    __tablename__ = "manual_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(16))
    field_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    override_value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    conflict_status: Mapped[str] = mapped_column(String(16), default="none")
    created_by: Mapped[str] = mapped_column(String(64), default="local-user")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ── 5.12 entity_aliases (P1-A에서는 스키마만) ──────────────────────────
class EntityAlias(Base):
    __tablename__ = "entity_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[str] = mapped_column(String(36))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    alias: Mapped[str] = mapped_column(Text)
    normalized_alias: Mapped[str] = mapped_column(Text, index=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    source: Mapped["Source | None"] = relationship()


# ── 5.13 review_items ──────────────────────────────────────────────────
class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("collection_runs.id"), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    issue_type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    run: Mapped["CollectionRun | None"] = relationship()


# ── 5.14 collection_run_stats (선행 수정안 §3.2) ───────────────────────
class CollectionRunStat(Base):
    """실행 한 번의 품질·건수.

    관측이 값 단위로 바뀌면서 `collection_runs.parsed_count`만으로는 그 실행이
    무엇을 했는지 알 수 없게 됐다. 4,010행을 받았는데 관측이 하나도 안 늘었다면
    그것은 실패가 아니라 **아무것도 안 바뀐 것**이다 — 둘을 구별할 자리가
    필요하다.
    """

    __tablename__ = "collection_run_stats"
    __table_args__ = (UniqueConstraint("run_id", name="uq_collection_run_stats_run"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("collection_runs.id"))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    parsed_count: Mapped[int] = mapped_column(Integer, default=0)
    # 값이 그대로라 행을 만들지 않은 건수. 이 값이 크면 정상이다.
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, default=0)
    new_variant_count: Mapped[int] = mapped_column(Integer, default=0)
    # 직전 실행에는 있었는데 이번에 안 온 비교 단위. 원천이 상품을 내렸거나
    # 우리가 덜 받아 온 것이다 — 둘을 구별하지 않고 세기만 한다.
    missing_variant_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    run: Mapped["CollectionRun"] = relationship()


class MarketIndicator(Base):
    """참고지표 시계열 (v4 §7.1).

    **기준금리를 금융상품으로 저장하지 않는다.** `rate_observations`에 넣으면
    기관·상품·가입기간 같은 칸이 전부 비고, 화면의 비교표에도 섞여 든다.
    기준금리는 비교 대상이 아니라 옆에 놓고 보는 값이다.

    `UNIQUE(indicator_code, source_effective_at, source_id)`가 같은 날짜를
    두 번 쌓지 않게 한다. 기준금리는 하루 1회 수집하는데 값이 며칠씩 같으므로,
    이게 없으면 안 바뀐 값이 매일 한 줄씩 늘어난다 (§7.3).
    """

    __tablename__ = "market_indicators"
    __table_args__ = (
        UniqueConstraint(
            "indicator_code", "source_effective_at", "source_id",
            name="uq_market_indicators_point",
        ),
        Index("ix_market_indicators_code", "indicator_code", "source_effective_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    indicator_code: Mapped[str] = mapped_column(String(64))
    indicator_name: Mapped[str] = mapped_column(String(128))
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    # 원천이 밝힌 적용일. 없으면 채우지 않는다 — 수집일로 대체하면 정책금리가
    # 바뀐 날이 우리가 받은 날로 바뀐다.
    source_effective_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 지표는 금리(percent)와 1,000조원을 넘는 잔액(trillion_krw)을 함께 담는다.
    # 상품금리 Rate를 넓히지 않고 이 표만 12+6자리 fixed-decimal Quantity를 쓴다.
    value: Mapped[Decimal] = mapped_column(Quantity)
    unit: Mapped[str] = mapped_column(String(16))
    raw_artifact_id: Mapped[str] = mapped_column(ForeignKey("raw_artifacts.id"))
    source_locator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(80))
    validation_status: Mapped[str] = mapped_column(String(16), default="valid")


ALL_TABLES = tuple(sorted(Base.metadata.tables))
