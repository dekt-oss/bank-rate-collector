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
from rate_monitor.services.institution_matching import normalize_institution
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


def _find_shared_institution(
    session: Session, row: ParsedRateRow, key: str
) -> Institution | None:
    """다른 원천이 이미 만들어 둔 **같은 기관**을 찾는다.

    ── 왜 필요한가 ────────────────────────────────────────────────────

    `_find_link`는 `source_id`까지 맞춰 찾는다. 그래서 같은 은행을 두 원천이
    받으면 org_key가 완전히 같아도 기관 행이 둘 생긴다. 화면에서는 이렇게
    보인다 (2026-08-06 발행 DB 실측).

        savings_bank:0010390  finlife_savings_bank  '고려저축은행'  주소 없음
        savings_bank:0010390  fsb                   '고려'         부산 동구

    저축은행 79곳이 **전부** 이렇게 갈라져 있었다. 다른 업권은 원천이
    하나뿐이라 해당 없다 (전체 2,296개 키 중 갈라진 것이 정확히 이 79개다).

    ── 붙이는 조건 두 가지 ────────────────────────────────────────────

    잘못 붙이는 것이 안 붙는 것보다 훨씬 나쁘다. 서로 다른 은행의 금리가
    한 기관으로 합쳐지면 화면이 조용히 거짓말을 한다. 그래서 둘 다 만족할
    때만 붙인다.

    1. **공식 코드로 만든 키일 것.** 이름 해시(`sector:name:...`)는 붙이지
       않는다. 코드가 없어서 이름으로 대신한 것이므로 근거가 약하다.
    2. **정규화한 이름도 같을 것.** 두 원천이 우연히 같은 번호를 다른 체계로
       쓸 수 있다. 이름까지 맞아야 같은 은행이라고 본다.

    조건이 안 맞으면 붙이지 않고 그대로 둘로 남긴다 — 갈라진 것은 화면에서
    보이지만, 잘못 합쳐진 것은 안 보인다.
    """
    if ":name:" in key:
        return None
    link = session.scalars(
        select(SourceEntityLink).where(
            SourceEntityLink.entity_type == "institution",
            SourceEntityLink.source_entity_key == key,
            SourceEntityLink.valid_to.is_(None),
        )
    ).first()
    if link is None:
        return None
    institution = session.get(Institution, link.entity_id)
    if institution is None or institution.sector != _sector_of(row):
        return None
    if normalize_institution(institution.canonical_name) != normalize_institution(
        row.institution_name
    ):
        return None
    return institution


def _absorb(institution: Institution, row: ParsedRateRow) -> None:
    """원천마다 다른 것을 준다. 빈 칸만 채운다.

    저축은행이 그렇다. finlife는 이름을 온전히(`고려저축은행`) 주지만 주소를
    안 주고, FSB는 본점 주소를 주지만 이름을 약칭(`고려`)으로 준다. 어느
    쪽이 먼저 수집되는지에 따라 화면이 달라지면 안 된다.

    **이미 있는 값은 절대 덮지 않는다.** 한 번 잘못 수집된 실행이 멀쩡한
    값을 조용히 지워버리는 것을 막는다. 채우는 것만 한다.

    이름만 예외다. 정규화하면 같은 이름 중 **긴 쪽**을 쓴다 — `고려`보다
    `고려저축은행`이 화면에서 덜 헷갈리고, 검색창에 사람이 치는 말과도
    가깝다. 수집 순서와 무관하게 같은 답이 나온다.
    """
    name = row.institution_name
    if (
        name
        and len(name) > len(institution.canonical_name or "")
        and normalize_institution(name) == normalize_institution(institution.canonical_name)
    ):
        institution.canonical_name = name
        institution.normalized_name = normalize_institution_name(name)

    # 주소가 없는 원천은 조회지역이라도 채운다 (신협, v3.1 §11.1).
    #
    # 여기가 없으면 신협의 지역은 **영원히 빈칸으로 남는다.** 기관 행은 처음
    # 만들 때 한 번만 채워지는데, 그때 지역을 안 넣고 수집했기 때문이다.
    # 다시 수집해도 `resolve_institution`이 링크를 찾아 그냥 돌아온다.
    # 실제로 2026-08-07 발행본에서 신협 30,994행이 전부 지역이 비어, 시도를
    # 고르면 신협이 통째로 사라졌다.
    if not institution.region_sido and row.sido:
        region = region_fields(row.source_id, row.address, query_region=row.sido)
        if region.sido:
            institution.region_sido = region.sido
            institution.region_sigungu = region.sigungu
            institution.geo_basis = region.basis.value
            institution.geo_confidence = region.confidence

    if institution.address or not row.address:
        return
    region = region_fields(row.source_id, row.address)
    institution.address = row.address
    institution.region_sido = region.sido
    institution.region_sigungu = region.sigungu
    institution.geo_basis = region.basis.value
    institution.geo_confidence = region.confidence


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
            _absorb(institution, row)
            return institution

    shared = _find_shared_institution(session, row, key)
    if shared is not None:
        shared.last_seen_at = now
        _absorb(shared, row)
        _link(
            session,
            source_id=row.source_id,
            entity_type="institution",
            key=key,
            entity_id=shared.id,
            source_name=row.institution_name,
            now=now,
        )
        return shared

    region = region_fields(row.source_id, row.address, query_region=row.sido)
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
