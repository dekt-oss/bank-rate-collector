"""NH 이자방식 판정은 직접 근거만 쓴다."""

from rate_monitor.collectors.nh_local import parser as nh
from rate_monitor.domain.enums import InterestMethod


def test_reference_only_simple_word_is_not_direct_evidence() -> None:
    """대상상품 설명의 `단리식` 언급을 현재 행의 단리로 오인하지 않는다."""
    assert (
        nh._interest_method("우대금리", "대상상품: 단리식 예탁금")
        == InterestMethod.UNKNOWN
    )
