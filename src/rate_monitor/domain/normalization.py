"""정규화 계약 (명세서 v3 §8).

원문은 항상 별도로 보존한다. 이 모듈은 비교·식별용 파생값만 만든다.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

# 법인 표기 — 기관명 정규화 시 제거한다 (v3 §8.1)
_CORP_TOKENS = ("주식회사", "(주)", "㈜", "(유)", "유한회사")
_WS = re.compile(r"\s+")
_PARENS = re.compile(r"\([^)]*\)")

# 금리 문자열에서 걷어낼 장식 (v3 §8.4)
_RATE_STRIP = re.compile(r"[%\s]|연|퍼센트|p\b", re.IGNORECASE)
_RATE_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def normalize_institution_name(raw: str) -> str:
    """기관명 정규화. 원문은 호출자가 별도 보존한다.

    >>> normalize_institution_name(" (주)애큐온 저축은행 ")
    '애큐온저축은행'
    >>> normalize_institution_name("서면신용협동조합")
    '서면신협'
    """
    text = unicodedata.normalize("NFKC", raw or "")
    for token in _CORP_TOKENS:
        text = text.replace(token, "")
    text = _PARENS.sub("", text)
    text = text.replace("신용협동조합", "신협")
    text = _WS.sub("", text)
    return text.strip()


def normalize_product_name(raw: str) -> str:
    """상품 정체성용 이름. 표시용 원문과 분리한다 (v3 §8.3).

    서로 다른 공식 상품명을 임의로 합치지 않는다. 공백·특수문자만 통일한다.

    >>> normalize_product_name("MG더뱅킹 정기예금 (비대면)")
    'mg더뱅킹정기예금'
    """
    text = unicodedata.normalize("NFKC", raw or "")
    text = _PARENS.sub("", text)
    text = re.sub(r"[^\w가-힣]", "", text)
    return text.strip().lower()


def parse_rate(value: object) -> Decimal | None:
    """금리 값을 Decimal로 변환한다. 실패하면 None.

    실패를 -1 같은 마법값으로 표기하지 않는다 (v3.1 §2가 승계한 v3 §8.4).
    호출자가 None을 받으면 validation_status=error로 기록한다.

    >>> parse_rate(2.5)
    Decimal('2.5')
    >>> parse_rate("연 2.75%")
    Decimal('2.75')
    >>> parse_rate("별도 문의") is None
    True
    >>> parse_rate(None) is None
    True
    """
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if not isinstance(value, str):
        return None

    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return None
    match = _RATE_NUM.search(_RATE_STRIP.sub("", text))
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def normalize_region_sido(raw: str | None) -> str | None:
    """시도명을 정식 표기로 통일한다 (v3 §8.2).

    행정구역 코드는 공식 출처 확인 전까지 부여하지 않는다 (v3.1 §11).

    >>> normalize_region_sido("부산")
    '부산광역시'
    >>> normalize_region_sido(None) is None
    True
    """
    if not raw:
        return None
    text = _WS.sub("", unicodedata.normalize("NFKC", raw))
    if text in ("부산", "부산시", "부산광역시"):
        return "부산광역시"
    return text
