"""결정적 식별키 생성 (명세서 v3 §5.8).

같은 입력이면 항상 같은 키가 나와야 한다. 오버라이드와 시점 비교가 모두
이 안정성 위에 서 있다.
"""

from hashlib import sha256

from rate_monitor.domain.normalization import (
    normalize_institution_name,
    normalize_product_name,
)

_SEP = "|"
_KEY_LENGTH = 16


def _digest(parts: list[str]) -> str:
    return sha256(_SEP.join(parts).encode("utf-8")).hexdigest()[:_KEY_LENGTH]


def make_org_key(
    *,
    sector: str,
    source_institution_key: str | None,
    institution_name: str,
) -> str:
    """기관 식별키. 공식 코드가 있으면 그것을 쓴다 (v3 §3.2 식별자 우선순위).

    >>> make_org_key(sector="savings_bank", source_institution_key="0010345",
    ...              institution_name="애큐온저축은행")
    'savings_bank:0010345'

    공식 코드가 없으면 정규화된 이름의 해시로 대체한다.

    >>> a = make_org_key(sector="kfcc", source_institution_key=None,
    ...                  institution_name="(주)대청 새마을금고")
    >>> b = make_org_key(sector="kfcc", source_institution_key=None,
    ...                  institution_name="대청새마을금고")
    >>> a == b
    True
    """
    if source_institution_key:
        return f"{sector}:{source_institution_key}"
    return f"{sector}:name:{_digest([normalize_institution_name(institution_name)])}"


def make_variant_key(
    *,
    sector: str,
    org_key: str,
    source_product_key: str | None,
    product_name: str,
    term_months: int | None,
    term_days: int | None,
    join_channel: str,
    interest_method: str,
    amount_min: int | None,
    amount_max: int | None,
    outlet_key: str | None,
) -> str:
    """비교 단위(product_variant) 식별키.

    구성 (v3 §5.8):
        sector | institution stable key | product stable key/name |
        term | channel | interest method | amount band | outlet key

    지역명은 넣지 않는다. 기관이 이사하거나 이름이 바뀌어도 금리 이력이
    끊기면 안 되기 때문이다.

    >>> kw = dict(sector="savings_bank", org_key="savings_bank:0010345",
    ...           source_product_key="HK00001", product_name="정기예금",
    ...           term_months=12, term_days=None, join_channel="any",
    ...           interest_method="simple", amount_min=None, amount_max=None,
    ...           outlet_key=None)
    >>> make_variant_key(**kw) == make_variant_key(**kw)
    True

    기간이 다르면 다른 비교 단위다.

    >>> make_variant_key(**{**kw, "term_months": 24}) != make_variant_key(**kw)
    True
    """
    product_part = source_product_key or f"name:{normalize_product_name(product_name)}"
    term_part = f"m{term_months}" if term_months is not None else (
        f"d{term_days}" if term_days is not None else "none"
    )
    # `or ''`를 쓰면 0이 falsy라 None과 같은 키가 된다. 명시적으로 구분한다.
    low = "" if amount_min is None else str(amount_min)
    high = "" if amount_max is None else str(amount_max)
    amount_part = f"{low}~{high}"
    parts = [
        sector,
        org_key,
        product_part,
        term_part,
        join_channel,
        interest_method,
        amount_part,
        outlet_key or "",
    ]
    return _digest(parts)
