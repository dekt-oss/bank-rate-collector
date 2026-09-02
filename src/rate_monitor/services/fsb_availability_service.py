"""FSB 정기예금 가입가능지역 census와 persistence.

핵심 계약:
- 공식 ``ratedepo`` AREA 17종만 다룬다. ``rateinst``로 확대하지 않는다.
- 지역별 금리 observation을 만들지 않는다.
- 지역전체 + 17개 AREA를 모두 확보·검증한 뒤에만 DB transaction을 연다.
- FSB ``FINAN_COMP_CODE``는 기존 active exact-code SourceEntityLink로만 푼다.
- partial/schema/identity 실패에서는 기존 membership을 변경하지 않는다.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from rate_monitor.collectors.fsb import parser as fsb_parser
from rate_monitor.collectors.fsb.adapter import (
    BASE_URL,
    CONNECT_TIMEOUT,
    PAGE_SIZE,
    READ_TIMEOUT,
    REQUEST_INTERVAL_SECONDS,
    REQUEST_TERM,
    SCREENS,
    USER_AGENT,
    FsbAdapter,
)
from rate_monitor.db.availability_models import InstitutionAvailabilityMembership
from rate_monitor.db.models import Institution, Source, SourceEntityLink
from rate_monitor.db.session import session_scope
from rate_monitor.domain.enums import Sector
from rate_monitor.domain.identifiers import make_org_key

SOURCE_ID = "fsb"
PRODUCT_TYPE = "term_deposit"
SCREEN = "ratedepo"
SCREEN_PATH, DATA_PATH = SCREENS[SCREEN]
MAX_CENSUS_PAGES = 10

# FSB 원문 코드다. 철자가 이상해 보여도 임의 교정하지 않는다.
AREAS: tuple[tuple[str, str], ...] = (
    ("YN_Kangwon", "강원"),
    ("YN_Kyungki", "경기"),
    ("YN_Kyungnam", "경남"),
    ("YN_Kyungbuk", "경북"),
    ("YN_Kwangju", "광주"),
    ("YN_Deaku", "대구"),
    ("YN_Deajeon", "대전"),
    ("YN_Busan", "부산"),
    ("YN_Seoul", "서울"),
    ("YN_Saejong", "세종"),
    ("YN_Ulsan", "울산"),
    ("YN_Incheon", "인천"),
    ("YN_Jeonnam", "전남"),
    ("YN_Jeonbuk", "전북"),
    ("YN_Jeju", "제주"),
    ("YN_Chungnam", "충남"),
    ("YN_Chungbuk", "충북"),
)
AREA_LABELS = dict(AREAS)
AREA_CODES = tuple(code for code, _label in AREAS)


class AvailabilityCensusError(RuntimeError):
    """부분/불일치 census를 authoritative truth로 승격하지 않기 위한 오류."""


@dataclass(frozen=True)
class AvailabilityCensus:
    query_date: date
    # FINAN_COMP_CODE -> AREA codes. 빈 membership은 허용하지 않는다.
    memberships: dict[str, frozenset[str]]
    institution_count: int
    product_count: int


@dataclass(frozen=True)
class AvailabilitySyncResult:
    query_date: date
    institution_count: int
    active_membership_count: int
    created: int
    unchanged: int
    expired: int


def availability_match_key(area_code: str) -> str:
    if area_code not in AREA_LABELS:
        raise ValueError(f"알 수 없는 FSB AREA: {area_code}")
    return f"{SOURCE_ID}:{PRODUCT_TYPE}:area:{area_code}"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _row_keys(rows: list[dict[str, Any]]) -> tuple[set[str], set[tuple[str, str]]]:
    institutions: set[str] = set()
    products: set[tuple[str, str]] = set()
    for row in rows:
        institution = _clean(row.get("FINAN_COMP_CODE"))
        product = _clean(row.get("FINAN_PROD_CODE"))
        if not institution or not product:
            raise AvailabilityCensusError(
                "FSB response lost FINAN_COMP_CODE/FINAN_PROD_CODE"
            )
        institutions.add(institution)
        products.add((institution, product))
    return institutions, products


def build_census_from_rows(
    query_date: date,
    rows_by_area: dict[str, list[dict[str, Any]]],
) -> AvailabilityCensus:
    """지역전체 + 정확히 17개 AREA를 institution-level membership으로 검증한다."""
    expected = {"", *AREA_CODES}
    actual = set(rows_by_area)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise AvailabilityCensusError(
            f"FSB census must contain 지역전체+17 AREA; missing={missing}, extra={extra}"
        )

    all_institutions, all_products = _row_keys(rows_by_area[""])
    if not all_institutions or not all_products:
        raise AvailabilityCensusError("FSB 지역전체 정기예금 census가 비었다")

    area_institutions: dict[str, set[str]] = {}
    area_products: dict[str, set[tuple[str, str]]] = {}
    for area_code in AREA_CODES:
        institutions, products = _row_keys(rows_by_area[area_code])
        if not institutions.issubset(all_institutions) or not products.issubset(all_products):
            raise AvailabilityCensusError(
                f"FSB AREA {area_code} contains rows absent from 지역전체"
            )
        area_institutions[area_code] = institutions
        area_products[area_code] = products

    institution_memberships = {
        institution: frozenset(
            code for code in AREA_CODES if institution in area_institutions[code]
        )
        for institution in all_institutions
    }
    no_area = sorted(
        institution for institution, memberships in institution_memberships.items()
        if not memberships
    )
    if no_area:
        raise AvailabilityCensusError(
            f"FSB 지역전체 기관이 17 AREA 어디에도 없다: {no_area[:10]}"
        )

    # 2026-09-01 evidence에서는 같은 기관의 모든 정기예금 상품이 같은 AREA
    # pattern이었다. 그 사실이 깨지면 institution × product_type으로 축약하면
    # 정보를 잃으므로 fail-closed한다.
    product_memberships = {
        product: frozenset(
            code for code in AREA_CODES if product in area_products[code]
        )
        for product in all_products
    }
    products_by_institution: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for product in all_products:
        products_by_institution[product[0]].append(product)
    inconsistent = {
        institution: sorted(product[1] for product in products)
        for institution, products in products_by_institution.items()
        if len({product_memberships[product] for product in products}) > 1
    }
    if inconsistent:
        sample = next(iter(sorted(inconsistent.items())))
        raise AvailabilityCensusError(
            "FSB 정기예금 상품별 AREA membership이 기관 내에서 갈라졌다; "
            f"institution={sample[0]}, products={sample[1]}"
        )

    return AvailabilityCensus(
        query_date=query_date,
        memberships=institution_memberships,
        institution_count=len(all_institutions),
        product_count=len(all_products),
    )


async def _fetch_area_rows(
    client: httpx.AsyncClient,
    adapter: FsbAdapter,
    query_date: date,
    area_code: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 1
    expected_total: int | None = None
    for _page in range(MAX_CENSUS_PAGES):
        end = start + PAGE_SIZE - 1
        _raw, payload = await adapter._post(  # same-package official FSB request contract
            client,
            DATA_PATH,
            adapter._rate_body(
                query_date=query_date.isoformat(),
                area=area_code,
                term=REQUEST_TERM,
                start=start,
                end=end,
            ),
        )
        page_rows = payload.get("REC")
        if not isinstance(page_rows, list):
            raise AvailabilityCensusError(
                f"FSB response has no REC list for area={area_code!r}"
            )
        if any(not isinstance(row, dict) for row in page_rows):
            raise AvailabilityCensusError(
                f"FSB REC contains non-object row for area={area_code!r}"
            )
        total = fsb_parser.total_count(payload)
        if total is None:
            raise AvailabilityCensusError(
                f"FSB response lost CNT for area={area_code!r}"
            )
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise AvailabilityCensusError(
                f"FSB CNT changed during paging for area={area_code!r}: "
                f"{expected_total} -> {total}"
            )
        rows.extend(page_rows)
        if len(rows) >= total:
            break
        if not page_rows:
            raise AvailabilityCensusError(
                f"FSB paging ended early for area={area_code!r}: {len(rows)}/{total}"
            )
        start = end + 1
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
    else:
        raise AvailabilityCensusError(
            f"FSB area={area_code!r} exceeded {MAX_CENSUS_PAGES} pages"
        )

    if expected_total is None or len(rows) != expected_total:
        raise AvailabilityCensusError(
            f"FSB area={area_code!r} returned {len(rows)} rows but CNT says {expected_total}"
        )
    return rows


async def fetch_fsb_availability_census(query_date: date) -> AvailabilityCensus:
    """공식 FSB ratedepo에서 지역전체 + 17 AREA를 완전하게 읽는다."""
    timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    adapter = FsbAdapter()
    rows_by_area: dict[str, list[dict[str, Any]]] = {}
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        page = await client.get(f"{BASE_URL}{SCREEN_PATH}")
        page.raise_for_status()
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        for area_code in ("", *AREA_CODES):
            rows_by_area[area_code] = await _fetch_area_rows(
                client, adapter, query_date, area_code
            )
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
    return build_census_from_rows(query_date, rows_by_area)


def _resolve_fsb_institutions(
    session: Session,
    source_codes: set[str],
) -> dict[str, str]:
    source = session.get(Source, SOURCE_ID)
    if source is None:
        raise AvailabilityCensusError(
            "FSB Source row가 없다. 먼저 정상 FSB 금리 수집으로 canonical identity를 구축한다"
        )

    resolved: dict[str, str] = {}
    for source_code in sorted(source_codes):
        source_key = make_org_key(Sector.SAVINGS_BANK, source_code)
        links = session.scalars(
            select(SourceEntityLink).where(
                SourceEntityLink.source_id == SOURCE_ID,
                SourceEntityLink.entity_type == "institution",
                SourceEntityLink.source_entity_key == source_key,
                SourceEntityLink.valid_to.is_(None),
            )
        ).all()
        if len(links) != 1:
            raise AvailabilityCensusError(
                f"FSB institution identity must resolve exactly once: {source_key}, "
                f"active_links={len(links)}"
            )
        link = links[0]
        if link.match_method != "exact_code":
            raise AvailabilityCensusError(
                f"FSB institution link is not exact_code: {source_key} ({link.match_method})"
            )
        institution = session.get(Institution, link.entity_id)
        if institution is None or institution.sector != Sector.SAVINGS_BANK:
            raise AvailabilityCensusError(
                f"FSB institution link points outside savings-bank canonical identity: {source_key}"
            )
        resolved[source_code] = institution.id
    return resolved


def reconcile_fsb_availability(
    session: Session,
    census: AvailabilityCensus,
    *,
    now: datetime,
) -> AvailabilitySyncResult:
    """검증된 완전 census를 한 transaction 안에서 temporal reconcile한다."""
    resolved = _resolve_fsb_institutions(session, set(census.memberships))
    desired: set[tuple[str, str]] = {
        (resolved[source_code], area_code)
        for source_code, areas in census.memberships.items()
        for area_code in areas
    }

    active_rows = session.scalars(
        select(InstitutionAvailabilityMembership).where(
            InstitutionAvailabilityMembership.source_id == SOURCE_ID,
            InstitutionAvailabilityMembership.product_type == PRODUCT_TYPE,
            InstitutionAvailabilityMembership.valid_to.is_(None),
        )
    ).all()
    active = {(row.institution_id, row.area_code): row for row in active_rows}

    created = unchanged = expired = 0
    locator = f"https://www.fsb.or.kr{DATA_PATH}"
    for institution_id, area_code in sorted(desired):
        row = active.get((institution_id, area_code))
        evidence = {
            "screen": "ratedepo_0100",
            "endpoint": DATA_PATH,
            "area_code": area_code,
            "query_date": census.query_date.isoformat(),
            "census_area_count": len(AREA_CODES),
        }
        if row is not None:
            row.last_seen_at = now
            row.seen_count += 1
            row.source_effective_date = census.query_date
            row.evidence_json = evidence
            row.updated_at = now
            unchanged += 1
            continue
        session.add(
            InstitutionAvailabilityMembership(
                source_id=SOURCE_ID,
                institution_id=institution_id,
                product_type=PRODUCT_TYPE,
                area_code=area_code,
                area_label=AREA_LABELS[area_code],
                availability_match_key=availability_match_key(area_code),
                source_effective_date=census.query_date,
                source_locator=locator,
                evidence_json=evidence,
                first_seen_at=now,
                last_seen_at=now,
                seen_count=1,
                valid_from=now,
                valid_to=None,
                created_at=now,
                updated_at=now,
            )
        )
        created += 1

    for key, row in active.items():
        if key not in desired:
            row.valid_to = now
            row.updated_at = now
            expired += 1

    session.flush()
    return AvailabilitySyncResult(
        query_date=census.query_date,
        institution_count=census.institution_count,
        active_membership_count=len(desired),
        created=created,
        unchanged=unchanged,
        expired=expired,
    )


FetchCensus = Callable[[date], Awaitable[AvailabilityCensus]]


async def sync_fsb_availability(
    factory: sessionmaker[Session],
    *,
    as_of: date | None = None,
    fetch_census: FetchCensus = fetch_fsb_availability_census,
    now: datetime | None = None,
) -> AvailabilitySyncResult:
    """완전 census 확보 후에만 transaction을 열어 membership을 동기화한다."""
    query_date = as_of or date.today()
    census = await fetch_census(query_date)
    if census.query_date != query_date:
        raise AvailabilityCensusError(
            f"census query_date mismatch: requested={query_date}, got={census.query_date}"
        )
    observed_at = now or datetime.now(UTC).replace(tzinfo=None)
    with session_scope(factory) as session:
        return reconcile_fsb_availability(session, census, now=observed_at)
