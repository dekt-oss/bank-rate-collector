"""Source-specific minimum-volume contracts for canonical local-rate collectors.

The three local collectors can return syntactically valid but catastrophically small
responses. HTTP success is therefore not enough to call the acquisition healthy.

Only canonical nationwide runs use the non-zero source floor. Manually scoped runs
(Busan, capital area, explicit CU/KFCC regions) still get the universal zero-row guard,
but must not be compared with nationwide volume.

The floors intentionally sit far below repository-observed normal volume. They are
circuit breakers, not expected counts:

- CU: repository recon documents about 30,994 rows -> floor 7,500
- KFCC: repository config documents about 93,816 rows -> floor 20,000
- NH local: repository config documents about 4,920 rows -> floor 1,000

Normal product churn must not trip them; empty/truncated source responses should.

## Previous-run drop (2026-09-13)

The absolute floor alone did not catch the 2026-09-09 04:01 KST CU run: the upstream
started answering ``[]`` mid-run and the run ended with 550 raw / 22,257 parsed rows
(73% of the previous 30,502). That is above 7,500, so it was stored and published as a
success while about 8,000 rows silently disappeared from the screen.

The publish-time volume gate (``scripts/volume_gate.py``) has compared each source with
its previous run at 75% since 2026-08-06, but it only sees the last ten runs of the whole
database, so the CU baseline is routinely pushed out of view by other sources.

So the same 75% rule is applied here, before canonical persistence, against the last
confirmed nationwide run of the same source stored in the database. A run below that
ratio is FAILED with ``SOURCE_VOLUME_DROP`` and keeps the previous observations on
screen. Operators who confirm the source really shrank pass ``accept_volume_drop``
(workflow input) which only relaxes this comparison, never the absolute floor or the
zero-row guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rate_monitor.domain.schemas import CollectionRequest

# 직전 정상 실행 대비 이 비율 아래면 급감이다. scripts/volume_gate.py와 같은 값이다.
PREVIOUS_RUN_MIN_RATIO = 0.75
# 직전 실행이 이보다 작으면 비율을 따지지 않는다 (작은 수의 흔들림).
PREVIOUS_RUN_MIN_BASELINE = 100

# 실행 요청 options / 환경변수 이름. workflow의 accept_volume_drop 입력이 여기로 온다.
ACCEPT_VOLUME_DROP_OPTION = "accept_volume_drop"
ACCEPT_VOLUME_DROP_ENV = "RATE_MONITOR_ACCEPT_VOLUME_DROP"

CODE_OK = "SOURCE_VOLUME_OK"
CODE_EMPTY = "SOURCE_EMPTY_RESULT"
CODE_BELOW_MINIMUM = "SOURCE_VOLUME_BELOW_MINIMUM"
CODE_DROP = "SOURCE_VOLUME_DROP"
FAILURE_CODES = frozenset({CODE_EMPTY, CODE_BELOW_MINIMUM, CODE_DROP})


@dataclass(frozen=True)
class SourceVolumePolicy:
    source_id: str
    full_scope_min_parsed: int


@dataclass(frozen=True)
class SourceVolumeDecision:
    ok: bool
    source_id: str
    parsed_count: int
    minimum: int
    full_scope: bool
    code: str
    message: str
    previous_parsed: int | None = None


POLICIES: dict[str, SourceVolumePolicy] = {
    "cu": SourceVolumePolicy("cu", 7_500),
    "kfcc": SourceVolumePolicy("kfcc", 20_000),
    "nh_local": SourceVolumePolicy("nh_local", 1_000),
}


def is_full_scope(source_id: str, request: CollectionRequest) -> bool:
    """Whether *request* represents the canonical nationwide acquisition.

    Request precedence must mirror the adapters. In particular, KFCC accepts an
    explicit ``regions`` subset even when ``scope`` is absent; treating that request
    as nationwide makes every legitimate Busan fixture/manual collection fail the
    20,000-row circuit breaker.
    """
    return is_full_scope_context(
        source_id, {"regions": list(request.regions), "options": dict(request.options)}
    )


def is_full_scope_context(source_id: str, query_context: dict[str, Any] | None) -> bool:
    """Same decision as :func:`is_full_scope`, from a stored ``query_context_json``.

    ``collection_runs.query_context_json`` records exactly ``regions`` and ``options``
    of the request, so historical runs can be classified with the same precedence.
    """
    context = query_context or {}
    regions = context.get("regions") or []
    options = context.get("options") or {}
    if source_id == "cu":
        # CU walks every known SIDO bucket only when no explicit region list exists.
        return not regions
    if source_id == "kfcc":
        # KFCC explicit regions take precedence over the named scope in the adapter.
        if regions:
            return False
        scope = options.get("scope")
        return scope in {None, "", "전국"}
    if source_id == "nh_local":
        # NH does not accept --regions; the named scope is the only scope selector.
        scope = options.get("scope")
        return scope in {None, "", "전국"}
    return False


def accept_volume_drop_requested(
    request: CollectionRequest, environ: dict[str, str] | None = None
) -> bool:
    """Operator confirmation that the source really shrank (workflow input)."""
    value = request.options.get(ACCEPT_VOLUME_DROP_OPTION)
    if value is None:
        value = (environ or {}).get(ACCEPT_VOLUME_DROP_ENV, "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def evaluate_source_volume(
    source_id: str,
    request: CollectionRequest,
    parsed_count: int,
    *,
    previous_parsed: int | None = None,
    accept_drop: bool = False,
) -> SourceVolumeDecision | None:
    """Return a decision for governed sources, otherwise ``None``.

    Zero rows are never healthy, even for a deliberately scoped manual run. The
    stronger absolute floor applies only to the canonical nationwide scope, and the
    previous-run comparison (``previous_parsed``) is likewise only meaningful for the
    canonical scope — the caller must pass the last confirmed nationwide run.
    """
    policy = POLICIES.get(source_id)
    if policy is None:
        return None

    full_scope = is_full_scope(source_id, request)
    minimum = policy.full_scope_min_parsed if full_scope else 1
    scope_label = "전국" if full_scope else "지정 범위"

    if parsed_count < minimum:
        code = CODE_EMPTY if parsed_count == 0 else CODE_BELOW_MINIMUM
        return SourceVolumeDecision(
            ok=False,
            source_id=source_id,
            parsed_count=parsed_count,
            minimum=minimum,
            full_scope=full_scope,
            code=code,
            message=(
                f"{code}: {source_id} {scope_label} 파싱 건수 {parsed_count:,}건이 "
                f"최소 정상 기준 {minimum:,}건보다 적다"
            ),
            previous_parsed=previous_parsed,
        )

    if (
        full_scope
        and not accept_drop
        and previous_parsed is not None
        and previous_parsed >= PREVIOUS_RUN_MIN_BASELINE
        and parsed_count < previous_parsed * PREVIOUS_RUN_MIN_RATIO
    ):
        ratio = parsed_count / previous_parsed
        return SourceVolumeDecision(
            ok=False,
            source_id=source_id,
            parsed_count=parsed_count,
            minimum=minimum,
            full_scope=full_scope,
            code=CODE_DROP,
            message=(
                f"{CODE_DROP}: {source_id} {scope_label} 파싱 건수 {parsed_count:,}건이 "
                f"직전 정상 실행 {previous_parsed:,}건의 {ratio:.1%}다 "
                f"(기준 {PREVIOUS_RUN_MIN_RATIO:.0%} 미만). 원천이 정말 줄었으면 "
                "accept_volume_drop으로 한 번 승인한다"
            ),
            previous_parsed=previous_parsed,
        )

    detail = f"{source_id}: parsed={parsed_count:,} >= minimum={minimum:,}"
    if previous_parsed is not None and full_scope:
        detail += f", previous={previous_parsed:,}"
    return SourceVolumeDecision(
        ok=True,
        source_id=source_id,
        parsed_count=parsed_count,
        minimum=minimum,
        full_scope=full_scope,
        code=CODE_OK,
        message=detail,
        previous_parsed=previous_parsed,
    )
