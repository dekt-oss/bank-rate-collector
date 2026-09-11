"""Source-specific minimum-volume contracts for canonical local-rate collectors.

The three local collectors can return syntactically valid but catastrophically small
responses.  HTTP success is therefore not enough to call the acquisition healthy.

Only canonical nationwide runs use the non-zero source floor.  Manually scoped runs
(Busan, capital area, explicit CU regions) still get the universal zero-row guard, but
must not be compared with nationwide volume.

The floors intentionally sit far below repository-observed normal volume.  They are
circuit breakers, not expected counts:

- CU: repository recon documents about 30,994 rows -> floor 7,500
- KFCC: repository config documents about 93,816 rows -> floor 20,000
- NH local: repository config documents about 4,920 rows -> floor 1,000

Normal product churn must not trip them; empty/truncated source responses should.
"""

from __future__ import annotations

from dataclasses import dataclass

from rate_monitor.domain.schemas import CollectionRequest


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


POLICIES: dict[str, SourceVolumePolicy] = {
    "cu": SourceVolumePolicy("cu", 7_500),
    "kfcc": SourceVolumePolicy("kfcc", 20_000),
    "nh_local": SourceVolumePolicy("nh_local", 1_000),
}


def is_full_scope(source_id: str, request: CollectionRequest) -> bool:
    """Whether *request* represents the canonical nationwide acquisition."""
    if source_id == "cu":
        # CU uses explicit regions when a subset is requested.  No regions means the
        # adapter walks every known SIDO bucket.
        return not request.regions
    if source_id in {"kfcc", "nh_local"}:
        scope = request.options.get("scope")
        return scope in {None, "", "전국"}
    return False


def evaluate_source_volume(
    source_id: str,
    request: CollectionRequest,
    parsed_count: int,
) -> SourceVolumeDecision | None:
    """Return a decision for governed sources, otherwise ``None``.

    Zero rows are never healthy, even for a deliberately scoped manual run.  The
    stronger absolute floor applies only to the canonical nationwide scope.
    """
    policy = POLICIES.get(source_id)
    if policy is None:
        return None

    full_scope = is_full_scope(source_id, request)
    minimum = policy.full_scope_min_parsed if full_scope else 1
    if parsed_count >= minimum:
        return SourceVolumeDecision(
            ok=True,
            source_id=source_id,
            parsed_count=parsed_count,
            minimum=minimum,
            full_scope=full_scope,
            code="SOURCE_VOLUME_OK",
            message=(
                f"{source_id}: parsed={parsed_count:,} >= minimum={minimum:,}"
            ),
        )

    code = "SOURCE_EMPTY_RESULT" if parsed_count == 0 else "SOURCE_VOLUME_BELOW_MINIMUM"
    scope_label = "전국" if full_scope else "지정 범위"
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
    )
