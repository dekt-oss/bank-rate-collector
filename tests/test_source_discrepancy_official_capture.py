from __future__ import annotations

import json
from pathlib import Path

from scripts.source_discrepancy_official_capture import (
    capture_evidence,
    finalize_capture_artifact,
)

DAISHIN_URL = "https://bank.daishin.com/sub.do?code=02_prod02"
DH_BRANCH_URL = "https://www.dhsavingsbank.co.kr/ProdList_001.act?rnum=17"

DAISHIN_HTML = """
<html><body>
<div>정기적금(정액식) 약정이율</div>
<table>
<tr><td>12 개월</td><td>4.00</td></tr>
<tr><td>24 개월</td><td>3.00</td></tr>
<tr><td>36 개월</td><td>3.00</td></tr>
</table>
<div>(기준일 : 2026-08-09 현재, %, 세전, 연이율)</div>
<div>중도해지이율</div>
</body></html>
""".encode()

DH_HTML = """
<html><body>
<div>금리정보표이며 기간, 약정이율 항목이 있습니다.</div>
<table>
<tr><th>기간</th><th>단리식(약정이율)</th><th>복리식(연평균수익률)</th></tr>
<tr><td>12개월</td><td>3.85</td><td>3.91</td></tr>
</table>
<div>우대조건</div>
</body></html>
""".encode()


def _report() -> dict[str, object]:
    return {
        "triage": {
            "queue": [
                {
                    "rank": 1,
                    "priority": "P1",
                    "classification": "stale_source",
                    "institution": "대신저축은행",
                    "product": "정기적금",
                    "product_type": "installment_savings",
                    "term_months": 24,
                    "join_channel": "any",
                    "interest_method": "simple",
                },
                {
                    "rank": 2,
                    "priority": "P3",
                    "classification": "freshness_gap",
                    "institution": "DH저축은행",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "join_channel": "branch",
                    "interest_method": "simple",
                },
                {
                    "rank": 3,
                    "priority": "P3",
                    "classification": "freshness_gap",
                    "institution": "DH저축은행",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "join_channel": "branch",
                    "interest_method": "compound",
                },
                {
                    "rank": 4,
                    "priority": "P3",
                    "classification": "freshness_gap",
                    "institution": "미설정저축은행",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "join_channel": "any",
                    "interest_method": "simple",
                },
            ]
        },
        "dimension_ambiguities": [],
    }


def _config() -> dict[str, object]:
    return json.loads(
        Path("config/source_discrepancy_official_targets.json").read_text(encoding="utf-8")
    )


def test_queue_capture_preserves_rate_semantics_and_unconfigured_coverage(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fetcher(url: str) -> dict[str, object]:
        calls.append(url)
        body = DAISHIN_HTML if url == DAISHIN_URL else DH_HTML
        return {
            "body": body,
            "status": 200,
            "final_url": url,
            "content_type": "text/html",
            "charset": "utf-8",
        }

    payload = capture_evidence(
        _report(),
        _config(),
        tmp_path / "raw",
        fetcher=fetcher,
        captured_at="2026-08-24T03:00:00+00:00",
        run_id="12345",
    )

    assert calls == [DAISHIN_URL, DH_BRANCH_URL]
    assert payload["coverage"] == {
        "queue_total": 4,
        "review_ambiguity_total": 0,
        "configured_references": 3,
        "unconfigured_references": 1,
        "configured_targets": 2,
        "successful_captures": 2,
        "failures": 0,
    }
    assert payload["unconfigured"][0]["institution"] == "미설정저축은행"
    assert payload["scope"]["canonical_mutated"] is False
    assert payload["scope"]["authority_selected"] is False

    records = payload["records"]
    daishin = next(record for record in records if record["institution"] == "대신저축은행")
    assert daishin["base_rate"] == "3.00"
    assert daishin["max_rate"] == "3.00"
    assert daishin["annualized_yield"] is None
    assert daishin["page_reference_date"] == "2026-08-09"
    assert daishin["effective_at"] is None
    assert daishin["rate_semantics"] == "nominal_contract_rate"
    assert daishin["raw_response_sha256"]

    dh_simple = next(
        record
        for record in records
        if record["institution"] == "DH저축은행"
        and record["interest_method"] == "simple"
    )
    assert dh_simple["base_rate"] == "3.85"
    assert dh_simple["annualized_yield"] is None
    assert dh_simple["join_channel"] == "branch"

    dh_compound = next(
        record
        for record in records
        if record["institution"] == "DH저축은행"
        and record["interest_method"] == "compound"
    )
    assert dh_compound["base_rate"] is None
    assert dh_compound["max_rate"] is None
    assert dh_compound["annualized_yield"] == "3.91"
    assert dh_compound["rate_semantics"] == (
        "annualized_yield_only; nominal_not_inferred"
    )


def test_finalize_adds_raw_artifact_identity_without_changing_authority(
    tmp_path: Path,
) -> None:
    def fetcher(url: str) -> dict[str, object]:
        body = DAISHIN_HTML if url == DAISHIN_URL else DH_HTML
        return {
            "body": body,
            "status": 200,
            "final_url": url,
            "content_type": "text/html",
            "charset": "utf-8",
        }

    payload = capture_evidence(
        _report(),
        _config(),
        tmp_path / "raw",
        fetcher=fetcher,
        captured_at="2026-08-24T03:00:00+00:00",
        run_id="12345",
    )
    finalized = finalize_capture_artifact(
        payload,
        artifact_id="9505000000",
        artifact_digest="sha256:abc123",
    )

    assert finalized["scope"]["capture_artifact_finalized"] is True
    assert finalized["scope"]["raw_capture_artifact_id"] == "9505000000"
    assert finalized["scope"]["raw_capture_artifact_sha256"] == "sha256:abc123"
    assert finalized["scope"]["canonical_mutated"] is False
    assert finalized["scope"]["authority_selected"] is False
    assert all(
        record["capture_artifact_id"] == "9505000000"
        for record in finalized["records"]
    )
    assert all(
        record["capture_artifact_sha256"] == "sha256:abc123"
        for record in finalized["records"]
    )
