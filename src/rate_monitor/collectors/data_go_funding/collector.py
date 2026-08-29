"""Data.go.kr 금융위원회 금융통계 기관별 수신잔액 수집.

원천 재무상태표의 ``예수부채`` 계정을 기관/기준년월 단위로 보존한다.
원천 금액은 원(KRW) 정수이며 DB 표준값은 lossless ``million_krw``로 저장한다.
원문 값은 ``source_value_text``와 raw artifact에 그대로 남긴다.

중요:
- ``basYm``은 포털 공식 정의가 "기준년월"이다. 수집기가 월말 공시라고
  확대 해석하지 않고 ``reported_period_end``로 저장한다.
- Data.go 재무 ``예수부채``와 ECOS ``수신잔액(말잔)``은 정의가 다를 수 있다.
  동일시하지 않고 별도 reconciliation quality metric으로만 비교한다.
- 기관 식별은 FSS ``fncoCd``를 1차 key로 쓴다. 코드가 다른 기관을 이름만으로
  자동 합병하지 않는다.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.types import canonical_quantity_text, quantize_quantity
from rate_monitor.domain.identifiers import make_org_key
from rate_monitor.domain.normalization import normalize_institution_name
from rate_monitor.domain.schemas import RawArtifactData
from rate_monitor.services.collection_service import save_raw_artifacts

MILLION = Decimal("1000000")
PAGE_SIZE = 9999
REQUEST_TIMEOUT = 30.0
MAX_PAGES = 20
RETRY_DELAYS = (1.0, 2.0, 4.0)
TOTAL_METRIC_CODE = "deposit_liabilities_total"
TOTAL_METRIC_NAME = "예수부채"
NORMALIZED_UNIT = "million_krw"
SOURCE_UNIT = "krw"
OBSERVATION_BASIS = "reported_period_end"
STATEMENT_BASIS = "source_reported_unconsolidated_unspecified"
SAVINGS_BANK_SECTOR_TOTAL_KEY = "030350S"
SAVINGS_BANK_SECTOR_TOTAL_NAME = "저축은행"

DATA_GO_BASE = "https://apis.data.go.kr/1160100/service"

CU_CANDIDATES = (
    f"{DATA_GO_BASE}/GetCredUnioInfoService/getCredUnioFinaInfo",
    f"{DATA_GO_BASE}/GetCredUnioInfoService/getCredUnioFinInfo",
    f"{DATA_GO_BASE}/GetCredUnioInfoService/getCrdtUnioFinaInfo",
    f"{DATA_GO_BASE}/CrdtUnionInfoService/getCrdtUnionFinaInfo",
    f"{DATA_GO_BASE}/GetCrdtUnionInfoService/getCrdtUnionFinaInfo",
)


class FundingContractError(RuntimeError):
    """원천 schema/계약이 검증된 범위를 벗어났다."""


class FundingTransportError(RuntimeError):
    """Data.go.kr transport가 모든 retry 뒤에도 실패했다."""


class FundingSourceUnavailable(RuntimeError):
    """공식 source는 있으나 현재 exact operational contract를 확정할 수 없다."""


@dataclass(frozen=True)
class AccountSchema:
    code_field: str
    name_field: str
    amount_field: str
    total_code: str


@dataclass(frozen=True)
class SourceContract:
    source_id: str
    source_name: str
    sector: str
    dataset_id: str
    key_env: str
    finance_endpoint: str | None
    account_schemas: tuple[AccountSchema, ...]
    population_scope: str
    cadence_months: tuple[int, ...]


CONTRACTS = (
    SourceContract(
        source_id="data_go_savings_bank_funding",
        source_name="금융위원회 금융통계 저축은행 재무현황",
        sector="savings_bank",
        dataset_id="15061316",
        key_env="DATA_GO_KR_SERVICE_KEY_SB",
        finance_endpoint=(
            f"{DATA_GO_BASE}/GetMutuSaviBankInfoService/getMutuSaviBankFinaInfo"
        ),
        account_schemas=(
            AccountSchema("dpsdbtDcd", "dpsdbtDcdNm", "dpsdbtClsfAmt", "A11"),
            AccountSchema(
                "debtCptlSmryStfnpsAcitCd",
                "debtCptlSmryStfnpsAcitCdNm",
                "debtCptlAmt",
                "A11",
            ),
        ),
        population_scope="savings_banks_all_source_reported",
        cadence_months=(3, 6, 9, 12),
    ),
    SourceContract(
        source_id="data_go_credit_union_funding",
        source_name="금융위원회 금융통계 신용협동조합 재무현황",
        sector="cu",
        dataset_id="15061337",
        key_env="DATA_GO_KR_SERVICE_KEY_SH",
        finance_endpoint=None,
        account_schemas=(),
        population_scope="credit_unions_all_source_reported",
        cadence_months=(3, 6, 9, 12),
    ),
    SourceContract(
        source_id="data_go_agri_coop_funding",
        source_name="금융위원회 금융통계 농업협동조합 재무현황",
        sector="nh_local",
        dataset_id="15061344",
        key_env="DATA_GO_KR_SERVICE_KEY_NH",
        finance_endpoint=f"{DATA_GO_BASE}/GetAgriCoopInfoService/getAgriCoopFinaInfo",
        account_schemas=(
            AccountSchema(
                "astDebtSmryBlnshDcd",
                "astDebtSmryBlnshDcdNm",
                "astDebtSmryBlnshClsfAmt",
                "A1",
            ),
        ),
        population_scope="agri_coops_local_units_source_reported",
        cadence_months=(6, 12),
    ),
)


@dataclass(frozen=True)
class FundingPoint:
    source_id: str
    sector: str
    dataset_id: str
    source_institution_key: str
    source_institution_name: str
    source_crno: str | None
    source_effective_month: str
    period_start: date
    period_end: date
    source_value_text: str
    value: Decimal
    population_scope: str
    source_locator: str


@dataclass(frozen=True)
class SourceResult:
    source_id: str
    status: str
    fetched_artifacts: int
    parsed_points: int
    stored: int
    unchanged: int
    revisions: int
    mapped: int
    unmapped: int
    message: str


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _service_key(contract: SourceContract) -> str:
    raw = os.environ.get(contract.key_env, "").strip()
    if not raw:
        raw = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not raw:
        raise FundingSourceUnavailable(f"{contract.key_env}가 없다")
    return urllib.parse.unquote(raw)


def candidate_months(contract: SourceContract, periods: int, today: date | None = None) -> list[str]:
    if periods < 1:
        raise ValueError("periods는 1 이상이어야 한다")
    cursor = today or datetime.now(UTC).date()
    out: list[str] = []
    year = cursor.year
    while len(out) < periods:
        for month in sorted(contract.cadence_months, reverse=True):
            if year == cursor.year and month > cursor.month:
                continue
            value = f"{year:04d}{month:02d}"
            if value not in out:
                out.append(value)
                if len(out) == periods:
                    return out
        year -= 1
    return out


def _flatten_items(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "item":
                if isinstance(child, dict):
                    rows.append(child)
                elif isinstance(child, list):
                    rows.extend(row for row in child if isinstance(row, dict))
            else:
                rows.extend(_flatten_items(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_flatten_items(child))
    return rows


def _metadata(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for name, child in value.items():
            if name == key and not isinstance(child, (dict, list)):
                found.append(child)
            else:
                found.extend(_metadata(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(_metadata(child, key))
    return found


def _accepted(payload: Any, text: str) -> bool:
    codes = {str(value) for value in _metadata(payload, "resultCode")}
    messages = " ".join(str(value) for value in _metadata(payload, "resultMsg")).upper()
    upper = text.upper()
    return "00" in codes or "NORMAL SERVICE" in messages or "NORMAL SERVICE" in upper


def _unknown_operation(payload: Any, text: str, status: int) -> bool:
    upper = (json.dumps(payload, ensure_ascii=False) if payload is not None else text).upper()
    return status == 404 or "NO_OPENAPI_SERVICE" in upper


def _request_json(
    client: httpx.Client,
    *,
    endpoint: str,
    key: str,
    bas_ym: str,
    page_no: int,
) -> tuple[dict[str, Any], bytes]:
    params = {
        "serviceKey": key,
        "numOfRows": str(PAGE_SIZE),
        "pageNo": str(page_no),
        "resultType": "json",
        "basYm": bas_ym,
    }
    last_error: Exception | None = None
    for delay in (0.0, *RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            response = client.get(endpoint, params=params)
            raw = response.content
            text = raw.decode("utf-8", "replace")
            payload: Any = None
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise FundingTransportError(
                    f"JSON이 아닌 응답: status={response.status_code} endpoint={endpoint}"
                ) from exc
            if _unknown_operation(payload, text, response.status_code):
                raise FundingSourceUnavailable(f"unknown operation: {endpoint}")
            if response.status_code >= 500:
                raise FundingTransportError(
                    f"Data.go 서버 오류 {response.status_code}: {endpoint}"
                )
            if not _accepted(payload, text):
                raise FundingContractError(
                    f"Data.go 정상응답 계약 불일치 status={response.status_code}: {endpoint}"
                )
            if not isinstance(payload, dict):
                raise FundingContractError("Data.go JSON root가 object가 아니다")
            return payload, raw
        except FundingSourceUnavailable:
            raise
        except FundingContractError:
            raise
        except (httpx.HTTPError, FundingTransportError) as exc:
            last_error = exc
    raise FundingTransportError(f"Data.go transport retry 소진: {last_error}")


def _discover_credit_union_endpoint(client: httpx.Client, key: str, bas_ym: str) -> str:
    transport_errors: list[str] = []
    for endpoint in CU_CANDIDATES:
        try:
            payload, _ = _request_json(
                client, endpoint=endpoint, key=key, bas_ym=bas_ym, page_no=1
            )
        except FundingSourceUnavailable:
            continue
        except FundingTransportError as exc:
            transport_errors.append(str(exc))
            continue
        rows = _flatten_items(payload)
        if rows:
            return endpoint
    if transport_errors and len(transport_errors) == len(CU_CANDIDATES):
        raise FundingTransportError(
            "신협 finance 후보가 모두 transport 실패; endpoint 부재로 판정하지 않는다"
        )
    raise FundingSourceUnavailable(
        "공식 카탈로그는 신협 재무현황 operation 존재를 명시하지만 "
        "현재 후보에서 exact operational path를 확정하지 못했다"
    )


def _infer_credit_union_schema(rows: list[dict[str, Any]]) -> tuple[AccountSchema, ...]:
    known = (
        AccountSchema(
            "astDebtSmryBlnshDcd",
            "astDebtSmryBlnshDcdNm",
            "astDebtSmryBlnshClsfAmt",
            "A1",
        ),
        AccountSchema("dpsdbtDcd", "dpsdbtDcdNm", "dpsdbtClsfAmt", "A11"),
        AccountSchema(
            "debtCptlSmryStfnpsAcitCd",
            "debtCptlSmryStfnpsAcitCdNm",
            "debtCptlAmt",
            "A11",
        ),
    )
    keys = {key for row in rows for key in row}
    matches = tuple(
        schema
        for schema in known
        if {schema.code_field, schema.name_field, schema.amount_field} <= keys
    )
    if not matches:
        raise FundingContractError(
            "신협 finance endpoint는 응답했지만 예수부채 schema를 검증된 naming family로 "
            f"인식하지 못했다. row keys={sorted(keys)}"
        )
    return matches


def _parse_month(raw: object) -> tuple[str, date, date]:
    text = str(raw or "").strip()
    if len(text) != 6 or not text.isdigit():
        raise FundingContractError(f"basYm 형식 오류: {raw!r}")
    year, month = int(text[:4]), int(text[4:])
    if not 1 <= month <= 12:
        raise FundingContractError(f"basYm 월 오류: {raw!r}")
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}", date(year, month, 1), date(year, month, last)


def _parse_source_amount(raw: object) -> tuple[str, Decimal]:
    text = str(raw if raw is not None else "").strip().replace(",", "")
    if not text or text.lower() in {"null", "none", "-"}:
        raise FundingContractError(f"예수부채 금액이 비어 있다: {raw!r}")
    try:
        krw = Decimal(text)
    except InvalidOperation as exc:
        raise FundingContractError(f"예수부채 금액 변환 실패: {raw!r}") from exc
    if not krw.is_finite() or krw < 0:
        raise FundingContractError(f"예수부채 금액은 비음수여야 한다: {raw!r}")
    if krw != krw.to_integral_value():
        raise FundingContractError(
            f"Data.go source_unit=KRW 계약에서 소수 금액을 받았다: {raw!r}"
        )
    normalized = quantize_quantity(krw / MILLION)
    return format(krw, "f"), normalized


def _exclude_validated_savings_bank_sector_totals(
    contract: SourceContract,
    points: list[FundingPoint],
) -> list[FundingPoint]:
    """검증된 저축은행 업권 합계행을 기관 observation 저장 전에 제외한다.

    raw artifact는 이미 별도로 그대로 보존된다. 이 함수는 기관별 observation
    후보만 다루며, ``030350S``가 같은 기준월의 나머지 기관 합계와 정확히
    일치할 때만 제외한다. 원천 의미가 바뀌면 조용히 버리지 않고 fail closed한다.
    """
    if contract.sector != "savings_bank":
        return points

    grouped: dict[str, list[FundingPoint]] = {}
    for point in points:
        grouped.setdefault(point.source_effective_month, []).append(point)

    filtered: list[FundingPoint] = []
    for month in sorted(grouped):
        month_points = grouped[month]
        aggregates = [
            point
            for point in month_points
            if point.source_institution_key == SAVINGS_BANK_SECTOR_TOTAL_KEY
        ]
        if not aggregates:
            filtered.extend(month_points)
            continue
        if len(aggregates) != 1:
            raise FundingContractError(
                "저축은행 sector-total row가 기준월에 하나가 아니다: "
                f"month={month} count={len(aggregates)}"
            )

        aggregate = aggregates[0]
        normalized_name = normalize_institution_name(aggregate.source_institution_name)
        crno = str(aggregate.source_crno or "").strip()
        if normalized_name != SAVINGS_BANK_SECTOR_TOTAL_NAME or crno:
            raise FundingContractError(
                "저축은행 sector-total identity 계약 불일치: "
                f"month={month} fncoCd={aggregate.source_institution_key!r} "
                f"fncoNm={aggregate.source_institution_name!r} "
                f"crno={aggregate.source_crno!r}"
            )

        peers = [
            point
            for point in month_points
            if point.source_institution_key != SAVINGS_BANK_SECTOR_TOTAL_KEY
        ]
        if not peers:
            raise FundingContractError(
                f"저축은행 sector-total 검증 대상 기관 row가 없다: month={month}"
            )
        institution_total = sum(
            (point.value for point in peers),
            start=Decimal("0"),
        )
        if aggregate.value != institution_total:
            raise FundingContractError(
                "저축은행 sector-total 합계 불일치: "
                f"month={month} aggregate={aggregate.value} "
                f"institutions={institution_total} institution_rows={len(peers)}"
            )
        filtered.extend(peers)

    return sorted(
        filtered,
        key=lambda point: (point.source_effective_month, point.source_institution_key),
    )


def parse_points(
    contract: SourceContract,
    rows: list[dict[str, Any]],
    *,
    endpoint: str,
    account_schemas: tuple[AccountSchema, ...] | None = None,
) -> list[FundingPoint]:
    schemas = account_schemas if account_schemas is not None else contract.account_schemas
    if not schemas:
        raise FundingContractError(f"{contract.source_id}: 예수부채 account schema 미확정")

    by_key: dict[tuple[str, str], FundingPoint] = {}
    seen_contract_row = False
    for row in rows:
        selected: AccountSchema | None = None
        for schema in schemas:
            if str(row.get(schema.code_field) or "").strip() == schema.total_code:
                selected = schema
                break
        if selected is None:
            continue

        account_name = str(row.get(selected.name_field) or "").replace(" ", "").strip()
        if "예수부채" not in account_name:
            raise FundingContractError(
                f"{selected.total_code} 코드명이 예수부채가 아니다: {account_name!r}"
            )
        seen_contract_row = True

        fnco_cd = str(row.get("fncoCd") or "").strip()
        fnco_nm = str(row.get("fncoNm") or "").strip()
        if not fnco_cd or not fnco_nm:
            raise FundingContractError(
                f"예수부채 row에 fncoCd/fncoNm이 없다: fncoCd={fnco_cd!r} fncoNm={fnco_nm!r}"
            )
        month, period_start, period_end = _parse_month(row.get("basYm"))
        source_text, value = _parse_source_amount(row.get(selected.amount_field))
        crno = str(row.get("crno") or "").strip() or None

        population = contract.population_scope
        if contract.sector == "nh_local" and (
            fnco_cd == "0212450" or normalize_institution_name(fnco_nm) == "농협중앙회"
        ):
            population = "agri_coop_central_excluded_from_local_sum"

        point = FundingPoint(
            source_id=contract.source_id,
            sector=contract.sector,
            dataset_id=contract.dataset_id,
            source_institution_key=fnco_cd,
            source_institution_name=fnco_nm,
            source_crno=crno,
            source_effective_month=month,
            period_start=period_start,
            period_end=period_end,
            source_value_text=source_text,
            value=value,
            population_scope=population,
            source_locator=endpoint,
        )
        natural = (fnco_cd, month)
        prior = by_key.get(natural)
        if prior is not None and (
            prior.source_value_text != point.source_value_text
            or prior.source_crno != point.source_crno
        ):
            raise FundingContractError(
                "같은 기관/기준월 예수부채가 서로 다르다: "
                f"{fnco_cd} {month} {prior.source_value_text} != {point.source_value_text}"
            )
        by_key[natural] = point

    if rows and not seen_contract_row:
        raise FundingContractError(
            f"{contract.source_id}: 응답 row는 있으나 총 예수부채 code를 찾지 못했다"
        )
    points = sorted(
        by_key.values(),
        key=lambda point: (point.source_effective_month, point.source_institution_key),
    )
    return _exclude_validated_savings_bank_sector_totals(contract, points)


def _content_hash(point: FundingPoint) -> str:
    payload = "|".join(
        (
            point.source_id,
            point.source_institution_key,
            TOTAL_METRIC_CODE,
            point.source_effective_month,
            point.source_value_text,
            SOURCE_UNIT,
            canonical_quantity_text(point.value),
            NORMALIZED_UNIT,
            point.population_scope,
        )
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _ensure_source(session: Any, contract: SourceContract, now: datetime) -> None:
    source = session.get(m.Source, contract.source_id)
    if source is None:
        session.add(
            m.Source(
                id=contract.source_id,
                name=contract.source_name,
                sector=contract.sector,
                mode="api",
                source_role="secondary_official",
                trust_level="official_direct",
                priority=40,
                base_reference=f"https://www.data.go.kr/data/{contract.dataset_id}/openapi.do",
                enabled=True,
                schedule_cron=None,
                policy_status="approved",
                coverage_status="partial",
                parser_version="1.0.0",
                created_at=now,
                updated_at=now,
            )
        )
    else:
        source.updated_at = now


def _resolve_identity(
    session: Any,
    point: FundingPoint,
    now: datetime,
) -> tuple[str | None, str]:
    """FSS code exact match only. Name-only merger is deliberately forbidden."""
    org_key = make_org_key(
        sector=point.sector,
        source_institution_key=point.source_institution_key,
        institution_name=point.source_institution_name,
    )

    own_link = session.scalars(
        select(m.SourceEntityLink).where(
            m.SourceEntityLink.source_id == point.source_id,
            m.SourceEntityLink.entity_type == "institution",
            m.SourceEntityLink.source_entity_key == org_key,
            m.SourceEntityLink.valid_to.is_(None),
        )
    ).first()
    if own_link is not None:
        payload = own_link.source_payload_json or {}
        old_crno = str(payload.get("crno") or "").strip()
        if old_crno and point.source_crno and old_crno != point.source_crno:
            session.add(
                m.ReviewItem(
                    entity_type="institution",
                    entity_id=own_link.entity_id,
                    issue_type="funding_identity_crno_conflict",
                    severity="error",
                    message=(
                        f"{point.source_institution_key} CRNO 충돌: "
                        f"{old_crno} != {point.source_crno}"
                    ),
                    payload_json={
                        "source_id": point.source_id,
                        "fncoCd": point.source_institution_key,
                        "old_crno": old_crno,
                        "new_crno": point.source_crno,
                        "source_effective_month": point.source_effective_month,
                    },
                    created_at=now,
                )
            )
            return None, "conflict"
        return own_link.entity_id, "mapped_exact_fss_code"

    links = list(
        session.scalars(
            select(m.SourceEntityLink).where(
                m.SourceEntityLink.entity_type == "institution",
                m.SourceEntityLink.source_entity_key == org_key,
                m.SourceEntityLink.valid_to.is_(None),
            )
        )
    )
    candidates: list[m.Institution] = []
    for link in links:
        institution = session.get(m.Institution, link.entity_id)
        if (
            institution is not None
            and institution.sector == point.sector
            and normalize_institution_name(institution.canonical_name)
            == normalize_institution_name(point.source_institution_name)
        ):
            candidates.append(institution)
    unique = {institution.id: institution for institution in candidates}
    if len(unique) != 1:
        return None, "unmapped_no_exact_cross_source_code"

    institution = next(iter(unique.values()))
    session.add(
        m.SourceEntityLink(
            source_id=point.source_id,
            entity_type="institution",
            source_entity_key=org_key,
            entity_id=institution.id,
            source_name=point.source_institution_name,
            source_payload_json={
                "fncoCd": point.source_institution_key,
                "crno": point.source_crno,
                "dataset_id": point.dataset_id,
                "observed_from_month": point.source_effective_month,
                "validity_basis": (
                    "source observation only; not a legal merger/closure effective date"
                ),
            },
            confidence=1.0,
            match_method="exact_fss_code_and_name",
            valid_from=None,
            valid_to=None,
            created_at=now,
            updated_at=now,
        )
    )
    return institution.id, "mapped_exact_fss_code"


def _upsert_point(
    session: Any,
    point: FundingPoint,
    *,
    raw_artifact_id: str,
    now: datetime,
) -> tuple[str, bool]:
    institution_id, identity_status = _resolve_identity(session, point, now)
    content_hash = _content_hash(point)
    existing = session.scalars(
        select(InstitutionFundingObservation)
        .where(
            InstitutionFundingObservation.source_id == point.source_id,
            InstitutionFundingObservation.source_institution_key
            == point.source_institution_key,
            InstitutionFundingObservation.metric_code == TOTAL_METRIC_CODE,
            InstitutionFundingObservation.source_effective_month
            == point.source_effective_month,
            InstitutionFundingObservation.valid_to.is_(None),
        )
        .order_by(InstitutionFundingObservation.revision.desc())
    ).first()

    if existing is not None and existing.content_hash == content_hash:
        return "unchanged", institution_id is not None

    revision = 1
    if existing is not None:
        existing.valid_to = now
        revision = existing.revision + 1

    session.add(
        InstitutionFundingObservation(
            institution_id=institution_id,
            source_id=point.source_id,
            source_institution_key=point.source_institution_key,
            source_institution_name=point.source_institution_name,
            source_crno=point.source_crno,
            sector=point.sector,
            metric_code=TOTAL_METRIC_CODE,
            metric_name=TOTAL_METRIC_NAME,
            source_effective_month=point.source_effective_month,
            period_start=point.period_start,
            period_end=point.period_end,
            value=point.value,
            unit=NORMALIZED_UNIT,
            source_value_text=point.source_value_text,
            source_unit=SOURCE_UNIT,
            observation_basis=OBSERVATION_BASIS,
            statement_basis=STATEMENT_BASIS,
            population_scope=point.population_scope,
            identity_status=identity_status,
            observed_at=now,
            source_locator=point.source_locator,
            raw_artifact_id=raw_artifact_id,
            content_hash=content_hash,
            revision=revision,
            valid_from=now,
            valid_to=None,
            created_at=now,
        )
    )
    return ("revision" if existing is not None else "stored"), institution_id is not None


def _artifact(
    *,
    contract: SourceContract,
    endpoint: str,
    bas_ym: str,
    page_no: int,
    raw: bytes,
) -> RawArtifactData:
    digest = hashlib.sha256(raw).hexdigest()
    return RawArtifactData(
        artifact_type="json",
        content=raw,
        filename=(
            f"{contract.source_id}-{bas_ym}-p{page_no:03d}-{digest[:12]}.json"
        ),
        request_meta={
            "dataset_id": contract.dataset_id,
            "endpoint": endpoint,
            "basYm": bas_ym,
            "pageNo": page_no,
            "numOfRows": PAGE_SIZE,
        },
        schema_fingerprint=digest,
        source_role="secondary_official",
        trust_level="official_direct",
    )


def _fetch_month(
    client: httpx.Client,
    *,
    contract: SourceContract,
    endpoint: str,
    key: str,
    bas_ym: str,
) -> tuple[list[dict[str, Any]], list[RawArtifactData]]:
    rows: list[dict[str, Any]] = []
    artifacts: list[RawArtifactData] = []
    seen_page_hashes: set[str] = set()
    for page_no in range(1, MAX_PAGES + 1):
        payload, raw = _request_json(
            client,
            endpoint=endpoint,
            key=key,
            bas_ym=bas_ym,
            page_no=page_no,
        )
        artifacts.append(
            _artifact(
                contract=contract,
                endpoint=endpoint,
                bas_ym=bas_ym,
                page_no=page_no,
                raw=raw,
            )
        )
        page_rows = _flatten_items(payload)
        rows.extend(page_rows)
        digest = hashlib.sha256(raw).hexdigest()
        if not page_rows:
            break
        if digest in seen_page_hashes:
            break
        seen_page_hashes.add(digest)

        counts = [
            int(str(value))
            for value in _metadata(payload, "totalCount")
            if str(value).isdigit()
        ]
        if counts and max(counts) <= page_no * PAGE_SIZE:
            break
        if len(page_rows) < PAGE_SIZE and not counts:
            break
    else:
        raise FundingContractError(
            f"{contract.source_id}/{bas_ym}: pagination이 {MAX_PAGES} page를 초과했다"
        )
    return rows, artifacts


def collect_source(
    contract: SourceContract,
    *,
    db_path: Path,
    raw_root: Path,
    periods: int,
    allow_unavailable: bool = False,
) -> SourceResult:
    now = _now()
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        _ensure_source(session, contract, now)
        run = m.CollectionRun(
            source_id=contract.source_id,
            mode="api",
            started_at=now,
            status="running",
            query_context_json={
                "dataset_id": contract.dataset_id,
                "metric": TOTAL_METRIC_CODE,
                "periods": periods,
            },
        )
        session.add(run)
        session.flush()
        run_id = run.id

    fetched_artifacts = parsed_points = stored = unchanged = revisions = mapped = 0
    endpoint = contract.finance_endpoint
    try:
        key = _service_key(contract)
        months = candidate_months(contract, periods)
        with httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "bank-rate-collector/1 institution-funding"},
        ) as client:
            if endpoint is None:
                endpoint = _discover_credit_union_endpoint(client, key, months[0])

            all_artifacts: list[RawArtifactData] = []
            month_rows: list[tuple[str, list[dict[str, Any]]]] = []
            schemas = contract.account_schemas
            for bas_ym in months:
                rows, artifacts = _fetch_month(
                    client,
                    contract=contract,
                    endpoint=endpoint,
                    key=key,
                    bas_ym=bas_ym,
                )
                if contract.sector == "cu" and rows and not schemas:
                    schemas = _infer_credit_union_schema(rows)
                month_rows.append((bas_ym, rows))
                all_artifacts.extend(artifacts)

        with session_scope(factory) as session:
            run = session.get(m.CollectionRun, run_id)
            records = save_raw_artifacts(session, run, all_artifacts, raw_root, now)
            fetched_artifacts = len(all_artifacts)
            artifact_by_month: dict[str, str] = {}
            for artifact, record in zip(all_artifacts, records, strict=True):
                bas_ym = str(artifact.request_meta["basYm"])
                artifact_by_month.setdefault(bas_ym, record.id)

            for bas_ym, rows in month_rows:
                points = parse_points(
                    contract,
                    rows,
                    endpoint=endpoint,
                    account_schemas=schemas,
                ) if rows else []
                parsed_points += len(points)
                raw_id = artifact_by_month.get(bas_ym)
                if points and raw_id is None:
                    raise FundingContractError(
                        f"{contract.source_id}/{bas_ym}: raw artifact provenance가 없다"
                    )
                for point in points:
                    action, is_mapped = _upsert_point(
                        session,
                        point,
                        raw_artifact_id=str(raw_id),
                        now=now,
                    )
                    mapped += int(is_mapped)
                    if action == "stored":
                        stored += 1
                    elif action == "revision":
                        revisions += 1
                    else:
                        unchanged += 1

        status = "success" if parsed_points else "no_change"
        message = (
            f"endpoint={endpoint}; artifacts={fetched_artifacts}; points={parsed_points}; "
            f"stored={stored}; revisions={revisions}; unchanged={unchanged}"
        )
    except FundingSourceUnavailable as exc:
        status = "partial" if allow_unavailable else "failed"
        message = str(exc)
        if not allow_unavailable:
            _finish_run(factory, run_id, status, message, fetched_artifacts, parsed_points)
            raise
    except Exception as exc:
        status = "failed"
        message = str(exc)
        _finish_run(factory, run_id, status, message, fetched_artifacts, parsed_points)
        raise

    _finish_run(factory, run_id, status, message, fetched_artifacts, parsed_points)
    return SourceResult(
        source_id=contract.source_id,
        status=status,
        fetched_artifacts=fetched_artifacts,
        parsed_points=parsed_points,
        stored=stored,
        unchanged=unchanged,
        revisions=revisions,
        mapped=mapped,
        unmapped=max(0, parsed_points - mapped),
        message=message,
    )


def _finish_run(
    factory: Any,
    run_id: str,
    status: str,
    message: str,
    raw_count: int,
    parsed_count: int,
) -> None:
    with session_scope(factory) as session:
        run = session.get(m.CollectionRun, run_id)
        run.status = status
        run.finished_at = _now()
        run.raw_count = raw_count
        run.parsed_count = parsed_count
        run.valid_count = parsed_count if status in {"success", "no_change"} else 0
        run.message = message[:500]


def collect_all(
    *,
    db_path: Path,
    raw_root: Path,
    periods: int,
    allow_unavailable_credit_union: bool = True,
) -> list[SourceResult]:
    results: list[SourceResult] = []
    for contract in CONTRACTS:
        results.append(
            collect_source(
                contract,
                db_path=db_path,
                raw_root=raw_root,
                periods=periods,
                allow_unavailable=(
                    allow_unavailable_credit_union and contract.sector == "cu"
                ),
            )
        )
    return results


def current_counts(db_path: Path) -> dict[str, int]:
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        total = session.scalar(select(func.count()).select_from(InstitutionFundingObservation))
        active = session.scalar(
            select(func.count())
            .select_from(InstitutionFundingObservation)
            .where(InstitutionFundingObservation.valid_to.is_(None))
        )
    return {"total": int(total or 0), "active": int(active or 0)}
