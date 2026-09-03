"""기관별 수신잔액 저장 모델.

기존 상품금리/거시지표와 별도 축이다. Data.go.kr 금융통계의 기관별
재무상태표 계정을 원천 기준월과 provenance와 함께 저장한다.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from rate_monitor.db.models import Base, new_id
from rate_monitor.db.types import Quantity


class InstitutionFundingObservation(Base):
    """기관별 수신/예수부채 point-in-time observation.

    자연키의 원천값이 바뀌면 overwrite하지 않고 revision을 올린다.
    현재 revision만 ``valid_to IS NULL``이다.
    """

    __tablename__ = "institution_funding_observations"
    __table_args__ = (
        Index(
            "uq_institution_funding_active",
            "source_id",
            "source_institution_key",
            "metric_code",
            "source_effective_month",
            unique=True,
            sqlite_where=text("valid_to IS NULL"),
        ),
        Index(
            "ix_institution_funding_sector_month",
            "sector",
            "source_effective_month",
        ),
        Index(
            "ix_institution_funding_institution_month",
            "institution_id",
            "source_effective_month",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    institution_id: Mapped[str | None] = mapped_column(
        ForeignKey("institutions.id"), nullable=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    source_institution_key: Mapped[str] = mapped_column(String(128))
    source_institution_name: Mapped[str] = mapped_column(Text)
    source_crno: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sector: Mapped[str] = mapped_column(String(32))
    metric_code: Mapped[str] = mapped_column(String(64))
    metric_name: Mapped[str] = mapped_column(String(128))
    source_effective_month: Mapped[str] = mapped_column(String(7))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Quantity)
    unit: Mapped[str] = mapped_column(String(32))
    source_value_text: Mapped[str] = mapped_column(Text)
    source_unit: Mapped[str] = mapped_column(String(16))
    observation_basis: Mapped[str] = mapped_column(String(32))
    statement_basis: Mapped[str] = mapped_column(String(32))
    population_scope: Mapped[str] = mapped_column(String(64))
    identity_status: Mapped[str] = mapped_column(String(24))
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    source_locator: Mapped[str] = mapped_column(Text)
    raw_artifact_id: Mapped[str] = mapped_column(ForeignKey("raw_artifacts.id"))
    content_hash: Mapped[str] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[datetime] = mapped_column(DateTime)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


# `verify_gate.py`와 일부 schema 검사기는 이 모듈을 extension registry hook으로
# import해 왔다. 새 extension 모델도 같은 hook에서 등록해 실제 DB와 metadata가
# 다르게 보이지 않게 한다. 별도 registry refactor는 이번 고위험 변경 범위 밖이다.
from rate_monitor.db import availability_models as _availability_models  # noqa: E402, F401
from rate_monitor.db import special_offer_models as _special_offer_models  # noqa: E402, F401
