"""엔터티 해석 — 원천 키를 내부 표준 엔터티에 붙인다 (명세서 v3 §5.7).

이름이 아니라 원천 식별자를 우선한다 (v3 §3.2). 이름은 바뀌지만 코드는
대체로 유지되고, 이름으로만 묶으면 통폐합·개명에서 이력이 끊긴다.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from rate_monitor.db.models import (
    Institution,
    Product,
    ProductVariant,
    SourceEntityLink,
)
from rate_monitor.domain.identifiers import make_org_key, make_variant_key
from rate_monitor.domain.normalization import (
    normalize_institution_name,
    normalize_product_name,
)
from rate_monitor.domain.schemas import ParsedRateRow


def _find_link(
    session: Session, source_id: str, entity_type: str, key: str
) -> SourceEntityLink | None:
    """활성 매핑(valid_to IS NULL)만 찾는다."""
    return session.scalars(
        select(SourceEntityLink).where(
            SourceEntityLink.source_id == source_id,
            SourceEntityLink.entity_type == entity_type,
            SourceEntityLink.source_entity_key == key,
            SourceEntityLink.valid_to.is_(None),
        )
    ).first()


def _link(
    session: Session,
    *,
    source_id: str,
    entity_type: str,
    key: str,
    entity_id: str,
    source_name: str | None,
    now: datetime,
) -> None:
    session.add(
        SourceEntityLink(
            source_id=source_id,
            entity_type=entity_type,
            source_entity_key=key,
            entity_id=entity_id,
            source_name=source_name,
            match_method="exact_code",
            valid_from=now.date(),
            valid_to=None,
            created_at=now,
            updated_at=now,
        )
    )


def resolve_institution(session: Session, row: ParsedRateRow, now: datetime) -> Institution:
    """기관을 찾거나 만든다.

    finlife 상품 API는 지역을 주지 않으므로 sido_code/sigungu_code를 채우지
    않는다. 추측해서 채우면 날조가 된다 (docs/source-recon/finlife.md §5).
    """
    key = make_org_key(
        sector=_sector_of(row),
        source_institution_key=row.source_institution_key,
        institution_name=row.institution_name,
    )
    link = _find_link(session, row.source_id, "institution", key)
    if link is not None:
        institution = session.get(Institution, link.entity_id)
        if institution is not None:
            institution.last_seen_at = now
            return institution

    institution = Institution(
        sector=_sector_of(row),
        canonical_name=row.institution_name,
        normalized_name=normalize_institution_name(row.institution_name),
        institution_type=row.institution_type,
        sido_code=None,
        sigungu_code=None,
        address=row.address,
        availability_scope=row.availability_scope,
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(institution)
    session.flush()
    _link(
        session,
        source_id=row.source_id,
        entity_type="institution",
        key=key,
        entity_id=institution.id,
        source_name=row.institution_name,
        now=now,
    )
    return institution


def resolve_product(
    session: Session, row: ParsedRateRow, institution: Institution, now: datetime
) -> Product:
    key = f"{institution.id}:{row.source_product_key or normalize_product_name(row.product_name)}"
    link = _find_link(session, row.source_id, "product", key)
    if link is not None:
        product = session.get(Product, link.entity_id)
        if product is not None:
            product.last_seen_at = now
            return product

    product = Product(
        institution_id=institution.id,
        product_type=row.product_type,
        name=row.product_name,
        normalized_name=normalize_product_name(row.product_name),
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(product)
    session.flush()
    _link(
        session,
        source_id=row.source_id,
        entity_type="product",
        key=key,
        entity_id=product.id,
        source_name=row.product_name,
        now=now,
    )
    return product


def resolve_variant(
    session: Session, row: ParsedRateRow, product: Product, institution: Institution
) -> ProductVariant:
    """비교 단위를 찾거나 만든다. variant_key가 유일 식별자다."""
    org_key = make_org_key(
        sector=institution.sector,
        source_institution_key=row.source_institution_key,
        institution_name=row.institution_name,
    )
    variant_key = make_variant_key(
        sector=institution.sector,
        org_key=org_key,
        source_product_key=row.source_product_key,
        product_name=row.product_name,
        term_months=row.term_months,
        term_days=row.term_days,
        join_channel=row.join_channel,
        interest_method=row.interest_method,
        amount_min=row.amount_min,
        amount_max=row.amount_max,
        outlet_key=row.source_outlet_key,
    )
    existing = session.scalars(
        select(ProductVariant).where(ProductVariant.variant_key == variant_key)
    ).first()
    if existing is not None:
        return existing

    variant = ProductVariant(
        product_id=product.id,
        outlet_id=None,  # finlife는 점포 단위 금리를 주지 않는다
        term_months=row.term_months,
        term_days=row.term_days,
        join_channel=row.join_channel,
        interest_method=row.interest_method,
        payment_method=row.payment_method,
        amount_min=row.amount_min,
        amount_max=row.amount_max,
        customer_scope=row.customer_scope,
        rate_scope=row.rate_scope,
        variant_key=variant_key,
    )
    session.add(variant)
    session.flush()
    return variant


def _sector_of(row: ParsedRateRow) -> str:
    """권역 판정.

    finlife는 권역코드로 요청하므로 rate_scope로 되짚는다. 저축은행 공시는
    본점 기준(head_office_reference)이고 은행은 전국(nationwide)이다.
    """
    from rate_monitor.domain.enums import RateScope, Sector

    if row.rate_scope == RateScope.HEAD_OFFICE_REFERENCE:
        return Sector.SAVINGS_BANK
    return Sector.BANK
