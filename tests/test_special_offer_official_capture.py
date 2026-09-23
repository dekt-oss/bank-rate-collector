from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from scripts.special_offer_official_capture import (
    EvidenceCaptureError,
    audit_fsb_bindings,
    parse_surface,
)

WELCOME = """
<html><body>
<h1>웰뱅 라이킷(LIKIT) 적금</h1>
<div>롯데카드 X 웰컴 한정 특판</div>
</body></html>
""".encode()

IBK = """
<html><body>
<h1>특판 청룡비상(靑龍飛上)정기적금</h1>
<h3>특판내용</h3>
<div>계약고 100억원 한도</div>
</body></html>
""".encode()

DAISHIN = """
<html><body>
<h4>기업자유예금 특판 안내</h4>
<div>상품명 : 기업자유예금</div>
<div>기간 : 2024.09.26(목)~2026.06.25(목), 2,000억한도 소진시 조기마감</div>
</body></html>
""".encode()


def _target(parser: str, product: str, kind: str = "explicit_source_field") -> dict:
    return {
        "target_id": parser,
        "institution": "테스트저축은행",
        "product_name": product,
        "fsb_institution_names": ["테스트저축은행"],
        "fsb_product_names": [product],
        "surface": {
            "url": "https://example.com/product",
            "parser": parser,
            "product_locator": "exact",
            "evidence_kind": kind,
        },
    }


def test_welcome_candidate_requires_exact_product_and_explicit_special_marker() -> None:
    parsed = parse_surface(
        _target("welcome_product_special", "웰뱅 라이킷(LIKIT) 적금"),
        WELCOME,
        "utf-8",
    )
    assert parsed["classification"] == "confirmed_special"
    assert parsed["identity_scope"] == "exact_product"
    assert parsed["assertion_marker"] == "웰컴 한정 특판"
    assert parsed["availability"] == "not_inferred"

    with pytest.raises(EvidenceCaptureError, match="explicit special-sale assertion"):
        parse_surface(
            _target("welcome_product_special", "웰뱅 라이킷(LIKIT) 적금"),
            WELCOME.replace("한정 특판".encode(), "일반 상품".encode()),
            "utf-8",
        )


def test_ibk_candidate_requires_structured_special_section() -> None:
    parsed = parse_surface(
        _target("ibk_product_special", "특판 청룡비상(靑龍飛上)정기적금"),
        IBK,
        "utf-8",
    )
    assert parsed["assertion_marker"] == "특판내용"

    with pytest.raises(EvidenceCaptureError, match="structured 특판내용"):
        parse_surface(
            _target("ibk_product_special", "특판 청룡비상(靑龍飛上)정기적금"),
            IBK.replace("특판내용".encode(), "상품내용".encode()),
            "utf-8",
        )


def test_daishin_versioned_notice_requires_explicit_period() -> None:
    parsed = parse_surface(
        _target(
            "daishin_special_notice",
            "기업자유예금",
            "versioned_product_scope_observation",
        ),
        DAISHIN,
        "utf-8",
    )
    assert parsed["source_effective_from"] == "2024-09-26"
    assert parsed["source_effective_to"] == "2026-06-25"

    with pytest.raises(EvidenceCaptureError, match="effective period"):
        parse_surface(
            _target(
                "daishin_special_notice",
                "기업자유예금",
                "versioned_product_scope_observation",
            ),
            "<html><body>기업자유예금 특판 안내 상품명 : 기업자유예금</body></html>".encode(),
            "utf-8",
        )


def test_exact_title_mismatch_fails_closed() -> None:
    with pytest.raises(EvidenceCaptureError, match="exact configured product title missing"):
        parse_surface(
            _target("welcome_product_special", "다른 적금"),
            WELCOME,
            "utf-8",
        )


def test_fsb_binding_audit_is_read_only_and_exact_alias_scoped(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE institutions(id TEXT PRIMARY KEY, canonical_name TEXT);
        CREATE TABLE products(id TEXT PRIMARY KEY, institution_id TEXT, name TEXT);
        CREATE TABLE source_entity_links(
            source_id TEXT,
            entity_type TEXT,
            entity_id TEXT,
            source_entity_key TEXT,
            match_method TEXT,
            valid_to TEXT
        );
        INSERT INTO institutions VALUES ('i1', '웰컴저축은행');
        INSERT INTO products VALUES ('p1', 'i1', '웰뱅 라이킷(LIKIT) 적금');
        INSERT INTO products VALUES ('p2', 'i1', '비슷한 웰뱅 라이킷 적금');
        INSERT INTO source_entity_links VALUES
            ('fsb', 'product', 'p1', 'i1:CODE1', 'exact_code', NULL),
            ('fsb', 'product', 'p2', 'i1:CODE2', 'exact_code', NULL);
        """
    )
    conn.commit()
    before = db.read_bytes()
    conn.close()

    config = {
        "version": 1,
        "policy": "test",
        "targets": [
            {
                **_target("welcome_product_special", "웰뱅 라이킷(LIKIT) 적금"),
                "institution": "웰컴저축은행",
            }
        ],
    }
    result = audit_fsb_bindings(config, db)

    assert result["unique_candidate_count"] == 1
    assert result["targets"][0]["match_count"] == 1
    assert result["targets"][0]["matches"][0]["product_id"] == "p1"
    assert result["targets"][0]["confirmation_written"] is False
    assert result["scope"]["alias_match_is_confirmation"] is False
    assert db.read_bytes() == before


def test_repository_target_config_is_https_and_read_only() -> None:
    config = json.loads(
        Path("config/special_offer_official_targets.json").read_text(encoding="utf-8")
    )
    assert config["policy"] == "special_offer_official_candidate_read_only_v1"
    assert len(config["targets"]) >= 3
    assert all(item["surface"]["url"].startswith("https://") for item in config["targets"])
