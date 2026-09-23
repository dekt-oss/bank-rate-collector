from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "special_offer_official_capture.py"
SPEC = importlib.util.spec_from_file_location("special_offer_official_capture", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
NOW = datetime(2026, 9, 24, tzinfo=UTC)


def _target(parser: str = "welcome_digiloca") -> dict[str, object]:
    return {
        "target_id": "welcome-digiloca-1130313564",
        "institution": "웰컴저축은행",
        "product_name": "웰컴 디지로카 100일적금",
        "official_product_key": "1130313564",
        "fsb_institution_names": ["웰컴저축은행"],
        "fsb_product_names": ["웰컴 디지로카 100일적금"],
        "url": "https://www.welcomebank.co.kr/path?prdCd=1130313564",
        "terms_parser": parser,
        "required_phrases": ["웰컴 디지로카 100일적금", "특판 상품"],
    }


def _response(text: str, *, url: str = "https://www.welcomebank.co.kr/path?prdCd=1130313564"):
    return {
        "body": text.encode(),
        "status": 200,
        "final_url": url,
        "charset": "utf-8",
        "content_type": "text/html",
    }


def test_welcome_digiloca_terms_and_past_availability_are_structured() -> None:
    body = (
        "웰컴 디지로카 100일적금 특판 상품 가입대상 실명의 개인 가입기간 100일 "
        "본 상품은 1만좌 한도 특판 상품 특판기간 : 2024.07.22. ~ 2024.12.31. "
        "(특판소진 시 조기 종료)"
    )
    result = MODULE.evaluate_target(_target(), _response(body), observed_at=NOW)
    terms = result["special_offer_terms"]
    assert result["classification_candidate"] == "confirmed_special_candidate"
    assert terms["sale_start"] == "2024-07-22"
    assert terms["sale_end"] == "2024-12-31"
    assert terms["quota_accounts"] == 10_000
    assert "실명의 개인" in terms["eligibility_text"]
    assert "조기 종료" in terms["early_termination_text"]
    assert result["availability"]["status"] == "confirmed_ended"


def test_ibk_explicit_rate_quota_and_eligibility_are_structured() -> None:
    target = {
        **_target("ibk_blue_dragon"),
        "target_id": "ibksb-blue-dragon-502132836",
        "institution": "IBK저축은행",
        "product_name": "특판 청룡비상(靑龍飛上)정기적금",
        "official_product_key": "502132836",
        "url": "https://www.ibksb.co.kr/m/deposit/502132836",
        "required_phrases": ["특판 청룡비상", "특판내용"],
    }
    body = (
        "특판 청룡비상(靑龍飛上)정기적금 특판내용 계약고 100억원 한도 "
        "가입기간: 12개월 금리: 4.90% 가입대상 제한없음(1인 1계좌) 이자지급"
    )
    result = MODULE.evaluate_target(
        target,
        _response(body, url=target["url"]),
        observed_at=NOW,
    )
    terms = result["special_offer_terms"]
    assert terms["special_rate"] == "4.90"
    assert terms["quota_amount_krw"] == 10_000_000_000
    assert terms["eligibility_text"] == "제한없음(1인 1계좌)"
    assert result["availability"]["status"] == "unknown"


def test_daishin_current_notice_terms_do_not_imply_active_when_early_close_exists() -> None:
    target = {
        **_target("daishin_corporate_free"),
        "target_id": "daishin-corporate-free-588",
        "institution": "대신저축은행",
        "product_name": "기업자유예금",
        "official_product_key": "notice:588",
        "url": "https://bank.daishin.com/sub.do?code=03_news02&mode=view&no=588",
        "required_phrases": ["기업자유예금", "특판"],
    }
    body = (
        "기업자유예금 특판 안내 상품명 : 기업자유예금 특판금리 : 연 3.25%(세전) "
        "기간 : 2024.09.26(목)~2026.12.28(월), 2,000억한도 소진시 조기마감 "
        "대상 : 해당기간 신규계좌로 50억원이상 예치 상품안내 "
        "가. 가입대상 : 법인, 개인사업자 나. 이자의 지급시기"
    )
    result = MODULE.evaluate_target(
        target,
        _response(body, url=target["url"]),
        observed_at=NOW,
    )
    terms = result["special_offer_terms"]
    assert terms["special_rate"] == "3.25"
    assert terms["sale_end"] == "2026-12-28"
    assert terms["quota_amount_krw"] == 200_000_000_000
    assert "법인, 개인사업자" in terms["eligibility_text"]
    assert "조기마감" in terms["early_termination_text"]
    assert result["availability"]["status"] == "unknown"


def test_sale_stop_surface_can_confirm_ended_for_exact_product() -> None:
    target = {
        **_target("welcome_likit"),
        "target_id": "welcome-likit-1130313563",
        "product_name": "웰뱅 라이킷(LIKIT) 적금",
        "official_product_key": "1130313563",
        "url": "https://www.welcomebank.co.kr/path?prdCd=1130313563",
        "required_phrases": ["웰뱅 라이킷", "한정 특판"],
        "availability_source": {
            "url": "https://www.welcomebank.co.kr/stopped",
            "status": "confirmed_ended",
            "required_phrase": "판매중지",
        },
    }
    primary = "웰뱅 라이킷(LIKIT) 적금 웰컴 한정 특판 가입대상 만 19세 이상 실명의 개인 가입기간 12개월 1만좌 한도"
    stopped = "판매중지상품 웰뱅 라이킷(LIKIT) 적금 롯데카드 X 웰컴 한정 특판 판매중지"
    result = MODULE.evaluate_target(
        target,
        _response(primary, url=target["url"]),
        observed_at=NOW,
        availability_response=_response(stopped, url=target["availability_source"]["url"]),
    )
    assert result["availability"]["status"] == "confirmed_ended"
    assert "판매중지" in result["availability"]["assertion_text"]


def test_future_end_date_alone_never_confirms_active() -> None:
    terms = {"sale_end": "2026-12-28"}
    status, assertion = MODULE._availability_from_period(terms, observed_at=NOW)
    assert status == "unknown"
    assert assertion is None


def test_missing_explicit_phrase_and_identity_fail_closed() -> None:
    result = MODULE.evaluate_target(
        _target(),
        _response("웰컴 디지로카 100일적금", url="https://www.welcomebank.co.kr/path?prdCd=other"),
        observed_at=NOW,
    )
    assert result["classification_candidate"] == "unverified"
    assert result["identity_marker_present"] is False
    assert result["missing_required_phrases"] == ["특판 상품"]


def test_fsb_binding_audit_is_read_only_and_exact_alias_scoped(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE institutions(id TEXT PRIMARY KEY, canonical_name TEXT);
        CREATE TABLE products(id TEXT PRIMARY KEY, institution_id TEXT, name TEXT);
        CREATE TABLE source_entity_links(
            source_id TEXT, entity_type TEXT, entity_id TEXT, source_entity_key TEXT,
            match_method TEXT, valid_to TEXT
        );
        INSERT INTO institutions VALUES ('i1', '웰컴저축은행');
        INSERT INTO products VALUES ('p1', 'i1', '웰컴 디지로카 100일적금');
        INSERT INTO source_entity_links VALUES
            ('fsb', 'product', 'p1', 'i1:CODE1', 'exact_code', NULL);
        """
    )
    conn.commit()
    before = db.read_bytes()
    conn.close()

    result = MODULE.audit_fsb_bindings({"version": 2, "targets": [_target()]}, db)
    assert result["unique_candidate_count"] == 1
    assert result["targets"][0]["binding_status"] == "unique_candidate"
    assert result["scope"]["confirmation_written"] is False
    assert db.read_bytes() == before


def test_config_rejects_non_https_and_repository_config_is_valid() -> None:
    bad = _target()
    bad["url"] = "http://example.com"
    with pytest.raises(ValueError, match="HTTPS"):
        MODULE._validate_config({"version": 2, "targets": [bad]})

    config = json.loads(
        (Path(__file__).parents[1] / "config" / "special_offer_official_targets.json").read_text(
            encoding="utf-8"
        )
    )
    MODULE._validate_config(config)
    assert len(config["targets"]) >= 3
