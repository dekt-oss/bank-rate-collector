"""저축은행중앙회(FSB) 파서 검증 — 실물 fixture로 계약을 못박는다.

fixture는 2026-08-05 정찰(`scripts/p1b_fsb_recon.py`)에서 받은 실제 응답이다.
네트워크를 호출하지 않는다.

    tests/fixtures/fsb/ratedepo_0100_01.json   정기예금 12개월 (부산 필터)
    tests/fixtures/fsb/rateinst_0100_01.json   정기적금 12개월 (부산 필터)
    tests/fixtures/fsb/sabfindquic_0100.json   저축은행 찾기 (부산/경남 지부)
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from rate_monitor.collectors.base import SchemaChangedError
from rate_monitor.collectors.fsb import parser
from rate_monitor.domain.enums import (
    InterestMethod,
    ProductType,
    RateScope,
    Sector,
    SourceRole,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fsb"


def _read(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def deposit() -> dict:
    return _read("ratedepo_0100_01.json")


@pytest.fixture(scope="module")
def savings() -> dict:
    return _read("rateinst_0100_01.json")


@pytest.fixture(scope="module")
def branches() -> dict:
    return parser.parse_branches(_read("sabfindquic_0100.json"))


# ── fixture 자체 모양 ───────────────────────────────────────────────────


def test_fixture_shape_is_pinned(deposit: dict, savings: dict) -> None:
    """fixture가 바뀌면 시끄럽게 실패해야 한다."""
    assert len(deposit["REC"]) == 10
    assert len(savings["REC"]) == 10
    # 총건수는 행 안에 있다 (docs/source-recon/fsb.md §3.3).
    assert parser.total_count(deposit) == 67


# ── 금리 행 ─────────────────────────────────────────────────────────────


def test_one_record_expands_into_simple_and_compound(deposit: dict) -> None:
    """단리와 복리는 서로 다른 비교 단위다. 한 행이 두 행으로 펼쳐진다."""
    rows, _ = parser.parse(deposit, screen="ratedepo", area="YN_Busan", only_terms=(12,))
    # 10건 중 OSB만 12개월을 취급하지 않는다. 나머지 9건이 두 행씩.
    with_12m = [r for r in deposit["REC"] if "JUNG_12M_DAN" in r]
    assert len(with_12m) == 9
    assert len(rows) == len(with_12m) * 2

    first = [r for r in rows if r.source_product_key == "BNK1003"]
    assert {r.interest_method for r in first} == {
        InterestMethod.SIMPLE,
        InterestMethod.COMPOUND,
    }
    assert {r.base_rate for r in first} == {Decimal("3.8")}


def test_bank_name_padding_is_stripped(deposit: dict) -> None:
    """`BANK_NAME`이 고정폭으로 온다. 그대로 두면 같은 은행이 갈린다."""
    assert deposit["REC"][0]["BANK_NAME"] != deposit["REC"][0]["BANK_NAME"].strip()
    rows, _ = parser.parse(deposit, screen="ratedepo", area="", only_terms=(12,))
    assert all(r.institution_name == r.institution_name.strip() for r in rows)
    assert "BNK" in {r.institution_name for r in rows}


def test_rate_scope_is_head_office_reference(deposit: dict) -> None:
    """화면이 스스로 본점 기준이라고 밝힌다. 지점 금리로 오해되면 안 된다."""
    rows, _ = parser.parse(deposit, screen="ratedepo", area="YN_Busan", only_terms=(12,))
    assert {r.rate_scope for r in rows} == {RateScope.HEAD_OFFICE_REFERENCE}
    assert {r.sector for r in rows} == {Sector.SAVINGS_BANK}
    assert {r.source_role for r in rows} == {SourceRole.PRIMARY_OFFICIAL}


def test_product_type_comes_from_the_screen(deposit: dict, savings: dict) -> None:
    depo, _ = parser.parse(deposit, screen="ratedepo", area="", only_terms=(12,))
    inst, _ = parser.parse(savings, screen="rateinst", area="", only_terms=(12,))
    assert {r.product_type for r in depo} == {ProductType.TERM_DEPOSIT}
    assert {r.product_type for r in inst} == {ProductType.INSTALLMENT_SAVINGS}


def test_term_comes_from_the_row_not_the_request(deposit: dict) -> None:
    """기간은 행에 실제로 있는 것을 쓴다.

    정찰 문서 §4는 `CHK_MONTH=12`면 12개월 필드만 온다고 적었지만 실물은
    다르다. 이 fixture는 12개월 조회로 받은 것인데도 1/3/6/24/36개월이 함께
    들어 있고, **36개월만 취급하는 상품(OSB)도 섞여 있다.** 요청값을 행에
    덮어씌우면 그 상품에 없는 12개월 금리를 지어내게 된다.
    """
    rows, _ = parser.parse(deposit, screen="ratedepo", area="")
    assert {r.term_months for r in rows} == {1, 3, 6, 12, 24, 36}

    # 36개월만 취급하는 상품에는 12개월 행이 생기면 안 된다.
    osb = [r for r in rows if r.institution_name == "OSB"]
    assert osb, "fixture에 OSB 행이 있어야 검사가 성립한다"
    assert {r.term_months for r in osb} == {36}

    # only_terms로 좁혀도 없는 기간을 만들어내지는 않는다.
    narrowed, _ = parser.parse(
        deposit, screen="ratedepo", area="", only_terms=(12,)
    )
    assert {r.term_months for r in narrowed} == {12}
    assert not [r for r in narrowed if r.institution_name == "OSB"]


def test_effective_date_comes_from_the_page(deposit: dict) -> None:
    rows, _ = parser.parse(deposit, screen="ratedepo", area="", only_terms=(12,))
    assert all(r.source_effective_at is not None for r in rows)
    assert str(rows[0].source_effective_at) == "2026-07-29"


def test_preference_text_is_kept_whole(deposit: dict) -> None:
    """finlife는 우대조건이 한 필드인데 FSB는 셋이다. 셋 다 남긴다."""
    rows, _ = parser.parse(deposit, screen="ratedepo", area="", only_terms=(12,))
    texts = [r.preference_raw for r in rows if r.preference_raw]
    assert texts
    assert any("우대조건:" in t for t in texts)
    assert any("가입대상:" in t for t in texts)


def test_contact_fields_are_dropped(deposit: dict) -> None:
    """`OWNER`에 담당 부서명과 전화번호가 들어온다. 저장하지 않는다."""
    assert "경영기획부" in deposit["REC"][0]["OWNER"]
    rows, _ = parser.parse(deposit, screen="ratedepo", area="", only_terms=(12,))
    blob = json.dumps([r.extra for r in rows], ensure_ascii=False)
    assert "경영기획부" not in blob
    assert not any("OWNER" in (r.extra or {}) for r in rows)


def test_record_hash_ignores_contact_churn(deposit: dict) -> None:
    """담당자가 바뀌었다고 금리가 바뀐 것으로 잡히면 안 된다."""
    record = deposit["REC"][0]
    changed = dict(record, OWNER="다른부서, 0000000000")
    assert parser._record_hash(record) == parser._record_hash(changed)

    moved = dict(record, JUNG_12M_DAN="9.9")
    assert parser._record_hash(record) != parser._record_hash(moved)


def test_locator_points_at_the_source_field(deposit: dict) -> None:
    rows, _ = parser.parse(deposit, screen="ratedepo", area="", only_terms=(12,))
    simple = next(r for r in rows if r.interest_method == InterestMethod.SIMPLE)
    assert simple.base_source_locator == "$.REC[0].JUNG_12M_DAN"

    # 실제로 그 자리를 가리키는지 역추적한다.
    assert deposit["REC"][0]["JUNG_12M_DAN"] == str(simple.base_rate)


def test_page_offset_shifts_the_locator(deposit: dict) -> None:
    """2페이지 행이 1페이지 행과 같은 위치를 가리키면 추적이 깨진다."""
    rows, _ = parser.parse(
        deposit, screen="ratedepo", area="", only_terms=(12,), page_offset=100
    )
    assert rows[0].base_source_locator == "$.REC[100].JUNG_12M_DAN"


def test_parsing_is_deterministic(deposit: dict) -> None:
    a, _ = parser.parse(deposit, screen="ratedepo", area="", only_terms=(12,))
    b, _ = parser.parse(deposit, screen="ratedepo", area="", only_terms=(12,))
    assert a == b


# ── 점포 명부 ───────────────────────────────────────────────────────────


def test_branches_are_keyed_by_bank_name(branches: dict) -> None:
    """금리 화면과 결합하는 키가 `BANK_NAME`이다."""
    assert "BNK" in branches
    entry = next(e for e in branches["BNK"] if e["name"] == "본점")
    assert entry["address"].startswith("부산광역시 동구")
    assert entry["source_outlet_key"] == "fb219:001"


def test_address_is_attached_from_the_head_office(
    deposit: dict, branches: dict
) -> None:
    """금리 화면에는 소재지가 없다. 저축은행 찾기 화면에서 붙인다."""
    rows, _ = parser.parse(
        deposit, screen="ratedepo", area="", only_terms=(12,), branches=branches
    )
    bnk = next(r for r in rows if r.institution_name == "BNK")
    assert bnk.address.startswith("부산광역시 동구")
    assert bnk.sigungu == "동구"
    # 그래도 금리는 본점 기준이다. 그 지점 적용금리가 아니다.
    assert bnk.rate_scope == RateScope.HEAD_OFFICE_REFERENCE


def test_branch_address_is_never_used_as_the_institution_address() -> None:
    """지점 주소를 기관 주소로 쓰면 "본점 소재지 기준" 표기가 거짓이 된다."""
    only_branch = [{"name": "해운대지점", "address": "부산 해운대구 1"}]
    assert parser.head_office(only_branch) is None

    with_head = [*only_branch, {"name": "본점", "address": "부산 동구 2"}]
    assert parser.head_office(with_head)["address"] == "부산 동구 2"


def test_rows_carry_the_outlet_directory(deposit: dict, branches: dict) -> None:
    """점포를 만들 수 있게 명부를 행에 싣는다."""
    rows, _ = parser.parse(
        deposit, screen="ratedepo", area="", only_terms=(12,), branches=branches
    )
    bnk = next(r for r in rows if r.institution_name == "BNK")
    assert len(bnk.outlets) == len(branches["BNK"])


# ── 구조 변화 ───────────────────────────────────────────────────────────


def test_missing_records_key_is_breaking() -> None:
    with pytest.raises(SchemaChangedError, match="REC"):
        parser.check_schema({"COMMON_HEAD": {}})


def test_missing_required_field_is_breaking(deposit: dict) -> None:
    broken = {"REC": [{k: v for k, v in deposit["REC"][0].items()
                       if k != "FINAN_COMP_CODE"}]}
    with pytest.raises(SchemaChangedError, match="FINAN_COMP_CODE"):
        parser.check_schema(broken)


def test_missing_optional_field_is_only_a_warning(deposit: dict) -> None:
    softened = {"REC": [{k: v for k, v in deposit["REC"][0].items()
                         if k != "SWEETENER"}]}
    warnings = parser.check_schema(softened)
    assert any("SWEETENER" in w for w in warnings)


def test_fingerprint_reacts_to_field_changes(deposit: dict, savings: dict) -> None:
    assert parser.schema_fingerprint(deposit) == parser.schema_fingerprint(deposit)
    # 정기적금에만 BANK_CODE·TOP_CREDIT이 더 있다.
    assert parser.schema_fingerprint(deposit) != parser.schema_fingerprint(savings)


# ── 값이 이상할 때 ──────────────────────────────────────────────────────


def test_zero_rate_becomes_a_warning_not_a_silent_value(deposit: dict) -> None:
    """0%가 실제 0인지 미취급인지 화면이 구분해주지 않는다. 검수로 넘긴다."""
    zeroed = {"REC": [dict(deposit["REC"][0], JUNG_12M_DAN="0", TOP_12M_DAN="0")]}
    rows, _ = parser.parse(zeroed, screen="ratedepo", area="", only_terms=(12,))
    simple = next(r for r in rows if r.interest_method == InterestMethod.SIMPLE)
    assert simple.base_rate == Decimal(0)
    assert simple.validation_status == "warning"
    assert "미취급" in simple.validation_message


def test_unreadable_rate_becomes_error_not_a_silent_null(deposit: dict) -> None:
    bad = {"REC": [dict(deposit["REC"][0], JUNG_12M_DAN="문의")]}
    rows, _ = parser.parse(bad, screen="ratedepo", area="", only_terms=(12,))
    simple = next(r for r in rows if r.interest_method == InterestMethod.SIMPLE)
    assert simple.base_rate is None
    assert simple.validation_status == "error"


def test_absent_interest_method_produces_no_row(deposit: dict) -> None:
    """복리를 취급하지 않으면 필드가 없다. 0으로 채우지 않는다."""
    no_bok = {"REC": [{k: v for k, v in deposit["REC"][0].items()
                       if not k.endswith("_BOK")}]}
    rows, _ = parser.parse(no_bok, screen="ratedepo", area="", only_terms=(12,))
    assert {r.interest_method for r in rows} == {InterestMethod.SIMPLE}
