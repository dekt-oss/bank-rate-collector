from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.source_volume_contract import evaluate_source_volume


def _request(source_id: str, *, scope: str | None = None, regions: tuple[str, ...] = ()):
    options = {} if scope is None else {"scope": scope}
    return CollectionRequest(source_id=source_id, regions=regions, options=options)


def test_cu_nationwide_floor_rejects_empty_and_truncated_results():
    empty = evaluate_source_volume("cu", _request("cu"), 0)
    truncated = evaluate_source_volume("cu", _request("cu"), 7_499)
    healthy = evaluate_source_volume("cu", _request("cu"), 7_500)

    assert empty is not None and not empty.ok
    assert empty.code == "SOURCE_EMPTY_RESULT"
    assert truncated is not None and not truncated.ok
    assert truncated.code == "SOURCE_VOLUME_BELOW_MINIMUM"
    assert truncated.minimum == 7_500
    assert healthy is not None and healthy.ok


def test_kfcc_nationwide_floor_is_source_specific():
    bad = evaluate_source_volume("kfcc", _request("kfcc", scope="전국"), 19_999)
    good = evaluate_source_volume("kfcc", _request("kfcc", scope="전국"), 20_000)

    assert bad is not None and not bad.ok
    assert bad.minimum == 20_000
    assert good is not None and good.ok


def test_nh_nationwide_floor_is_source_specific():
    bad = evaluate_source_volume("nh_local", _request("nh_local", scope="전국"), 999)
    good = evaluate_source_volume("nh_local", _request("nh_local", scope="전국"), 1_000)

    assert bad is not None and not bad.ok
    assert bad.minimum == 1_000
    assert good is not None and good.ok


def test_scoped_runs_only_enforce_non_empty_contract():
    cu_one = evaluate_source_volume("cu", _request("cu", regions=("부산",)), 1)
    kfcc_scope_one = evaluate_source_volume("kfcc", _request("kfcc", scope="부산"), 1)
    kfcc_region_one = evaluate_source_volume("kfcc", _request("kfcc", regions=("부산",)), 1)
    nh_one = evaluate_source_volume("nh_local", _request("nh_local", scope="부산"), 1)

    assert cu_one is not None and cu_one.ok and cu_one.minimum == 1
    assert kfcc_scope_one is not None and kfcc_scope_one.ok and kfcc_scope_one.minimum == 1
    assert kfcc_region_one is not None and kfcc_region_one.ok and kfcc_region_one.minimum == 1
    assert nh_one is not None and nh_one.ok and nh_one.minimum == 1


def test_kfcc_explicit_regions_override_nationwide_scope_for_volume_policy():
    decision = evaluate_source_volume(
        "kfcc",
        _request("kfcc", scope="전국", regions=("부산",)),
        78,
    )

    assert decision is not None and decision.ok
    assert decision.full_scope is False
    assert decision.minimum == 1


def test_scoped_zero_result_is_never_healthy():
    decision = evaluate_source_volume("kfcc", _request("kfcc", scope="부산"), 0)

    assert decision is not None and not decision.ok
    assert decision.code == "SOURCE_EMPTY_RESULT"
    assert decision.minimum == 1


def test_unmanaged_sources_keep_existing_collection_contract():
    assert evaluate_source_volume("fsb", _request("fsb"), 0) is None
