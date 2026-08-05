"""신협(CU) 전자공시 금리비교 파서.

순수 함수다. 네트워크·파일·DB를 건드리지 않는다 (명세서 v3 §6.2).
같은 원본이면 항상 같은 결과를 반환한다.

필드 매핑 근거: `docs/source-recon/cu.md` (2026-08-05 실물 정찰).

## 이 원천이 왜 중요한가

지금까지 확보한 원천 중 **지역과 최고 우대금리를 동시에 주는 유일한 곳**이다.

    finlife   지역 없음 · 최고금리 없음
    FSB       지역은 본점 소재지만 · 최고금리 있음
    새마을금고  지역 있음 · **최고금리 열 자체가 없음**
    신협      지역 있음 · 최고금리 있음      ← 여기

`baseRate`와 `highRate`가 별도 필드로 온다. 새마을금고에서 하지 못한
"우대조건을 다 채우면 얼마"를 신협에서는 말할 수 있다.

## 금리는 조합 단위다

`cuIngno`(조합 코드)당 한 벌이고 점포별 금리가 아니다. 그래서
`rate_scope = INSTITUTION`이다 — 새마을금고와 같은 성질이다.

지역은 조회 조건(`sido`/`subSido`)으로 좁힐 뿐 응답 행에는 들어 있지 않다.
어느 지역으로 물어봤는지는 어댑터가 `request_meta`로 넘긴다.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from rate_monitor.collectors.base import SchemaChangedError
from rate_monitor.domain.enums import (
    AvailabilityScope,
    InterestMethod,
    JoinChannel,
    ProductType,
    RateScope,
    Sector,
    SourceRole,
    TrustLevel,
    ValidationStatus,
)
from rate_monitor.domain.schemas import ParsedRateRow

SOURCE_ID = "cu"

# 화면 → 상품유형 (docs/source-recon/cu.md §2).
SCREEN_PRODUCT_TYPE = {
    "findInrst15": ProductType.TERM_DEPOSIT,        # 거치식예금
    "findInrst17": ProductType.INSTALLMENT_SAVINGS,  # 적립식예금
}

# breaking 판정 기준. 이 넷이 없으면 행을 만들 수 없다.
REQUIRED_FIELDS = frozenset({"cuIngno", "cuNm", "stockCode", "baseRate"})

# `tretYn` 원문 → 채널. 화면이 주는 한글 표기를 그대로 옮긴 것이다.
CHANNEL = {
    "영업점": JoinChannel.BRANCH,
    "인터넷": JoinChannel.INTERNET,
    "스마트폰": JoinChannel.MOBILE,
    "텔레뱅킹": JoinChannel.TELEPHONE,
}

# 담당자 연락처. 공개 항목이지만 금리 비교에 쓸 이유가 없다.
DROPPED_FIELDS = frozenset({"ownTelNo", "rnum", "listTotalCount"})

# `"3.40%"` 형태로 온다.
_RATE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%?")


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def parse_percent(raw: object) -> Decimal | None:
    """`"3.40%"`를 소수로 바꾼다.

    >>> parse_percent("3.40%")
    Decimal('3.40')
    >>> parse_percent("0%")
    Decimal('0')

    읽지 못하면 지어내지 않고 비운다.

    >>> parse_percent("조합문의") is None
    True
    >>> parse_percent(None) is None
    True
    """
    text = str(raw or "").strip()
    if not text:
        return None
    match = _RATE.fullmatch(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def parse_channel(raw: object) -> str:
    """가입채널. 여러 개면 좁히지 않고 ANY로 둔다.

    >>> str(parse_channel("스마트폰"))
    'mobile'
    >>> str(parse_channel("영업점,인터넷"))
    'any'
    >>> str(parse_channel(""))
    'unknown'
    """
    tokens = [t.strip() for t in str(raw or "").split(",") if t.strip()]
    if not tokens:
        return JoinChannel.UNKNOWN
    if len(tokens) > 1:
        return JoinChannel.ANY
    return CHANNEL.get(tokens[0], JoinChannel.UNKNOWN)


def parse_effective_date(raw: object) -> date | None:
    """`pubiBeginDate`는 `YYYY-MM-DD`로 온다.

    >>> parse_effective_date("2026-08-05")
    datetime.date(2026, 8, 5)
    >>> parse_effective_date("-") is None
    True
    """
    text = str(raw or "").strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_term_months(raw: object) -> int | None:
    """`monTy`는 조회 기간이 그대로 실려 온다.

    >>> parse_term_months("12")
    12
    >>> parse_term_months("별도") is None
    True
    """
    text = str(raw or "").strip()
    return int(text) if text.isdigit() else None


def preference_raw(row: dict[str, Any]) -> str:
    """우대조건 원문.

    `"없음"`도 그대로 남긴다 — 값이 없는 것과 우대조건이 없다는 것은 다르다.

    >>> preference_raw({"prefCondMemo": "없음", "joinSubjMemo": "실명의 개인"})
    '우대조건: 없음\\n가입대상: 실명의 개인'
    >>> preference_raw({"prefCondMemo": "null"})
    ''
    """
    parts = []
    for label, key in (
        ("우대조건", "prefCondMemo"),
        ("가입대상", "joinSubjMemo"),
        ("가입제한", "joinLimtCode"),
        ("유의사항", "etcAtntMatt"),
    ):
        value = str(row.get(key) or "").strip()
        # 이 원천은 빈 값을 문자열 "null"로 보낸다.
        if value and value != "null":
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


def check_schema(rows: list[dict[str, Any]]) -> list[str]:
    """구조 검사. 필수 필드가 사라지면 breaking이다 (v3.1 §8)."""
    if not isinstance(rows, list):
        raise SchemaChangedError(f"응답이 배열이 아니다: {type(rows).__name__}")
    if not rows:
        return ["행이 0건이다. 조회 조건을 확인한다"]

    missing = sorted(REQUIRED_FIELDS - set(rows[0]))
    if missing:
        raise SchemaChangedError(f"필수 필드가 없다: {missing}")

    warnings: list[str] = []
    for optional in ("highRate", "tretYn", "pubiBeginDate", "payPaymMethName"):
        if optional not in rows[0]:
            warnings.append(f"{optional}가 없다. 값 없이 진행한다")
    return warnings


def total_count(rows: list[dict[str, Any]]) -> int | None:
    """전체 건수. 페이지네이션 종료 판정에 쓴다.

    >>> total_count([{"listTotalCount": 279}])
    279
    >>> total_count([]) is None
    True
    """
    if not rows:
        return None
    raw = rows[0].get("listTotalCount")
    return int(raw) if isinstance(raw, int | str) and str(raw).isdigit() else None


def parse(
    rows: list[dict[str, Any]],
    *,
    screen: str,
    sido: str,
    sido_name: str | None = None,
    page_offset: int = 0,
) -> tuple[list[ParsedRateRow], list[str]]:
    """금리 응답 한 장을 표준 행으로 바꾼다.

    `sido_name`은 조회에 쓴 지역의 사람이 읽는 이름이다. 응답 행에는 지역이
    없으므로 조회 조건에서 가져온다. **주소가 아니다** — 조합이 그 지역에서
    영업한다는 뜻이고, 지번까지는 이 화면이 주지 않는다.
    """
    warnings = check_schema(rows)
    product_type = SCREEN_PRODUCT_TYPE.get(screen, ProductType.OTHER)

    out: list[ParsedRateRow] = []
    for index, record in enumerate(rows):
        base_rate = parse_percent(record.get("baseRate"))
        max_rate = parse_percent(record.get("highRate"))

        status = ValidationStatus.VALID
        message: str | None = None
        if base_rate is None:
            status = ValidationStatus.ERROR
            message = f"기본금리 변환 실패: {record.get('baseRate')!r}"
        elif max_rate is not None and max_rate < base_rate:
            status = ValidationStatus.WARNING
            message = f"최고금리({max_rate})가 기본금리({base_rate})보다 낮다"
        elif record.get("highRate") is not None and max_rate is None:
            status = ValidationStatus.WARNING
            message = f"최고금리 변환 실패: {record.get('highRate')!r}"

        cu_no = str(record.get("cuIngno") or "").strip()
        stock = str(record.get("stockCode") or "").strip()
        term = parse_term_months(record.get("monTy"))

        out.append(
            ParsedRateRow(
                source_id=SOURCE_ID,
                source_role=SourceRole.PRIMARY_OFFICIAL,
                trust_level=TrustLevel.OFFICIAL_DIRECT,
                sector=Sector.CU,
                source_institution_key=cu_no,
                # 금리는 조합 단위 공시다. 점포마다 복제하지 않는다.
                source_outlet_key=None,
                source_product_key=stock,
                institution_name=str(record.get("cuNm") or "").strip(),
                outlet_name=None,
                institution_type=None,
                # 조회 조건에서 온 지역이다. 점포 주소가 아니므로 address는 비운다.
                sido=sido_name,
                sigungu=None,
                address=None,
                product_type=product_type,
                product_name=str(record.get("stockNm") or "").strip(),
                term_months=term,
                term_days=None,
                join_channel=parse_channel(record.get("tretYn")),
                # 화면이 단리·복리를 구분해 주지 않는다. 추측하지 않는다.
                interest_method=InterestMethod.UNKNOWN,
                payment_method=str(record.get("payPaymMethName") or "").strip() or None,
                amount_min=None,
                amount_max=(
                    record.get("highLimtAmt")
                    if isinstance(record.get("highLimtAmt"), int)
                    else None
                ),
                customer_scope=str(record.get("joinSubjMemo") or "").strip() or None,
                # 신협은 조합원 중심이지만 화면이 "제한없음"이라고 적는 상품이
                # 많다. 지어내지 않고 원문을 preference_raw에 남긴다.
                availability_scope=AvailabilityScope.LOCAL_MEMBERS,
                rate_scope=RateScope.INSTITUTION,
                base_rate=base_rate,
                max_rate=max_rate,
                preference_raw=preference_raw(record),
                source_row_ref=f"{cu_no}/{stock}/{term}/{record.get('payPaymMeth')}",
                base_source_locator=f"$[{index + page_offset}].baseRate",
                source_record_hash=_record_hash(record),
                source_effective_at=parse_effective_date(record.get("pubiBeginDate")),
                validation_status=status,
                validation_message=message,
                extra={
                    "screen": screen,
                    "sido": sido,
                    "sido_name": sido_name,
                    "pay_paym_meth": str(record.get("payPaymMeth") or "") or None,
                    "due_after_rate": str(record.get("dueAfIntRateMemo") or "") or None,
                    "product_url": str(record.get("stockUrl") or "") or None,
                },
            )
        )
    return out, warnings


def _record_hash(record: dict[str, Any]) -> str:
    """행 단위 원본 해시 (v3.1 §7).

    `rnum`·`listTotalCount`는 조회 결과에 따라 달라지는 값이라 뺀다. 페이지를
    다르게 넘겼다고 금리가 바뀐 것으로 잡히면 안 된다.
    """
    payload = {k: v for k, v in sorted(record.items()) if k not in DROPPED_FIELDS}
    return _digest(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def schema_fingerprint(rows: list[dict[str, Any]]) -> str:
    """구조 지문. 값이 아니라 필드 구성이 바뀌었는지만 본다."""
    fields = sorted(rows[0]) if rows else []
    return _digest("|".join(fields))
