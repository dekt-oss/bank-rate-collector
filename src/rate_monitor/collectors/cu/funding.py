"""신협중앙회 경영공시 기반 기관별 수신잔액 수집.

Data.go 신협 재무 API의 exact operation URL은 아직 검증되지 않았다. 대신
금리 collector가 이미 사용하는 신협중앙회 공식 기관키 ``cuIngno``를 seed로
삼아 중앙회 경영공시의 구조화 요약재무현황에서 ``예수부채``를 읽는다.

안전 경계:
- 기관은 기존 active ``cu:<cuIngno>`` SourceEntityLink만 사용한다.
- 이름 유사도나 전국 검색으로 새 기관을 만들지 않는다.
- 공시목록이 요청한 cuIngno만 반환하는지 exact 검증한다.
- 요약공시 제공 대상(``bogoTy=Y``, ``chkYn3=Y``)만 사용한다.
- 요약표 단위 ``백만원``과 행명 ``예수부채``를 exact 검증한다.
- PDF/OCR을 사용하지 않는다.
- 값이 같으면 새 observation을 만들지 않고, 값이 바뀔 때만 revision을 만든다.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.types import canonical_quantity_text, quantize_quantity
from rate_monitor.domain.schemas import RawArtifactData
from rate_monitor.domain.timeutil import kst_path_stamp
from rate_monitor.services.collection_service import save_raw_artifacts

SOURCE_ID = "cu_disclosure_funding"
SOURCE_NAME = "신협중앙회 경영공시 요약재무현황"
RATE_SOURCE_ID = "cu"
SECTOR = "cu"
METRIC_CODE = "deposit_liabilities_total"
METRIC_NAME = "예수부채"
SOURCE_UNIT = "million_krw"
NORMALIZED_UNIT = "million_krw"
OBSERVATION_BASIS = "summary_disclosure_period_end"
STATEMENT_BASIS = "source_reported_summary_disclosure"
POPULATION_SCOPE = "credit_unions_current_rate_directory_with_disclosure_history"
IDENTITY_STATUS = "mapped_exact_cu_ingno"

BASE = "https://www.cu.co.kr"
LIST_PATH = "/cu/ad/dis/getDisclosureList.do"
SUMMARY_PATH = "/GSSP020000.do"
BASE_REFERENCE = f"{BASE}/cu/ad/disclosureList.do?mi=100518"
USER_AGENT = "rate-monitor/1 (+public CU management-disclosure funding collector)"
REQUEST_TIMEOUT = 25.0
REQUEST_INTERVAL_SECONDS = 1.0
MAX_LIST_PAGES = 20
LIST_PAGE_SIZE = 10

_TAG = re.compile(r"<[^>]+>")
_TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
_CELL = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)
_YEAR = re.compile(r"^\s*(20\d{2})(?:\s*년(?:도)?|\s*회계연도)?")


class CuFundingContractError(RuntimeError):
    """신협 경영공시의 검증된 source contract가 깨졌다."""


@dataclass(frozen=True)
class DisclosureRecord:
    cu_ingno: str
    disclosure_no: int
    disclosure_type: str
    disclosure_name: str
    reg_date: str
    short_file_name: str
    year: int
    month: int

    @property
    def source_effective_month(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass(frozen=True)
class CuFundingPoint:
    institution_id: str
    cu_ingno: str
    institution_name: str
    source_effective_month: str
    period_start: date
    period_end: date
    value: Decimal
    source_value_text: str
    disclosure_no: int
    disclosure_type: str
    source_locator: str


@dataclass(frozen=True)
class CuFundingCollectionResult:
    status: str
    run_id: str
    target_count: int
    completed_targets: int
    failed_targets: tuple[str, ...]
    fetched_artifacts: int
    parsed_points: int
    stored: int
    unchanged: int
    revisions: int
    message: str


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean_cell(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", html.unescape(text))).strip()


def _normalized_label(text: str) -> str:
    return re.sub(r"\s+", "", text)


def extract_table_rows(text: str) -> list[list[str]]:
    """구조화 요약공시 HTML의 표를 순서대로 text cell 목록으로 바꾼다."""
    rows: list[list[str]] = []
    for tr in _TR.finditer(text):
        cells = [_clean_cell(match.group(1)) for match in _CELL.finditer(tr.group(1))]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)
    return rows


def _record_from_row(row: dict[str, Any], expected_cu: str) -> DisclosureRecord | None:
    cu_ingno = str(row.get("cuIngno") or "").strip()
    if cu_ingno != expected_cu:
        raise CuFundingContractError(
            f"신협 공시목록 identity 불일치: requested={expected_cu} returned={cu_ingno!r}"
        )
    disclosure_type = str(row.get("disclosureTy") or "").strip()
    if disclosure_type not in {"1", "2"}:
        return None
    if str(row.get("bogoTy") or "").strip() != "Y":
        return None
    if str(row.get("chkYn3") or "").strip() != "Y":
        return None
    short_file_name = str(row.get("shortFileName") or "").strip()
    if not short_file_name:
        return None
    name = str(row.get("disclosureName") or "").strip()
    match = _YEAR.search(name)
    if match is None:
        raise CuFundingContractError(f"공시명에서 연도를 읽을 수 없다: {name!r}")
    year = int(match.group(1))
    month = 12 if disclosure_type == "1" else 6
    raw_no = str(row.get("disclosureNo") or "").strip()
    if not raw_no.isdigit():
        raise CuFundingContractError(f"disclosureNo 형식 오류: {raw_no!r}")
    return DisclosureRecord(
        cu_ingno=cu_ingno,
        disclosure_no=int(raw_no),
        disclosure_type=disclosure_type,
        disclosure_name=name,
        reg_date=str(row.get("regDate") or "").strip(),
        short_file_name=short_file_name,
        year=year,
        month=month,
    )


def select_latest_disclosures(
    rows: list[dict[str, Any]],
    *,
    cu_ingno: str,
    periods: int,
) -> list[DisclosureRecord]:
    """정기/반기 요약공시를 reporting period별 한 건으로 결정론적으로 고른다."""
    if periods < 1:
        raise ValueError("periods는 1 이상이어야 한다")
    candidates = [
        record
        for row in rows
        if (record := _record_from_row(row, cu_ingno)) is not None
    ]
    by_period: dict[str, DisclosureRecord] = {}
    for record in candidates:
        prior = by_period.get(record.source_effective_month)
        if prior is None or record.disclosure_no > prior.disclosure_no:
            by_period[record.source_effective_month] = record
    return sorted(
        by_period.values(),
        key=lambda record: (record.year, record.month, record.disclosure_no),
        reverse=True,
    )[:periods]


def _parse_amount(raw: str) -> Decimal:
    text = raw.strip().replace(",", "")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise CuFundingContractError(f"예수부채 금액 변환 실패: {raw!r}") from exc
    if not value.is_finite() or value < 0:
        raise CuFundingContractError(f"예수부채 금액은 비음수여야 한다: {raw!r}")
    return quantize_quantity(value)


def parse_summary_point(
    text: str,
    *,
    disclosure: DisclosureRecord,
    institution_id: str,
    institution_name: str,
    source_locator: str,
) -> CuFundingPoint:
    """요약재무현황에서 해당 공시기간의 현재연도 예수부채 한 건만 읽는다."""
    cleaned = re.sub(r"\s+", " ", _TAG.sub(" ", html.unescape(text))).strip()
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

    targets = [row for row in rows if row and _normalized_label(row[0]) == METRIC_NAME]
    if len(targets) != 1:
        raise CuFundingContractError(
            f"예수부채 row는 정확히 1개여야 한다: count={len(targets)}"
        )
    target = targets[0]
    if len(target) < 2:
        raise CuFundingContractError(f"예수부채 row 금액 cell이 없다: {target}")
    value = _parse_amount(target[1])

    last = calendar.monthrange(disclosure.year, disclosure.month)[1]
    return CuFundingPoint(
        institution_id=institution_id,
        cu_ingno=disclosure.cu_ingno,
        institution_name=institution_name,
        source_effective_month=disclosure.source_effective_month,
        period_start=date(disclosure.year, disclosure.month, 1),
        period_end=date(disclosure.year, disclosure.month, last),
        value=value,
        source_value_text=target[1],
        disclosure_no=disclosure.disclosure_no,
        disclosure_type=disclosure.disclosure_type,
        source_locator=source_locator,
    )


def _list_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("list", "data", "items", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    raise CuFundingContractError(
        f"신협 공시목록 JSON shape 불일치: {type(payload).__name__}"
    )


def _artifact(
    *,
    content: bytes,
    filename: str,
    request_meta: dict[str, Any],
    artifact_type: str,
) -> RawArtifactData:
    return RawArtifactData(
        artifact_type=artifact_type,
        content=content,
        filename=filename,
        request_meta=request_meta,
        schema_fingerprint=hashlib.sha256(content).hexdigest(),
        source_role="primary_official",
        trust_level="official_direct",
    )


def _fetch_disclosure_rows(
    client: httpx.Client,
    *,
    cu_ingno: str,
    periods: int,
    request_interval: float,
) -> tuple[list[dict[str, Any]], list[RawArtifactData]]:
    all_rows: list[dict[str, Any]] = []
    artifacts: list[RawArtifactData] = []
    declared_total: int | None = None

    for page in range(1, MAX_LIST_PAGES + 1):
        body = {
            "usrId": cu_ingno,
            "currPage": str(page),
            "srchVal": "",
            "btnChk": "N",
        }
        response = client.post(f"{BASE}{LIST_PATH}", data=body)
        response.raise_for_status()
        raw = response.content
        try:
            payload = response.json()
        except ValueError as exc:
            raise CuFundingContractError("신협 공시목록이 JSON이 아니다") from exc
        rows = _list_rows(payload)
        for row in rows:
            returned = str(row.get("cuIngno") or "").strip()
            if returned != cu_ingno:
                raise CuFundingContractError(
                    "신협 공시목록 identity 불일치: "
                    f"requested={cu_ingno} returned={returned!r}"
                )

        page_totals = {
            int(str(row.get("listTotalCount")))
            for row in rows
            if str(row.get("listTotalCount") or "").isdigit()
        }
        if len(page_totals) > 1:
            raise CuFundingContractError(
                f"신협 공시목록 totalCount가 한 페이지 안에서 다르다: {sorted(page_totals)}"
            )
        if page_totals:
            page_total = next(iter(page_totals))
            if declared_total is None:
                declared_total = page_total
            elif declared_total != page_total:
                raise CuFundingContractError(
                    "신협 공시목록 totalCount가 페이지 사이에서 바뀌었다: "
                    f"expected={declared_total} actual={page_total}"
                )
        artifacts.append(
            _artifact(
                content=raw,
                filename=f"cu-funding-{cu_ingno}-list-p{page:02d}.json",
                request_meta={
                    "kind": "disclosure_list",
                    "cuIngno": cu_ingno,
                    "page": page,
                    "endpoint": f"{BASE}{LIST_PATH}",
                },
                artifact_type="json",
            )
        )
        all_rows.extend(rows)
        if declared_total is not None:
            if len(all_rows) > declared_total:
                raise CuFundingContractError(
                    "신협 공시목록 row 수가 declared total을 초과했다: "
                    f"rows={len(all_rows)} total={declared_total}"
                )
            if len(all_rows) == declared_total:
                break
        if not rows:
            break
        if declared_total is None and len(rows) < LIST_PAGE_SIZE:
            break
        if request_interval:
            time.sleep(request_interval)
    else:
        raise CuFundingContractError(
            f"신협 공시목록 pagination이 {MAX_LIST_PAGES} page를 초과했다: {cu_ingno}"
        )

    if declared_total is not None and len(all_rows) != declared_total:
        raise CuFundingContractError(
            "신협 공시목록 pagination 미완료: "
            f"rows={len(all_rows)} total={declared_total} cuIngno={cu_ingno}"
        )
    return all_rows, artifacts


def _summary_url(disclosure: DisclosureRecord) -> str:
    params = urllib.parse.urlencode(
        {
            "cu_ingno": disclosure.cu_ingno,
            "busi_ty": "610",
            "disclosure_no": str(disclosure.disclosure_no),
            "disclosure_ty": disclosure.disclosure_type,
        }
    )
    return f"{BASE}{SUMMARY_PATH}?{params}"


def _fetch_target(
    client: httpx.Client,
    *,
    cu_ingno: str,
    institution_id: str,
    institution_name: str,
    periods: int,
    request_interval: float,
) -> tuple[list[CuFundingPoint], list[RawArtifactData], dict[int, int]]:
    rows, artifacts = _fetch_disclosure_rows(
        client,
        cu_ingno=cu_ingno,
        periods=periods,
        request_interval=request_interval,
    )
    disclosures = select_latest_disclosures(
        rows,
        cu_ingno=cu_ingno,
        periods=periods,
    )
    if not disclosures:
        raise CuFundingContractError(f"정기/반기 요약공시가 없다: cuIngno={cu_ingno}")

    points: list[CuFundingPoint] = []
    summary_artifact_index: dict[int, int] = {}
    for disclosure in disclosures:
        if request_interval:
            time.sleep(request_interval)
        url = _summary_url(disclosure)
        response = client.get(url)
        response.raise_for_status()
        raw = response.content
        point = parse_summary_point(
            response.text,
            disclosure=disclosure,
            institution_id=institution_id,
            institution_name=institution_name,
            source_locator=url,
        )
        summary_artifact_index[disclosure.disclosure_no] = len(artifacts)
        artifacts.append(
            _artifact(
                content=raw,
                filename=(
                    f"cu-funding-{cu_ingno}-{point.source_effective_month}-"
                    f"{disclosure.disclosure_no}.html"
                ),
                request_meta={
                    "kind": "summary_disclosure",
                    "cuIngno": cu_ingno,
                    "disclosure_no": disclosure.disclosure_no,
                    "disclosure_type": disclosure.disclosure_type,
                    "source_effective_month": point.source_effective_month,
                    "endpoint": url,
                },
                artifact_type="html",
            )
        )
        points.append(point)
    return points, artifacts, summary_artifact_index


def _ensure_source(session: Any, now: datetime) -> None:
    source = session.get(m.Source, SOURCE_ID)
    if source is None:
        session.add(
            m.Source(
                id=SOURCE_ID,
                name=SOURCE_NAME,
                sector=SECTOR,
                mode="http",
                source_role="primary_official",
                trust_level="official_direct",
                priority=10,
                base_reference=BASE_REFERENCE,
                enabled=True,
                schedule_cron=None,
                policy_status="review",
                coverage_status="partial",
                parser_version="1.0.0",
                created_at=now,
                updated_at=now,
            )
        )
    else:
        source.updated_at = now


def _targets(
    factory: Any,
    only_cu_nos: set[str] | None,
) -> list[tuple[str, str, str]]:
    with session_scope(factory) as session:
        links = list(
            session.scalars(
                select(m.SourceEntityLink).where(
                    m.SourceEntityLink.source_id == RATE_SOURCE_ID,
                    m.SourceEntityLink.entity_type == "institution",
                    m.SourceEntityLink.valid_to.is_(None),
                )
            )
        )
        targets: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for link in links:
            prefix = f"{SECTOR}:"
            if not link.source_entity_key.startswith(prefix):
                continue
            cu_ingno = link.source_entity_key.removeprefix(prefix).strip()
            if not cu_ingno:
                continue
            if only_cu_nos is not None and cu_ingno not in only_cu_nos:
                continue
            if cu_ingno in seen:
                raise CuFundingContractError(f"active CU link가 중복됐다: {cu_ingno}")
            institution = session.get(m.Institution, link.entity_id)
            if institution is None or institution.sector != SECTOR:
                raise CuFundingContractError(
                    f"CU link 대상 institution 계약 불일치: {cu_ingno} -> {link.entity_id}"
                )
            name = str(link.source_name or institution.canonical_name).strip()
            if not name:
                raise CuFundingContractError(f"CU institution name이 비어 있다: {cu_ingno}")
            targets.append((cu_ingno, institution.id, name))
            seen.add(cu_ingno)
    targets.sort(key=lambda row: row[0])
    if only_cu_nos is not None:
        missing = sorted(only_cu_nos - {row[0] for row in targets})
        if missing:
            raise CuFundingContractError(f"active CU source link가 없다: {missing}")
    if not targets:
        raise CuFundingContractError("수집할 active CU institution link가 없다")
    return targets


def _save_artifacts_reusing_run(
    *,
    session: Any,
    run: m.CollectionRun,
    artifacts: list[RawArtifactData],
    raw_root: Path,
    now: datetime,
) -> list[m.RawArtifact]:
    saved: list[m.RawArtifact] = []
    for artifact in artifacts:
        digest = hashlib.sha256(artifact.content).hexdigest()
        existing = session.scalar(
            select(m.RawArtifact).where(
                m.RawArtifact.run_id == run.id,
                m.RawArtifact.sha256 == digest,
            )
        )
        if existing is None:
            saved.extend(save_raw_artifacts(session, run, [artifact], raw_root, now))
            continue
        day_dir = raw_root / kst_path_stamp(now) / run.id
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / artifact.filename).write_bytes(artifact.content)
        meta = dict(existing.request_meta_json or {})
        shared = list(meta.get("shared_requests", []))
        if artifact.request_meta not in shared:
            shared.append(dict(artifact.request_meta))
        meta["shared_requests"] = shared
        existing.request_meta_json = meta
        saved.append(existing)
    session.flush()
    return saved


def _content_hash(point: CuFundingPoint) -> str:
    payload = "|".join(
        (
            SOURCE_ID,
            point.cu_ingno,
            METRIC_CODE,
            point.source_effective_month,
            canonical_quantity_text(point.value),
            SOURCE_UNIT,
            NORMALIZED_UNIT,
            POPULATION_SCOPE,
            STATEMENT_BASIS,
        )
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _upsert_point(
    session: Any,
    point: CuFundingPoint,
    *,
    raw_artifact_id: str,
    now: datetime,
) -> str:
    content_hash = _content_hash(point)
    existing = session.scalars(
        select(InstitutionFundingObservation)
        .where(
            InstitutionFundingObservation.source_id == SOURCE_ID,
            InstitutionFundingObservation.source_institution_key == point.cu_ingno,
            InstitutionFundingObservation.metric_code == METRIC_CODE,
            InstitutionFundingObservation.source_effective_month
            == point.source_effective_month,
            InstitutionFundingObservation.valid_to.is_(None),
        )
        .order_by(InstitutionFundingObservation.revision.desc())
    ).first()
    if existing is not None and existing.content_hash == content_hash:
        if existing.institution_id != point.institution_id:
            raise CuFundingContractError(
                "CU funding identity conflict on unchanged value: "
                f"{point.cu_ingno}/{point.source_effective_month} "
                f"{existing.institution_id} != {point.institution_id}"
            )
        return "unchanged"

    revision = 1
    if existing is not None:
        if existing.institution_id != point.institution_id:
            raise CuFundingContractError(
                "CU funding identity conflict on revision: "
                f"{point.cu_ingno}/{point.source_effective_month}"
            )
        existing.valid_to = now
        revision = existing.revision + 1

    session.add(
        InstitutionFundingObservation(
            institution_id=point.institution_id,
            source_id=SOURCE_ID,
            source_institution_key=point.cu_ingno,
            source_institution_name=point.institution_name,
            source_crno=None,
            sector=SECTOR,
            metric_code=METRIC_CODE,
            metric_name=METRIC_NAME,
            source_effective_month=point.source_effective_month,
            period_start=point.period_start,
            period_end=point.period_end,
            value=point.value,
            unit=NORMALIZED_UNIT,
            source_value_text=point.source_value_text,
            source_unit=SOURCE_UNIT,
            observation_basis=OBSERVATION_BASIS,
            statement_basis=STATEMENT_BASIS,
            population_scope=POPULATION_SCOPE,
            identity_status=IDENTITY_STATUS,
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
    return "revision" if existing is not None else "stored"


def collect_cu_disclosure_funding(
    *,
    db_path: Path,
    raw_root: Path,
    periods: int,
    only_cu_nos: set[str] | None = None,
    request_interval: float = REQUEST_INTERVAL_SECONDS,
) -> CuFundingCollectionResult:
    """기존 CU exact links를 seed로 latest N 정기/반기 수신잔액을 수집한다."""
    if periods < 1:
        raise ValueError("periods는 1 이상이어야 한다")
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    targets = _targets(factory, only_cu_nos)
    now = _now()
    with session_scope(factory) as session:
        _ensure_source(session, now)
        run = m.CollectionRun(
            source_id=SOURCE_ID,
            mode="http",
            started_at=now,
            status="running",
            query_context_json={
                "metric": METRIC_CODE,
                "periods": periods,
                "target_count": len(targets),
                "identity_seed": "active cu SourceEntityLink exact cuIngno",
                "checkpoint_unit": "institution",
            },
        )
        session.add(run)
        session.flush()
        run_id = run.id

    fetched = parsed = stored = unchanged = revisions = 0
    completed = 0
    failures: dict[str, str] = {}
    timeout = httpx.Timeout(REQUEST_TIMEOUT)

    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for cu_ingno, institution_id, institution_name in targets:
            try:
                points, artifacts, summary_index = _fetch_target(
                    client,
                    cu_ingno=cu_ingno,
                    institution_id=institution_id,
                    institution_name=institution_name,
                    periods=periods,
                    request_interval=request_interval,
                )
                target_now = _now()
                with session_scope(factory) as session:
                    run = session.get(m.CollectionRun, run_id)
                    if run is None:
                        raise CuFundingContractError(f"collection run이 없다: {run_id}")
                    records = _save_artifacts_reusing_run(
                        session=session,
                        run=run,
                        artifacts=artifacts,
                        raw_root=raw_root,
                        now=target_now,
                    )
                    for point in points:
                        artifact_index = summary_index.get(point.disclosure_no)
                        if artifact_index is None or artifact_index >= len(records):
                            raise CuFundingContractError(
                                "summary raw provenance가 없다: "
                                f"{cu_ingno}/{point.disclosure_no}"
                            )
                        action = _upsert_point(
                            session,
                            point,
                            raw_artifact_id=records[artifact_index].id,
                            now=target_now,
                        )
                        if action == "stored":
                            stored += 1
                        elif action == "revision":
                            revisions += 1
                        else:
                            unchanged += 1
                fetched += len(artifacts)
                parsed += len(points)
                completed += 1
            except (httpx.HTTPError, CuFundingContractError) as exc:
                failures[cu_ingno] = f"{type(exc).__name__}: {exc}"
                print(
                    f"CU funding target failed cuIngno={cu_ingno}: {failures[cu_ingno]}",
                    flush=True,
                )

    status = "success" if not failures else "partial"
    message = (
        f"targets={completed}/{len(targets)} points={parsed} stored={stored} "
        f"revisions={revisions} unchanged={unchanged} failures={len(failures)}"
    )
    with session_scope(factory) as session:
        run = session.get(m.CollectionRun, run_id)
        if run is None:
            raise CuFundingContractError(f"collection run이 없다: {run_id}")
        run.status = status
        run.finished_at = _now()
        run.raw_count = fetched
        run.parsed_count = parsed
        run.valid_count = parsed if not failures else 0
        run.error_count = len(failures)
        run.message = message[:500]

    return CuFundingCollectionResult(
        status=status,
        run_id=run_id,
        target_count=len(targets),
        completed_targets=completed,
        failed_targets=tuple(sorted(failures)),
        fetched_artifacts=fetched,
        parsed_points=parsed,
        stored=stored,
        unchanged=unchanged,
        revisions=revisions,
        message=message,
    )
