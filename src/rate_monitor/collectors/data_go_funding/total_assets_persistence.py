"""Canonical persistence for validated Data.go total-assets observations.

The existing institution financial-observation table is metric-aware, so no
schema migration is required. This writer deliberately operates on one explicit
reporting month at a time and only for the two source contracts whose asset
schema/aggregate hierarchy have authenticated evidence: savings banks and local
agricultural cooperatives.

Important safety properties:
- aggregate pseudo rows are validated for the *asset* metric before exclusion;
- identity uses the existing exact FSS-code/CRNO source-link path;
- the natural active key includes ``metric_code``, so funding revisions cannot
  be superseded by an asset write;
- content hash includes ``total_assets`` and canonical/source values;
- rerunning an unchanged source month is idempotent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    REQUEST_TIMEOUT,
    FundingContractError,
    SourceContract,
    _ensure_source,
    _finish_run,
    _now,
    _resolve_identity,
    _service_key,
)
from rate_monitor.collectors.data_go_funding.total_assets_evidence import (
    AGRI_COOP_SOURCE_ID,
    NORMALIZED_UNIT,
    SAVINGS_BANK_SOURCE_ID,
    SOURCE_UNIT,
    TOTAL_ASSETS_METRIC_CODE,
    TOTAL_ASSETS_METRIC_NAME,
    TotalAssetsEvidenceError,
    TotalAssetsEvidencePoint,
    parse_total_assets_rows,
    partition_validated_total_assets,
)
from rate_monitor.collectors.data_go_funding.total_assets_transport import fetch_month
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.types import canonical_quantity_text
from rate_monitor.services.collection_service import save_raw_artifacts

OBSERVATION_BASIS = "reported_period_end"
STATEMENT_BASIS = "source_reported_unconsolidated_unspecified"
SUPPORTED_SOURCE_IDS = (SAVINGS_BANK_SOURCE_ID, AGRI_COOP_SOURCE_ID)


@dataclass(frozen=True)
class TotalAssetsPersistResult:
    source_id: str
    source_effective_month: str
    fetched_artifacts: int
    parsed_contract_rows: int
    aggregate_rows_validated: int
    institution_rows: int
    stored: int
    unchanged: int
    revisions: int
    mapped: int
    unmapped: int


def _contract(source_id: str) -> SourceContract:
    if source_id not in SUPPORTED_SOURCE_IDS:
        raise FundingContractError(f"total-assets persistence 미지원 source: {source_id}")
    matches = [contract for contract in CONTRACTS if contract.source_id == source_id]
    if len(matches) != 1:
        raise FundingContractError(
            f"total-assets source contract count 불일치: source={source_id} count={len(matches)}"
        )
    contract = matches[0]
    if not contract.finance_endpoint:
        raise FundingContractError(f"finance endpoint 미확정: {source_id}")
    return contract


def _canonical_bas_ym(value: str) -> str:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 6 or not text.isdigit():
        raise ValueError("bas_ym must be YYYYMM or YYYY-MM")
    month = int(text[4:])
    if not 1 <= month <= 12:
        raise ValueError("bas_ym month must be 01..12")
    return text


def _content_hash(point: TotalAssetsEvidencePoint) -> str:
    payload = "|".join(
        (
            point.source_id,
            point.source_institution_key,
            TOTAL_ASSETS_METRIC_CODE,
            point.source_effective_month,
            point.source_value_text,
            SOURCE_UNIT,
            canonical_quantity_text(point.value),
            NORMALIZED_UNIT,
            point.population_scope,
        )
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _upsert_asset_point(
    session: Any,
    point: TotalAssetsEvidencePoint,
    *,
    raw_artifact_id: str,
    now: datetime,
) -> tuple[str, bool]:
    # _resolve_identity is source-identity logic despite its historical module
    # location. The asset point intentionally carries the same exact source key,
    # official name and CRNO fields as a funding point.
    institution_id, identity_status = _resolve_identity(session, point, now)  # type: ignore[arg-type]
    content_hash = _content_hash(point)
    existing = session.scalars(
        select(InstitutionFundingObservation)
        .where(
            InstitutionFundingObservation.source_id == point.source_id,
            InstitutionFundingObservation.source_institution_key
            == point.source_institution_key,
            InstitutionFundingObservation.metric_code == TOTAL_ASSETS_METRIC_CODE,
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
            metric_code=TOTAL_ASSETS_METRIC_CODE,
            metric_name=TOTAL_ASSETS_METRIC_NAME,
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


def _new_run(factory: Any, contract: SourceContract, *, bas_ym: str) -> str:
    now = _now()
    with session_scope(factory) as session:
        _ensure_source(session, contract, now)
        run = m.CollectionRun(
            source_id=contract.source_id,
            mode="api",
            started_at=now,
            status="running",
            query_context_json={
                "dataset_id": contract.dataset_id,
                "metric": TOTAL_ASSETS_METRIC_CODE,
                "requested_month": bas_ym,
                "checkpoint_unit": "source_month_metric",
            },
        )
        session.add(run)
        session.flush()
        return run.id


def collect_total_assets_source(
    source_id: str,
    *,
    bas_ym: str,
    db_path: Path,
    raw_root: Path,
) -> TotalAssetsPersistResult:
    """Fetch, validate and persist one exact asset source/month."""
    requested = _canonical_bas_ym(bas_ym)
    contract = _contract(source_id)
    assert contract.finance_endpoint is not None

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    run_id = _new_run(factory, contract, bas_ym=requested)
    fetched = parsed = aggregate_count = institution_count = 0
    stored = unchanged = revisions = mapped = 0

    try:
        key = _service_key(contract)
        with httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "bank-rate-collector/1 institution-total-assets"},
        ) as client:
            rows, artifacts = fetch_month(
                client,
                contract=contract,
                endpoint=contract.finance_endpoint,
                key=key,
                bas_ym=requested,
            )
        fetched = len(artifacts)
        if not rows:
            raise FundingContractError(
                f"{source_id}/{requested}: total-assets target table has no rows"
            )
        reported_months = {str(row.get("basYm") or "").strip() for row in rows}
        if reported_months != {requested}:
            raise FundingContractError(
                f"{source_id}/{requested}: basYm filter mismatch reported={sorted(reported_months)}"
            )

        points = parse_total_assets_rows(
            source_id=source_id,
            rows=rows,
            endpoint=contract.finance_endpoint,
        )
        parsed = len(points)
        partitions = partition_validated_total_assets(points)
        if len(partitions) != 1:
            count = len(partitions)
            raise FundingContractError(
                f"{source_id}/{requested}: expected one validated asset partition, got {count}"
            )
        partition = partitions[0]
        aggregate_count = len(partition.aggregate_rows)
        institution_count = len(partition.institution_rows)
        if institution_count == 0:
            raise FundingContractError(
                f"{source_id}/{requested}: validated institution asset rows are empty"
            )

        now = datetime.now(UTC).replace(tzinfo=None)
        with session_scope(factory) as session:
            run = session.get(m.CollectionRun, run_id)
            if run is None:
                raise FundingContractError(f"collection run이 없다: {run_id}")
            records = save_raw_artifacts(session, run, artifacts, raw_root, now)
            if not records:
                raise FundingContractError(
                    f"{source_id}/{requested}: raw artifact provenance가 없다"
                )
            raw_id = records[0].id
            for point in partition.institution_rows:
                action, is_mapped = _upsert_asset_point(
                    session,
                    point,
                    raw_artifact_id=raw_id,
                    now=now,
                )
                mapped += int(is_mapped)
                if action == "stored":
                    stored += 1
                elif action == "revision":
                    revisions += 1
                else:
                    unchanged += 1

        status = "success"
        message = (
            f"metric={TOTAL_ASSETS_METRIC_CODE}; month={requested}; artifacts={fetched}; "
            f"contract_rows={parsed}; aggregate_rows={aggregate_count}; "
            f"institution_rows={institution_count}; stored={stored}; revisions={revisions}; "
            f"unchanged={unchanged}"
        )
    except TotalAssetsEvidenceError as exc:
        status = "failed"
        message = str(exc)
        _finish_run(factory, run_id, status, message, fetched, parsed)
        raise FundingContractError(message) from exc
    except Exception as exc:
        status = "failed"
        message = str(exc)
        _finish_run(factory, run_id, status, message, fetched, parsed)
        raise

    _finish_run(factory, run_id, status, message, fetched, institution_count)
    return TotalAssetsPersistResult(
        source_id=source_id,
        source_effective_month=f"{requested[:4]}-{requested[4:]}",
        fetched_artifacts=fetched,
        parsed_contract_rows=parsed,
        aggregate_rows_validated=aggregate_count,
        institution_rows=institution_count,
        stored=stored,
        unchanged=unchanged,
        revisions=revisions,
        mapped=mapped,
        unmapped=max(0, institution_count - mapped),
    )


def collect_total_assets(
    *,
    bas_ym: str,
    db_path: Path,
    raw_root: Path,
) -> tuple[TotalAssetsPersistResult, ...]:
    """Persist both currently approved total-assets sources for one common month."""
    return tuple(
        collect_total_assets_source(
            source_id,
            bas_ym=bas_ym,
            db_path=db_path,
            raw_root=raw_root,
        )
        for source_id in SUPPORTED_SOURCE_IDS
    )


def active_metric_counts(db_path: Path) -> dict[str, int]:
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        rows = session.execute(
            select(
                InstitutionFundingObservation.metric_code,
                InstitutionFundingObservation.source_id,
            ).where(InstitutionFundingObservation.valid_to.is_(None))
        ).all()
    counts: dict[str, int] = {}
    for metric_code, source_id in rows:
        key = f"{metric_code}:{source_id}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
