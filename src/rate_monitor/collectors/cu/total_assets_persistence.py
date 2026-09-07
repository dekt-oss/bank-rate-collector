"""Candidate persistence for CU total-assets observations.

The writer is deliberately separate from the read-only source evidence module.
It accepts already authenticated same-disclosure size pairs, revalidates the exact
``cu:<cuIngno>`` canonical link and the existing deposit-liability observation for
the same reporting month, then writes only ``total_assets`` under the existing
``cu_disclosure_funding`` source.

Nothing in this module uploads canonical storage or schedules collection.
"""

from __future__ import annotations

import calendar
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from rate_monitor.collectors.cu.funding import (
    IDENTITY_STATUS,
    METRIC_CODE,
    NORMALIZED_UNIT,
    OBSERVATION_BASIS,
    POPULATION_SCOPE,
    SECTOR,
    SOURCE_ID,
    SOURCE_UNIT,
    STATEMENT_BASIS,
    CuFundingContractError,
    _artifact,
    _ensure_source,
    _now,
    _targets,
)
from rate_monitor.collectors.cu.total_assets_evidence import CuSizePairEvidence
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.types import canonical_quantity_text
from rate_monitor.services.collection_service import save_raw_artifacts

TOTAL_ASSETS_METRIC_CODE = "total_assets"
TOTAL_ASSETS_METRIC_NAME = "자산합계"


@dataclass(frozen=True)
class CuTotalAssetsPersistResult:
    status: str
    run_id: str
    target_count: int
    stored: int
    unchanged: int
    revisions: int
    message: str


def _period_bounds(source_effective_month: str) -> tuple[date, date]:
    text = str(source_effective_month or "").strip()
    if len(text) != 7 or text[4] != "-" or not text[:4].isdigit() or not text[5:].isdigit():
        raise CuFundingContractError(
            f"CU total-assets source_effective_month 형식 오류: {source_effective_month!r}"
        )
    year = int(text[:4])
    month = int(text[5:])
    if not 1 <= month <= 12:
        raise CuFundingContractError(
            f"CU total-assets source_effective_month 월 오류: {source_effective_month!r}"
        )
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _content_hash(pair: CuSizePairEvidence) -> str:
    payload = "|".join(
        (
            SOURCE_ID,
            pair.cu_ingno,
            TOTAL_ASSETS_METRIC_CODE,
            pair.source_effective_month,
            canonical_quantity_text(pair.total_assets),
            pair.total_assets_source_text,
            SOURCE_UNIT,
            NORMALIZED_UNIT,
            POPULATION_SCOPE,
            STATEMENT_BASIS,
        )
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_matching_funding(
    session,
    pair: CuSizePairEvidence,
) -> InstitutionFundingObservation:
    rows = list(
        session.scalars(
            select(InstitutionFundingObservation).where(
                InstitutionFundingObservation.source_id == SOURCE_ID,
                InstitutionFundingObservation.source_institution_key == pair.cu_ingno,
                InstitutionFundingObservation.metric_code == METRIC_CODE,
                InstitutionFundingObservation.source_effective_month
                == pair.source_effective_month,
                InstitutionFundingObservation.valid_to.is_(None),
            )
        )
    )
    if len(rows) != 1:
        raise CuFundingContractError(
            "CU total-assets same-period funding observation은 정확히 1개여야 한다: "
            f"cuIngno={pair.cu_ingno} month={pair.source_effective_month} count={len(rows)}"
        )
    funding = rows[0]
    if funding.institution_id != pair.institution_id:
        raise CuFundingContractError(
            "CU total-assets funding identity 불일치: "
            f"cuIngno={pair.cu_ingno} pair={pair.institution_id} "
            f"funding={funding.institution_id}"
        )
    if funding.identity_status != IDENTITY_STATUS:
        raise CuFundingContractError(
            "CU total-assets funding identity_status 불일치: "
            f"cuIngno={pair.cu_ingno} status={funding.identity_status!r}"
        )
    if funding.value != pair.deposit_liabilities_total:
        raise CuFundingContractError(
            "CU total-assets same-disclosure deposit 값 불일치: "
            f"cuIngno={pair.cu_ingno} month={pair.source_effective_month} "
            f"stored={funding.value} disclosure={pair.deposit_liabilities_total}"
        )
    return funding


def _upsert_asset(
    session,
    pair: CuSizePairEvidence,
    *,
    raw_artifact_id: str,
    now: datetime,
) -> str:
    _require_matching_funding(session, pair)
    period_start, period_end = _period_bounds(pair.source_effective_month)
    content_hash = _content_hash(pair)
    existing = session.scalars(
        select(InstitutionFundingObservation)
        .where(
            InstitutionFundingObservation.source_id == SOURCE_ID,
            InstitutionFundingObservation.source_institution_key == pair.cu_ingno,
            InstitutionFundingObservation.metric_code == TOTAL_ASSETS_METRIC_CODE,
            InstitutionFundingObservation.source_effective_month
            == pair.source_effective_month,
            InstitutionFundingObservation.valid_to.is_(None),
        )
        .order_by(InstitutionFundingObservation.revision.desc())
    ).first()

    if existing is not None and existing.content_hash == content_hash:
        if existing.institution_id != pair.institution_id:
            raise CuFundingContractError(
                "CU total-assets unchanged identity conflict: "
                f"cuIngno={pair.cu_ingno} month={pair.source_effective_month}"
            )
        return "unchanged"

    revision = 1
    if existing is not None:
        if existing.institution_id != pair.institution_id:
            raise CuFundingContractError(
                "CU total-assets revision identity conflict: "
                f"cuIngno={pair.cu_ingno} month={pair.source_effective_month}"
            )
        existing.valid_to = now
        revision = existing.revision + 1

    session.add(
        InstitutionFundingObservation(
            institution_id=pair.institution_id,
            source_id=SOURCE_ID,
            source_institution_key=pair.cu_ingno,
            source_institution_name=pair.institution_name,
            source_crno=None,
            sector=SECTOR,
            metric_code=TOTAL_ASSETS_METRIC_CODE,
            metric_name=TOTAL_ASSETS_METRIC_NAME,
            source_effective_month=pair.source_effective_month,
            period_start=period_start,
            period_end=period_end,
            value=pair.total_assets,
            unit=NORMALIZED_UNIT,
            source_value_text=pair.total_assets_source_text,
            source_unit=SOURCE_UNIT,
            observation_basis=OBSERVATION_BASIS,
            statement_basis=STATEMENT_BASIS,
            population_scope=POPULATION_SCOPE,
            identity_status=IDENTITY_STATUS,
            observed_at=now,
            source_locator=pair.source_locator,
            raw_artifact_id=raw_artifact_id,
            content_hash=content_hash,
            revision=revision,
            valid_from=now,
            valid_to=None,
            created_at=now,
        )
    )
    return "revision" if existing is not None else "stored"


def persist_cu_total_assets_pairs(
    *,
    db_path: Path,
    evidence_raw_root: Path,
    artifact_root: Path,
    pairs: Iterable[CuSizePairEvidence],
) -> CuTotalAssetsPersistResult:
    """Persist validated CU total-assets pairs into a candidate database.

    The caller controls whether the candidate is ever published. This function
    never calls the storage service and never mutates deposit observations.
    """
    ordered = tuple(sorted(pairs, key=lambda pair: (pair.cu_ingno, pair.source_effective_month)))
    if not ordered:
        raise CuFundingContractError("CU total-assets persistence pair가 비어 있다")

    keys = [pair.cu_ingno for pair in ordered]
    if len(set(keys)) != len(keys):
        raise CuFundingContractError(f"CU total-assets persistence cuIngno 중복: {keys}")

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    resolved = {
        cu_ingno: (institution_id, name)
        for cu_ingno, institution_id, name in _targets(factory, set(keys))
    }
    for pair in ordered:
        target = resolved.get(pair.cu_ingno)
        if target is None or target[0] != pair.institution_id:
            raise CuFundingContractError(
                "CU total-assets exact link identity 불일치: "
                f"cuIngno={pair.cu_ingno} pair={pair.institution_id} target={target}"
            )

    now = _now()
    with session_scope(factory) as session:
        _ensure_source(session, now)
        run = m.CollectionRun(
            source_id=SOURCE_ID,
            mode="http",
            started_at=now,
            status="running",
            query_context_json={
                "metric": TOTAL_ASSETS_METRIC_CODE,
                "target_count": len(ordered),
                "identity_seed": "active cu SourceEntityLink exact cuIngno",
                "evidence": "same-disclosure deposit + total-assets pair",
                "candidate_only": True,
            },
        )
        session.add(run)
        session.flush()
        run_id = run.id

    stored = unchanged = revisions = 0
    try:
        for pair in ordered:
            filename = (
                f"cu-size-pair-{pair.cu_ingno}-{pair.source_effective_month}-"
                f"{pair.disclosure_no}.html"
            )
            source_file = evidence_raw_root / filename
            if not source_file.is_file():
                raise CuFundingContractError(f"CU total-assets raw evidence가 없다: {source_file}")
            content = source_file.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != pair.raw_sha256:
                raise CuFundingContractError(
                    "CU total-assets raw SHA256 불일치: "
                    f"cuIngno={pair.cu_ingno} expected={pair.raw_sha256} actual={digest}"
                )

            target_now = _now()
            with session_scope(factory) as session:
                run = session.get(m.CollectionRun, run_id)
                if run is None:
                    raise CuFundingContractError(f"collection run이 없다: {run_id}")
                artifact = _artifact(
                    content=content,
                    filename=filename,
                    request_meta={
                        "kind": "summary_disclosure_size_pair",
                        "cuIngno": pair.cu_ingno,
                        "disclosure_no": pair.disclosure_no,
                        "disclosure_type": pair.disclosure_type,
                        "source_effective_month": pair.source_effective_month,
                        "endpoint": pair.source_locator,
                        "candidate_only": True,
                    },
                    artifact_type="html",
                )
                records = save_raw_artifacts(
                    session,
                    run,
                    [artifact],
                    artifact_root,
                    target_now,
                )
                if len(records) != 1:
                    raise CuFundingContractError(
                        f"CU total-assets raw artifact 저장 수 불일치: {len(records)}"
                    )
                action = _upsert_asset(
                    session,
                    pair,
                    raw_artifact_id=records[0].id,
                    now=target_now,
                )
                if action == "stored":
                    stored += 1
                elif action == "revision":
                    revisions += 1
                else:
                    unchanged += 1
        status = "success"
        message = (
            f"targets={len(ordered)} stored={stored} revisions={revisions} "
            f"unchanged={unchanged} candidate_only=true"
        )
    except Exception as exc:
        status = "failed"
        message = f"{type(exc).__name__}: {exc}"
        with session_scope(factory) as session:
            run = session.get(m.CollectionRun, run_id)
            if run is not None:
                run.status = status
                run.finished_at = _now()
                run.error_count = 1
                run.message = message[:500]
        raise

    with session_scope(factory) as session:
        run = session.get(m.CollectionRun, run_id)
        if run is None:
            raise CuFundingContractError(f"collection run이 없다: {run_id}")
        run.status = status
        run.finished_at = _now()
        run.parsed_count = len(ordered)
        run.valid_count = len(ordered)
        run.error_count = 0
        run.message = message[:500]

    return CuTotalAssetsPersistResult(
        status=status,
        run_id=run_id,
        target_count=len(ordered),
        stored=stored,
        unchanged=unchanged,
        revisions=revisions,
        message=message,
    )
