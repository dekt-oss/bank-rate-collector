"""우대조건 원문을 표준 분류로 옮긴다 (우대조건 명세서 v1 §5).

분류가 틀리는 것보다 **세 상태를 뭉개는 것**이 나쁘다. 원천이 안 준 것과
원천이 없다고 말한 것은 다르고, 전자를 후자로 적으면 화면이 거짓말을 한다.
"""

import pytest

from rate_monitor.domain.preference_taxonomy import (
    PreferenceStatus,
    classify,
    condition_body,
    labels,
)

# ── 세 상태 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [None, "", "   ", "\n"])
def test_no_text_at_all_is_missing_not_none(raw) -> None:
    """새마을금고는 공식 화면에 우대금리 열 자체가 없다.

    발행 DB 150,311건 중 109,149건(72.6%)이 여기 걸린다. "없음"으로 적으면
    우대금리가 없는 상품처럼 보인다 (v4 §3.3).
    """
    assert classify(raw).status is PreferenceStatus.MISSING


@pytest.mark.parametrize(
    "raw", ["없음", "해당사항없음", "해당 없음", "-", "우대조건: 없음\n가입대상: 제한없음"]
)
def test_the_source_saying_none_is_its_own_state(raw) -> None:
    """원천이 스스로 없다고 말한 것. 미제공과 구별해 저장한다."""
    tags = classify(raw)
    assert tags.status is PreferenceStatus.NONE
    assert tags.codes == ()


# ── 분류 ────────────────────────────────────────────────────────────────


def test_one_condition_can_belong_to_several_categories() -> None:
    """「비대면 기한부예금 가입실적」은 비대면이면서 상품보유다.

    하나로 우겨넣으면 사람이 한쪽으로 찾을 때 안 나온다.
    """
    codes = set(classify("비대면 기한부예금 가입실적 : 0.1%p").codes)
    assert {"DIGITAL_CHANNEL", "PRODUCT_HOLDING"} <= codes


def test_the_real_phrases_from_the_sources_are_classified() -> None:
    """발행 DB에서 실제로 가장 많이 나온 문구들 (2026-08-06)."""
    cases = {
        "신협체크카드 결제실적 : 0.2%p": "CARD_USAGE",
        "자동이체 납입실적 : 0.1%p": "AUTO_PAYMENT",
        "급여이체 실적 : 0.1%p": "INCOME_TRANSFER",
        "장기가입조합원 : 최대 0.2%p": "MEMBERSHIP",
        "가입연령기준 충족": "AGE_LIFE_STAGE",
    }
    for raw, expected in cases.items():
        assert expected in classify(raw).codes, f"{raw!r} → {classify(raw).codes}"


def test_an_unmatched_condition_becomes_other_not_a_guess() -> None:
    """규칙에 안 걸리면 «기타»다. 값을 지어내지 않는다."""
    assert classify("- 만기이자지급식 기준").codes == ("OTHER",)


def test_only_the_preference_part_is_read() -> None:
    """저축은행중앙회는 여러 칸을 라벨로 이어 붙여 준다.

    가입대상까지 세면 "실명의 개인"이 우대조건으로 잡힌다.
    """
    raw = "우대조건: 없음\n가입대상: 실명의 개인 및 개인사업자\n유의사항: 체크카드"
    assert condition_body(raw) == "없음"
    assert classify(raw).status is PreferenceStatus.NONE


def test_every_category_has_a_korean_label() -> None:
    """코드가 화면에 그대로 나오면 읽는 사람이 뜻을 알 수 없다."""
    for code, label in labels().items():
        assert label and label != code, f"{code}에 표시명이 없다"
