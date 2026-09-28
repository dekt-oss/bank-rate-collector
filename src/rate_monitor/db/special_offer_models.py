"""상품 특판 여부의 forward-only 근거 저장 모델.

``Product.is_special_sale``의 ``False``는 과거 스키마 기본값이라 미확인과
일반상품을 구분하지 못한다. 이 표는 그 필드를 덮어쓰지 않고, 특정 공식
snapshot에서 확인한 3상태와 원본 근거를 append-only로 보존한다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from rate_monitor.db.models import Base, new_id


class ProductSpecialOfferEvidence(Base):
    """정확한 원천 상품키에 귀속된 불변 특판 판정 근거 한 건."""

    __tablename__ = "product_special_offer_evidence"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('unknown', 'confirmed_special', 'confirmed_normal')",
            name="ck_product_special_offer_classification",
        ),
        CheckConstraint(
            "source_effective_to IS NULL OR "
            "(source_effective_from IS NOT NULL AND "
            "source_effective_to >= source_effective_from)",
            name="ck_product_special_offer_effective_period",
        ),
        UniqueConstraint("evidence_key", name="uq_product_special_offer_evidence_key"),
        Index(
            "ix_product_special_offer_snapshot",
            "product_id",
            "snapshot_as_of",
            "observed_at",
        ),
        Index(
            "ix_product_special_offer_source_key",
            "source_id",
            "source_product_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    source_product_key: Mapped[str] = mapped_column(String(128))

    # unknown / confirmed_special / confirmed_normal. Boolean으로 낮추지 않는다.
    classification: Mapped[str] = mapped_column(String(24))
    evidence_kind: Mapped[str] = mapped_column(String(48))
    snapshot_as_of: Mapped[date] = mapped_column(Date)
    source_effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    observed_at: Mapped[datetime] = mapped_column(DateTime)
    source_locator: Mapped[str] = mapped_column(Text)
    evidence_ref: Mapped[str] = mapped_column(Text)
    raw_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("raw_artifacts.id"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(80))
    evidence_key: Mapped[str] = mapped_column(String(80))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class OfficialSpecialOfferCatalogEvidence(Base):
    """Canonical rate products와 분리된 bank-direct 특판 근거.

    FSB 현재 상품 universe에 존재하지 않는 과거/별도 특판도 공식 상품키와
    원문 근거를 append-only로 보존한다. canonical_product_id는 향후
    검증된 cross-reference 용도일 뿐 필수 identity가 아니다.
    """

    __tablename__ = "official_special_offer_catalog_evidence"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('confirmed_special', 'confirmed_normal')",
            name="ck_official_special_offer_catalog_classification",
        ),
        CheckConstraint(
            "availability_status IN ('confirmed_active', 'confirmed_ended', 'unknown')",
            name="ck_official_special_offer_catalog_availability",
        ),
        CheckConstraint(
            "source_effective_to IS NULL OR "
            "(source_effective_from IS NOT NULL AND "
            "source_effective_to >= source_effective_from)",
            name="ck_official_special_offer_catalog_effective_period",
        ),
        CheckConstraint(
            "binding_status IN ('unbound', 'candidate', 'bound')",
            name="ck_official_special_offer_catalog_binding_status",
        ),
        UniqueConstraint(
            "evidence_key", name="uq_official_special_offer_catalog_evidence_key"
        ),
        Index(
            "ix_official_special_offer_catalog_identity",
            "source_namespace",
            "institution_normalized",
            "official_product_key",
            "observed_at",
        ),
        Index(
            "ix_official_special_offer_catalog_availability",
            "availability_status",
            "observed_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_namespace: Mapped[str] = mapped_column(String(64))
    institution_name: Mapped[str] = mapped_column(Text)
    institution_normalized: Mapped[str] = mapped_column(Text)
    official_product_key: Mapped[str] = mapped_column(String(128))
    product_name: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(24))
    availability_status: Mapped[str] = mapped_column(String(24))
    snapshot_as_of: Mapped[date] = mapped_column(Date)
    source_effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    source_locator: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(80))
    evidence_key: Mapped[str] = mapped_column(String(80))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    canonical_product_id: Mapped[str | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    binding_status: Mapped[str] = mapped_column(String(32), default="unbound")
    created_at: Mapped[datetime] = mapped_column(DateTime)
