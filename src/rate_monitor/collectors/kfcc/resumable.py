"""KFCC durable resumable acquisition integration.

The existing :class:`KfccAdapter` remains the direct-fetch implementation. This
subclass is enabled explicitly by the CLI/workflow and keeps the public adapter
contract unchanged: ``fetch(CollectionRequest) -> list[RawArtifactData]``.

Regional list responses are frozen before the rate work plan is committed. Only
acquisition staging is checkpointed; canonical rows are still written by the
existing collection service after acquisition, except for the existing RepeatGuard
PARTIAL contract.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from rate_monitor.collectors.base import SchemaChangedError, SourceBlockedError
from rate_monitor.collectors.kfcc import parser
from rate_monitor.collectors.kfcc.adapter import (
    BASE_URL,
    CONNECT_TIMEOUT,
    DEFAULT_GROUPS,
    MAX_REQUESTS,
    READ_TIMEOUT,
    REQUEST_INTERVAL_SECONDS,
    USER_AGENT,
    KfccAdapter,
    KfccRequestFailure,
)
from rate_monitor.collectors.repeat_guard import RepeatGuard
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.resumable_acquisition import (
    AcquisitionManifest,
    AcquisitionSessionIdentity,
    CheckpointArtifact,
    CheckpointIncompatibleError,
    ResumableAcquisitionService,
    canonical_fingerprint,
)
from rate_monitor.services.storage_service import ObjectStore

KFCC_ACQUISITION_CONTRACT_VERSION = 1
KFCC_CHECKPOINT_FLUSH_ITEMS = 100
KFCC_CHECKPOINT_FLUSH_SECONDS = 5 * 60.0

Monotonic = Callable[[], float]
GuardFactory = Callable[[], RepeatGuard]


@dataclass(frozen=True)
class KfccCheckpointContext:
    source_id: str
    cycle_date_kst: str
    request_fingerprint: str
    acquisition_contract_version: int = KFCC_ACQUISITION_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "cycle_date_kst": self.cycle_date_kst,
            "request_fingerprint": self.request_fingerprint,
            "acquisition_contract_version": self.acquisition_contract_version,
        }


def kfcc_request_fingerprint(
    request: CollectionRequest,
    *,
    regions_path: Path | None = None,
) -> str:
    """Fingerprint the request knobs that define one KFCC acquisition contract."""
    probe = KfccAdapter(regions_path=regions_path)
    regions = probe._load_regions(request)
    groups = tuple(str(value) for value in (request.options.get("groups") or DEFAULT_GROUPS))
    return canonical_fingerprint(
        {
            "source_id": "kfcc",
            "regions": regions,
            "groups": list(groups),
            "acquisition_contract_version": KFCC_ACQUISITION_CONTRACT_VERSION,
        }
    )


def build_kfcc_checkpoint_context(
    request: CollectionRequest,
    *,
    cycle_date_kst: str,
    regions_path: Path | None = None,
) -> KfccCheckpointContext:
    return KfccCheckpointContext(
        source_id="kfcc",
        cycle_date_kst=cycle_date_kst,
        request_fingerprint=kfcc_request_fingerprint(request, regions_path=regions_path),
    )


class KfccResumableAdapter(KfccAdapter):
    """KFCC acquisition that checkpoints immutable raw responses in ObjectStore."""

    def __init__(
        self,
        store: ObjectStore,
        *,
        cycle_date_kst: str,
        resume_mode: str = "auto",
        regions_path: Path | None = None,
        sleep=None,  # noqa: ANN001 - preserve parent injection contract
        monotonic: Monotonic | None = None,
        guard_factory: GuardFactory | None = None,
        flush_items: int = KFCC_CHECKPOINT_FLUSH_ITEMS,
        flush_seconds: float = KFCC_CHECKPOINT_FLUSH_SECONDS,
    ) -> None:
        super().__init__(regions_path=regions_path, sleep=sleep)
        if resume_mode not in {"auto", "fresh"}:
            raise ValueError(f"KFCC resume mode는 auto/fresh만 가능하다: {resume_mode!r}")
        if flush_items < 1:
            raise ValueError("KFCC checkpoint flush_items는 1 이상이어야 한다")
        if flush_seconds <= 0:
            raise ValueError("KFCC checkpoint flush_seconds는 양수여야 한다")
        self._checkpoint_store = store
        self._cycle_date_kst = cycle_date_kst
        self._resume_mode = resume_mode
        self._monotonic = monotonic or time.monotonic
        self._guard_factory = guard_factory or RepeatGuard
        self._flush_items = flush_items
        self._flush_seconds = flush_seconds

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        regions = self._load_regions(request)
        groups = tuple(str(value) for value in (request.options.get("groups") or DEFAULT_GROUPS))
        context = build_kfcc_checkpoint_context(
            request,
            cycle_date_kst=self._cycle_date_kst,
            regions_path=self._regions_path,
        )
        service = ResumableAcquisitionService(
            self._checkpoint_store,
            AcquisitionSessionIdentity(
                source_id=self.source_id,
                cycle_date_kst=context.cycle_date_kst,
                request_fingerprint=context.request_fingerprint,
                acquisition_contract_version=context.acquisition_contract_version,
            ),
        )
        manifest = service.open(self._resume_mode)
        if manifest.status == "complete":
            raise CheckpointIncompatibleError(
                "KFCC complete checkpoint replay는 아직 자동 승인하지 않는다; fresh가 필요하다"
            )

        self._reset_retry_state()
        self._restore_retry_state(manifest)
        artifacts = service.materialize(manifest) if manifest.completed_work_count else []
        try:
            self._validate_durable_artifacts(manifest, artifacts)
        except CheckpointIncompatibleError as exc:
            self._seal_contract_failure(service, manifest, exc)
            raise

        guard = self._guard_factory()
        try:
            self._replay_guard(guard, artifacts)
        except CheckpointIncompatibleError as exc:
            self._seal_contract_failure(service, manifest, exc)
            raise
        if guard.tripped:
            terminal = service.mark_terminal(
                manifest,
                status="guard_tripped",
                reason_code="GUARD_TRIPPED",
                reason=guard.summary(),
                guard_state=self._checkpoint_state(),
            )
            return self._finish_guard_partial(service, terminal, guard)

        completed = set(manifest.completed_work_keys)
        buffer: list[CheckpointArtifact] = []
        last_flush = self._monotonic()
        requests_made = manifest.completed_work_count

        timeout = httpx.Timeout(
            connect=CONNECT_TIMEOUT,
            read=READ_TIMEOUT,
            write=READ_TIMEOUT,
            pool=CONNECT_TIMEOUT,
        )
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                list_by_region = self._list_artifacts(artifacts, regions)

                # Phase A — acquire and freeze every required regional list before
                # committing the gmgoCd × group rate work plan.
                for region in regions:
                    work_key = self._list_work_key(region)
                    if work_key in completed:
                        if region not in list_by_region:
                            raise CheckpointIncompatibleError(
                                f"KFCC completed directory work에 artifact가 없다: {region}"
                            )
                        continue
                    if requests_made >= MAX_REQUESTS:
                        raise SourceBlockedError(
                            f"요청 상한 {MAX_REQUESTS}회에 도달했다. 설정을 확인한다"
                        )
                    params = {"r1": region, "r2": ""}
                    body = await self._get(client, f"{BASE_URL}/map/list.do", params)
                    requests_made += 1
                    guard.observe(body, where=f"list r1={region}")
                    artifact = self._artifact(
                        body,
                        filename=f"list_{region}.html",
                        meta={"kind": "list", "r1": region, "r2": ""},
                    )
                    buffer.append(CheckpointArtifact(work_key, artifact))
                    artifacts.append(artifact)
                    completed.add(work_key)
                    list_by_region[region] = artifact

                    # Validate after staging the raw response so a graceful schema
                    # failure can still flush durable evidence before sealing.
                    parser.check_list_schema(body.decode("utf-8", "replace"))

                    if guard.tripped:
                        manifest = service.flush(
                            manifest,
                            buffer,
                            guard_state=self._checkpoint_state(),
                        )
                        buffer = []
                        terminal = service.mark_terminal(
                            manifest,
                            status="guard_tripped",
                            reason_code="GUARD_TRIPPED",
                            reason=guard.summary(),
                            guard_state=self._checkpoint_state(),
                        )
                        return self._finish_guard_partial(service, terminal, guard)

                    now_tick = self._monotonic()
                    if (
                        len(buffer) >= self._flush_items
                        or now_tick - last_flush >= self._flush_seconds
                    ):
                        manifest = service.flush(
                            manifest,
                            buffer,
                            guard_state=self._checkpoint_state(),
                        )
                        buffer = []
                        last_flush = now_tick
                    await self._sleep(REQUEST_INTERVAL_SECONDS)

                # All required lists are now frozen before the rate plan exists.
                if buffer:
                    manifest = service.flush(
                        manifest,
                        buffer,
                        guard_state=self._checkpoint_state(),
                    )
                    buffer = []
                    last_flush = self._monotonic()

                outlets, directory = self._build_directory(regions, list_by_region)
                if not outlets:
                    raise SourceBlockedError("KFCC 지역 목록에서 금고를 하나도 찾지 못했다")

                plan = self._build_rate_plan(outlets, directory, groups)
                manifest = service.set_plan(
                    manifest,
                    work_plan_hash=canonical_fingerprint(
                        {
                            "regions": regions,
                            "groups": list(groups),
                            "directory": [
                                {
                                    "gmgoCd": gmgo_cd,
                                    "outlet": row,
                                    "outlet_directory": directory.get(gmgo_cd, [row]),
                                }
                                for gmgo_cd, row in outlets.items()
                            ],
                        }
                    ),
                    expected_work_count=len(regions) + len(plan),
                )

                for item in plan:
                    if guard.tripped:
                        break
                    work_key = item["work_key"]
                    if work_key in completed:
                        continue
                    if requests_made >= MAX_REQUESTS:
                        raise SourceBlockedError(
                            f"요청 상한 {MAX_REQUESTS}회에 도달했다. 설정을 확인한다"
                        )
                    gmgo_cd = item["gmgoCd"]
                    group = item["gubuncode"]
                    row = item["outlet"]
                    params = {"OPEN_TRMID": gmgo_cd, "gubuncode": group}
                    body = await self._get(client, f"{BASE_URL}/map/goods_19.do", params)
                    requests_made += 1
                    await self._sleep(REQUEST_INTERVAL_SECONDS)
                    guard.observe(
                        body,
                        where=f"gmgoCd={gmgo_cd} gubuncode={group}",
                        stream=group,
                    )
                    artifact = self._artifact(
                        body,
                        filename=f"rate_{gmgo_cd}_{group}.html",
                        meta={
                            "kind": "rate",
                            "gmgoCd": gmgo_cd,
                            "gubuncode": group,
                            "r1": row.get("r1"),
                            "r2": row.get("r2"),
                            "outlet": row,
                            "outlet_directory": directory.get(gmgo_cd, [row]),
                        },
                    )
                    buffer.append(CheckpointArtifact(work_key, artifact))
                    artifacts.append(artifact)
                    completed.add(work_key)

                    now_tick = self._monotonic()
                    if (
                        guard.tripped
                        or len(buffer) >= self._flush_items
                        or now_tick - last_flush >= self._flush_seconds
                    ):
                        manifest = service.flush(
                            manifest,
                            buffer,
                            guard_state=self._checkpoint_state(),
                        )
                        buffer = []
                        last_flush = now_tick
                    if guard.tripped:
                        break

                if buffer:
                    manifest = service.flush(
                        manifest,
                        buffer,
                        guard_state=self._checkpoint_state(),
                    )
                    buffer = []

                if guard.tripped:
                    terminal = service.mark_terminal(
                        manifest,
                        status="guard_tripped",
                        reason_code="GUARD_TRIPPED",
                        reason=guard.summary(),
                        guard_state=self._checkpoint_state(),
                    )
                    return self._finish_guard_partial(service, terminal, guard)

                complete = service.mark_complete(manifest)
                result = service.materialize(complete)
                self._set_fetch_notes(guard)
                return result
        except KfccRequestFailure as exc:
            if buffer:
                manifest = service.flush(
                    manifest,
                    buffer,
                    guard_state=self._checkpoint_state(),
                )
            service.mark_recoverable_failed(
                manifest,
                reason_code=(
                    "RECOVERABLE_HTTP_SERVER"
                    if exc.code == "HTTP_SERVER_ERROR"
                    else "RECOVERABLE_NETWORK"
                ),
                reason=str(exc),
                guard_state=self._checkpoint_state(),
            )
            raise
        except SourceBlockedError as exc:
            if buffer:
                manifest = service.flush(
                    manifest,
                    buffer,
                    guard_state=self._checkpoint_state(),
                )
            service.mark_terminal(
                manifest,
                status="blocked",
                reason_code="SOURCE_BLOCKED",
                reason=str(exc),
                guard_state=self._checkpoint_state(),
            )
            raise
        except CheckpointIncompatibleError as exc:
            self._seal_contract_failure(service, manifest, exc)
            raise
        except SchemaChangedError as exc:
            if buffer:
                manifest = service.flush(
                    manifest,
                    buffer,
                    guard_state=self._checkpoint_state(),
                )
            service.mark_terminal(
                manifest,
                status="contract_failed",
                reason_code="SOURCE_SCHEMA_CHANGED",
                reason=str(exc),
                guard_state=self._checkpoint_state(),
            )
            raise

    def _seal_contract_failure(
        self,
        service: ResumableAcquisitionService,
        manifest: AcquisitionManifest,
        exc: CheckpointIncompatibleError,
    ) -> None:
        try:
            service.mark_terminal(
                manifest,
                status="contract_failed",
                reason_code="ACQUISITION_CONTRACT_CHANGED",
                reason=str(exc),
                guard_state=self._checkpoint_state(),
            )
        except CheckpointIncompatibleError:
            return

    @staticmethod
    def _list_work_key(region: str) -> str:
        return f"directory:{region}"

    @staticmethod
    def _rate_work_key(gmgo_cd: str, group: str) -> str:
        return f"rate:{gmgo_cd}:{group}"

    def _artifact_work_key(self, artifact: RawArtifactData) -> str:
        meta = artifact.request_meta
        kind = meta.get("kind")
        if kind == "list":
            region = str(meta.get("r1") or "")
            if not region:
                raise CheckpointIncompatibleError(
                    "KFCC checkpoint list artifact의 r1 metadata가 비어 있다"
                )
            return self._list_work_key(region)
        if kind == "rate":
            gmgo_cd = str(meta.get("gmgoCd") or "")
            group = str(meta.get("gubuncode") or "")
            if not gmgo_cd or not group:
                raise CheckpointIncompatibleError(
                    "KFCC checkpoint rate artifact의 gmgoCd/gubuncode metadata가 불완전하다"
                )
            return self._rate_work_key(gmgo_cd, group)
        raise CheckpointIncompatibleError(
            f"KFCC checkpoint에 알 수 없는 artifact kind가 있다: {kind!r}"
        )

    def _validate_durable_artifacts(
        self,
        manifest: AcquisitionManifest,
        artifacts: list[RawArtifactData],
    ) -> None:
        actual = tuple(self._artifact_work_key(artifact) for artifact in artifacts)
        if actual != manifest.completed_work_keys:
            raise CheckpointIncompatibleError(
                "KFCC checkpoint artifact 순서/identity가 completed_work_keys와 다르다"
            )

    def _list_artifacts(
        self,
        artifacts: list[RawArtifactData],
        regions: list[str],
    ) -> dict[str, RawArtifactData]:
        allowed = set(regions)
        found: dict[str, RawArtifactData] = {}
        for artifact in artifacts:
            if artifact.request_meta.get("kind") != "list":
                continue
            region = str(artifact.request_meta.get("r1") or "")
            if region not in allowed:
                raise CheckpointIncompatibleError(
                    f"KFCC checkpoint directory artifact의 region이 현재 범위 밖이다: {region!r}"
                )
            if region in found:
                raise CheckpointIncompatibleError(
                    f"KFCC checkpoint에 같은 region directory가 둘 이상 있다: {region}"
                )
            found[region] = artifact
        return found

    def _build_directory(
        self,
        regions: list[str],
        list_by_region: dict[str, RawArtifactData],
    ) -> tuple[dict[str, dict[str, str]], dict[str, list[dict[str, str]]]]:
        missing = [region for region in regions if region not in list_by_region]
        if missing:
            raise CheckpointIncompatibleError(
                f"KFCC rate plan 전에 required region list가 비어 있다: {missing}"
            )
        outlets: dict[str, dict[str, str]] = {}
        directory: dict[str, list[dict[str, str]]] = {}
        for region in regions:
            artifact = list_by_region[region]
            html = artifact.content.decode("utf-8", "replace")
            parser.check_list_schema(html)
            for row in parser.parse_list(html):
                gmgo_cd = row["gmgoCd"]
                outlets.setdefault(gmgo_cd, row)
                entries = directory.setdefault(gmgo_cd, [])
                if not any(entry.get("divCd") == row.get("divCd") for entry in entries):
                    entries.append(row)
        return outlets, directory

    def _build_rate_plan(
        self,
        outlets: dict[str, dict[str, str]],
        directory: dict[str, list[dict[str, str]]],
        groups: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for gmgo_cd, row in outlets.items():
            for group in groups:
                plan.append(
                    {
                        "work_key": self._rate_work_key(gmgo_cd, group),
                        "gmgoCd": gmgo_cd,
                        "gubuncode": group,
                        "outlet": row,
                        "outlet_directory": directory.get(gmgo_cd, [row]),
                    }
                )
        return plan

    def _replay_guard(self, guard: RepeatGuard, artifacts: list[RawArtifactData]) -> None:
        for artifact in artifacts:
            meta = artifact.request_meta
            kind = meta.get("kind")
            if kind == "list":
                region = str(meta.get("r1") or "")
                if not region:
                    raise CheckpointIncompatibleError(
                        "KFCC checkpoint list artifact의 r1 metadata가 비어 있다"
                    )
                guard.observe(artifact.content, where=f"list r1={region}")
                continue
            if kind != "rate":
                raise CheckpointIncompatibleError(
                    f"KFCC checkpoint에 알 수 없는 artifact kind가 있다: {kind!r}"
                )
            gmgo_cd = str(meta.get("gmgoCd") or "")
            group = str(meta.get("gubuncode") or "")
            if not gmgo_cd or not group:
                raise CheckpointIncompatibleError(
                    "KFCC checkpoint rate artifact의 gmgoCd/gubuncode metadata가 불완전하다"
                )
            guard.observe(
                artifact.content,
                where=f"gmgoCd={gmgo_cd} gubuncode={group}",
                stream=group,
            )

    def _checkpoint_state(self) -> dict[str, Any]:
        return {
            "retry_count": self._retry_count,
            "retry_reasons": dict(self._retry_reasons),
            "retry_delay_seconds": float(self._retry_delay_seconds),
        }

    def _restore_retry_state(self, manifest: AcquisitionManifest) -> None:
        state = manifest.guard_state or {}
        self._retry_count = int(state.get("retry_count") or 0)
        self._retry_reasons = Counter(
            {str(key): int(value) for key, value in dict(state.get("retry_reasons") or {}).items()}
        )
        self._retry_delay_seconds = float(state.get("retry_delay_seconds") or 0.0)

    def _set_fetch_notes(self, guard: RepeatGuard) -> None:
        self.fetch_note = guard.summary()
        retry_note = self._retry_note()
        if retry_note:
            self.fetch_note = f"{self.fetch_note} · {retry_note}"
        self.fetch_alert = guard.tripped

    def _finish_guard_partial(
        self,
        service: ResumableAcquisitionService,
        terminal: AcquisitionManifest,
        guard: RepeatGuard,
    ) -> list[RawArtifactData]:
        self._set_fetch_notes(guard)
        return service.materialize(terminal)
