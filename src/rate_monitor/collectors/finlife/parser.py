"""금융감독원 finlife 오픈API 파서.

순수 함수다. 네트워크·파일·DB를 건드리지 않는다 (명세서 v3 §6.2).
같은 원본이면 항상 같은 결과를 반환한다.

필드 매핑 근거: docs/source-recon/finlife.md §3.2 (2026-08-05 실물 검증).
"""

import json
from datetime import date, datetime
from hashlib import sha256
from typing import Any

from rate_monitor.collectors.base import ParseError, SchemaChangedError
from rate_monitor.domain.enums import (
    AvailabilityScope,
    InterestMethod,
    JoinChannel,
    ProductType,
    RateScope,
    SourceRole,
    TrustLevel,
    ValidationStatus,
)
from rate_monitor.domain.normalization import parse_rate
from rate_monitor.domain.schemas import ParsedRateRow

SOURCE_ID = "finlife"

# breaking 판정 기준이 되는 필수 필드 (v3.1 §8)
REQUIRED_BASE_FIELDS = frozenset({"fin_co_no", "fin_prdt_cd", "kor_co_nm", "fin_prdt_nm"})
REQUIRED_OPTION_FIELDS = frozenset({"fin_co_no", "fin_prdt_cd", "save_trm"})

# 서비스명 → 상품유형
SERVICE_PRODUCT_TYPE = {
    "depositProductsSearch": ProductType.TERM_DEPOSIT,
    "savingProductsSearch": ProductType.INSTALLMENT_SAVINGS,
}

# 권역코드 → rate_scope
# 저축은행 공시는 본점 기준이므로 지역별 지점금리로 오해되면 안 된다 (v3.1 §6.4).
GROUP_RATE_SCOPE = {
    "020000": RateScope.NATIONWIDE,
    "030300": RateScope.HEAD_OFFICE_REFERENCE,
}

_INTEREST_METHOD = {"S": InterestMethod.SIMPLE, "M": InterestMethod.COMPOUND}

# join_way 원문 → 채널. 여러 개면 ANY로 둔다.
_CHANNEL_TOKENS = {
    "영업점": JoinChannel.BRANCH,
    "인터넷": JoinChannel.INTERNET,
    "스마트폰": JoinChannel.MOBILE,
    "전화(텔레뱅킹)": JoinChannel.TELEPHONE,
    "모집인": JoinChannel.AGENT,
}

_NO_PREFERENCE = {"", "-", "없음", "해당없음"}


def _fingerprint(result: dict[str, Any]) -> str:
    """구조 지문. 응답 키 집합과 리스트 필드 구성을 담는다 (v3 §8.3)."""
    base_keys = sorted(result.get("baseList", [{}])[0].keys()) if result.get("baseList") else []
    opt_keys = sorted(result.get("optionList", [{}])[0].keys()) if result.get("optionList") else []
    payload = {"top": sorted(result.keys()), "base": base_keys, "option": opt_keys}
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _record_hash(base: dict[str, Any], option: dict[str, Any] | None) -> str:
    payload = json.dumps([base, option], sort_keys=True, ensure_ascii=False)
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def _parse_dcls_day(value: object) -> date | None:
    """공시 시작일 YYYYMMDD → date.

    dcls_month(YYYYMM)는 일자가 없으므로 날짜로 만들지 않는다. 없으면 None을
    유지하고 collected_at으로 대체하지 않는다 (v3.1 §7.3).
    """
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _join_channel(join_way: object) -> str:
    if not isinstance(join_way, str) or not join_way.strip():
        return JoinChannel.UNKNOWN
    matched = {ch for token, ch in _CHANNEL_TOKENS.items() if token in join_way}
    if not matched:
        return JoinChannel.UNKNOWN
    if len(matched) > 1:
        return JoinChannel.ANY
    return next(iter(matched))


def _term_months(save_trm: object) -> int | None:
    if isinstance(save_trm, int):
        return save_trm
    if isinstance(save_trm, str) and save_trm.strip().isdigit():
        return int(save_trm.strip())
    return None


def _preference_raw(spcl_cnd: object) -> str:
    """우대조건 원문. 어떤 경우에도 원문 그대로 보존한다 (v3 §6.2)."""
    if not isinstance(spcl_cnd, str):
        return ""
    return "" if spcl_cnd.strip() in _NO_PREFERENCE else spcl_cnd


def check_schema(result: dict[str, Any]) -> list[str]:
    """구조를 검사한다. breaking이면 SchemaChangedError, 호환 변경은 경고로 반환.

    v3.1 §8: 선택 필드 추가나 알 수 없는 필드로 수집을 멈추지 않는다.
    """
    for key in ("baseList", "optionList"):
        if key not in result:
            raise SchemaChangedError(f"필수 리스트 소실: result.{key}")

    warnings: list[str] = []
    base_list = result.get("baseList") or []
    option_list = result.get("optionList") or []

    if base_list:
        missing = REQUIRED_BASE_FIELDS - set(base_list[0])
        if missing:
            raise SchemaChangedError(f"baseList 필수 필드 소실: {sorted(missing)}")
        extra = set(base_list[0]) - REQUIRED_BASE_FIELDS - _KNOWN_BASE_OPTIONAL
        if extra:
            warnings.append(f"baseList 미지 필드: {sorted(extra)}")

    if option_list:
        missing = REQUIRED_OPTION_FIELDS - set(option_list[0])
        if missing:
            raise SchemaChangedError(f"optionList 필수 필드 소실: {sorted(missing)}")
        extra = set(option_list[0]) - REQUIRED_OPTION_FIELDS - _KNOWN_OPTION_OPTIONAL
        if extra:
            warnings.append(f"optionList 미지 필드: {sorted(extra)}")

    return warnings


_KNOWN_BASE_OPTIONAL = frozenset(
    {
        "dcls_month", "join_way", "mtrt_int", "spcl_cnd", "join_deny", "join_member",
        "etc_note", "max_limit", "dcls_strt_day", "dcls_end_day", "fin_co_subm_day",
    }
)
_KNOWN_OPTION_OPTIONAL = frozenset(
    {"dcls_month", "intr_rate_type", "intr_rate_type_nm", "intr_rate", "intr_rate2",
     "rsrv_type", "rsrv_type_nm"}
)


def parse(
    payload: dict[str, Any],
    service: str,
    top_fin_grp_no: str,
) -> tuple[list[ParsedRateRow], list[str]]:
    """finlife 응답 → (ParsedRateRow[], 경고 목록).

    Args:
        payload: 응답 JSON 전체 (`{"result": {...}}`)
        service: `depositProductsSearch` 또는 `savingProductsSearch`
        top_fin_grp_no: 권역코드. `030300`(저축은행)은 본점 기준 참고값이 된다.
    """
    if service not in SERVICE_PRODUCT_TYPE:
        raise ParseError(f"지원하지 않는 서비스: {service}")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise SchemaChangedError("응답에 result 객체가 없다")

    err_cd = result.get("err_cd")
    if err_cd not in (None, "000"):
        raise ParseError(f"API 오류 err_cd={err_cd} err_msg={result.get('err_msg')}")

    warnings = check_schema(result)
    product_type = SERVICE_PRODUCT_TYPE[service]
    rate_scope = GROUP_RATE_SCOPE.get(top_fin_grp_no, RateScope.UNKNOWN)

    # 결합키: fin_co_no + fin_prdt_cd (docs/source-recon/finlife.md §3.2)
    base_index: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
    for idx, base in enumerate(result.get("baseList") or []):
        key = (str(base.get("fin_co_no")), str(base.get("fin_prdt_cd")))
        base_index[key] = (idx, base)

    rows: list[ParsedRateRow] = []
    seen_orphans: set[tuple[str, str]] = set()

    for opt_idx, option in enumerate(result.get("optionList") or []):
        key = (str(option.get("fin_co_no")), str(option.get("fin_prdt_cd")))
        found = base_index.get(key)
        if found is None:
            # 대응 상품이 없는 옵션은 버리지 않고 경고로 남긴다 (v3 §6.2).
            if key not in seen_orphans:
                seen_orphans.add(key)
                warnings.append(f"optionList에 대응 baseList 없음: {key[0]}/{key[1]}")
            continue
        base_idx, base = found
        rows.append(
            _build_row(
                base=base,
                option=option,
                base_idx=base_idx,
                opt_idx=opt_idx,
                product_type=product_type,
                rate_scope=rate_scope,
            )
        )

    return rows, warnings


def _build_row(
    *,
    base: dict[str, Any],
    option: dict[str, Any],
    base_idx: int,
    opt_idx: int,
    product_type: str,
    rate_scope: str,
) -> ParsedRateRow:
    base_rate = parse_rate(option.get("intr_rate"))
    # intr_rate2가 없으면 base_rate와 같다고 단정하지 않는다 (v3 §8.4).
    # 소스가 명시적으로 우대 없음이라고 할 때만 같게 처리하는데, finlife는
    # 그런 표시를 주지 않으므로 항상 NULL로 남긴다.
    max_rate = parse_rate(option.get("intr_rate2"))

    status = ValidationStatus.VALID
    message: str | None = None
    if base_rate is None:
        status = ValidationStatus.ERROR
        message = f"기본금리 변환 실패: {option.get('intr_rate')!r}"
    elif max_rate is not None and max_rate < base_rate:
        status = ValidationStatus.WARNING
        message = f"최고금리({max_rate})가 기본금리({base_rate})보다 낮다"
    elif option.get("intr_rate2") is not None and max_rate is None:
        status = ValidationStatus.WARNING
        message = f"우대금리 변환 실패: {option.get('intr_rate2')!r}"

    return ParsedRateRow(
        source_id=SOURCE_ID,
        source_role=SourceRole.SECONDARY_OFFICIAL,
        trust_level=TrustLevel.OFFICIAL_DIRECT,
        source_institution_key=str(base.get("fin_co_no")),
        source_outlet_key=None,
        source_product_key=str(base.get("fin_prdt_cd")),
        institution_name=str(base.get("kor_co_nm") or ""),
        outlet_name=None,
        institution_type=None,
        # finlife 상품 API는 지역 필드를 제공하지 않는다 (docs/source-recon/finlife.md §5).
        sido=None,
        sigungu=None,
        address=None,
        product_type=product_type,
        product_name=str(base.get("fin_prdt_nm") or ""),
        term_months=_term_months(option.get("save_trm")),
        term_days=None,
        join_channel=_join_channel(base.get("join_way")),
        interest_method=_INTEREST_METHOD.get(
            option.get("intr_rate_type"), InterestMethod.UNKNOWN
        ),
        payment_method=option.get("rsrv_type_nm"),
        amount_min=None,
        amount_max=base.get("max_limit") if isinstance(base.get("max_limit"), int) else None,
        customer_scope=base.get("join_member"),
        availability_scope=AvailabilityScope.NATIONWIDE,
        rate_scope=rate_scope,
        base_rate=float(base_rate) if base_rate is not None else None,
        max_rate=float(max_rate) if max_rate is not None else None,
        preference_raw=_preference_raw(base.get("spcl_cnd")),
        source_row_ref=f"{base.get('fin_co_no')}/{base.get('fin_prdt_cd')}/{option.get('save_trm')}",
        base_source_locator=f"$.result.baseList[{base_idx}]",
        option_source_locator=f"$.result.optionList[{opt_idx}]",
        source_record_hash=_record_hash(base, option),
        source_effective_at=_parse_dcls_day(base.get("dcls_strt_day")),
        validation_status=status,
        validation_message=message,
        extra={
            "dcls_month": base.get("dcls_month"),
            "mtrt_int": base.get("mtrt_int"),
            "etc_note": base.get("etc_note"),
            "join_deny": base.get("join_deny"),
            "dcls_end_day": base.get("dcls_end_day"),
            "intr_rate_type_nm": option.get("intr_rate_type_nm"),
        },
    )


def schema_fingerprint(payload: dict[str, Any]) -> str:
    """어댑터가 raw artifact 메타에 넣을 구조 지문."""
    result = payload.get("result")
    return _fingerprint(result if isinstance(result, dict) else {})
