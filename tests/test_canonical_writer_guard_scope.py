from rate_monitor.services.canonical_writer_guard import (
    _infer_writer_scope,
    _is_publish_safe_stale_path,
    _is_scope_irrelevant_stale_path,
    _workflow_path_from_ref,
)


def test_unrelated_cu_total_assets_workflow_does_not_invalidate_rate_collectors() -> None:
    path = ".github/workflows/collect-cu-total-assets-bootstrap.yml"
    assert _is_scope_irrelevant_stale_path(path, "collect")
    assert _is_scope_irrelevant_stale_path(path, "nh_local")
    assert _is_scope_irrelevant_stale_path(path, "institution_funding")
    assert not _is_scope_irrelevant_stale_path(path, "cu_total_assets")


def test_source_specific_collector_change_only_blocks_affected_scope() -> None:
    cu_path = "src/rate_monitor/collectors/cu/client.py"
    nh_path = "src/rate_monitor/collectors/nh_local/collector.py"

    assert not _is_scope_irrelevant_stale_path(cu_path, "collect")
    assert _is_scope_irrelevant_stale_path(cu_path, "nh_local")
    assert not _is_scope_irrelevant_stale_path(nh_path, "nh_local")
    assert _is_scope_irrelevant_stale_path(nh_path, "collect")


def test_shared_schema_and_storage_paths_remain_fail_closed() -> None:
    assert not _is_scope_irrelevant_stale_path(
        "alembic/versions/999_add_column.py", "nh_local"
    )
    assert not _is_scope_irrelevant_stale_path(
        "src/rate_monitor/services/storage_service.py", "nh_local"
    )
    assert not _is_scope_irrelevant_stale_path(
        "src/rate_monitor/collectors/base.py", "nh_local"
    )


def test_unknown_scope_preserves_strict_backward_compatibility() -> None:
    assert not _is_scope_irrelevant_stale_path(
        ".github/workflows/collect-cu-total-assets-bootstrap.yml", ""
    )
    assert not _is_scope_irrelevant_stale_path(
        "src/rate_monitor/collectors/cu/client.py", "unknown"
    )


def test_workflow_ref_infers_known_writer_scope(monkeypatch) -> None:
    monkeypatch.delenv("RATE_MONITOR_WRITER_SCOPE", raising=False)
    monkeypatch.setenv(
        "GITHUB_WORKFLOW_REF",
        "dekt-oss/bank-rate-collector/.github/workflows/collect-nh.yml@refs/heads/main",
    )
    assert _workflow_path_from_ref(monkeypatch.getenv("GITHUB_WORKFLOW_REF")) == (
        ".github/workflows/collect-nh.yml"
    )
    assert _infer_writer_scope() == "nh_local"


def test_explicit_writer_scope_overrides_workflow_ref(monkeypatch) -> None:
    monkeypatch.setenv("RATE_MONITOR_WRITER_SCOPE", "manual_scope")
    monkeypatch.setenv(
        "GITHUB_WORKFLOW_REF",
        "dekt-oss/bank-rate-collector/.github/workflows/collect-nh.yml@refs/heads/main",
    )
    assert _infer_writer_scope() == "manual_scope"


def test_presentation_allowlist_remains_independent_of_writer_scope() -> None:
    assert _is_publish_safe_stale_path("docs/ops.md")
    assert _is_publish_safe_stale_path("tests/test_something.py")
    assert _is_publish_safe_stale_path(
        "src/rate_monitor/services/foo_presentation.py"
    )
