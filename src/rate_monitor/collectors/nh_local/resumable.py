"""NH local durable resumable acquisition integration.

The existing :class:`NhLocalAdapter` remains the direct-fetch implementation. This
subclass is enabled explicitly by the CLI/workflow and keeps the public adapter
contract unchanged: ``fetch(CollectionRequest) -> list[RawArtifactData]``.

Only acquisition staging is checkpointed. Canonical rows are still written by the
existing collection service *after* a complete acquisition, except for the existing
RepeatGuard contract where received artifacts intentionally become PARTIAL and the
checkpoint is terminal/non-resumable.
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
from rate_monitor.collectors.nh_local import parser
from rate_monitor.collectors.nh_local.adapter import (
    CONNECT_TIMEOUT,
    DEFAULT_PRODUCTS,
    LIST_SCREEN,
    MAX_REQUESTS,
    READ_TIMEOUT,
    REQUEST_INTERVAL_SECONDS,
    USER_AGENT,
    NhLocalAdapter,
    NhRequestFailure,
)
from rate_monitor.collectors.repeat_guard import RepeatGuard
from rate_monitor.domain.enums import ProductType
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.domain.timeutil import now_kst
from rate_monitor.services.resumable_acquisition import (
    AcquisitionManifest,
    AcquisitionSessionIdentity,
    CheckpointArtifact,
    CheckpointIncompatibleError,
    ResumableAcquisitionService,
    canonical_fingerprint,
)
from rate_monitor.services.storage_service import ObjectStore

NH_ACQUISITION_CONTRACT_VERSION = 1
NH_CHECKPOINT_FLUSH_ITEMS = 200
NH_CHECKPOINT_FLUSH_SECONDS = 5 * 60.0
LIST_WORK_KEY = f"directory:{LIST_SCREEN}"

Monotonic = Callable[[], float]
GuardFactory = Callable[[], RepeatGuard]


@dataclass(frozen=True)
class NhCheckpointContext:
    source_id: str
    cycle_date_kst: str
    request_fingerprint: str
    acquisition_contract_version: int = NH_ACQUISITION_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "cycle_date_kst": self.cycle_date_kst,
            "request_fingerprint": self.request_fingerprint,
            "acquisition_contract_version": self.acquisition_contract_version,
        }


def nh_request_fingerprint(
    request: CollectionRequest,
    *,
    regions_path: Path | None = None,
) -> str:
    """Fingerprint the request knobs that define one NH acquisition contract.

    The directory response itself is deliberately *not* part of this fingerprint. The
    first fetched directory becomes a durable checkpoint artifact and its derived work
    plan is separately frozen with ``work_plan_hash``.
    """
    probe = NhLocalAdapter(regions_path=regions_path)
    prefixes = probe._load_prefixes(request)
    products = tuple(request.options.get("products") or DEFAULT_PRODUCTS)
    return canonical_fingerprint(
        {
            "source_id": "nh_local",
            "address_prefixes": list(prefixes) if prefixes is not None else None,
            "products": [product.value for product in products],
            "screens": [parser.SCREEN_BY_PRODUCT[product] for product in products],
            "acquisition_contract_version": NH_ACQUISITION_CONTRACT_VERSION,
        }
    )


def build_nh_checkpoint_context(
    request: CollectionRequest,
    *,
    cycle_date_kst: str,
    regions_path: Path | None = None,
) -> NhCheckpointContext:
    return NhCheckpointContext(
        source_id="nh_local",
        cycle_date_kst=cycle_date_kst,
        request_fingerprint=nh_request_fingerprint(request, regions_path=regions_path),
    )


class NhResumableAdapter(NhLocalAdapter):
    """NH acquisition that checkpoints immutable raw responses in R2/ObjectStore."""

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
        flush_items: int = NH_CHECKPOINT_FLUSH_ITEMS,
        flush_seconds: float = NH_CHECKPOINT_FLUSH_SECONDS,
    ) -> None:
        super().__init__(regions_path=regions_path, sleep=sleep)
        if resume_mode not in {"auto", "fresh"}:
            raise ValueError(f"NH resume mode는 auto/fresh만 가능하다: {resume_mode!r}")
        if flush_items < 1:
            raise ValueError("NH checkpoint flush_items는 1 이상이어야 한다")
        if flush_seconds <= 0:
            raise ValueError("NH checkpoint flush_seconds는 양수여야 한다")
        self._checkpoint_store = store
        self._cycle_date_kst = cycle_date_kst
        self._resume_mode = resume_mode
        self._monotonic = monotonic or time.monotonic
        self._guard_factory = guard_factory or RepeatGuard
        self._flush_items = flush_items
        self._flush_seconds = flush_seconds

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        prefixes = self._load_prefixes(request)
        products = tuple(request.options.get("products") or DEFAULT_PRODUCTS)
        context = build_nh_checkpoint_context(
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
                "NH complete checkpoint replay는 아직 자동 승인하지 않는다; fresh가 필요하다"
            )

        self._reset_retry_state()
        self._restore_retry_state(manifest)
        artifacts = service.materialize(manifest) if manifest.completed_work_count else []
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
                list_artifact = self._find_list_artifact(artifacts)
                if list_artifact is None:
                    body = await self._get(client, LIST_SCREEN, {}, phase="preflight")
                    guard.observe(body, where="outlet list")
                    as_of = now_kst().date().isoformat()
                    list_artifact = self._artifact(
                        body,
                        filename="outlet_list.html",
                        meta={
                            "kind": "list",
                            "screen": LIST_SCREEN,
                            "as_of": as_of,
                        },
                    )
                    manifest = service.flush(
                        manifest,
                        [CheckpointArtifact(LIST_WORK_KEY, list_artifact)],
                        guard_state=self._checkpoint_state(),
                    )
                    completed.add(LIST_WORK_KEY)
                    artifacts.append(list_artifact)
                    last_flush = self._monotonic()
                    await self._sleep(REQUEST_INTERVAL_SECONDS)
                else:
                    as_of = str(list_artifact.request_meta.get("as_of") or "")
                    if not as_of:
                        raise CheckpointIncompatibleError(
                            "NH checkpoint directory artifact에 frozen as_of가 없다"
                        )

                outlets = parser.outlets_in(
                    parser.parse_outlet_list(
                        list_artifact.content.decode("utf-8", "replace")
                    ),
                    prefixes,
                )
                if not outlets:
                    raise SourceBlockedError(
                        f"명부에서 범위에 맞는 점포가 하나도 없다 (접두어 {prefixes})"
                    )

                plan = self._build_plan(outlets, products)
                manifest = service.set_plan(
                    manifest,
                    work_plan_hash=canonical_fingerprint(
                        [item["descriptor"] for item in plan]
                    ),
                    expected_work_count=1 + len(plan),
                )

                # Existing MAX_REQUESTS includes the directory request. A resume
                # therefore starts from all durable completed work, not details only.
                requests_made = manifest.completed_work_count
                for item in plan:
                    if guard.tripped:
                        break
                    outlet = item["outlet"]
                    product = item["product"]
                    screen = item["screen"]
                    work_key = item["work_key"]
                    if work_key in completed:
                        continue
                    if requests_made >= MAX_REQUESTS:
                        raise SourceBlockedError(
                            f"요청 상한 {MAX_REQUESTS}회에 도달했다. 설정을 확인한다"
                        )
                    body = await self._get(
                        client,
                        screen,
                        {
                            "brc": outlet.brc,
                            "brnm": outlet.name,
                            "inq_dsc": "",
                            "inq_str": "",
                            "searchContent": "",
                        },
                        phase="detail",
                    )
                    requests_made += 1
                    await self._sleep(REQUEST_INTERVAL_SECONDS)
                    guard.observe(
                        body,
                        where=f"brc={outlet.brc} screen={screen}",
                        stream=screen,
                    )
                    artifact = self._artifact(
                        body,
                        filename=f"rate_{outlet.brc}_{screen}.html",
                        meta={
                            "kind": "rate",
                            "screen": screen,
                            "product_type": product.value,
                            "as_of": as_of,
                            "outlet": outlet._asdict(),
                        },
                    )
                    buffer.append(CheckpointArtifact(work_key, artifact))
                    artifacts.append(artifact)
                    completed.add(work_key)

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
        except NhRequestFailure as exc:
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
        """Seal same-session contract drift so workflow recovery cannot loop it."""
        try:
            service.mark_terminal(
                manifest,
                status="contract_failed",
                reason_code="ACQUISITION_CONTRACT_CHANGED",
                reason=str(exc),
                guard_state=self._checkpoint_state(),
            )
        except CheckpointIncompatibleError:
            # Identity-level incompatibility can mean this manifest is not the active
            # session. In that case the common recovery decision itself fails closed.
            return

    def _build_plan(
        self,
        outlets,
        products: tuple[ProductType, ...],
    ) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for outlet in outlets:
            for product in products:
                screen = parser.SCREEN_BY_PRODUCT[product]
                work_key = f"detail:{outlet.brc}:{screen}"
                plan.append(
                    {
                        "work_key": work_key,
                        "outlet": outlet,
                        "product": product,
                        "screen": screen,
                        "descriptor": {
                            "work_key": work_key,
                            "brc": outlet.brc,
                            "name": outlet.name,
                            "address": outlet.address,
                            "product_type": product.value,
                            "screen": screen,
                        },
                    }
                )
        return plan

    @staticmethod
    def _find_list_artifact(artifacts: list[RawArtifactData]) -> RawArtifactData | None:
        found = [artifact for artifact in artifacts if artifact.request_meta.get("kind") == "list"]
        if len(found) > 1:
            raise CheckpointIncompatibleError("NH checkpoint에 directory artifact가 둘 이상 있다")
        return found[0] if found else None

    def _replay_guard(self, guard: RepeatGuard, artifacts: list[RawArtifactData]) -> None:
        for artifact in artifacts:
            meta = artifact.request_meta
            if meta.get("kind") == "list":
                guard.observe(artifact.content, where="outlet list")
                continue
            if meta.get("kind") != "rate":
                raise CheckpointIncompatibleError(
                    f"NH checkpoint에 알 수 없는 artifact kind가 있다: {meta.get('kind')!r}"
                )
            screen = str(meta.get("screen") or "")
            outlet = dict(meta.get("outlet") or {})
            brc = str(outlet.get("brc") or "")
            if not screen or not brc:
                raise CheckpointIncompatibleError(
                    "NH checkpoint rate artifact의 screen/brc metadata가 불완전하다"
                )
            guard.observe(
                artifact.content,
                where=f"brc={brc} screen={screen}",
                stream=screen,
            )

    def _checkpoint_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "retry_count": self._retry_count,
            "retry_reasons": dict(self._retry_reasons),
        }
        if hasattr(self, "_retry_delay_seconds"):
            state["retry_delay_seconds"] = float(self._retry_delay_seconds)
        return state

    def _restore_retry_state(self, manifest: AcquisitionManifest) -> None:
        state = manifest.guard_state or {}
        self._retry_count = int(state.get("retry_count") or 0)
        self._retry_reasons = Counter(
            {str(key): int(value) for key, value in dict(state.get("retry_reasons") or {}).items()}
        )
        if hasattr(self, "_retry_delay_seconds"):
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
