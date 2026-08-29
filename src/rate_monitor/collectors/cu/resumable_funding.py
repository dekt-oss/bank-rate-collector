"""Durable institution-level checkpointing for CU disclosure funding.

The checkpoint contains one immutable staging bundle per ``cuIngno``.  Bundles
preserve exact official list/summary response bytes, but they are *not* canonical
raw rows.  Canonical persistence happens only after the whole work plan is
complete and every bundle is reparsed against the current source contract.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from rate_monitor.collectors.cu.funding import (
    REQUEST_INTERVAL_SECONDS,
    REQUEST_TIMEOUT,
    SOURCE_ID,
    USER_AGENT,
    CuFundingContractError,
    CuFundingPoint,
    _ensure_source,
    _fetch_target,
    _list_rows,
    _parse_summary_with_history_policy,
    _save_artifacts_reusing_run,
    _select_latest_disclosures_with_warnings,
    _targets,
    _upsert_point,
)
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.schemas import RawArtifactData
from rate_monitor.services.resumable_acquisition import (
    AcquisitionManifest,
    AcquisitionSessionIdentity,
    CheckpointArtifact,
    CheckpointIncompatibleError,
    ResumableAcquisitionService,
    canonical_fingerprint,
)
from rate_monitor.services.storage_service import ObjectStore

CU_FUNDING_ACQUISITION_CONTRACT_VERSION = 1
CU_FUNDING_BUNDLE_SCHEMA_VERSION = 1
CU_FUNDING_BUNDLE_KIND = "cu_funding_target_bundle"

FetchTarget = Callable[
    ..., tuple[list[CuFundingPoint], list[RawArtifactData], dict[int, int], list[str]]
]


@dataclass(frozen=True)
class CuFundingCheckpointContext:
    source_id: str
    cycle_date_kst: str
    request_fingerprint: str
    acquisition_contract_version: int = CU_FUNDING_ACQUISITION_CONTRACT_VERSION


@dataclass(frozen=True)
class CuFundingCheckpointProgress:
    status: str
    session_id: str
    expected_targets: int
    completed_targets: int
    newly_completed_targets: int
    warning_count: int


@dataclass(frozen=True)
class CuFundingTargetBundle:
    cu_ingno: str
    institution_id: str
    institution_name: str
    periods: int
    artifacts: tuple[RawArtifactData, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CuFundingReplayResult:
    run_id: str
    target_count: int
    raw_artifacts: int
    parsed_points: int
    stored: int
    unchanged: int
    revisions: int
    warning_count: int


def build_cu_funding_checkpoint_context(
    *, periods: int, cycle_date_kst: str
) -> CuFundingCheckpointContext:
    if periods < 1:
        raise ValueError("periods는 1 이상이어야 한다")
    return CuFundingCheckpointContext(
        source_id=SOURCE_ID,
        cycle_date_kst=cycle_date_kst,
        request_fingerprint=canonical_fingerprint(
            {
                "source_id": SOURCE_ID,
                "periods": periods,
                "bundle_schema_version": CU_FUNDING_BUNDLE_SCHEMA_VERSION,
                "acquisition_contract_version": CU_FUNDING_ACQUISITION_CONTRACT_VERSION,
                "identity_seed": "active cu SourceEntityLink exact cuIngno",
                "metric": "deposit_liabilities_total",
            }
        ),
    )


def _service(
    store: ObjectStore,
    context: CuFundingCheckpointContext,
) -> ResumableAcquisitionService:
    return ResumableAcquisitionService(
        store,
        AcquisitionSessionIdentity(
            source_id=context.source_id,
            cycle_date_kst=context.cycle_date_kst,
            request_fingerprint=context.request_fingerprint,
            acquisition_contract_version=context.acquisition_contract_version,
        ),
    )


def _artifact_to_payload(artifact: RawArtifactData) -> dict[str, Any]:
    digest = hashlib.sha256(artifact.content).hexdigest()
    if artifact.schema_fingerprint != digest:
        raise CuFundingContractError(
            "CU funding raw artifact fingerprint가 content SHA256과 다르다: "
            f"{artifact.filename}"
        )
    return {
        "artifact_type": artifact.artifact_type,
        "content_b64": base64.b64encode(artifact.content).decode("ascii"),
        "filename": artifact.filename,
        "request_meta": artifact.request_meta,
        "schema_fingerprint": digest,
        "source_role": artifact.source_role,
        "trust_level": artifact.trust_level,
    }


def _artifact_from_payload(data: dict[str, Any]) -> RawArtifactData:
    try:
        content = base64.b64decode(str(data["content_b64"]), validate=True)
        fingerprint = str(data["schema_fingerprint"])
        artifact = RawArtifactData(
            artifact_type=str(data["artifact_type"]),
            content=content,
            filename=str(data["filename"]),
            request_meta=dict(data["request_meta"]),
            schema_fingerprint=fingerprint,
            source_role=str(data["source_role"]),
            trust_level=str(data["trust_level"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CheckpointIncompatibleError(
            f"CU funding checkpoint raw artifact 형식 오류: {exc}"
        ) from exc
    if hashlib.sha256(content).hexdigest() != fingerprint:
        raise CheckpointIncompatibleError(
            f"CU funding checkpoint raw artifact hash 불일치: {artifact.filename}"
        )
    return artifact


def encode_target_bundle(bundle: CuFundingTargetBundle) -> RawArtifactData:
    payload = {
        "schema_version": CU_FUNDING_BUNDLE_SCHEMA_VERSION,
        "cu_ingno": bundle.cu_ingno,
        "institution_id": bundle.institution_id,
        "institution_name": bundle.institution_name,
        "periods": bundle.periods,
        "warnings": list(bundle.warnings),
        "artifacts": [_artifact_to_payload(artifact) for artifact in bundle.artifacts],
    }
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    return RawArtifactData(
        artifact_type="json",
        content=content,
        filename=f"cu-funding-checkpoint-{bundle.cu_ingno}.json",
        request_meta={
            "kind": CU_FUNDING_BUNDLE_KIND,
            "cuIngno": bundle.cu_ingno,
            "periods": bundle.periods,
        },
        schema_fingerprint=digest,
        source_role="internal_checkpoint",
        trust_level="content_addressed_staging",
    )


def decode_target_bundle(artifact: RawArtifactData) -> CuFundingTargetBundle:
    if artifact.request_meta.get("kind") != CU_FUNDING_BUNDLE_KIND:
        raise CheckpointIncompatibleError(
            f"CU funding checkpoint bundle kind 불일치: {artifact.request_meta.get('kind')!r}"
        )
    if hashlib.sha256(artifact.content).hexdigest() != artifact.schema_fingerprint:
        raise CheckpointIncompatibleError("CU funding checkpoint bundle hash 불일치")
    try:
        payload = json.loads(artifact.content)
        if int(payload["schema_version"]) != CU_FUNDING_BUNDLE_SCHEMA_VERSION:
            raise CheckpointIncompatibleError(
                f"CU funding bundle schema 불일치: {payload['schema_version']}"
            )
        cu_ingno = str(payload["cu_ingno"])
        periods = int(payload["periods"])
        bundle = CuFundingTargetBundle(
            cu_ingno=cu_ingno,
            institution_id=str(payload["institution_id"]),
            institution_name=str(payload["institution_name"]),
            periods=periods,
            artifacts=tuple(_artifact_from_payload(dict(item)) for item in payload["artifacts"]),
            warnings=tuple(str(item) for item in payload["warnings"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CheckpointIncompatibleError(
            f"CU funding checkpoint bundle 형식 오류: {exc}"
        ) from exc
    if artifact.request_meta.get("cuIngno") != bundle.cu_ingno:
        raise CheckpointIncompatibleError("CU funding checkpoint bundle target identity 불일치")
    if artifact.request_meta.get("periods") != bundle.periods:
        raise CheckpointIncompatibleError("CU funding checkpoint bundle periods 불일치")
    if not bundle.cu_ingno or not bundle.institution_id or bundle.periods < 1:
        raise CheckpointIncompatibleError("CU funding checkpoint bundle 필수 identity가 비어 있다")
    return bundle


def _plan_hash(targets: list[tuple[str, str, str]], periods: int) -> str:
    return canonical_fingerprint(
        [
            {
                "cu_ingno": cu_ingno,
                "institution_id": institution_id,
                "institution_name": institution_name,
                "periods": periods,
            }
            for cu_ingno, institution_id, institution_name in targets
        ]
    )


def _validate_plan(
    manifest: AcquisitionManifest,
    *,
    work_plan_hash: str,
    expected_work_count: int,
) -> None:
    if manifest.work_plan_hash != work_plan_hash:
        raise CheckpointIncompatibleError("CU funding checkpoint work_plan_hash 불일치")
    if manifest.expected_work_count != expected_work_count:
        raise CheckpointIncompatibleError("CU funding checkpoint expected_work_count 불일치")


def acquire_cu_funding_checkpoint(
    *,
    store: ObjectStore,
    db_path: Path,
    periods: int,
    cycle_date_kst: str,
    resume_mode: str = "auto",
    only_cu_nos: set[str] | None = None,
    max_new_targets: int | None = None,
    request_interval: float = REQUEST_INTERVAL_SECONDS,
    fetch_target: FetchTarget = _fetch_target,
) -> CuFundingCheckpointProgress:
    """Acquire exact CU source responses into staging only, one target per work key."""
    if max_new_targets is not None and max_new_targets < 1:
        raise ValueError("max_new_targets는 1 이상이어야 한다")
    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    targets = _targets(factory, only_cu_nos)
    context = build_cu_funding_checkpoint_context(
        periods=periods,
        cycle_date_kst=cycle_date_kst,
    )
    service = _service(store, context)
    manifest = service.open(resume_mode)
    plan_hash = _plan_hash(targets, periods)
    if manifest.status == "complete":
        _validate_plan(
            manifest,
            work_plan_hash=plan_hash,
            expected_work_count=len(targets),
        )
        bundles = [decode_target_bundle(item) for item in service.materialize(manifest)]
        return CuFundingCheckpointProgress(
            status="complete",
            session_id=manifest.session_id,
            expected_targets=len(targets),
            completed_targets=manifest.completed_work_count,
            newly_completed_targets=0,
            warning_count=sum(len(bundle.warnings) for bundle in bundles),
        )

    if manifest.work_plan_hash is None:
        manifest = service.set_plan(
            manifest,
            work_plan_hash=plan_hash,
            expected_work_count=len(targets),
        )
    else:
        _validate_plan(
            manifest,
            work_plan_hash=plan_hash,
            expected_work_count=len(targets),
        )
        if manifest.status == "recoverable_failed":
            manifest = service.set_plan(
                manifest,
                work_plan_hash=plan_hash,
                expected_work_count=len(targets),
            )

    completed = set(manifest.completed_work_keys)
    existing_bundles = [decode_target_bundle(item) for item in service.materialize(manifest)]
    warning_count = sum(len(bundle.warnings) for bundle in existing_bundles)
    newly_completed = 0
    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            for cu_ingno, institution_id, institution_name in targets:
                if cu_ingno in completed:
                    continue
                _points, artifacts, _summary_index, warnings = fetch_target(
                    client,
                    cu_ingno=cu_ingno,
                    institution_id=institution_id,
                    institution_name=institution_name,
                    periods=periods,
                    request_interval=request_interval,
                )
                bundle = CuFundingTargetBundle(
                    cu_ingno=cu_ingno,
                    institution_id=institution_id,
                    institution_name=institution_name,
                    periods=periods,
                    artifacts=tuple(artifacts),
                    warnings=tuple(warnings),
                )
                warning_count += len(warnings)
                manifest = service.flush(
                    manifest,
                    [CheckpointArtifact(cu_ingno, encode_target_bundle(bundle))],
                    guard_state={"warning_count": warning_count},
                )
                completed.add(cu_ingno)
                newly_completed += 1
                if max_new_targets is not None and newly_completed >= max_new_targets:
                    return CuFundingCheckpointProgress(
                        status="collecting",
                        session_id=manifest.session_id,
                        expected_targets=len(targets),
                        completed_targets=manifest.completed_work_count,
                        newly_completed_targets=newly_completed,
                        warning_count=warning_count,
                    )
    except httpx.HTTPError as exc:
        service.mark_recoverable_failed(
            manifest,
            reason_code="RECOVERABLE_NETWORK",
            reason=str(exc),
            guard_state={"warning_count": warning_count},
        )
        raise
    except CuFundingContractError as exc:
        service.mark_terminal(
            manifest,
            status="contract_failed",
            reason_code="SOURCE_CONTRACT_FAILED",
            reason=str(exc),
            guard_state={"warning_count": warning_count},
        )
        raise

    complete = service.mark_complete(manifest)
    return CuFundingCheckpointProgress(
        status="complete",
        session_id=complete.session_id,
        expected_targets=len(targets),
        completed_targets=complete.completed_work_count,
        newly_completed_targets=newly_completed,
        warning_count=warning_count,
    )


def _verify_bundle_identity(factory: Any, bundle: CuFundingTargetBundle) -> None:
    with session_scope(factory) as session:
        links = list(
            session.scalars(
                select(m.SourceEntityLink).where(
                    m.SourceEntityLink.source_id == "cu",
                    m.SourceEntityLink.entity_type == "institution",
                    m.SourceEntityLink.source_entity_key == f"cu:{bundle.cu_ingno}",
                    m.SourceEntityLink.valid_to.is_(None),
                )
            )
        )
        if len(links) != 1 or links[0].entity_id != bundle.institution_id:
            raise CheckpointIncompatibleError(
                "CU funding checkpoint identity가 current exact link와 다르다: "
                f"{bundle.cu_ingno}"
            )
        institution = session.get(m.Institution, bundle.institution_id)
        if institution is None or institution.sector != "cu":
            raise CheckpointIncompatibleError(
                f"CU funding checkpoint institution이 current DB와 다르다: {bundle.cu_ingno}"
            )


def _reparse_bundle(
    bundle: CuFundingTargetBundle,
) -> tuple[list[CuFundingPoint], dict[int, int], list[str]]:
    rows: list[dict[str, Any]] = []
    summary_by_no: dict[int, tuple[int, RawArtifactData]] = {}
    for index, artifact in enumerate(bundle.artifacts):
        kind = artifact.request_meta.get("kind")
        if kind == "disclosure_list":
            try:
                rows.extend(_list_rows(json.loads(artifact.content)))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise CheckpointIncompatibleError(
                    f"CU funding checkpoint list JSON 재파싱 실패: {bundle.cu_ingno}"
                ) from exc
            continue
        if kind == "summary_disclosure":
            raw_no = artifact.request_meta.get("disclosure_no")
            try:
                disclosure_no = int(raw_no)
            except (TypeError, ValueError) as exc:
                raise CheckpointIncompatibleError(
                    f"CU funding checkpoint summary disclosure_no 오류: {raw_no!r}"
                ) from exc
            if disclosure_no in summary_by_no:
                raise CheckpointIncompatibleError(
                    f"CU funding checkpoint summary 중복: {bundle.cu_ingno}/{disclosure_no}"
                )
            summary_by_no[disclosure_no] = (index, artifact)
            continue
        raise CheckpointIncompatibleError(
            f"CU funding checkpoint raw artifact kind 불일치: {kind!r}"
        )

    disclosures, warnings = _select_latest_disclosures_with_warnings(
        rows,
        cu_ingno=bundle.cu_ingno,
        periods=bundle.periods,
    )
    if not disclosures:
        raise CheckpointIncompatibleError(
            f"CU funding checkpoint에 재파싱 가능한 disclosure가 없다: {bundle.cu_ingno}"
        )

    points: list[CuFundingPoint] = []
    summary_index: dict[int, int] = {}
    for index, disclosure in enumerate(disclosures):
        found = summary_by_no.get(disclosure.disclosure_no)
        if found is None:
            raise CheckpointIncompatibleError(
                "CU funding checkpoint에 selected summary raw가 없다: "
                f"{bundle.cu_ingno}/{disclosure.disclosure_no}"
            )
        artifact_index, artifact = found
        try:
            text = artifact.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CheckpointIncompatibleError(
                f"CU funding checkpoint summary UTF-8 오류: {bundle.cu_ingno}"
            ) from exc
        point, warning = _parse_summary_with_history_policy(
            text,
            disclosure=disclosure,
            institution_id=bundle.institution_id,
            institution_name=bundle.institution_name,
            source_locator=str(artifact.request_meta.get("endpoint") or ""),
            is_latest=index == 0,
        )
        if warning is not None:
            if artifact.request_meta.get("quarantined") is not True:
                raise CheckpointIncompatibleError(
                    "CU funding checkpoint quarantine marker가 없다: "
                    f"{bundle.cu_ingno}/{disclosure.disclosure_no}"
                )
            if artifact.request_meta.get("quarantine_reason") != warning:
                raise CheckpointIncompatibleError(
                    "CU funding checkpoint quarantine reason이 재파싱 결과와 다르다: "
                    f"{bundle.cu_ingno}/{disclosure.disclosure_no}"
                )
            warnings.append(warning)
            continue
        if artifact.request_meta.get("quarantined"):
            raise CheckpointIncompatibleError(
                "CU funding checkpoint가 현재 유효한 summary를 quarantine으로 표시했다: "
                f"{bundle.cu_ingno}/{disclosure.disclosure_no}"
            )
        if point is None:
            raise CheckpointIncompatibleError("CU funding checkpoint summary 결과가 비어 있다")
        points.append(point)
        summary_index[disclosure.disclosure_no] = artifact_index

    if tuple(warnings) != bundle.warnings:
        raise CheckpointIncompatibleError(
            "CU funding checkpoint warning set이 current parser replay와 다르다: "
            f"{bundle.cu_ingno} checkpoint={len(bundle.warnings)} replay={len(warnings)}"
        )
    if not points:
        raise CheckpointIncompatibleError(
            f"CU funding checkpoint에 유효 observation이 없다: {bundle.cu_ingno}"
        )
    return points, summary_index, warnings


def replay_cu_funding_checkpoint(
    *,
    store: ObjectStore,
    db_path: Path,
    raw_root: Path,
    periods: int,
    cycle_date_kst: str,
) -> CuFundingReplayResult:
    """Reparse a complete staging checkpoint and atomically persist its valid rows."""
    context = build_cu_funding_checkpoint_context(
        periods=periods,
        cycle_date_kst=cycle_date_kst,
    )
    service = _service(store, context)
    manifest = service.open("auto")
    if manifest.status != "complete":
        raise CheckpointIncompatibleError(
            f"complete CU funding checkpoint만 replay할 수 있다: {manifest.status}"
        )
    bundles = [decode_target_bundle(item) for item in service.materialize(manifest)]
    if len(bundles) != manifest.expected_work_count:
        raise CheckpointIncompatibleError("CU funding checkpoint bundle 수가 work plan과 다르다")
    if tuple(bundle.cu_ingno for bundle in bundles) != manifest.completed_work_keys:
        raise CheckpointIncompatibleError("CU funding checkpoint bundle 순서가 work keys와 다르다")

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    for bundle in bundles:
        if bundle.periods != periods:
            raise CheckpointIncompatibleError("CU funding checkpoint bundle periods drift")
        _verify_bundle_identity(factory, bundle)

    reparsed = [_reparse_bundle(bundle) for bundle in bundles]
    now = datetime.now(UTC).replace(tzinfo=None)
    stored = unchanged = revisions = 0
    raw_count = sum(len(bundle.artifacts) for bundle in bundles)
    parsed_count = sum(len(item[0]) for item in reparsed)
    warning_count = sum(len(item[2]) for item in reparsed)

    with session_scope(factory) as session:
        _ensure_source(session, now)
        run = m.CollectionRun(
            source_id=SOURCE_ID,
            mode="checkpoint_replay",
            started_at=now,
            status="running",
            query_context_json={
                "checkpoint_session_id": manifest.session_id,
                "cycle_date_kst": cycle_date_kst,
                "periods": periods,
                "target_count": len(bundles),
                "staging_only_until_validation": True,
            },
        )
        session.add(run)
        session.flush()
        run_id = run.id

        for bundle, (points, summary_index, _warnings) in zip(
            bundles, reparsed, strict=True
        ):
            records = _save_artifacts_reusing_run(
                session=session,
                run=run,
                artifacts=list(bundle.artifacts),
                raw_root=raw_root,
                now=now,
            )
            for point in points:
                artifact_index = summary_index.get(point.disclosure_no)
                if artifact_index is None or artifact_index >= len(records):
                    raise CheckpointIncompatibleError(
                        "CU funding checkpoint replay provenance index가 없다: "
                        f"{bundle.cu_ingno}/{point.disclosure_no}"
                    )
                action = _upsert_point(
                    session,
                    point,
                    raw_artifact_id=records[artifact_index].id,
                    now=now,
                )
                if action == "stored":
                    stored += 1
                elif action == "revision":
                    revisions += 1
                else:
                    unchanged += 1

        run.finished_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "success"
        run.raw_count = raw_count
        run.parsed_count = parsed_count
        run.valid_count = parsed_count
        run.warning_count = warning_count
        run.error_count = 0
        run.message = (
            f"checkpoint targets={len(bundles)} points={parsed_count} "
            f"stored={stored} revisions={revisions} unchanged={unchanged} "
            f"warnings={warning_count}"
        )[:500]

    return CuFundingReplayResult(
        run_id=run_id,
        target_count=len(bundles),
        raw_artifacts=raw_count,
        parsed_points=parsed_count,
        stored=stored,
        unchanged=unchanged,
        revisions=revisions,
        warning_count=warning_count,
    )
