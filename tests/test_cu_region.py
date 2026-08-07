"""신협의 지역이 실제로 저장되는가 (v3.1 §11.1).

2026-08-07 발행본에서 신협 30,994행의 지역이 **전부** 비어 있었다. 화면에서
시도를 하나라도 고르면 신협이 통째로 사라졌다 — 부산 사람이 부산을 골라도
부산 신협이 안 나왔다.

원인은 두 겹이었고 둘 다 조용했다.

1. 어댑터가 전체(`AA`)를 한 번에 받아서 어느 행이 어느 지역 조합인지 몰랐다.
2. 알았더라도 저장이 안 됐다. `region_fields`가 **주소에서만** 지역을 뽑는데
   신협은 주소를 주지 않는다.

그래서 이 파일은 「조회조건에서 온 지역」이 끝까지 살아남는지를 본다.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine
from rate_monitor.domain.enums import (
    AvailabilityScope,
    InterestMethod,
    ProductType,
    RateScope,
    Sector,
    SourceRole,
    TrustLevel,
    ValidationStatus,
)
from rate_monitor.domain.schemas import ParsedRateRow
from rate_monitor.services.entity_service import resolve_institution
from rate_monitor.services.region_service import region_fields

NOW = datetime(2026, 8, 7, 5, 0, tzinfo=UTC)


def _cu_row(*, sido: str | None, name: str = "부산항운신협") -> ParsedRateRow:
    return ParsedRateRow(
        source_id="cu",
        source_role=SourceRole.PRIMARY_OFFICIAL,
        trust_level=TrustLevel.OFFICIAL_DIRECT,
        sector=Sector.CU,
        source_institution_key="02022",
        source_outlet_key=None,
        source_product_key="S001",
        institution_name=name,
        outlet_name=None,
        institution_type=None,
        sido=sido,
        sigungu=None,
        address=None,
        product_type=ProductType.TERM_DEPOSIT,
        product_name="정기예탁금",
        term_months=12,
        term_days=None,
        join_channel=None,
        interest_method=InterestMethod.UNKNOWN,
        payment_method=None,
        amount_min=None,
        amount_max=None,
        customer_scope=None,
        availability_scope=AvailabilityScope.LOCAL_MEMBERS,
        rate_scope=RateScope.INSTITUTION,
        base_rate=None,
        max_rate=None,
        preference_raw=None,
        source_row_ref="02022/S001/12",
        base_source_locator="$[0].baseRate",
        source_record_hash="x" * 16,
        source_effective_at=None,
        validation_status=ValidationStatus.VALID,
        validation_message=None,
        extra={},
    )


@pytest.fixture
def session(tmp_path):
    engine = create_db_engine(tmp_path / "t.sqlite3")
    m.Base.metadata.create_all(engine)
    with Session(engine) as s:
        # source_entity_links가 sources를 가리킨다. 없으면 외래키에서 죽는다.
        s.add(m.Source(
            id="cu", name="신협 전자공시", sector="cu", mode="http",
            source_role="primary_official", trust_level="official_direct",
            priority=10, enabled=True, policy_status="review",
            coverage_status="partial", created_at=NOW, updated_at=NOW,
        ))
        s.flush()
        yield s
    engine.dispose()


# ── 규칙 자체 ───────────────────────────────────────────────────────────


def test_the_query_region_becomes_a_sido_but_never_a_district() -> None:
    """조회지역은 시도까지다. 구·군을 붙이면 없는 것을 지어내는 것이다."""
    f = region_fields("cu", None, query_region="부산")
    assert (f.sido, f.sigungu) == ("부산", None)
    assert f.basis.value == "source_query_region"
    assert f.confidence == "medium"


def test_a_source_with_addresses_never_borrows_the_query_region() -> None:
    """주소를 주는 원천에 조회지역을 섞으면 어느 쪽이 답인지 알 수 없다."""
    assert region_fields("kfcc", None, query_region="부산").sido is None
    assert region_fields("fsb", None, query_region="부산").sido is None


def test_a_lump_the_screen_will_not_split_stays_a_lump() -> None:
    """신협 코드 18은 광주와 전남이 섞여 있다 (어댑터 주석의 실측).

    한쪽 이름을 붙이면 나머지 지역 조합이 거짓으로 그 지역에 들어간다.
    """
    assert region_fields("cu", None, query_region="광주·전남").sido == "광주·전남"


# ── 저장까지 ────────────────────────────────────────────────────────────


def test_a_new_institution_keeps_the_region_it_was_found_in(session) -> None:
    inst = resolve_institution(session, _cu_row(sido="부산"), NOW)
    session.flush()
    assert inst.region_sido == "부산"
    assert inst.region_sigungu is None
    assert inst.geo_basis == "source_query_region"


def test_an_institution_collected_without_a_region_gets_one_later(session) -> None:
    """**이 테스트가 이 파일의 이유다.**

    기관 행은 처음 만들 때 한 번만 채워진다. 지역 없이 만들어진 신협
    848곳은, 지역을 채우는 경로가 없으면 다시 수집해도 영원히 빈칸이다.
    """
    first = resolve_institution(session, _cu_row(sido=None), NOW)
    session.flush()
    assert first.region_sido is None, "전제가 틀렸다"

    again = resolve_institution(session, _cu_row(sido="부산"), NOW)
    session.flush()
    assert again.id == first.id, "같은 조합이 둘로 갈렸다"
    assert again.region_sido == "부산", "다시 수집해도 지역이 안 채워진다"


def test_a_region_already_recorded_is_never_overwritten(session) -> None:
    """한 조합이 여러 지역 조회에 걸릴 수 있다. 먼저 만난 지역이 남는다.

    덮어쓰기를 허용하면 실행 순서에 따라 화면의 지역이 바뀐다 — 데이터가
    안 바뀌었는데 화면이 달라지는 것은 신뢰를 깎는다.
    """
    resolve_institution(session, _cu_row(sido="부산"), NOW)
    session.flush()
    later = resolve_institution(session, _cu_row(sido="경남"), NOW)
    session.flush()
    assert later.region_sido == "부산"
