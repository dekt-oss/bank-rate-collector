import pytest

from rate_monitor.services.size_peer_universe import (
    BRANCH_BUSAN,
    BUSAN_ALL_DISTRICTS,
    REMOTE,
    SizePeerUniverseCandidate,
    select_size_peer_universe,
)


def _candidate(
    institution_id: str,
    sector: str,
    *,
    channels: tuple[str, ...] = (),
    districts: tuple[str, ...] = (),
) -> SizePeerUniverseCandidate:
    return SizePeerUniverseCandidate(
        institution_id=institution_id,
        sector=sector,
        source_channels=channels,
        outlet_sigungu=districts,
        channel_evidence_source_id="official-rate-source" if channels else None,
        locality_evidence_source_id="official-outlet-source" if districts else None,
    )


def test_remote_universe_includes_all_savings_banks_without_channel_inference() -> None:
    result = select_size_peer_universe(
        [
            _candidate("savings-a", "savings_bank"),
            _candidate("savings-b", "savings_bank", channels=("unknown",)),
        ],
        mode=REMOTE,
    )
    assert result.eligible_ids == ("savings-a", "savings-b")
    assert all(decision.eligible for decision in result.decisions)
    assert all(
        decision.reason == "savings_bank_nationwide_remote_universe"
        for decision in result.decisions
    )


def test_remote_mutual_finance_requires_explicit_internet_or_mobile_member() -> None:
    result = select_size_peer_universe(
        [
            _candidate("cu-mobile", "cu", channels=("스마트폰",)),
            _candidate("kfcc-internet", "kfcc", channels=("인터넷",)),
            _candidate("nh-any", "nh_local", channels=("any",)),
            _candidate("cu-unknown", "cu", channels=("unknown",)),
        ],
        mode=REMOTE,
    )
    assert result.eligible_ids == ("cu-mobile", "kfcc-internet")
    by_id = {decision.institution_id: decision for decision in result.decisions}
    assert by_id["cu-mobile"].matched_remote_channels == ("mobile",)
    assert by_id["kfcc-internet"].matched_remote_channels == ("internet",)
    assert by_id["nh-any"].reason == "remote_eligibility_unverified"
    assert by_id["cu-unknown"].reason == "remote_eligibility_unverified"


def test_branch_scope_is_all_16_busan_gu_gun() -> None:
    assert BUSAN_ALL_DISTRICTS == {
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


def test_branch_universe_uses_official_busan_district_evidence_across_sectors() -> None:
    result = select_size_peer_universe(
        [
            _candidate("savings", "savings_bank", districts=("해운대구",)),
            _candidate("cu", "cu", districts=("기장군",)),
            _candidate("kfcc", "kfcc", districts=("동래구",)),
            _candidate("nh", "nh_local", districts=("영도구",)),
        ],
        mode=BRANCH_BUSAN,
    )
    assert result.eligible_ids == ("cu", "kfcc", "nh", "savings")
    assert all(
        decision.reason == "official_busan_district_evidence"
        for decision in result.decisions
    )


def test_branch_universe_excludes_outside_busan_and_missing_locality_evidence() -> None:
    result = select_size_peer_universe(
        [
            _candidate("gimhae", "cu", districts=("김해시",)),
            _candidate("missing", "nh_local"),
        ],
        mode=BRANCH_BUSAN,
    )
    assert result.eligible_ids == ()
    by_id = {decision.institution_id: decision for decision in result.decisions}
    assert by_id["gimhae"].reason == "outside_busan"
    assert by_id["missing"].reason == "local_outlet_evidence_missing"


def test_size_peer_universe_rejects_bank_sector_and_duplicate_canonical_identity() -> None:
    result = select_size_peer_universe(
        [_candidate("commercial-bank", "bank", channels=("mobile",), districts=("동구",))],
        mode=REMOTE,
    )
    assert result.eligible_ids == ()
    assert result.decisions[0].reason == "unsupported_sector"

    with pytest.raises(ValueError, match="duplicate canonical institution"):
        select_size_peer_universe(
            [_candidate("dup", "cu"), _candidate("dup", "kfcc")],
            mode=REMOTE,
        )


def test_size_peer_universe_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unsupported size-peer universe mode"):
        select_size_peer_universe([], mode="nationwide")
