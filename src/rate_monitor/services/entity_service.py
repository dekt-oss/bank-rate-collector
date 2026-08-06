"""엔터티 해석 — 원천 키를 내부 표준 엔터티에 붙인다 (명세서 v3 §5.7).

이름이 아니라 원천 식별자를 우선한다 (v3 §3.2). 이름은 바뀌지만 코드는
대체로 유지되고, 이름으로만 묶으면 통폐합·개명에서 이력이 끊긴다.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from rate_monitor.db.models import (
    Institution,
    Outlet,
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
from rate_monitor.services.region_service import region_fields


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

    region = region_fields(row.source_id, row.address)
    institution = Institution(
        sector=_sector_of(row),
        canonical_name=row.institution_name,
        normalized_name=normalize_institution_name(row.institution_name),
        institution_type=row.institution_type,
        sido_code=None,
        sigungu_code=None,
        region_sido=region.sido,
        region_sigungu=region.sigungu,
        geo_basis=region.basis.value,
        geo_confidence=region.confidence,
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


def resolve_outlet(
    session: Session, row: ParsedRateRow, institution: Institution, now: datetime
) -> Outlet | None:
    """점포를 찾거나 만든다. 원천이 점포키를 주지 않으면 None이다.

    finlife는 점포 단위 정보를 주지 않으므로 항상 None이다. 새마을금고는
    `(gmgoCd, divCd)`를 주므로 여기서 점포가 생긴다.

    **점포를 왜 만드는가**: 금리는 금고 단위지만 구·군 주소는 점포에 있다.
    "부산 ○○구에서 가입 가능한 상품"을 만들려면 점포 명부가 필요하다.

    `sido_code`/`sigungu_code`는 채우지 않는다. 원천이 주는 `r1`/`r2`는 그
    사이트의 화면 파라미터이지 행정구역 공식 코드가 아니다
    (`config/regions.yaml` 참조). 주소 원문만 남긴다.
    """
    if not row.source_outlet_key:
        return None

    key = f"{institution.id}:{row.source_outlet_key}"
    link = _find_link(session, row.source_id, "outlet", key)
    if link is not None:
        outlet = session.get(Outlet, link.entity_id)
        if outlet is not None:
            return outlet

    region = region_fields(row.source_id, row.address)
    outlet = Outlet(
        institution_id=institution.id,
        name=row.outlet_name or row.source_outlet_key,
        sido_code=None,
        sigungu_code=None,
        region_sido=region.sido,
        region_sigungu=region.sigungu,
        geo_basis=region.basis.value,
        geo_confidence=region.confidence,
        address=row.address,
        active=True,
    )
    session.add(outlet)
    session.flush()
    _link(
        session,
        source_id=row.source_id,
        entity_type="outlet",
        key=key,
        entity_id=outlet.id,
        source_name=row.outlet_name,
        now=now,
    )
    return outlet


def resolve_outlet_directory(
    session: Session, row: ParsedRateRow, institution: Institution, now: datetime
) -> list[Outlet]:
    """행이 실어 온 점포 명부를 저장한다.

    금리가 기관 단위인 원천에서 쓴다. 새마을금고는 금리가 금고마다 하나인데
    주소는 점포마다 다르고, 한 금고가 두 구에 점포를 두기도 한다. 명부가
    없으면 대표 점포가 있는 구에서만 그 금고가 보인다.

    `row.outlets`가 비어 있으면 아무것도 하지 않으므로 finlife에는 영향이 없다.
    같은 점포를 두 번 만들지 않는 것은 `source_entity_links`의 부분 유니크
    인덱스가 보장한다.
    """
    created: list[Outlet] = []
    for entry in row.outlets:
        source_key = entry.get("source_outlet_key")
        if not source_key:
            continue
        key = f"{institution.id}:{source_key}"
        link = _find_link(session, row.source_id, "outlet", key)
        if link is not None:
            existing = session.get(Outlet, link.entity_id)
            if existing is not None:
                # 주소·전화는 바뀔 수 있으므로 최신값으로 맞춘다.
                existing.address = entry.get("address") or existing.address
                existing.phone = entry.get("phone") or existing.phone
                # 주소가 바뀌면 지역도 따라가야 한다. 안 그러면 이사한 점포가
                # 옛 구에 남아 그 구의 최고금리를 계속 만든다.
                region = region_fields(row.source_id, existing.address)
                existing.region_sido = region.sido
                existing.region_sigungu = region.sigungu
                existing.geo_basis = region.basis.value
                existing.geo_confidence = region.confidence
                continue

        region = region_fields(row.source_id, entry.get("address"))
        outlet = Outlet(
            institution_id=institution.id,
            name=entry.get("name") or source_key,
            sido_code=None,
            sigungu_code=None,
            region_sido=region.sido,
            region_sigungu=region.sigungu,
            geo_basis=region.basis.value,
            geo_confidence=region.confidence,
            address=entry.get("address"),
            phone=entry.get("phone"),
            active=True,
        )
        session.add(outlet)
        session.flush()
        _link(
            session,
            source_id=row.source_id,
            entity_type="outlet",
            key=key,
            entity_id=outlet.id,
            source_name=entry.get("name"),
            now=now,
        )
        created.append(outlet)
    return created


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
    session: Session,
    row: ParsedRateRow,
    product: Product,
    institution: Institution,
    outlet: Outlet | None = None,
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
        payment_method=row.payment_method,
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
        # 점포를 준 원천만 채워진다. finlife는 점포 단위 금리를 주지 않아 None이다.
        outlet_id=outlet.id if outlet is not None else None,
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
    """권역은 행이 밝힌 값을 그대로 쓴다.

    예전에는 `rate_scope`로 되짚어 추측했다. 저축은행 하나만 있을 때는
    맞았지만 원천이 늘면 곧바로 틀린다. 새마을금고 행은 `rate_scope=institution`
    이라 그 추측이 `bank`를 돌려주고, 그 값이 `make_org_key`에 들어가
    `"bank:1203"` 같은 잘못된 식별키를 만든다.
    """
    return row.sector
