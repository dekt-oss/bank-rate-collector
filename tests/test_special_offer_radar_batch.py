"""Batch-query regression coverage for the Strategy special-offer Radar."""

from rate_monitor.services.special_offer_radar_service import _BATCH_SIZE, _batches


def test_radar_batches_bound_sqlite_parameter_count() -> None:
    values = [f"product-{index}" for index in range(_BATCH_SIZE * 2 + 3)]

    batches = list(_batches(values))

    assert [len(batch) for batch in batches] == [_BATCH_SIZE, _BATCH_SIZE, 3]
    assert [value for batch in batches for value in batch] == values
