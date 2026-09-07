WORKFLOW = ".github/workflows/collect-cu-total-assets-bootstrap.yml"


def _text() -> str:
    with open(WORKFLOW, encoding="utf-8") as handle:
        return handle.read()


def test_cu_total_assets_bootstrap_uses_serialized_authoritative_writer_lane() -> None:
    text = _text()
    assert "group: rate-data-writer" in text
    assert "queue: max" in text
    assert "cancel-in-progress: false" in text
    assert "storage restore --dest work/rate_monitor.sqlite3" in text
    assert "storage upload --db publish/rate_monitor.sqlite3" in text
    assert "cmp -s publish/rate_monitor.sqlite3 work/cu-total-assets-from-r2.sqlite3" in text


def test_cu_total_assets_bootstrap_requires_production_funding_first() -> None:
    text = _text()
    prerequisite = text.index("- name: Require production CU funding prerequisite and seal it")
    evidence = text.index("- name: Collect same-disclosure CU size pairs for every funded institution")
    persistence = text.index("- name: Persist CU total assets twice and require idempotency")
    assert prerequisite < evidence < persistence
    assert "minimum_funding = math.ceil(exact_targets * 0.97)" in text
    assert "active_rows >= minimum_funding" in text
    assert "duplicate_active_institutions == 0" in text
    assert "mapped_exact_cu_ingno" in text
    assert "COUNT(DISTINCT source_id) > 1" in text


def test_cu_total_assets_bootstrap_requires_complete_pairs_for_every_funded_cu() -> None:
    text = _text()
    assert "only_cu_nos=funded_keys" in text
    assert 'assert evidence.status == "success"' in text
    assert "evidence.completed_targets == len(funded_keys)" in text
    assert "not evidence.failed_targets" in text
    assert "len(evidence.pairs) == len(funded_keys)" in text
    assert "{pair.cu_ingno for pair in evidence.pairs} == funded_keys" in text


def test_cu_total_assets_bootstrap_seals_funding_and_enforces_asset_idempotency() -> None:
    text = _text()
    assert '"funding_sha256"' in text
    assert "funding_sha == baseline[\"funding_sha256\"]" in text
    assert "first.revisions == 0" in text
    assert "second.stored == 0" in text
    assert "second.revisions == 0" in text
    assert "second.unchanged == len(funded_keys)" in text
    assert "len(assets) == len(funding)" in text
    assert "pair_matches == len(funding)" in text


def test_cu_total_assets_bootstrap_requires_provenance_and_r2_readback() -> None:
    text = _text()
    qc = text.index("- name: Verify funding isolation and exact pair completeness")
    snapshot = text.index("- name: Snapshot and validate candidate")
    raw_upload = text.index("- name: Persist raw CU total-assets evidence to R2 long-term tier")
    state_upload = text.index("- name: Upload authoritative state to R2")
    readback = text.index("- name: Verify authoritative R2 restore byte-for-byte")
    assert qc < snapshot < raw_upload < state_upload < readback
    assert "missing_raw_provenance == 0" in text
    assert "bad_asset_rows == 0" in text
    assert "foreign_key_violations" in text


def test_cu_total_assets_bootstrap_is_one_time_and_does_not_change_ranking() -> None:
    text = _text()
    assert "schedule:" not in text
    assert "collect-cu-total-assets-bootstrap.yml" in text
    assert "size_peer_two_axis" not in text
    assert "similarity" not in text
    assert "ranking" not in text
