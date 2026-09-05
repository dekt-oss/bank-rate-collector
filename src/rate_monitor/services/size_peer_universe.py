"""Eligibility universe for Strategy size peers.

Size-peer eligibility is deliberately independent from size similarity. This
module answers only "can this institution belong to the comparison universe?".
Funding balance and total assets are evaluated by later layers.

The policy is fail-closed around evidence:

* savings banks are nationwide candidates for REMOTE scenarios by product
  contract;
* mutual-finance institutions require explicit internet/mobile/smartphone
  channel evidence for REMOTE scenarios;
* branch scenarios require official outlet/availability evidence inside Busan;
* ``any`` and ``unknown`` never prove remote eligibility.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

SIZE_PEER_UNIVERSE_POLICY_ID = "strategy-size-peer-universe"
SIZE_PEER_UNIVERSE_POLICY_VERSION = "2"

REMOTE = "remote"
BRANCH_BUSAN = "branch_busan"
SUPPORTED_MODES = frozenset({REMOTE, BRANCH_BUSAN})

SAVINGS_BANK = "savings_bank"
MUTUAL_FINANCE_SECTORS = frozenset({"cu", "kfcc", "nh_local"})
ELIGIBLE_SECTORS = frozenset({SAVINGS_BANK, *MUTUAL_FINANCE_SECTORS})

# v2 contract: branch comparison universe is all 16 Busan gu/gun.
# See docs/specs/20260905-strategy-size-peer-total-assets-v1.md §2.2.
BUSAN_ALL_DISTRICTS = frozenset(
    {
        "강서구",
        "금정구",
        "기장군",
        "남구",
        "동구",
        "동래구",
        "부산진구",
        "북구",
        "사상구",
        "사하구",
        "서구",
        "수영구",
        "연제구",
        "영도구",
        "중구",
        "해운대구",
    }
)

_REMOTE_CHANNEL_ALIASES = {
    "internet": "internet",
    "인터넷": "internet",
    "mobile": "mobile",
    "모바일": "mobile",
    "smartphone": "mobile",
    "smart_phone": "mobile",
    "스마트폰": "mobile",
}


@dataclass(frozen=True)
class SizePeerUniverseCandidate:
    """Evidence already resolved to one canonical institution.

    ``source_channels`` must contain source-declared channel members, not the
    lossy generic ``JoinChannel.ANY`` summary. ``outlet_sigungu`` must come from
    official outlet/address evidence (or an equally strong district-level
    availability contract), never from institution-name inference.
    """

    institution_id: str
    sector: str
    source_channels: tuple[str, ...] = ()
    outlet_sigungu: tuple[str, ...] = ()
    channel_evidence_source_id: str | None = None
    locality_evidence_source_id: str | None = None


@dataclass(frozen=True)
class SizePeerEligibilityDecision:
    institution_id: str
    sector: str
    mode: str
    eligible: bool
    reason: str
    matched_remote_channels: tuple[str, ...]
    matched_districts: tuple[str, ...]
    channel_evidence_source_id: str | None
    locality_evidence_source_id: str | None


@dataclass(frozen=True)
class SizePeerUniverseSelection:
    mode: str
    policy_id: str
    policy_version: str
    anchor_sido: str
    eligible_ids: tuple[str, ...]
    eligible_count: int
    excluded_count: int
    local_scope_districts: tuple[str, ...]
    decisions: tuple[SizePeerEligibilityDecision, ...]


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _normalized_remote_channels(values: Iterable[str]) -> tuple[str, ...]:
    channels = {
        canonical
        for raw in values
        if (canonical := _REMOTE_CHANNEL_ALIASES.get(str(raw or "").strip().casefold()))
    }
    return tuple(sorted(channels))


def _normalized_districts(values: Iterable[str]) -> tuple[str, ...]:
    districts = {
        str(value or "").strip()
        for value in values
        if str(value or "").strip()
    }
    return tuple(sorted(districts))


def _decision(
    candidate: SizePeerUniverseCandidate,
    *,
    mode: str,
) -> SizePeerEligibilityDecision:
    institution_id = _required_text(candidate.institution_id, field="institution_id")
    sector = _required_text(candidate.sector, field="sector")
    remote_channels = _normalized_remote_channels(candidate.source_channels)
    districts = _normalized_districts(candidate.outlet_sigungu)
    matched_districts = tuple(
        district for district in districts if district in BUSAN_ALL_DISTRICTS
    )

    if sector not in ELIGIBLE_SECTORS:
        eligible = False
        reason = "unsupported_sector"
    elif mode == REMOTE:
        if sector == SAVINGS_BANK:
            eligible = True
            reason = "savings_bank_nationwide_remote_universe"
        elif remote_channels:
            eligible = True
            reason = "explicit_remote_channel_evidence"
        else:
            eligible = False
            reason = "remote_eligibility_unverified"
    else:
        if matched_districts:
            eligible = True
            reason = "official_busan_district_evidence"
        elif not districts:
            eligible = False
            reason = "local_outlet_evidence_missing"
        else:
            eligible = False
            reason = "outside_busan"

    return SizePeerEligibilityDecision(
        institution_id=institution_id,
        sector=sector,
        mode=mode,
        eligible=eligible,
        reason=reason,
        matched_remote_channels=remote_channels if eligible and mode == REMOTE else (),
        matched_districts=matched_districts if eligible and mode == BRANCH_BUSAN else (),
        channel_evidence_source_id=(
            str(candidate.channel_evidence_source_id).strip()
            if candidate.channel_evidence_source_id
            else None
        ),
        locality_evidence_source_id=(
            str(candidate.locality_evidence_source_id).strip()
            if candidate.locality_evidence_source_id
            else None
        ),
    )


def select_size_peer_universe(
    candidates: Iterable[SizePeerUniverseCandidate],
    *,
    mode: str,
) -> SizePeerUniverseSelection:
    """Return deterministic eligibility decisions for one comparison mode."""

    normalized_mode = _required_text(mode, field="mode").casefold()
    if normalized_mode not in SUPPORTED_MODES:
        raise ValueError(f"unsupported size-peer universe mode: {mode!r}")

    by_id: dict[str, SizePeerUniverseCandidate] = {}
    for candidate in candidates:
        institution_id = _required_text(candidate.institution_id, field="institution_id")
        if institution_id in by_id:
            raise ValueError(
                "duplicate canonical institution in size-peer universe: " + institution_id
            )
        by_id[institution_id] = candidate

    decisions = tuple(
        _decision(by_id[institution_id], mode=normalized_mode)
        for institution_id in sorted(by_id)
    )
    eligible_ids = tuple(
        decision.institution_id for decision in decisions if decision.eligible
    )
    return SizePeerUniverseSelection(
        mode=normalized_mode,
        policy_id=SIZE_PEER_UNIVERSE_POLICY_ID,
        policy_version=SIZE_PEER_UNIVERSE_POLICY_VERSION,
        anchor_sido="부산",
        eligible_ids=eligible_ids,
        eligible_count=len(eligible_ids),
        excluded_count=len(decisions) - len(eligible_ids),
        local_scope_districts=tuple(sorted(BUSAN_ALL_DISTRICTS)),
        decisions=decisions,
    )
