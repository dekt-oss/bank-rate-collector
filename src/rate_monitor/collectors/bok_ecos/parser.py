"""한국은행 ECOS 응답 파서 (v4 §7).

순수 함수다. 네트워크·파일·DB를 건드리지 않는다.

계약은 **추정이 아니라 정찰로 확정했다** (2026-08-06, Actions run 31098447877).
명세서 §7.2가 "확인하지 않은 통계코드를 추정 하드코딩하지 않는다"고 못 박아서,
코드를 적는 대신 이름으로 찾아냈다.

    통계표 834개 중 이름에 '기준금리'가 든 것 2개
      722Y001  1.3.1. 한국은행 기준금리 및 여수신금리   주기 D   ← 이것
      902Y006  9.1.1.3. 국제 주요국 중앙은행 정책금리    주기 M

    722Y001 항목 48개 중 '기준금리'가 든 것
      0101000  한국은행 기준금리   주기 A·D·M·Q 모두 제공

`902Y006`도 한국 3.5%를 주지만 월 단위이고 국가 비교용이다. **정책금리는
바뀐 날짜가 중요하므로 일 단위 원천을 쓴다.**

기록: `docs/source-recon/bok-ecos.md`
실물: `tests/fixtures/bok_ecos/`
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple

from rate_monitor.collectors.base import ParseError, SchemaChangedError

SOURCE_ID = "bok_ecos"

# 정찰로 확인한 값. 여기를 바꾸면 다른 통계를 받게 되므로 근거 없이 고치지 않는다.
STAT_CODE = "722Y001"
ITEM_CODE = "0101000"
CYCLE = "D"

INDICATOR_CODE = "bok_base_rate"
INDICATOR_NAME = "한국은행 기준금리"

# 명세서 §7.1이 못 박은 단위. 원천은 「연%」로 준다.
UNIT = "percent"
SOURCE_UNIT = "연%"

RESULT_KEY = "StatisticSearch"
REQUIRED_FIELDS = frozenset({"STAT_CODE", "ITEM_CODE1", "TIME", "DATA_VALUE", "UNIT_NAME"})

# 기준금리가 이 범위를 벗어나면 원천이 다른 것을 주고 있다.
#
# 한국은행 기준금리는 1999년 제도 도입 이후 0.50%~5.25% 사이였다. 넉넉히
# 잡아도 이 밖이면 통계표나 항목이 바뀐 것이다 — 조용히 저장하면 그 값이
# 화면에 "기준금리"로 뜬다.
MIN_RATE = Decimal("0")
MAX_RATE = Decimal("25")


class IndicatorPoint(NamedTuple):
    """시점 하나. 화면과 저장이 함께 쓴다."""

    indicator_code: str
    indicator_name: str
    value: Decimal
    unit: str
    source_effective_at: date
    source_locator: str


def _parse_time(value: object, cycle: str) -> date | None:
    """ECOS의 TIME을 날짜로. 주기마다 자릿수가 다르다.

    >>> _parse_time("20240108", "D")
    datetime.date(2024, 1, 8)
    >>> _parse_time("202401", "M")
    datetime.date(2024, 1, 1)
    >>> _parse_time("2024", "A")
    datetime.date(2024, 1, 1)
    >>> _parse_time("20240132", "D") is None
    True
    """
    text = str(value or "").strip()
    formats = {"D": "%Y%m%d", "M": "%Y%m", "A": "%Y"}
    fmt = formats.get(cycle)
    if fmt is None or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, fmt).date()
    except ValueError:
        return None


def check_schema(result: dict[str, Any]) -> list[str]:
    """구조 검사. 필수 필드가 사라지면 멈춘다 (v3.1 §8)."""
    rows = result.get("row") or []
    if not rows:
        return ["시계열에 행이 없다"]
    missing = REQUIRED_FIELDS - set(rows[0])
    if missing:
        raise SchemaChangedError(f"ECOS 응답 필수 필드 소실: {sorted(missing)}")
    return []


def parse(payload: dict[str, Any], *, cycle: str = CYCLE) -> tuple[list[IndicatorPoint], list[str]]:
    """ECOS 시계열 응답 → 지표 시점들.

    >>> import json, pathlib
    >>> raw = json.loads(pathlib.Path(
    ...     "tests/fixtures/bok_ecos/base_rate_daily.json").read_text(encoding="utf-8"))
    >>> points, warnings = parse(raw)
    >>> len(points), warnings
    (10, [])
    >>> points[0].value, points[0].unit
    (Decimal('3.5'), 'percent')
    >>> points[0].source_effective_at
    datetime.date(2024, 1, 1)
    """
    # ECOS는 오류도 200으로 준다. 본문을 봐야 안다.
    if "RESULT" in payload:
        result = payload["RESULT"]
        raise ParseError(
            f"ECOS 오류 {result.get('CODE')}: {result.get('MESSAGE')}"
        )

    result = payload.get(RESULT_KEY)
    if not isinstance(result, dict):
        raise SchemaChangedError(f"응답에 {RESULT_KEY} 객체가 없다")

    warnings = check_schema(result)
    points: list[IndicatorPoint] = []

    for row in result.get("row") or []:
        # 다른 통계표나 항목이 섞여 오면 버린다. 조용히 저장하면 그 값이
        # 화면에 "기준금리"로 뜬다.
        if str(row.get("STAT_CODE")) != STAT_CODE:
            warnings.append(f"다른 통계표가 섞였다: {row.get('STAT_CODE')}")
            continue
        if str(row.get("ITEM_CODE1")) != ITEM_CODE:
            warnings.append(f"다른 항목이 섞였다: {row.get('ITEM_CODE1')}")
            continue

        when = _parse_time(row.get("TIME"), cycle)
        if when is None:
            warnings.append(f"시점을 읽지 못했다: {row.get('TIME')!r}")
            continue

        try:
            value = Decimal(str(row.get("DATA_VALUE")).strip())
        except (InvalidOperation, AttributeError):
            warnings.append(f"값을 읽지 못했다: {row.get('DATA_VALUE')!r}")
            continue

        if not (MIN_RATE <= value <= MAX_RATE):
            warnings.append(f"기준금리 범위를 벗어났다: {value}")
            continue

        # 단위가 바뀌면 화면의 숫자가 뜻을 잃는다. 명세서가 percent로 고정한다.
        if str(row.get("UNIT_NAME")).strip() != SOURCE_UNIT:
            warnings.append(f"단위가 바뀌었다: {row.get('UNIT_NAME')!r}")
            continue

        points.append(
            IndicatorPoint(
                indicator_code=INDICATOR_CODE,
                indicator_name=INDICATOR_NAME,
                value=value,
                unit=UNIT,
                source_effective_at=when,
                source_locator=f"{STAT_CODE}/{ITEM_CODE}/{row.get('TIME')}",
            )
        )

    return points, warnings


def latest(points: list[IndicatorPoint]) -> IndicatorPoint | None:
    """가장 최근 시점.

    ECOS가 시간 오름차순으로 주지만 그 순서에 기대지 않는다.

    >>> latest([]) is None
    True
    """
    return max(points, key=lambda p: p.source_effective_at) if points else None
