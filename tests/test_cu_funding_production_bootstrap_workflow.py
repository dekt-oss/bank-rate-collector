WORKFLOW = ".github/workflows/collect-cu-funding-bootstrap.yml"


def _text() -> str:
    with open(WORKFLOW, encoding="utf-8") as handle:
        return handle.read()


def test_cu_funding_bootstrap_uses_serialized_authoritative_writer_lane() -> None:
    text = _text()
    assert "group: rate-data-writer" in text
    assert "cancel-in-progress: false" in text
    assert "storage restore --dest work/rate_monitor.sqlite3" in text
    assert "storage upload --db publish/rate_monitor.sqlite3" in text
    assert "cmp -s publish/rate_monitor.sqlite3 work/cu-funding-from-r2.sqlite3" in text


def test_cu_funding_bootstrap_is_one_time_latest_period_contract() -> None:
    text = _text()
    assert "branches:\n      - main" in text
    assert "collect-cu-funding-bootstrap.yml" in text
    assert "schedule:" not in text
    assert "periods=1" in text
    assert "request_interval=1.0" in text
    assert "timeout-minutes: 420" in text


def test_cu_funding_bootstrap_has_fail_closed_coverage_and_identity_gate() -> None:
    text = _text()
    assert "target_count * 0.97" in text
    assert 'identity_status!=\'mapped_exact_cu_ingno\'' in text
    assert "duplicate_active_natural_keys" in text
    assert "exact_link_mismatches" in text
    assert "COUNT(DISTINCT source_id) > 1" in text
    assert 'assert run["revisions"] == 0' in text


def test_cu_funding_bootstrap_requires_idempotency_before_snapshot_and_publish() -> None:
    text = _text()
    idempotency = text.index("- name: Bounded idempotency regression on exact controls")
    snapshot = text.index("- name: Snapshot and validate candidate")
    raw_upload = text.index("- name: Persist raw CU funding evidence to R2 long-term tier")
    state_upload = text.index("- name: Upload authoritative state to R2")
    readback = text.index("- name: Verify authoritative R2 restore byte-for-byte")
    assert idempotency < snapshot < raw_upload < state_upload < readback
    assert "assert result.stored == 0" in text
    assert "assert result.revisions == 0" in text
    assert "assert result.unchanged == len(controls)" in text


def test_cu_funding_bootstrap_does_not_mix_total_assets_activation() -> None:
    text = _text()
    assert "persist_cu_total_assets_pairs" not in text
    assert "metric_code='total_assets'" not in text
