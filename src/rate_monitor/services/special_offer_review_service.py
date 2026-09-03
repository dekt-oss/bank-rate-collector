"""운영자가 특판 evidence registry를 검수하는 최소 서비스.

자동 수집은 FSB snapshot을 ``unknown``으로만 쌓는다. 이 모듈은 그 근거를
조회하고, 사람이 상품 단위의 명시적 공식 근거를 확인한 경우에만 기존
append-only 계약을 통해 ``confirmed_special``/``confirmed_normal``을 추가한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rate_monitor.db.models import Institution, Product, SourceEntityLink
from rate_monitor.db.special_offer_models import ProductSpecialOfferEvidence
from rate_monitor.services.special_offer_evidence_service import (
    CONFIRMED_NORMAL,
    CONFIRMED_SPECIAL,
    CONFIRMING_KINDS,
    SpecialOfferEvidenceError,
    SpecialOfferEvidenceInput,
    append_special_offer_evidence,
)

CONFIRMED_CLASSIFICATIONS = frozenset({CONFIRMED_SPECIAL, CONFIRMED_NORMAL})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class SpecialOfferReviewRow:
    evidence_id: str
    source_id: str
    product_id: str
    institution_name: str
    product_name: str
    source_product_key: str
    classification: str
    evidence_kind: str
    snapshot_as_of: date
    observed_at: datetime
    evidence_ref: str


def summarize_special_offer_evidence(session: Session) -> dict[str, object]:
    """분류별 evidence 행/상품 수를 반환한다. 판정 비율로 해석하지 않는다."""
    summary = {
        classification: {"evidence_rows": 0, "products": 0}
        for classification in ("unknown", CONFIRMED_SPECIAL, CONFIRMED_NORMAL)
    }
    rows = session.execute(
        select(
            ProductSpecialOfferEvidence.classification,
            func.count(ProductSpecialOfferEvidence.id),
            func.count(func.distinct(ProductSpecialOfferEvidence.product_id)),
        ).group_by(ProductSpecialOfferEvidence.classification)
    ).all()
    for classification, evidence_rows, products in rows:
        summary[classification] = {
            "evidence_rows": int(evidence_rows),
            "products": int(products),
        }
    total_rows = session.scalar(select(func.count()).select_from(ProductSpecialOfferEvidence)) or 0
    total_products = session.scalar(
        select(func.count(func.distinct(ProductSpecialOfferEvidence.product_id)))
    ) or 0
    return {
        "total_evidence_rows": int(total_rows),
        "total_products": int(total_products),
        "by_classification": summary,
        "radar_activation": "off_until_confirmed_evidence_is_reviewed_and_separately_approved",
    }


def list_special_offer_evidence(
    session: Session,
    *,
    classification: str | None = None,
    source_id: str = "fsb",
    limit: int = 50,
) -> list[SpecialOfferReviewRow]:
    """최근 evidence를 사람이 검수할 수 있는 상품 문맥과 함께 보여준다."""
    if limit < 1 or limit > 500:
        raise SpecialOfferEvidenceError("limit must be between 1 and 500")
    stmt = (
        select(ProductSpecialOfferEvidence, Product, Institution)
        .join(Product, Product.id == ProductSpecialOfferEvidence.product_id)
        .join(Institution, Institution.id == Product.institution_id)
        .where(ProductSpecialOfferEvidence.source_id == source_id)
        .order_by(
            ProductSpecialOfferEvidence.observed_at.desc(),
            ProductSpecialOfferEvidence.snapshot_as_of.desc(),
            ProductSpecialOfferEvidence.id.desc(),
        )
        .limit(limit)
    )
    if classification is not None:
        stmt = stmt.where(ProductSpecialOfferEvidence.classification == classification)

    result: list[SpecialOfferReviewRow] = []
    for evidence, product, institution in session.execute(stmt):
        result.append(
            SpecialOfferReviewRow(
                evidence_id=evidence.id,
                source_id=evidence.source_id,
                product_id=evidence.product_id,
                institution_name=institution.canonical_name,
                product_name=product.name,
                source_product_key=evidence.source_product_key,
                classification=evidence.classification,
                evidence_kind=evidence.evidence_kind,
                snapshot_as_of=evidence.snapshot_as_of,
                observed_at=evidence.observed_at,
                evidence_ref=evidence.evidence_ref,
            )
        )
    return result


def _source_product_key(session: Session, *, source_id: str, product_id: str) -> str:
    product = session.get(Product, product_id)
    if product is None:
        raise SpecialOfferEvidenceError("product_id does not exist")
    links = session.scalars(
        select(SourceEntityLink).where(
            SourceEntityLink.source_id == source_id,
            SourceEntityLink.entity_type == "product",
            SourceEntityLink.entity_id == product_id,
            SourceEntityLink.match_method == "exact_code",
            SourceEntityLink.valid_to.is_(None),
        )
    ).all()
    if len(links) != 1:
        raise SpecialOfferEvidenceError(
            "confirmation requires exactly one active exact_code product link"
        )
    prefix = f"{product.institution_id}:"
    if not links[0].source_entity_key.startswith(prefix):
        raise SpecialOfferEvidenceError("exact product link has an unexpected source key")
    source_product_key = links[0].source_entity_key.removeprefix(prefix).strip()
    if not source_product_key:
        raise SpecialOfferEvidenceError("exact product link has an empty source product key")
    return source_product_key


def _content_hash(content_sha256: str) -> str:
    value = content_sha256.removeprefix("sha256:").strip()
    if not _SHA256_RE.fullmatch(value):
        raise SpecialOfferEvidenceError("content_sha256 must be exactly 64 hex characters")
    return f"sha256:{value.lower()}"


def append_operator_confirmation(
    session: Session,
    *,
    source_id: str,
    product_id: str,
    classification: str,
    evidence_kind: str,
    snapshot_as_of: date,
    observed_at: datetime,
    source_locator: str,
    evidence_ref: str,
    content_sha256: str,
    source_effective_from: date | None = None,
    source_effective_to: date | None = None,
    note: str | None = None,
) -> ProductSpecialOfferEvidence:
    """명시적 공식 근거를 검수자가 확인한 뒤 확정 evidence를 append한다.

    ``observed_at``은 CLI에서 실행 시각으로 고정한다. 과거에 이미 알았던 것처럼
    보이게 backdate하는 인터페이스는 제공하지 않는다. 과거 적용 판정이 필요하면
    공식 근거가 밝힌 ``source_effective_from/to``를 별도로 기록해야 한다.
    """
    if classification not in CONFIRMED_CLASSIFICATIONS:
        raise SpecialOfferEvidenceError(
            "operator confirmation must be confirmed_special or confirmed_normal"
        )
    if evidence_kind not in CONFIRMING_KINDS:
        raise SpecialOfferEvidenceError("evidence_kind is not approved for confirmation")
    source_product_key = _source_product_key(
        session, source_id=source_id, product_id=product_id
    )
    evidence = {
        "identity_scope": "exact_product",
        "explicit_assertion": classification,
        "review_method": "manual_cli",
    }
    if note and note.strip():
        evidence["operator_note"] = note.strip()

    return append_special_offer_evidence(
        session,
        SpecialOfferEvidenceInput(
            source_id=source_id,
            product_id=product_id,
            source_product_key=source_product_key,
            classification=classification,
            evidence_kind=evidence_kind,
            snapshot_as_of=snapshot_as_of,
            observed_at=observed_at,
            source_locator=source_locator,
            evidence_ref=evidence_ref,
            content_hash=_content_hash(content_sha256),
            source_effective_from=source_effective_from,
            source_effective_to=source_effective_to,
            evidence=evidence,
        ),
    )
