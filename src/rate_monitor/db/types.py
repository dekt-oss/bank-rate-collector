"""SQLite용 커스텀 고정소수 컬럼 타입.

SQLite에는 진짜 DECIMAL 타입이 없고 SQLAlchemy Numeric을 쓰면 float 왕복을
거칠 수 있다. 금리와 금융시장 수량은 사람이 원천과 직접 대조해야 하므로,
고정소수 문자열로 저장해 십진 정확도와 정렬 순서를 함께 보장한다.
"""

from decimal import Decimal, InvalidOperation

from sqlalchemy import String, TypeDecorator

RATE_EXPONENT = Decimal("0.0001")
# DECIMAL(7,4) = 정수 3자리 + 소수 4자리. "999.9999"가 최대.
INT_DIGITS = 3
DEC_DIGITS = 4
# "000.0000" = 3 + 1 + 4
RATE_WIDTH = INT_DIGITS + 1 + DEC_DIGITS
MAX_RATE = Decimal("999.9999")

# MarketIndicator는 금리뿐 아니라 조원 단위 수신잔액도 담는다. 은행 총예금은
# 2026-06 실측 2,281조원이라 Rate 상한 999.9999를 넘는다. 향후 단위가 더 큰
# 공식 통계도 같은 저장계약을 쓸 수 있도록 12+6자리로 고정한다.
QUANTITY_INT_DIGITS = 12
QUANTITY_DEC_DIGITS = 6
QUANTITY_EXPONENT = Decimal("0.000001")
QUANTITY_WIDTH = QUANTITY_INT_DIGITS + 1 + QUANTITY_DEC_DIGITS
MAX_QUANTITY = Decimal("999999999999.999999")


class RateOutOfRangeError(ValueError):
    """금리가 저장 가능한 범위를 벗어났다."""


class QuantityOutOfRangeError(ValueError):
    """금융시장 수량이 저장 가능한 범위를 벗어났다."""


class QuantityPrecisionError(ValueError):
    """원천 값이 Quantity의 6자리 소수 정밀도에 정확히 들어오지 않는다."""


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise QuantityOutOfRangeError(f"십진 수량으로 변환할 수 없다: {value!r}") from exc


def quantize_quantity(value: object) -> Decimal:
    """MarketIndicator 저장값을 lossless canonical Decimal로 만든다.

    TypeDecorator bind 시점에 조용히 반올림하면 content hash와 실제 DB 값이
    달라질 수 있다. 따라서 6자리보다 정밀한 원천 값은 저장하지 않고 계약
    재검토 대상으로 보낸다.
    """
    decimal_value = _decimal(value)
    if not decimal_value.is_finite():
        raise QuantityOutOfRangeError(f"유한한 수량만 지원한다: {decimal_value}")
    if decimal_value < 0:
        raise QuantityOutOfRangeError(f"음수 수량은 지원하지 않는다: {decimal_value}")
    if decimal_value > MAX_QUANTITY:
        raise QuantityOutOfRangeError(
            f"수량이 고정소수 저장 범위를 넘는다: {decimal_value} > {MAX_QUANTITY}"
        )
    quantized = decimal_value.quantize(QUANTITY_EXPONENT)
    if quantized != decimal_value:
        raise QuantityPrecisionError(
            "수량이 6자리 소수 정밀도를 초과한다: "
            f"{decimal_value} -> {quantized}"
        )
    return quantized


def canonical_quantity_text(value: object) -> str:
    """해시·감사 로그에 쓰는 부호 없는 6자리 canonical decimal text."""
    return f"{quantize_quantity(value):.{QUANTITY_DEC_DIGITS}f}"


def quantity_storage_text(value: object) -> str:
    """SQLite에 저장하는 zero-padded Quantity 문자열."""
    quantized = quantize_quantity(value)
    return f"{quantized:0{QUANTITY_WIDTH}f}"


class Rate(TypeDecorator):
    """금리를 정렬 가능한 고정 소수 문자열로 저장한다.

    >>> t = Rate()
    >>> t.process_bind_param(Decimal("2.75"), None)
    '002.7500'
    >>> t.process_bind_param(Decimal("10"), None)
    '010.0000'
    >>> t.process_result_value('002.7500', None)
    Decimal('2.7500')
    >>> t.process_bind_param(None, None) is None
    True

    저장 문자열의 사전순이 수치순과 일치한다.
    """

    impl = String(RATE_WIDTH)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        if value < 0:
            raise RateOutOfRangeError(f"음수 금리는 지원하지 않는다: {value}")
        if value > MAX_RATE:
            raise RateOutOfRangeError(f"금리가 DECIMAL(7,4) 범위를 넘는다: {value}")
        quantized = value.quantize(RATE_EXPONENT)
        return f"{quantized:0{RATE_WIDTH}f}"

    def process_result_value(self, value: object, dialect: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))


class Quantity(TypeDecorator):
    """시장 금리·잔액 등 비음수 scalar를 고정소수 문자열로 저장한다.

    `Rate`를 넓히지 않는 이유는 상품금리 컬럼의 DECIMAL(7,4) 계약을 그대로
    유지하기 위해서다. `market_indicators.value`처럼 단위가 percent일 수도,
    trillion_krw일 수도 있는 참고지표만 이 타입을 사용한다.

    >>> t = Quantity()
    >>> t.process_bind_param(Decimal("2281.4891"), None)
    '000000002281.489100'
    >>> t.process_bind_param(Decimal("3.48"), None)
    '000000000003.480000'
    >>> t.process_result_value('000000002281.489100', None)
    Decimal('2281.489100')
    """

    impl = String(QUANTITY_WIDTH)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: object) -> str | None:
        if value is None:
            return None
        return quantity_storage_text(value)

    def process_result_value(self, value: object, dialect: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))
