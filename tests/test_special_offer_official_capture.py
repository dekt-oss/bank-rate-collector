from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "special_offer_official_capture.py"
SPEC = importlib.util.spec_from_file_location("special_offer_official_capture", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _target() -> dict[str, object]:
    return {
        "target_id": "welcome-digiloca-1130313564",
        "institution": "웰컴저축은행",
        "product_name": "웰컴 디지로카 100일적금",
        "official_product_key": "1130313564",
        "url": "https://www.welcomebank.co.kr/path?prdCd=1130313564",
        "required_phrases": ["웰컴 디지로카 100일적금", "특판 상품"],
        "effective_from": "2024-07-22",
        "effective_to": "2024-12-31",
    }


def test_explicit_product_page_becomes_candidate_only() -> None:
    body = "<html><body>웰컴 디지로카 100일적금 본 상품은 1만좌 한도 특판 상품</body></html>"
    result = MODULE.evaluate_target(
        _target(),
        {
            "body": body.encode(),
            "status": 200,
            "final_url": "https://www.welcomebank.co.kr/path?prdCd=1130313564",
            "charset": "utf-8",
            "content_type": "text/html",
        },
    )
    assert result["classification_candidate"] == "confirmed_special_candidate"
    assert result["evidence_kind_candidate"] == "versioned_product_scope_observation"
    assert result["fsb_binding_status"] == "not_checked"
    assert result["canonical_mutated"] is False
    assert str(result["content_sha256"]).startswith("sha256:")


def test_missing_explicit_phrase_fails_closed() -> None:
    result = MODULE.evaluate_target(
        _target(),
        {
            "body": "웰컴 디지로카 100일적금".encode(),
            "status": 200,
            "final_url": "https://www.welcomebank.co.kr/path?prdCd=1130313564",
            "charset": "utf-8",
            "content_type": "text/html",
        },
    )
    assert result["classification_candidate"] == "unverified"
    assert result["missing_required_phrases"] == ["특판 상품"]


def test_missing_identity_marker_fails_closed() -> None:
    result = MODULE.evaluate_target(
        _target(),
        {
            "body": "웰컴 디지로카 100일적금 특판 상품".encode(),
            "status": 200,
            "final_url": "https://www.welcomebank.co.kr/path?prdCd=other",
            "charset": "utf-8",
            "content_type": "text/html",
        },
    )
    assert result["identity_marker_present"] is False
    assert result["classification_candidate"] == "unverified"


def test_config_rejects_non_https_and_duplicate_ids(tmp_path: Path) -> None:
    bad = {"version": 1, "targets": [_target(), {**_target(), "url": "http://example.com"}]}
    with pytest.raises(ValueError, match="duplicate"):
        MODULE._validate_config(bad)

    one = _target()
    one["url"] = "http://example.com"
    with pytest.raises(ValueError, match="HTTPS"):
        MODULE._validate_config({"version": 1, "targets": [one]})


def test_repository_config_is_valid() -> None:
    config = json.loads(
        (Path(__file__).parents[1] / "config" / "special_offer_official_targets.json").read_text(
            encoding="utf-8"
        )
    )
    MODULE._validate_config(config)
    assert len(config["targets"]) >= 3
