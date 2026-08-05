"""저축은행중앙회(FSB) 소비자포털 파서.

순수 함수다. 네트워크·파일·DB를 건드리지 않는다 (명세서 v3 §6.2).
같은 원본이면 항상 같은 결과를 반환한다.

필드 매핑 근거: `docs/source-recon/fsb.md` §4 (2026-08-05 실물 정찰).

## 이 원천의 성질 — 표기에 반영해야 한다

화면이 스스로 밝힌다: "본 화면에 고시된 금리는 저축은행의 **본점 기준**이며,
좀 더 자세한 지점별 금리는 해당 저축은행으로 연락하시기 바랍니다."

따라서 `rate_scope = HEAD_OFFICE_REFERENCE`다. 점포 주소를 알게 되더라도
(§4-2) 그것은 **본점 소재지**이지 그 지점의 적용금리가 아니다.

## 한 행이 여러 개로 펼쳐진다

한 행에 그 상품이 취급하는 **모든 기간 × 이자방식**이 함께 온다.

    JUNG_12M_DAN  12개월 단리 기본      TOP_12M_DAN  12개월 단리 최고
    JUNG_12M_BOK  12개월 복리 기본      TOP_12M_BOK  12개월 복리 최고

각각이 서로 다른 비교 단위이므로 행 하나가 최대 12행(기간 6 × 방식 2)으로
펼쳐진다.

### 정찰 문서 §4의 기술은 틀렸다 (2026-08-05 fixture로 확인)

`docs/source-recon/fsb.md` §4는 "`CHK_MONTH=12`로 요청하면 행에는 12개월
필드만 온다"고 적었다. 실물 fixture는 그렇지 않다.

    tests/fixtures/fsb/ratedepo_0100_01.json — CHK_MONTH=12로 받은 응답
      행 1·2·3·7·8   1/3/6/12/24/36개월 필드를 전부 가진다
      행 0·5·6       12개월만
      행 9 (OSB)     **36개월만** — 12개월 필드가 아예 없다

36개월만 취급하는 상품이 12개월 조회에 나왔다는 것은 `CHK_MONTH`가 결과를
걸러내지 않는다는 뜻이다. 정렬이나 화면 상단 평균금리에 쓰이는 것으로 보인다.

그래서 파서는 **행에 실제로 있는 기간만** 옮긴다. 요청한 기간을 행에
덮어씌우지 않는다 — 없는 금리를 지어내게 된다.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
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
from rate_monitor.domain.normalization import parse_rate
from rate_monitor.domain.schemas import ParsedRateRow

SOURCE_ID = "fsb"

# 화면 → 상품유형. `.jct` 엔드포인트 이름으로 가른다.
SCREEN_PRODUCT_TYPE = {
    "ratedepo": ProductType.TERM_DEPOSIT,
    "rateinst": ProductType.INSTALLMENT_SAVINGS,
}

# breaking 판정 기준. 이 넷이 없으면 행을 만들 수 없다.
REQUIRED_FIELDS = frozenset(
    {"FINAN_COMP_CODE", "FINAN_PROD_CODE", "BANK_NAME", "PRODUCT_NAME"}
)

# JOIN_LOCATION 코드 → 채널 (docs/source-recon/fsb.md §3.5).
# 화면의 체크박스 라벨을 그대로 옮긴 것이고 우리가 지어낸 대응이 아니다.
JOIN_LOCATION_CHANNEL = {
    "1": JoinChannel.BRANCH,
    "2": JoinChannel.INTERNET,
    "3": JoinChannel.MOBILE,
    "4": JoinChannel.AGENT,
    "5": JoinChannel.TELEPHONE,
    "9": JoinChannel.UNKNOWN,
}

# 이자방식별 금리 필드 접미사.
_METHOD_SUFFIX = (
    (InterestMethod.SIMPLE, "DAN"),
    (InterestMethod.COMPOUND, "BOK"),
)

# 담당 부서명과 전화번호가 들어오는 필드. 공개 공시 항목이지만 금리 비교에
# 쓸 이유가 없으므로 저장하지 않는다 (docs/source-recon/fsb.md §4).
DROPPED_FIELDS = frozenset({"OWNER", "TEL", "CTEL", "DTEL"})


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def clean(value: object) -> str:
    """우측 공백 패딩을 걷어낸다.

    `BANK_NAME`이 고정폭으로 온다. 이대로 두면 같은 은행이 이름 길이에 따라
    다른 기관으로 갈린다.

    >>> clean("BNK                 ")
    'BNK'
    >>> clean(None)
    ''
    """
    return str(value or "").strip()


def parse_join_channel(raw: object) -> str:
    """`JOIN_LOCATION`을 채널로 옮긴다.

    여러 개면 하나로 좁히지 않고 ANY로 둔다. finlife 파서와 같은 규칙이다.

    >>> str(parse_join_channel("1"))
    'branch'
    >>> str(parse_join_channel("1,2,3"))
    'any'
    >>> str(parse_join_channel(""))
    'unknown'
    """
    codes = [c.strip() for c in str(raw or "").split(",") if c.strip()]
    if not codes:
        return JoinChannel.UNKNOWN
    if len(codes) > 1:
        return JoinChannel.ANY
    return JOIN_LOCATION_CHANNEL.get(codes[0], JoinChannel.UNKNOWN)


def parse_submit_date(row: dict[str, Any]) -> date | None:
    """공시기준일. `YYYYMMDD` 형태의 필드를 앞에서부터 본다.

    >>> parse_submit_date({"FINAN_COMP_SUBMIT_DATE": "20260729"})
    datetime.date(2026, 7, 29)
    >>> parse_submit_date({"START_DATE": "20260729"})
    datetime.date(2026, 7, 29)

    지어내지 않는다. 읽을 수 있는 값이 없으면 비운다.

    >>> parse_submit_date({"START_DATE": "-"}) is None
    True
    """
    for key in ("FINAN_COMP_SUBMIT_DATE", "START_DATE"):
        raw = clean(row.get(key))
        if len(raw) == 8 and raw.isdigit():
            try:
                return datetime.strptime(raw, "%Y%m%d").date()
            except ValueError:
                continue
    return None


def preference_raw(row: dict[str, Any]) -> str:
    """우대조건 원문. 세 필드를 붙여 둔다.

    finlife는 `spcl_cnd` 하나뿐인데 FSB는 셋으로 나뉘어 있다. 조건별로
    쪼개는 것은 `preference_conditions` 테이블의 일이고, 여기서는 원문을
    잃지 않는 것만 한다.

    >>> preference_raw({"SWEETENER": "없음", "JOIN_TARGET": "제한없음"})
    '우대조건: 없음\\n가입대상: 제한없음'
    >>> preference_raw({"SWEETENER": "", "ETC_NOTE_MATTER": ""})
    ''
    """
    parts = []
    for label, key in (
        ("우대조건", "SWEETENER"),
        ("가입대상", "JOIN_TARGET"),
        ("기타", "ETC_NOTE_MATTER"),
    ):
        value = clean(row.get(key))
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


def check_schema(payload: dict[str, Any], *, records_key: str = "REC") -> list[str]:
    """구조 검사. 필수 필드가 사라지면 breaking이다 (v3.1 §8)."""
    if records_key not in payload:
        raise SchemaChangedError(
            f"응답에 {records_key}가 없다: {sorted(payload)[:8]}"
        )
    rows = payload[records_key]
    if not isinstance(rows, list):
        raise SchemaChangedError(f"{records_key}가 배열이 아니다: {type(rows).__name__}")
    if not rows:
        return ["행이 0건이다. 조회 조건을 확인한다"]

    missing = sorted(REQUIRED_FIELDS - set(rows[0]))
    if missing:
        raise SchemaChangedError(f"필수 필드가 없다: {missing}")

    warnings: list[str] = []
    for optional in ("JOIN_LOCATION", "SWEETENER", "EXPIRE_INTRST_RATE"):
        if optional not in rows[0]:
            warnings.append(f"{optional}가 없다. 값 없이 진행한다")
    return warnings


_TERM_FIELD = re.compile(r"^JUNG_(\d+)M_(DAN|BOK)$")


def rate_fields(term_months: int) -> tuple[str, str, str, str]:
    """기간에 대응하는 네 금리 필드 이름.

    >>> rate_fields(12)
    ('JUNG_12M_DAN', 'TOP_12M_DAN', 'JUNG_12M_BOK', 'TOP_12M_BOK')
    """
    return (
        f"JUNG_{term_months}M_DAN",
        f"TOP_{term_months}M_DAN",
        f"JUNG_{term_months}M_BOK",
        f"TOP_{term_months}M_BOK",
    )


def terms_in(record: dict[str, Any]) -> list[int]:
    """행에 실제로 들어 있는 가입기간.

    요청한 기간을 덮어씌우지 않는다. 36개월만 취급하는 상품이 12개월
    조회에 섞여 오므로 (모듈 설명 참조), 요청값을 믿으면 없는 금리를
    지어내게 된다.

    >>> terms_in({"JUNG_12M_DAN": "3.8", "JUNG_6M_BOK": "3.0", "CNT": "67"})
    [6, 12]
    >>> terms_in({"CNT": "67"})
    []
    """
    found = {
        int(m.group(1)) for key in record if (m := _TERM_FIELD.match(key))
    }
    return sorted(found)


def parse_branches(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """저축은행 찾기 응답을 은행별 점포 명부로 옮긴다.

    금리 화면에는 소재지가 없다. `BANK_NAME`으로 결합한다
    (docs/source-recon/fsb.md §4-2, 부산 본점 9곳 9/9 매칭 확인).

    >>> d = parse_branches({"REC": [
    ...     {"BANK_NAME": "BNK  ", "BRANCH_NAME": "본점", "BRANCH_CODE": "001",
    ...      "ADDRESS": "부산광역시 동구 범일로 92", "BANK_CODE": "fb219"}]})
    >>> d["BNK"][0]["source_outlet_key"], d["BNK"][0]["name"]
    ('fb219:001', '본점')
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for row in payload.get("REC") or []:
        bank = clean(row.get("BANK_NAME"))
        code = clean(row.get("BANK_CODE"))
        branch = clean(row.get("BRANCH_CODE"))
        if not bank or not code or not branch:
            continue
        entries = out.setdefault(bank, [])
        key = f"{code}:{branch}"
        if any(e["source_outlet_key"] == key for e in entries):
            continue
        entries.append(
            {
                "source_outlet_key": key,
                "name": clean(row.get("BRANCH_NAME")) or branch,
                "address": clean(row.get("ADDRESS")) or None,
                "phone": None,  # 대표번호는 지점이 아니라 은행 것이다
            }
        )
    return out


def head_office(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """점포 명부에서 본점을 고른다.

    금리가 본점 기준이므로 기관 주소는 본점 것이어야 한다. 지점 주소를
    기관 주소로 쓰면 "본점 소재지 기준"이라는 표기가 거짓이 된다.

    >>> head_office([{"name": "해운대지점", "address": "a"},
    ...              {"name": "본점", "address": "b"}])["address"]
    'b'
    >>> head_office([{"name": "해운대지점", "address": "a"}]) is None
    True
    """
    for entry in entries:
        if entry.get("name") == "본점":
            return entry
    return None


def parse(
    payload: dict[str, Any],
    *,
    screen: str,
    area: str,
    branches: dict[str, list[dict[str, Any]]] | None = None,
    page_offset: int = 0,
    only_terms: tuple[int, ...] | None = None,
) -> tuple[list[ParsedRateRow], list[str]]:
    """금리 응답 한 장을 표준 행으로 바꾼다.

    `screen`은 `ratedepo`(정기예금) 또는 `rateinst`(정기적금)다.

    기간은 요청값이 아니라 **행에 실제로 있는 것**을 쓴다 (`terms_in`).
    `only_terms`를 주면 그중에서만 고른다 — 없는 기간을 만들어내지는 않는다.
    """
    warnings = check_schema(payload)
    product_type = SCREEN_PRODUCT_TYPE.get(screen, ProductType.OTHER)
    directory = branches or {}
    wanted = set(only_terms) if only_terms else None

    rows: list[ParsedRateRow] = []
    for index, record in enumerate(payload.get("REC") or []):
        bank = clean(record.get("BANK_NAME"))
        outlets = directory.get(bank) or []
        office = head_office(outlets)

        terms = terms_in(record)
        if wanted is not None:
            terms = [t for t in terms if t in wanted]
        if not terms:
            warnings.append(
                f"금리 필드가 없는 행: {clean(record.get('FINAN_PROD_CODE'))!r}"
            )
            continue

        for term in terms:
            jung_dan, top_dan, jung_bok, top_bok = rate_fields(term)
            for method, suffix in _METHOD_SUFFIX:
                base_key = jung_dan if suffix == "DAN" else jung_bok
                max_key = top_dan if suffix == "DAN" else top_bok
                if base_key not in record and max_key not in record:
                    # 그 이자방식을 취급하지 않으면 필드 자체가 없다. 0으로
                    # 채우지 않는다 — 0%로 판다는 뜻이 아니라 없다는 뜻이다.
                    continue
                rows.append(
                    _build_row(
                        record=record,
                        index=index + page_offset,
                        screen=screen,
                        product_type=product_type,
                        term_months=term,
                        area=area,
                        interest_method=method,
                        base_key=base_key,
                        max_key=max_key,
                        office=office,
                        outlets=outlets,
                    )
                )

    return rows, warnings


def _build_row(  # noqa: PLR0913 — 한 행을 옮기는 데 필요한 맥락이다
    *,
    record: dict[str, Any],
    index: int,
    screen: str,
    product_type: str,
    term_months: int,
    area: str,
    interest_method: str,
    base_key: str,
    max_key: str,
    office: dict[str, Any] | None,
    outlets: list[dict[str, Any]],
) -> ParsedRateRow:
    base_rate = parse_rate(record.get(base_key))
    max_rate = parse_rate(record.get(max_key))

    status = ValidationStatus.VALID
    message: str | None = None
    if base_rate is None:
        status = ValidationStatus.ERROR
        message = f"기본금리 변환 실패: {base_key}={record.get(base_key)!r}"
    elif max_rate is not None and max_rate < base_rate:
        status = ValidationStatus.WARNING
        message = f"최고금리({max_rate})가 기본금리({base_rate})보다 낮다"
    elif base_rate == Decimal(0) and max_rate in (None, Decimal(0)):
        # 취급하지 않는 이자방식이 0으로 오는 경우가 있다. 값을 버리지 않고
        # 검수로 넘긴다 — 실제 0%인지 미취급인지 화면이 구분해주지 않는다.
        status = ValidationStatus.WARNING
        message = "금리가 0이다. 실제 0%인지 미취급인지 확인이 필요하다"

    comp_code = clean(record.get("FINAN_COMP_CODE"))
    prod_code = clean(record.get("FINAN_PROD_CODE"))
    address = (office or {}).get("address")

    return ParsedRateRow(
        source_id=SOURCE_ID,
        # 명세서 v3 §7.2가 FSB를 저축은행 1차 원천으로 둔다. finlife가 교차검증.
        source_role=SourceRole.PRIMARY_OFFICIAL,
        trust_level=TrustLevel.OFFICIAL_DIRECT,
        sector=Sector.SAVINGS_BANK,
        source_institution_key=comp_code,
        # 금리는 본점 기준 공시다. 점포마다 복제하지 않는다.
        source_outlet_key=None,
        source_product_key=prod_code,
        institution_name=clean(record.get("BANK_NAME")),
        outlet_name=None,
        institution_type=None,
        # 주소는 **본점 소재지**다. 그 지점의 적용금리를 뜻하지 않는다.
        sido=_token(address, 0),
        sigungu=_token(address, 1),
        address=address,
        product_type=product_type,
        product_name=clean(record.get("PRODUCT_NAME")),
        term_months=term_months,
        term_days=None,
        join_channel=parse_join_channel(record.get("JOIN_LOCATION")),
        interest_method=interest_method,
        payment_method=None,
        amount_min=None,
        amount_max=None,
        customer_scope=clean(record.get("JOIN_TARGET")) or None,
        availability_scope=AvailabilityScope.NATIONWIDE,
        # 화면이 스스로 본점 기준이라고 밝힌다 (docs/source-recon/fsb.md §1).
        rate_scope=RateScope.HEAD_OFFICE_REFERENCE,
        base_rate=base_rate,
        max_rate=max_rate,
        preference_raw=preference_raw(record),
        source_row_ref=f"{comp_code}/{prod_code}/{term_months}/{interest_method}",
        base_source_locator=f"$.REC[{index}].{base_key}",
        source_record_hash=_record_hash(record),
        source_effective_at=parse_submit_date(record),
        validation_status=status,
        validation_message=message,
        outlets=tuple(outlets),
        extra={
            "area": area,
            "screen": screen,
            "tb_seq": clean(record.get("TB_SEQ")),
            "expire_interest_rate": clean(record.get("EXPIRE_INTRST_RATE")) or None,
            "product_url": clean(record.get("PRODUCT_URL")) or None,
            "submit_month": clean(record.get("SUBMIT_MONTH")) or None,
        },
    )


def _token(address: str | None, position: int) -> str | None:
    """주소에서 시도·시군구 토막을 뽑는다.

    >>> _token("부산광역시 동구 범일로 92", 0)
    '부산광역시'
    >>> _token("부산광역시 동구 범일로 92", 1)
    '동구'
    >>> _token(None, 0) is None
    True
    """
    tokens = (address or "").split()
    return tokens[position] if len(tokens) > position else None


def _record_hash(record: dict[str, Any]) -> str:
    """행 단위 원본 해시 (v3.1 §7).

    개인정보성 필드는 해시 대상에서도 뺀다. 담당자가 바뀌었다고 금리가
    바뀐 것으로 잡히면 안 된다.
    """
    payload = {k: v for k, v in sorted(record.items()) if k not in DROPPED_FIELDS}
    return _digest(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def schema_fingerprint(payload: dict[str, Any]) -> str:
    """구조 지문. 값이 아니라 필드 구성이 바뀌었는지만 본다."""
    rows = payload.get("REC") or []
    fields = sorted(rows[0]) if rows else []
    return _digest("|".join(fields))


def total_count(payload: dict[str, Any]) -> int | None:
    """전체 건수. 페이지네이션 종료 판정에 쓴다.

    행 안의 `CNT`에 들어 있다 (docs/source-recon/fsb.md §3.3).

    >>> total_count({"REC": [{"CNT": "67"}]})
    67
    >>> total_count({"REC": []}) is None
    True
    """
    rows = payload.get("REC") or []
    if not rows:
        return None
    raw = clean(rows[0].get("CNT"))
    return int(raw) if raw.isdigit() else None
