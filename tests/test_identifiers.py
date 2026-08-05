"""식별키 결정성 검증 (명세서 v3 §5.8, §17.1).

오버라이드와 시점 비교가 모두 이 안정성 위에 서 있다.
"""

from rate_monitor.domain.identifiers import make_org_key, make_variant_key

BASE = dict(
    sector="savings_bank",
    org_key="savings_bank:0010345",
    source_product_key="HK00001",
    product_name="정기예금",
    term_months=12,
    term_days=None,
    join_channel="any",
    interest_method="simple",
    payment_method=None,
    amount_min=None,
    amount_max=None,
    outlet_key=None,
)


def test_variant_key_is_stable_across_calls() -> None:
    keys = {make_variant_key(**BASE) for _ in range(100)}
    assert len(keys) == 1


def test_variant_key_ignores_region() -> None:
    """지역명은 키에 들어가지 않는다.

    기관이 이사하거나 지역 표기가 바뀌어도 금리 이력이 끊기면 안 된다.
    make_variant_key는 애초에 지역 인자를 받지 않으므로, 시그니처로 이를 보장한다.
    """
    import inspect

    params = set(inspect.signature(make_variant_key).parameters)
    assert not {"sido", "sigungu", "region", "address"} & params


def test_variant_key_distinguishes_term() -> None:
    assert make_variant_key(**{**BASE, "term_months": 24}) != make_variant_key(**BASE)


def test_variant_key_distinguishes_interest_method() -> None:
    """단리·복리는 다른 비교 단위다 (v3 §7.2)."""
    assert make_variant_key(**{**BASE, "interest_method": "compound"}) != make_variant_key(**BASE)


def test_variant_key_distinguishes_channel() -> None:
    assert make_variant_key(**{**BASE, "join_channel": "internet"}) != make_variant_key(**BASE)


def test_variant_key_distinguishes_amount_band() -> None:
    assert make_variant_key(**{**BASE, "amount_min": 1_000_000}) != make_variant_key(**BASE)


def test_variant_key_distinguishes_outlet() -> None:
    assert make_variant_key(**{**BASE, "outlet_key": "001"}) != make_variant_key(**BASE)


def test_variant_key_falls_back_to_normalized_product_name() -> None:
    """공식 상품코드가 없으면 정규화된 상품명으로 대체한다.

    표기 차이(공백·대소문자)만 흡수한다.
    """
    without_key = {**BASE, "source_product_key": None}
    a = make_variant_key(**{**without_key, "product_name": " 정기 예금 "})
    b = make_variant_key(**{**without_key, "product_name": "정기예금"})
    assert a == b


def test_variant_key_keeps_parenthesised_product_names_apart() -> None:
    """괄호는 장식이 아니라 상품을 가르는 표시다.

    이 테스트는 한때 반대를 단언했다. 그래서 상품코드가 없는 원천에서
    서로 다른 상품이 같은 키를 받아 뒤엣것이 버려졌다. 부산 새마을금고
    실수집에서 MG기업정기예금 (A)와 (B)가 합쳐져 60행을 잃었다.
    """
    without_key = {**BASE, "source_product_key": None}
    a = make_variant_key(**{**without_key, "product_name": "MG기업정기예금(A)"})
    b = make_variant_key(**{**without_key, "product_name": "MG기업정기예금(B)"})
    assert a != b

    online = make_variant_key(**{**without_key, "product_name": "정기예금(비대면)"})
    offline = make_variant_key(**{**without_key, "product_name": "정기예금"})
    assert online != offline


def test_variant_key_term_days_distinct_from_months() -> None:
    months = make_variant_key(**{**BASE, "term_months": 1, "term_days": None})
    days = make_variant_key(**{**BASE, "term_months": None, "term_days": 1})
    assert months != days


def test_org_key_prefers_official_code() -> None:
    assert (
        make_org_key(
            sector="savings_bank", source_institution_key="0010345",
            institution_name="애큐온저축은행",
        )
        == "savings_bank:0010345"
    )


def test_org_key_name_variants_collapse() -> None:
    """법인표기·공백 차이는 같은 기관으로 본다 (v3 §8.1)."""
    a = make_org_key(sector="kfcc", source_institution_key=None, institution_name="(주)대청 금고")
    b = make_org_key(sector="kfcc", source_institution_key=None, institution_name="대청금고")
    assert a == b


def test_org_key_different_sectors_are_distinct() -> None:
    a = make_org_key(sector="kfcc", source_institution_key="1203", institution_name="대청")
    b = make_org_key(sector="cu", source_institution_key="1203", institution_name="대청")
    assert a != b


def test_variant_key_distinguishes_reserve_type() -> None:
    """정액적립식과 자유적립식은 다른 비교 단위다 (v3 §5.2).

    2026-08-05 실제 적금 수집에서 이 값이 키에 없어 충돌이 났다.
    """
    fixed = make_variant_key(**{**BASE, "payment_method": "S"})
    free = make_variant_key(**{**BASE, "payment_method": "F"})
    assert fixed != free
    assert fixed != make_variant_key(**BASE)
