import json

import pytest
import scripts.production_smoke as smoke

EXPECTED_MANIFEST = {
    "generated_at": "2026-08-11T08:57:02+09:00",
    "rows": 326_793,
    "data_bytes": 21_251_456,
    "files": ["index.html", "strategy.html", "data/table.json"],
}


def test_validate_root_requires_operational_markers() -> None:
    smoke.validate_root("<button>수집 상태</button><span>업권</span>")

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.validate_root("<button>수집 상태</button><span>권역</span>")

    assert exc.value.category == "content-mismatch"
    assert "업권" in exc.value.detail


def test_validate_strategy_requires_unified_workspace_markers() -> None:
    smoke.validate_strategy(
        "수신상품 전략 대시보드 "
        '<script id="strategy-workspace-script"></script> '
        '<script id="strategy-brand-theme-script"></script>'
    )

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.validate_strategy("수신상품 전략 대시보드")

    assert exc.value.category == "content-mismatch"
    assert "strategy-workspace-script" in exc.value.detail


def test_validate_manifest_detects_stale_publish() -> None:
    actual = dict(EXPECTED_MANIFEST, generated_at="2026-08-11T08:40:00+09:00")

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.validate_manifest(actual, EXPECTED_MANIFEST)

    assert exc.value.category == "content-mismatch"
    assert "stale" in exc.value.detail


def test_validate_manifest_accepts_newer_successful_publish() -> None:
    actual = dict(
        EXPECTED_MANIFEST,
        generated_at="2026-08-11T09:02:00+09:00",
        rows=EXPECTED_MANIFEST["rows"] + 17,
        data_bytes=EXPECTED_MANIFEST["data_bytes"] + 2048,
    )

    smoke.validate_manifest(actual, EXPECTED_MANIFEST)


def test_validate_manifest_requires_strategy_in_expected_and_production() -> None:
    missing_expected = dict(EXPECTED_MANIFEST, files=["index.html", "data/table.json"])
    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.validate_manifest(EXPECTED_MANIFEST, missing_expected)
    assert "strategy.html" in exc.value.detail

    missing_actual = dict(EXPECTED_MANIFEST, files=["index.html", "data/table.json"])
    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.validate_manifest(missing_actual, EXPECTED_MANIFEST)
    assert "strategy.html" in exc.value.detail


def test_validate_manifest_same_generation_requires_exact_size_contract() -> None:
    actual = dict(EXPECTED_MANIFEST, rows=EXPECTED_MANIFEST["rows"] - 1)
    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.validate_manifest(actual, EXPECTED_MANIFEST)
    assert "rows" in exc.value.detail


def test_validate_health_requires_read_only_contract() -> None:
    payload = {
        "ok": True,
        "latest_collection": None,
        "active_collection": None,
        "active_publish": None,
        "latest_publish": None,
        "source_steps": {},
        "pipeline_steps": {},
    }
    smoke.validate_health(payload)

    payload.pop("pipeline_steps")
    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.validate_health(payload)

    assert exc.value.category == "endpoint"
    assert "pipeline_steps" in exc.value.detail


def test_run_once_checks_root_strategy_manifest_and_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health = {
        "ok": True,
        "latest_collection": None,
        "active_collection": None,
        "active_publish": None,
        "latest_publish": None,
        "source_steps": {},
        "pipeline_steps": {},
    }
    strategy = (
        "수신상품 전략 대시보드 "
        '<script id="strategy-workspace-script"></script> '
        '<script id="strategy-brand-theme-script"></script>'
    )
    responses = {
        "https://example.test/": (200, "업권 수집 상태".encode(), "text/html"),
        "https://example.test/strategy.html": (200, strategy.encode(), "text/html"),
        "https://example.test/site-manifest.json": (
            200,
            json.dumps(EXPECTED_MANIFEST).encode(),
            "application/json",
        ),
        "https://example.test/api/health": (
            200,
            json.dumps(health).encode(),
            "application/json",
        ),
    }

    monkeypatch.setattr(smoke, "_get", lambda url, timeout: responses[url])

    smoke.run_once("https://example.test", EXPECTED_MANIFEST, timeout=1)


def test_run_once_rejects_manifest_without_strategy_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = dict(EXPECTED_MANIFEST, files=["index.html", "data/table.json"])
    monkeypatch.setattr(
        smoke,
        "_get",
        lambda url, timeout: pytest.fail(f"unexpected network call: {url}"),
    )

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.run_once("https://example.test", manifest, timeout=1)

    assert "strategy.html" in exc.value.detail
