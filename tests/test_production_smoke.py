from __future__ import annotations

import json

import pytest
from scripts import production_smoke as smoke


EXPECTED_MANIFEST = {
    "generated_at": "2026-08-11T08:57:02+09:00",
    "rows": 326_793,
    "data_bytes": 21_251_456,
}


def test_validate_root_requires_operational_markers() -> None:
    smoke.validate_root("<button>수집 상태</button><span>업권</span>")

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.validate_root("<button>수집 상태</button><span>권역</span>")

    assert exc.value.category == "content-mismatch"
    assert "업권" in exc.value.detail


def test_validate_manifest_detects_stale_publish() -> None:
    actual = dict(EXPECTED_MANIFEST, generated_at="2026-08-11T08:40:00+09:00")

    with pytest.raises(smoke.SmokeFailure) as exc:
        smoke.validate_manifest(actual, EXPECTED_MANIFEST)

    assert exc.value.category == "content-mismatch"
    assert "stale" in exc.value.detail


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


def test_run_once_checks_root_manifest_and_health(monkeypatch: pytest.MonkeyPatch) -> None:
    health = {
        "ok": True,
        "latest_collection": None,
        "active_collection": None,
        "active_publish": None,
        "latest_publish": None,
        "source_steps": {},
        "pipeline_steps": {},
    }
    responses = {
        "https://example.test/": (200, "업권 수집 상태".encode(), "text/html"),
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
