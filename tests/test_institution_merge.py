"""같은 은행이 두 기관으로 갈라지지 않는다.

`resolve_institution`이 `source_id`까지 맞춰 매핑을 찾았기 때문에, 같은
은행을 두 원천이 받으면 org_key가 완전히 같아도 기관 행이 둘 생겼다.
2026-08-06 발행 DB 실측으로 저축은행 **79곳 전부**가 갈라져 있었다.

    savings_bank:0010390  finlife_savings_bank  '고려저축은행'  주소 없음
    savings_bank:0010390  fsb                   '고려'         부산광역시 동구 …

화면에서는 `고려`와 `고려저축은행`이 따로 섰고, 뒤엣것은 지역이 비어
`본점 기준` 배지만 달렸다.

**잘못 붙이는 것이 안 붙는 것보다 나쁘다.** 서로 다른 은행의 금리가 한
기관으로 합쳐지면 화면이 조용히 거짓말을 한다. 그래서 이 파일은 붙는
경우만큼 **안 붙어야 하는 경우**를 많이 본다.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.enums import (
    AvailabilityScope,
    CollectionMode,
    InterestMethod,
    JoinChannel,
    ProductType,
    RateScope,
    Sector,
    SourceRole,
    TrustLevel,
)
from rate_monitor.domain.schemas import ParsedRateRow
from rate_monitor.services import entity_service


@pytest.fixture
def factory(tmp_path: Path):
    engine = create_db_engine(tmp_path / "test.sqlite3")
    m.Base.metadata.create_all(engine)
    f = make_session_factory(engine)
    now = _now()
    with session_scope(f) as session:
        for source_id in ("fsb", "finlife_savings_bank"):
            session.add(
                m.Source(
                    id=source_id,
                    name=source_id,
                    sector=Sector.SAVINGS_BANK,
                    mode=CollectionMode.HTTP,
                    source_role=SourceRole.PRIMARY_OFFICIAL,
                    trust_level=TrustLevel.OFFICIAL_DIRECT,
                    priority=10,
                    base_reference="test",
                    enabled=True,
                    policy_status="review",
                    coverage_status="partial",
                    created_at=now,
                    updated_at=now,
                )
            )
    return f


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _row(**overrides) -> ParsedRateRow:
    """저축은행 모양의 행. 원천마다 이름 표기와 주소 유무가 다르다."""
    base = dict(
        source_id="fsb",
        source_role=SourceRole.PRIMARY_OFFICIAL,
        trust_level=TrustLevel.OFFICIAL_DIRECT,
        sector=Sector.SAVINGS_BANK,
        source_institution_key="0010390",
        source_outlet_key=None,
        source_product_key=None,
        institution_name="고려",
        outlet_name=None,
        institution_type=None,
        sido="부산",
        sigungu="동구",
        address="부산광역시 동구 중앙대로 244",
        product_type=ProductType.TERM_DEPOSIT,
        product_name="정기예금",
        term_months=12,
        term_days=None,
        join_channel=JoinChannel.BRANCH,
        interest_method=InterestMethod.SIMPLE,
        payment_method=None,
        amount_min=None,
        amount_max=None,
        customer_scope=None,
        availability_scope=AvailabilityScope.NATIONWIDE,
        rate_scope=RateScope.INSTITUTION,
        base_rate=Decimal("3.9000"),
        max_rate=None,
        preference_raw="",
        source_row_ref="0010390/12",
        base_source_locator="REC[0]",
        source_record_hash="sha256:test",
    )
    base.update(overrides)
    return ParsedRateRow(**base)


def _resolve(factory, row: ParsedRateRow) -> str:
    with session_scope(factory) as session:
        return entity_service.resolve_institution(session, row, _now()).id


def _institutions(factory) -> list[m.Institution]:
    with session_scope(factory) as session:
        return list(session.scalars(select(m.Institution)).all())


# ── 붙어야 하는 경우 ────────────────────────────────────────────────────


def test_two_sources_with_the_same_code_share_one_institution(factory) -> None:
    """org_key가 같으면 원천이 달라도 기관은 하나다.

    이것이 `고려` / `고려저축은행`이 두 줄로 서던 원인이다.
    """
    first = _resolve(factory, _row(source_id="finlife_savings_bank",
                                   institution_name="고려저축은행", address=None))
    second = _resolve(factory, _row(source_id="fsb", institution_name="고려"))

    assert first == second
    assert len(_institutions(factory)) == 1


def test_the_longer_name_wins_whichever_source_came_first(factory) -> None:
    """`고려`보다 `고려저축은행`이 화면에서 덜 헷갈린다.

    수집 순서에 따라 이름이 달라지면 안 되므로 양쪽 순서를 다 본다.
    """
    _resolve(factory, _row(source_id="fsb", institution_name="고려"))
    _resolve(factory, _row(source_id="finlife_savings_bank",
                           institution_name="고려저축은행", address=None))
    assert _institutions(factory)[0].canonical_name == "고려저축은행"


def test_the_address_arrives_even_when_the_addressless_source_ran_first(factory) -> None:
    """finlife가 먼저 돌아 주소 없이 만들어도 FSB가 채운다.

    수집 워크플로가 실제로 그 순서다 (collect.yml). 채우지 않으면 지역이
    영영 비고 화면에 `본점 기준` 배지만 남는다.
    """
    _resolve(factory, _row(source_id="finlife_savings_bank",
                           institution_name="고려저축은행", address=None))
    _resolve(factory, _row(source_id="fsb", institution_name="고려"))

    institution = _institutions(factory)[0]
    assert institution.address == "부산광역시 동구 중앙대로 244"
    assert (institution.region_sido, institution.region_sigungu) == ("부산", "동구")
    assert institution.geo_basis == "head_office"


def test_an_existing_address_is_never_overwritten(factory) -> None:
    """빈 칸만 채운다. 한 번 잘못 수집된 실행이 멀쩡한 값을 지우면 안 된다."""
    _resolve(factory, _row(source_id="fsb", institution_name="고려"))
    _resolve(factory, _row(source_id="finlife_savings_bank",
                           institution_name="고려저축은행", address=None))
    assert _institutions(factory)[0].address == "부산광역시 동구 중앙대로 244"


# ── 붙으면 안 되는 경우 ─────────────────────────────────────────────────


def test_a_different_bank_with_the_same_code_is_not_merged(factory) -> None:
    """두 원천이 우연히 같은 번호를 다른 체계로 쓸 수 있다.

    이름까지 맞아야 같은 은행으로 본다. 안 맞으면 갈라진 채로 둔다 —
    갈라진 것은 화면에 보이지만 잘못 합쳐진 것은 안 보인다.
    """
    first = _resolve(factory, _row(source_id="fsb", institution_name="고려"))
    second = _resolve(factory, _row(source_id="finlife_savings_bank",
                                    institution_name="페퍼저축은행", address=None))

    assert first != second
    assert len(_institutions(factory)) == 2


def test_a_name_hashed_key_is_never_merged(factory) -> None:
    """공식 코드가 없으면 붙이지 않는다.

    코드가 없어서 이름으로 대신한 것이므로 근거가 약하다. 같은 이름의
    다른 금고가 실제로 있다 (중앙·제일 등).
    """
    first = _resolve(factory, _row(source_id="fsb", source_institution_key=None,
                                   institution_name="중앙"))
    second = _resolve(factory, _row(source_id="finlife_savings_bank",
                                    source_institution_key=None,
                                    institution_name="중앙", address=None))

    assert first != second


def test_the_same_source_twice_still_resolves_to_one(factory) -> None:
    """원래 되던 것이 깨지지 않았는지. 같은 원천이 두 번 오면 하나다."""
    first = _resolve(factory, _row())
    second = _resolve(factory, _row())

    assert first == second
    assert len(_institutions(factory)) == 1
