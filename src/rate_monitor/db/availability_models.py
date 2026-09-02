"""공식 원천이 제공하는 고객 가입가능지역 membership 저장 모델.

소재지(`Institution.region_*`)와 고객 가입가능지역은 서로 다른 축이다.
금리 observation을 지역별로 복제하지 않고 이 표에 membership만 보존한다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from rate_monitor.db.models import Base, new_id


class InstitutionAvailabilityMembership(Base):
    """기관 × 상품군 × 공식 AREA의 temporal membership.

    같은 자연키에 살아 있는 행은 하나뿐이다. 완전한 census에서 membership이
    사라지면 hard delete하지 않고 ``valid_to``를 닫고, 나중에 다시 나타나면
    새 행을 만들어 이력을 보존한다.
    """

    __tablename__ = "institution_availability_memberships"
    __table_args__ = (
        Index(
            "uq_institution_availability_active",
            "source_id",
            "institution_id",
            "product_type",
            "area_code",
            unique=True,
            sqlite_where=text("valid_to IS NULL"),
        ),
        Index(
            "ix_institution_availability_cohort",
            "source_id",
            "product_type",
            "area_code",
            "institution_id",
        ),
        Index(
            "ix_institution_availability_institution",
            "institution_id",
            "product_type",
            "valid_to",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"))
    product_type: Mapped[str] = mapped_column(String(32))
    area_code: Mapped[str] = mapped_column(String(32))
    area_label: Mapped[str] = mapped_column(String(32))
    availability_match_key: Mapped[str] = mapped_column(String(128))

    # FSB 요청의 REG_DATE/CHG_DATE. 수집시각으로 대체하지 않는다.
    source_effective_date: Mapped[date] = mapped_column(Date)
    source_locator: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[datetime] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
