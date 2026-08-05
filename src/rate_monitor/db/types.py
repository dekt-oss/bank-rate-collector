"""SQLite용 커스텀 컬럼 타입.

명세서 v3 §5.9는 금리를 DECIMAL(7,4)로, §8.4는 "소수점 4자리까지 보존"을
요구한다. 그런데 SQLite에는 DECIMAL 타입이 없고, SQLAlchemy Numeric을
SQLite에 쓰면 float를 거쳐 저장되어 2진 부동소수 왕복으로 4자리가 어긋날 수
있다. 금리는 사람이 눈으로 대조하는 값이므로 저장 정확도를 우선한다.

문자열로 저장하면 정렬이 사전순이 되어 "10.0000" < "2.0000"이 참이 된다.
금리 순위 비교는 핵심 기능이므로 정수부를 0으로 채워 사전순과 수치순을
일치시킨다. 규율("집계할 때 CAST 해라")에 기대지 않고 저장 형식 자체로
보장한다.
"""

from decimal import Decimal

from sqlalchemy import String, TypeDecorator

RATE_EXPONENT = Decimal("0.0001")
# DECIMAL(7,4) = 정수 3자리 + 소수 4자리. "999.9999"가 최대.
INT_DIGITS = 3
DEC_DIGITS = 4
# "000.0000" = 3 + 1 + 4
RATE_WIDTH = INT_DIGITS + 1 + DEC_DIGITS
MAX_RATE = Decimal("999.9999")


class RateOutOfRangeError(ValueError):
    """금리가 저장 가능한 범위를 벗어났다.

    음수는 0 패딩으로 정렬되지 않으므로 조용히 틀리게 두지 않고 막는다.
    음수 금리를 다뤄야 하면 저장 형식을 먼저 바꾼다.
    """


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

    >>> t.process_bind_param(Decimal("2"), None) < t.process_bind_param(Decimal("10"), None)
    True
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
        # "002.7500" → Decimal("2.7500"). 선행 0은 수치에 영향이 없다.
        return Decimal(str(value))
