"""농·축협 파서 골든 테스트 (v4 §5, PR 4).

실물 fixture로만 검증한다. 2026-08-06에 `wmall.nonghyup.com`에서 받은 것이고,
계약은 `docs/source-recon/nh-local.md` §0.2에 실측으로 적혀 있다.

파서가 네트워크를 타지 않으므로 여기서 원천에 요청이 나가지 않는다.
"""

from datetime import date
from pathlib import Path

import pytest

from rate_monitor.collectors.base import SchemaChangedError
from rate_monitor.collectors.nh_local import parser as nh
from rate_monitor.domain.enums import InterestMethod, ProductType, RateScope, Sector

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nh_local"
AS_OF = date(2026, 8, 6)


@pytest.fixture()
def outlets() -> list[nh.NhOutlet]:
    return nh.parse_outlet_list((FIXTURES / "outlet_list_busan.html").read_text(encoding="utf-8"))


def _rows(outlet: nh.NhOutlet, name: str, product_type: ProductType):
    return nh.parse_detail(
        (FIXTURES / name).read_text(encoding="utf-8"),
        outlet=outlet,
        product_type=product_type,
        as_of=AS_OF,
    )


# ── 명부 ────────────────────────────────────────────────────────────────


def test_the_roster_yields_every_busan_outlet(outlets) -> None:
    """fixture는 전국 4,871행에서 부산 120행을 잘라 온 것이다."""
    assert len(outlets) == 120
    assert outlets[0] == nh.NhOutlet(
        brc="817020", name="가락농협", address="부산광역시 강서구 가락대로 1459"
    )
    # 식별자가 비면 상세를 못 부른다.
    assert all(o.brc and o.brc.isdigit() for o in outlets)


def test_phone_numbers_are_not_carried(outlets) -> None:
    """원천이 전화번호를 주지만 담지 않는다 (v3.1 §16.2).

    저축은행중앙회 TEL/CTEL, 신협 ownTelNo와 같은 규칙이다. 명부 HTML에는
    분명히 들어 있으므로, 안 담는 것이 우연이 아님을 여기서 못 박는다.
    """
    raw = (FIXTURES / "outlet_list_busan.html").read_text(encoding="utf-8")
    assert "051-" in raw, "fixture에 전화번호가 있어야 이 검사가 의미 있다"
    assert not any("051-" in "".join(o) for o in outlets)
    assert nh.NhOutlet._fields == ("brc", "name", "address")


def test_busan_filter_uses_the_address_not_the_name() -> None:
    """이름에 부산이 들어가도 주소가 경남인 조합이 있다 (v4 §4.3)."""
    mixed = [
        nh.NhOutlet("1", "가락농협", "부산광역시 강서구 가락대로 1459"),
        nh.NhOutlet("2", "부산경남양돈농협", "경상남도 김해시 주촌면 서부로 1585"),
    ]
    assert [o.brc for o in nh.busan_outlets(mixed)] == ["1"]


def test_a_changed_roster_header_stops_us() -> None:
    """열이 바뀐 것을 모르고 파싱하면 엉뚱한 칸을 주소로 읽는다."""
    with pytest.raises(SchemaChangedError):
        nh.parse_outlet_list("<table><tr><td>아무것도 아니다</td></tr></table>")


# ── 금리 상세 ───────────────────────────────────────────────────────────


def test_deposit_rates_match_the_screen(outlets) -> None:
    """2026-08-06 가락농협 거치식 실측값."""
    rows, _ = _rows(outlets[0], "deposit_detail_333072.html", ProductType.TERM_DEPOSIT)
    assert len(rows) == 24

    twelve = [r for r in rows if r.product_name == "정기예탁금" and r.term_months == 12]
    assert len(twelve) == 1
    assert str(twelve[0].base_rate) == "3"
    assert twelve[0].sector == Sector.NH_LOCAL
    assert twelve[0].source_effective_at == AS_OF


def test_rowspan_does_not_leak_the_product_name(outlets) -> None:
    """상품명에 rowspan이 걸려 첫 행만 그 칸을 갖는다.

    이어지는 칸을 안 들고 내려가면 둘째 행부터 기간을 상품명으로 읽는다.
    """
    rows, _ = _rows(outlets[0], "deposit_detail_333072.html", ProductType.TERM_DEPOSIT)
    names = {r.product_name for r in rows}
    assert "정기예탁금" in names and "복리식정기예탁금" in names
    # 기간 문자열이 상품명 자리에 들어오면 안 된다.
    assert not any("개월" in name for name in names)

    # 상품이 바뀌면 이어지던 칸도 끊겨야 한다.
    compound = [r for r in rows if r.product_name == "복리식정기예탁금"]
    assert len(compound) == 4
    assert all(r.interest_method == InterestMethod.COMPOUND for r in compound)


def test_simple_and_compound_are_told_apart(outlets) -> None:
    rows, _ = _rows(outlets[0], "deposit_detail_333072.html", ProductType.TERM_DEPOSIT)
    plain = [r for r in rows if r.product_name == "정기예탁금"]
    assert all(r.interest_method == InterestMethod.SIMPLE for r in plain)


def test_max_rate_is_never_filled_from_the_base(outlets) -> None:
    """원천에 최고 우대금리 열이 없다. 없는 것을 있는 것처럼 만들지 않는다 (v4 §3.3)."""
    rows, _ = _rows(outlets[0], "deposit_detail_333072.html", ProductType.TERM_DEPOSIT)
    assert all(r.max_rate is None for r in rows)


def test_a_bonus_rate_row_is_flagged_not_dropped(outlets) -> None:
    """`우대금리`는 더해 주는 금리이지 그 자체로 가입할 상품이 아니다.

    버리면 원천이 공시한 것을 우리가 지우는 것이고, 조용히 두면 0.1%가
    예금금리처럼 보인다. 남기고 센다.
    """
    rows, warnings = _rows(outlets[0], "deposit_detail_333072.html", ProductType.TERM_DEPOSIT)
    bonus = [r for r in rows if "우대금리" in r.product_name]
    assert bonus, "우대금리 행이 fixture에 있다"
    assert len(warnings) == len(bonus)
    assert all(r.join_channel == "internet" for r in bonus)


def test_an_unreadable_term_is_flagged_not_invented(outlets) -> None:
    """적립식 fixture에 기간이 `-`인 행이 하나 있다 (농어가목돈마련저축)."""
    rows, _ = _rows(outlets[0], "saving_detail_333072.html", ProductType.INSTALLMENT_SAVINGS)
    flagged = [r for r in rows if r.validation_status == "warning"]
    assert len(flagged) == 1
    assert flagged[0].term_months is None
    assert "계약기간을 읽지 못했다" in flagged[0].validation_message
    # 금리는 읽혔으므로 버리지 않는다.
    assert flagged[0].base_rate is not None


def test_savings_rates_match_the_screen(outlets) -> None:
    rows, _ = _rows(outlets[0], "saving_detail_333072.html", ProductType.INSTALLMENT_SAVINGS)
    assert len(rows) == 17
    twelve = [r for r in rows if r.product_name == "정기적금" and r.term_months == 12]
    assert str(twelve[0].base_rate) == "3.2"


def test_rows_carry_the_outlet_not_a_head_office(outlets) -> None:
    """금리가 점포 단위로 나온다. 조합마다 다르고 지점마다 다르다."""
    rows, _ = _rows(outlets[0], "deposit_detail_333072.html", ProductType.TERM_DEPOSIT)
    assert all(r.rate_scope == RateScope.OUTLET for r in rows)
    assert all(r.source_outlet_key == "817020" for r in rows)
    assert all(r.address == "부산광역시 강서구 가락대로 1459" for r in rows)


def test_the_parser_does_not_split_the_address(outlets) -> None:
    """지역은 저장 계층이 한 곳에서 정한다 (v4 §4). 여기서 또 자르면 두 벌이 된다."""
    rows, _ = _rows(outlets[0], "deposit_detail_333072.html", ProductType.TERM_DEPOSIT)
    assert all(r.sido is None and r.sigungu is None for r in rows)


def test_row_hashes_are_stable_and_distinct(outlets) -> None:
    """같은 행은 같은 해시, 다른 행은 다른 해시 (v3.1 §7)."""
    first, _ = _rows(outlets[0], "deposit_detail_333072.html", ProductType.TERM_DEPOSIT)
    again, _ = _rows(outlets[0], "deposit_detail_333072.html", ProductType.TERM_DEPOSIT)
    assert [r.source_record_hash for r in first] == [r.source_record_hash for r in again]
    assert len({r.source_record_hash for r in first}) == len(first)


def test_a_changed_detail_table_stops_us() -> None:
    with pytest.raises(SchemaChangedError):
        nh.parse_rate_table("<table><caption>다른 표</caption></table>")


def test_the_fingerprint_moves_when_the_columns_move() -> None:
    same = nh.schema_fingerprint("<table><th>상품명</th><th>금리</th></table>")
    other = nh.schema_fingerprint("<table><th>상품명</th><th>이율</th></table>")
    assert same != other
