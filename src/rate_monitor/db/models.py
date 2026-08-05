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

from rate_monitor.db.types import Rate


def new_id() -> str:
    return str(uuid4())


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
    __tablename__ = "rate_observations"
    __table_args__ = (
        UniqueConstraint(
            "variant_id", "run_id", name="uq_rate_observations_variant_run"
        ),
        # 위 유니크는 variant_id가 선두라 WHERE run_id = ? 조회에 쓰이지 않는다.
        # 대시보드는 실행 단위로 집계하므로 단독 인덱스가 필요하다.
        Index("ix_rate_observations_run_id", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    variant_id: Mapped[str] = mapped_column(ForeignKey("product_variants.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("collection_runs.id"))
    raw_artifact_id: Mapped[str] = mapped_column(ForeignKey("raw_artifacts.id"))
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
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
    run: Mapped["CollectionRun"] = relationship()
    raw_artifact: Mapped["RawArtifact"] = relationship()


# ── 5.10 preference_conditions (P1-A에서는 스키마만) ───────────────────
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


ALL_TABLES = tuple(sorted(Base.metadata.tables))
