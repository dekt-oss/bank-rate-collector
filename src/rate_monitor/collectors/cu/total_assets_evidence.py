"""Read-only CU size-pair evidence from official management disclosures.

This module intentionally does not persist observations or publish R2 state. It reuses the
current-main CU disclosure list, reporting-period selection, and exact ``cuIngno`` identity
contract, then reads ``예수부채`` and ``자산합계`` from the same structured summary page.

When an explicit CU target set is supplied, the collector also binds every institution to its
single active ``deposit_liabilities_total`` observation month. This prevents a newer disclosure
from being paired with an older funding row during production recovery/bootstrap.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from sqlalchemy import select

from rate_monitor.collectors.cu.funding import (
    IDENTITY_STATUS,
    LIST_PAGE_SIZE,
    MAX_LIST_PAGES,
    METRIC_CODE,
    REQUEST_INTERVAL_SECONDS,
    REQUEST_TIMEOUT,
    SOURCE_ID,
    USER_AGENT,
    CuFundingContractError,
    DisclosureRecord,
    _fetch_disclosure_rows,
    _select_latest_disclosures_with_warnings,
    _summary_url,
    _targets,
    extract_table_rows,
)
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.types import quantize_quantity

DEPOSIT_LABEL = "예수부채"
TOTAL_ASSETS_LABEL = "자산합계"
SOURCE_UNIT = "million_krw"
_YEAR = re.compile(r"^\s*(20\d{2})")
_EFFECTIVE_MONTH = re.compile(r"^20\d{2}-(?:06|12)$")


@dataclass(frozen=True)
class CuSizePairEvidence:
    institution_id: str
    cu_ingno: str
    institution_name: str
    source_effective_month: str
    disclosure_no: int
    disclosure_type: str
    deposit_liabilities_total: Decimal
    total_assets: Decimal
    deposit_source_text: str
    total_assets_source_text: str
    source_locator: str
    raw_sha256: str


@dataclass(frozen=True)
class CuSizePairEvidenceResult:
    status: str
    target_count: int
    completed_targets: int
    failed_targets: tuple[str, ...]
    pairs: tuple[CuSizePairEvidence, ...]
    warning_count: int
    message: str


def _normalized_label(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _parse_amount(raw: str, *, label: str) -> Decimal:
    text = raw.strip().replace(",", "")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise CuFundingContractError(f"{label} 금액 변환 실패: {raw!r}") from exc
    if not value.is_finite() or value < 0:
        raise CuFundingContractError(f"{label} 금액은 비음수여야 한다: {raw!r}")
    return quantize_quantity(value)


def parse_summary_size_pair(
    text: str,
    *,
    disclosure: DisclosureRecord,
    institution_id: str,
    institution_name: str,
    source_locator: str,
) -> CuSizePairEvidence:
    """Parse exact deposit-liability and total-assets rows from one CU summary page."""
    cleaned = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(text))).strip()
    if "백만원" not in cleaned:
        raise CuFundingContractError("신협 요약재무현황 단위 '백만원'을 확인하지 못했다")

    rows = extract_table_rows(text)
    header = next(
        (row for row in rows if row and _normalized_label(row[0]) == "구분"),
        None,
    )
    if header is None or len(header) < 3:
        raise CuFundingContractError("신협 요약재무현황 연도 header를 찾지 못했다")
    years = [
        int(match.group(1))
        for cell in header
        for match in [_YEAR.search(cell)]
        if match
    ]
    if not years or years[0] != disclosure.year:
        raise CuFundingContractError(
            "신협 공시연도와 요약재무현황 header 불일치: "
            f"disclosure={disclosure.year} header={years}"
        )

    by_label: dict[str, list[list[str]]] = {DEPOSIT_LABEL: [], TOTAL_ASSETS_LABEL: []}
    for row in rows:
        if not row:
            continue
        label = _normalized_label(row[0])
        if label in by_label:
            by_label[label].append(row)

    values: dict[str, tuple[Decimal, str]] = {}
    for label in (DEPOSIT_LABEL, TOTAL_ASSETS_LABEL):
        matches = by_label[label]
        if len(matches) != 1:
            raise CuFundingContractError(
                f"{label} row는 정확히 1개여야 한다: count={len(matches)}"
            )
        target = matches[0]
        if len(target) < 2:
            raise CuFundingContractError(f"{label} row 금액 cell이 없다: {target}")
        values[label] = (_parse_amount(target[1], label=label), target[1])

    raw = text.encode("utf-8")
    return CuSizePairEvidence(
        institution_id=institution_id,
        cu_ingno=disclosure.cu_ingno,
        institution_name=institution_name,
        source_effective_month=disclosure.source_effective_month,
        disclosure_no=disclosure.disclosure_no,
        disclosure_type=disclosure.disclosure_type,
        deposit_liabilities_total=values[DEPOSIT_LABEL][0],
        total_assets=values[TOTAL_ASSETS_LABEL][0],
        deposit_source_text=values[DEPOSIT_LABEL][1],
        total_assets_source_text=values[TOTAL_ASSETS_LABEL][1],
        source_locator=source_locator,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _write_bytes(root: Path | None, filename: str, content: bytes) -> None:
    if root is None:
        return
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_bytes(content)


def select_disclosure_for_effective_month(
    rows: list[dict[str, object]],
    *,
    cu_ingno: str,
    source_effective_month: str,
) -> tuple[DisclosureRecord, list[str]]:
    """Select exactly one official CU disclosure for a required funding month.

    The list endpoint is fully paginated before this selector runs. Corrections for the same
    reporting period are resolved by the existing highest-``disclosureNo`` policy. A missing
    required month is a contract failure; callers must never silently fall back to the latest
    disclosure because that would break same-period persistence.
    """
    required_month = str(source_effective_month or "").strip()
    if _EFFECTIVE_MONTH.fullmatch(required_month) is None:
        raise CuFundingContractError(
            "신협 Size Peer required funding month 형식 오류: "
            f"cuIngno={cu_ingno} month={source_effective_month!r}"
        )

    disclosures, warnings = _select_latest_disclosures_with_warnings(
        rows,
        cu_ingno=cu_ingno,
        periods=MAX_LIST_PAGES * LIST_PAGE_SIZE,
    )
    matches = [
        disclosure
        for disclosure in disclosures
        if disclosure.source_effective_month == required_month
    ]
    if len(matches) != 1:
        available = sorted(
            {disclosure.source_effective_month for disclosure in disclosures},
            reverse=True,
        )
        raise CuFundingContractError(
            "신협 Size Peer funding month와 일치하는 요약공시는 정확히 1개여야 한다: "
            f"cuIngno={cu_ingno} required={required_month} "
            f"count={len(matches)} available={available}"
        )
    return matches[0], warnings


def _active_funding_months_for_targets(
    factory: object,
    cu_nos: set[str],
) -> dict[str, str]:
    """Load one exact active funding month for each explicitly targeted CU institution."""
    with session_scope(factory) as session:
        observations = list(
            session.scalars(
                select(InstitutionFundingObservation).where(
                    InstitutionFundingObservation.source_id == SOURCE_ID,
                    InstitutionFundingObservation.metric_code == METRIC_CODE,
                    InstitutionFundingObservation.valid_to.is_(None),
                    InstitutionFundingObservation.source_institution_key.in_(cu_nos),
                )
            )
        )

    required: dict[str, str] = {}
    for observation in observations:
        cu_ingno = str(observation.source_institution_key or "").strip()
        if cu_ingno not in cu_nos:
            continue
        if observation.institution_id is None or observation.identity_status != IDENTITY_STATUS:
            raise CuFundingContractError(
                "신협 Size Peer active funding identity 계약 불일치: "
                f"cuIngno={cu_ingno} institution_id={observation.institution_id!r} "
                f"identity_status={observation.identity_status!r}"
            )
        if cu_ingno in required:
            raise CuFundingContractError(
                "신협 Size Peer active funding observation은 기관별 정확히 1개여야 한다: "
                f"cuIngno={cu_ingno}"
            )
        month = str(observation.source_effective_month or "").strip()
        if _EFFECTIVE_MONTH.fullmatch(month) is None:
            raise CuFundingContractError(
                "신협 Size Peer active funding month 형식 오류: "
                f"cuIngno={cu_ingno} month={month!r}"
            )
        required[cu_ingno] = month

    missing = sorted(cu_nos - set(required))
    if missing:
        raise CuFundingContractError(
            "신협 Size Peer active funding observation이 없는 target이 있다: "
            f"{missing}"
        )
    return required


def collect_cu_size_pair_evidence(
    *,
    db_path: Path,
    periods: int = 1,
    only_cu_nos: set[str] | None = None,
    request_interval: float = REQUEST_INTERVAL_SECONDS,
    raw_root: Path | None = None,
) -> CuSizePairEvidenceResult:
    """Fetch CU size-pair evidence without mutating the database or canonical storage.

    If ``only_cu_nos`` is supplied, each requested CU is pinned to the effective month of its
    unique active funding observation. This is the production recovery/bootstrap contract and
    intentionally differs from a generic "latest disclosure" lookup.
    """
    if periods < 1:
        raise ValueError("periods는 1 이상이어야 한다")

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    targets = _targets(factory, only_cu_nos)
    required_months = (
        _active_funding_months_for_targets(factory, set(only_cu_nos))
        if only_cu_nos is not None
        else None
    )
    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    pairs: list[CuSizePairEvidence] = []
    failures: dict[str, str] = {}
    warning_count = 0
    completed = 0

    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for cu_ingno, institution_id, institution_name in targets:
            try:
                rows, artifacts = _fetch_disclosure_rows(
                    client,
                    cu_ingno=cu_ingno,
                    periods=periods,
                    request_interval=request_interval,
                )
                for artifact in artifacts:
                    _write_bytes(raw_root, artifact.filename, artifact.content)

                if required_months is None:
                    disclosures, warnings = _select_latest_disclosures_with_warnings(
                        rows,
                        cu_ingno=cu_ingno,
                        periods=periods,
                    )
                else:
                    disclosure, warnings = select_disclosure_for_effective_month(
                        rows,
                        cu_ingno=cu_ingno,
                        source_effective_month=required_months[cu_ingno],
                    )
                    disclosures = [disclosure]
                warning_count += len(warnings)
                if not disclosures:
                    raise CuFundingContractError(
                        f"정기/반기 요약공시가 없다: cuIngno={cu_ingno}"
                    )

                target_pairs: list[CuSizePairEvidence] = []
                for disclosure in disclosures:
                    if request_interval:
                        time.sleep(request_interval)
                    url = _summary_url(disclosure)
                    response = client.get(url)
                    response.raise_for_status()
                    filename = (
                        f"cu-size-pair-{cu_ingno}-{disclosure.source_effective_month}-"
                        f"{disclosure.disclosure_no}.html"
                    )
                    _write_bytes(raw_root, filename, response.content)
                    target_pairs.append(
                        parse_summary_size_pair(
                            response.text,
                            disclosure=disclosure,
                            institution_id=institution_id,
                            institution_name=institution_name,
                            source_locator=url,
                        )
                    )
                pairs.extend(target_pairs)
                completed += 1
            except (httpx.HTTPError, CuFundingContractError) as exc:
                failures[cu_ingno] = f"{type(exc).__name__}: {exc}"

    status = "success" if not failures else "partial"
    message = (
        f"targets={completed}/{len(targets)} pairs={len(pairs)} "
        f"warnings={warning_count} failures={len(failures)}"
    )
    return CuSizePairEvidenceResult(
        status=status,
        target_count=len(targets),
        completed_targets=completed,
        failed_targets=tuple(sorted(failures)),
        pairs=tuple(pairs),
        warning_count=warning_count,
        message=message,
    )
