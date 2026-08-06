"""두 원천이 같은 저축은행을 준다 (v4 §9.1·§11.1, PR 7-4).

같은 상품이 화면에 두 줄로 나오면 안 된다. 그렇다고 한 원천을 통째로 빼면
그쪽에만 있는 상품이 사라진다. **겹치는 것만** 빼는 것이 이 파일의 계약이다.
"""

from rate_monitor.services.dashboard_service import (
    _comparison_key,
    _drop_duplicate_source_rows,
    dedupe_sources,
    reference_sectors,
)
from rate_monitor.services.institution_matching import (
    MANUAL_ALIASES,
    normalize_institution,
    unmatched,
)


def _row(source: str, name: str, kind: str = "term_deposit", term: int = 12) -> dict:
    return {
        "source_id": source, "institution": name,
        "product_type": kind, "term_months": term,
    }


# ── 이름 맞추기 ─────────────────────────────────────────────────────────


def test_the_two_sources_name_the_same_bank_differently() -> None:
    """실측한 네 쌍. 여기가 깨지면 화면에 중복이 되살아난다."""
    pairs = [("BNK저축은행", "BNK"), ("디비저축은행", "DB"),
             ("엔에이치저축은행", "NH"), ("키움예스저축은행", "키움YES"),
             ("대명상호저축은행", "대명")]
    for left, right in pairs:
        assert normalize_institution(left) == normalize_institution(right), (left, right)


def test_different_banks_never_collapse() -> None:
    """잘못 붙이는 쪽이 훨씬 나쁘다 — 서로 다른 은행의 금리가 합쳐진다."""
    assert normalize_institution("대신저축은행") != normalize_institution("DS")
    assert normalize_institution("우리저축은행") != normalize_institution("우리금융저축은행")


def test_unmatched_names_are_countable() -> None:
    """원천이 이름을 바꾸면 조용히 중복이 살아난다. 셀 수 있어야 한다."""
    left, right = unmatched({"BNK저축은행", "새이름저축은행"}, {"BNK", "웰컴"})
    assert left == {"새이름저축은행"}
    assert right == {"웰컴"}


def test_manual_aliases_are_small_and_explicit() -> None:
    """규칙으로 되는 데까지만 하고 나머지는 손으로 적는다.

    이 표가 커지면 자동화를 다시 생각해야 한다는 신호다.
    """
    assert len(MANUAL_ALIASES) <= 10


# ── 중복 제거 ───────────────────────────────────────────────────────────


def test_the_overlapping_product_appears_once() -> None:
    """같은 은행·상품유형·기간이면 한 줄만 남는다."""
    rows = [_row("fsb", "BNK"), _row("finlife_savings_bank", "BNK저축은행")]
    kept = _drop_duplicate_source_rows(rows)
    assert [r["source_id"] for r in kept] == ["fsb"]


def test_a_product_only_one_source_has_survives() -> None:
    """통째로 빼면 이게 사라진다. 실측으로 11개 조합 20건이 여기 해당한다."""
    rows = [
        _row("fsb", "BNK"),
        _row("finlife_savings_bank", "BNK저축은행"),
        # FSB에 없는 기간
        _row("finlife_savings_bank", "BNK저축은행", "installment_savings", 3),
    ]
    kept = _drop_duplicate_source_rows(rows)
    assert len(kept) == 2
    assert any(
        r["source_id"] == "finlife_savings_bank" and r["term_months"] == 3 for r in kept
    )


def test_nothing_is_dropped_when_the_other_source_is_missing() -> None:
    """FSB 수집이 실패한 날 화면이 통째로 비면 안 된다.

    물러날 상대가 없으면 물러나지 않는다.
    """
    rows = [_row("finlife_savings_bank", "BNK저축은행")]
    assert _drop_duplicate_source_rows(rows) == rows


def test_the_comparison_ignores_the_product_name() -> None:
    """두 원천이 같은 상품을 다른 이름으로 부른다.

    이름까지 맞추라고 하면 아무것도 안 붙는다.
    """
    left = _row("fsb", "BNK") | {"product": "정기예금"}
    right = _row("finlife_savings_bank", "BNK저축은행") | {"product": "정기예금(인터넷)"}
    assert _comparison_key(left) == _comparison_key(right)


# ── 설정 ────────────────────────────────────────────────────────────────


def test_the_two_config_lists_do_different_things() -> None:
    """`reference_sectors`는 통째로 빼고 `db_only_sources`는 겹칠 때만 뺀다.

    한때 둘을 같은 필터로 쓰려다 finlife가 통째로 사라질 뻔했다.
    """
    assert reference_sectors() == ("bank",)
    assert dedupe_sources() == ("finlife_savings_bank",)
