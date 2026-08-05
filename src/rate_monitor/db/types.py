"""SQLite용 커스텀 컬럼 타입.

명세서 v3 §5.9는 금리를 DECIMAL(7,4)로, §8.4는 "소수점 4자리까지 보존"을
요구한다. 그런데 SQLite에는 DECIMAL 타입이 없고, SQLAlchemy Numeric을
SQLite에 쓰면 float를 거쳐 저장되어 2진 부동소수 왕복으로 4자리가 어긋날 수
있다. 금리는 사람이 눈으로 대조하는 값이므로 저장 정확도를 비교 성능보다
우선한다. 정렬·집계가 필요하면 SQL에서 CAST(... AS REAL)로 처리한다.
"""

from decimal import Decimal

from sqlalchemy import String, TypeDecorator

RATE_EXPONENT = Decimal("0.0001")


class Rate(TypeDecorator):
    """금리를 고정 소수 문자열로 저장한다.

    >>> t = Rate()
    >>> t.process_bind_param(Decimal("2.75"), None)
    '2.7500'
    >>> t.process_result_value('2.7500', None)
    Decimal('2.7500')
    >>> t.process_bind_param(None, None) is None
    True
    """

    impl = String(16)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return str(value.quantize(RATE_EXPONENT))

    def process_result_value(self, value: object, dialect: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))
