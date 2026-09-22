from __future__ import annotations

from rate_monitor.services.official_evidence_policy import (
    annotate_official_evidence_policy,
    prepare_official_evidence_payload,
)


def _source(status: str) -> dict[str, object]:
    return {
        "record": {"source_id": "fsb"},
        "base_rate_comparison": {"status": status},
        "max_rate_comparison": {"status": status},
    }


def test_prepare_manual_evidence_alias_preserves_official_product() -> None:
    payload = {
        "records": [
            {
                "evidence_id": "debec-apple-12m",
                "institution": "대백저축은행",
                "product": "애플정기예금복리식(인터넷뱅킹)",
                "comparison_product": "애플정기예금",
                "product_type": "term_deposit",
                "term_months": 12,
                "captured_at": "2026-08-20T11:30:00+09:00",
                "url": "https://example.invalid/debec",
            }
        ]
    }

    prepared = prepare_official_evidence_payload(payload)
    record = prepared["records"][0]

    assert record["product"] == "애플정기예금"
    assert record["official_product"] == "애플정기예금복리식(인터넷뱅킹)"
    assert record["comparison_product"] == "애플정기예금"
    assert record["evidence_match_method"] == "manual_evidence_alias"


def test_official_internal_conflict_blocks_source_authority_signal() -> None:
    report = {
        "generated_at": "2026-08-21T00:00:00+09:00",
        "scope": {"canonical_mutated": False},
        "summary": {"official_evidence_records": 2},
        "official_evidence": [
            {
                "official": {
                    "evidence_id": "page",
                    "evidence_group": "kiwoomyes:e-revolving:12m",
                    "institution": "키움예스저축은행",
                    "official_product": "e-회전yes정기예금",
                    "product": "e-회전yes정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "base_rate": "3.90",
                    "max_rate": "3.90",
                    "captured_at": "2026-08-20T11:30:00+09:00",
                    "url": "https://example.invalid/product",
                },
                "sources": {"primary": _source("mismatch"), "secondary": _source("agree")},
            },
            {
                "official": {
                    "evidence_id": "notice",
                    "evidence_group": "kiwoomyes:e-revolving:12m",
                    "institution": "키움예스저축은행",
                    "official_product": "e-회전yes정기예금",
                    "product": "e-회전yes정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "base_rate": "4.05",
                    "max_rate": "4.05",
                    "effective_at": "2026-08-10",
                    "captured_at": "2026-08-20T11:30:00+09:00",
                    "url": "https://example.invalid/notice",
                },
                "sources": {"primary": _source("agree"), "secondary": _source("mismatch")},
            },
        ],
    }

    annotated = annotate_official_evidence_policy(report)
    group = annotated["official_evidence_groups"][0]

    assert group["status"] == "conflict"
    assert group["conflict_fields"] == ["base_rate", "max_rate"]
    assert group["source_support"] == {
        "primary": "blocked_by_official_conflict",
        "secondary": "blocked_by_official_conflict",
    }
    assert group["reconciliation_signal"] == "official_conflict"
    assert annotated["summary"]["official_evidence_conflicts"] == 1
    assert annotated["scope"]["official_conflict_blocks_authority"] is True


def test_official_conflict_blocks_authority_even_without_source_match() -> None:
    report = {
        "generated_at": "2026-08-21T00:00:00+09:00",
        "scope": {"canonical_mutated": False},
        "summary": {"official_evidence_records": 2},
        "official_evidence": [
            {
                "official": {
                    "evidence_id": "page",
                    "evidence_group": "unknown:product:12m",
                    "institution": "테스트저축은행",
                    "official_product": "공식상품",
                    "product": "공식상품",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "base_rate": "3.90",
                    "max_rate": "3.90",
                    "captured_at": "2026-08-20T11:30:00+09:00",
                    "url": "https://example.invalid/product",
                },
                "sources": {"primary": None, "secondary": None},
            },
            {
                "official": {
                    "evidence_id": "notice",
                    "evidence_group": "unknown:product:12m",
                    "institution": "테스트저축은행",
                    "official_product": "공식상품",
                    "product": "공식상품",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "base_rate": "4.05",
                    "max_rate": "4.05",
                    "captured_at": "2026-08-20T11:30:00+09:00",
                    "url": "https://example.invalid/notice",
                },
                "sources": {"primary": None, "secondary": None},
            },
        ],
    }

    group = annotate_official_evidence_policy(report)["official_evidence_groups"][0]

    assert group["status"] == "conflict"
    assert group["source_support"] == {
        "primary": "blocked_by_official_conflict",
        "secondary": "blocked_by_official_conflict",
    }
    assert group["reconciliation_signal"] == "official_conflict"


def test_consistent_official_group_can_support_one_source_without_overwrite() -> None:
    report = {
        "generated_at": "2026-08-21T00:00:00+09:00",
        "scope": {"canonical_mutated": False},
        "summary": {"official_evidence_records": 1},
        "official_evidence": [
            {
                "official": {
                    "evidence_id": "cheongju-12m",
                    "evidence_group": "cheongju:installment:12m",
                    "institution": "청주저축은행",
                    "official_product": "정기적금",
                    "product": "정기적금",
                    "product_type": "installment_savings",
                    "term_months": 12,
                    "base_rate": "3.80",
                    "max_rate": "3.80",
                    "effective_at": "2026-06-18",
                    "captured_at": "2026-08-20T11:30:00+09:00",
                    "url": "https://example.invalid/cheongju",
                },
                "sources": {"primary": _source("agree"), "secondary": _source("mismatch")},
            }
        ],
    }

    annotated = annotate_official_evidence_policy(report)
    group = annotated["official_evidence_groups"][0]

    assert group["status"] == "consistent"
    assert group["source_support"] == {
        "primary": "supported",
        "secondary": "not_supported",
    }
    assert group["reconciliation_signal"] == "primary_supported"
    assert annotated["scope"]["canonical_mutated"] is False
    assert annotated["scope"]["official_evidence_authority"] == "read_only_support_only"


def test_stale_official_evidence_is_preserved_but_not_current_support() -> None:
    report = {
        "generated_at": "2026-09-22T00:00:00+09:00",
        "scope": {"canonical_mutated": False},
        "summary": {"official_evidence_records": 1},
        "official_evidence": [
            {
                "official": {
                    "evidence_id": "stale-page",
                    "evidence_group": "test:stale:12m",
                    "institution": "테스트저축은행",
                    "official_product": "정기예금",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "base_rate": "4.00",
                    "max_rate": "4.00",
                    "captured_at": "2026-08-23T12:00:00+09:00",
                    "url": "https://example.invalid/stale",
                },
                "sources": {
                    "primary": _source("agree"),
                    "secondary": _source("mismatch"),
                },
            }
        ],
    }

    annotated = annotate_official_evidence_policy(report)
    group = annotated["official_evidence_groups"][0]
    record = group["records"][0]

    assert group["status"] == "consistent"
    assert group["freshness_status"] == "stale"
    assert group["current_status"] == "no_current_evidence"
    assert group["current_support_records"] == 0
    assert group["source_support"] == {
        "primary": "stale_evidence",
        "secondary": "stale_evidence",
    }
    assert group["reconciliation_signal"] == "stale_official_evidence"
    assert record["freshness"]["captured_age_days"] == 30
    assert record["freshness"]["current_support_eligible"] is False
    assert record["freshness"]["current_support_reason"] == "captured_age_ge_30d"
    assert annotated["summary"]["official_evidence_stale_groups"] == 1
    assert annotated["summary"]["official_stale_signal_groups"] == 1


def test_future_captured_at_fails_closed_as_unknown() -> None:
    report = {
        "generated_at": "2026-09-22T00:00:00+09:00",
        "scope": {"canonical_mutated": False},
        "summary": {"official_evidence_records": 1},
        "official_evidence": [
            {
                "official": {
                    "evidence_id": "future-page",
                    "evidence_group": "test:future:12m",
                    "institution": "테스트저축은행",
                    "official_product": "정기예금",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "base_rate": "4.00",
                    "max_rate": "4.00",
                    "captured_at": "2026-09-23T12:00:00+09:00",
                    "url": "https://example.invalid/future",
                },
                "sources": {
                    "primary": _source("agree"),
                    "secondary": _source("mismatch"),
                },
            }
        ],
    }

    annotated = annotate_official_evidence_policy(report)
    group = annotated["official_evidence_groups"][0]
    freshness = group["records"][0]["freshness"]

    assert group["freshness_status"] == "unknown"
    assert group["current_status"] == "no_current_evidence"
    assert group["reconciliation_signal"] == "insufficient_official_evidence"
    assert freshness["captured_at_known"] is True
    assert freshness["captured_age_days"] is None
    assert freshness["status"] == "unknown"
    assert freshness["current_support_eligible"] is False
    assert freshness["current_support_reason"] == "captured_at_in_future"


def test_official_evidence_younger_than_30_days_remains_current_support() -> None:
    report = {
        "generated_at": "2026-09-21T00:00:00+09:00",
        "scope": {"canonical_mutated": False},
        "summary": {"official_evidence_records": 1},
        "official_evidence": [
            {
                "official": {
                    "evidence_id": "current-page",
                    "evidence_group": "test:current:12m",
                    "institution": "테스트저축은행",
                    "official_product": "정기예금",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "base_rate": "4.00",
                    "max_rate": "4.00",
                    "captured_at": "2026-08-23T12:00:00+09:00",
                    "url": "https://example.invalid/current",
                },
                "sources": {
                    "primary": _source("agree"),
                    "secondary": _source("mismatch"),
                },
            }
        ],
    }

    annotated = annotate_official_evidence_policy(report)
    group = annotated["official_evidence_groups"][0]

    assert group["freshness_status"] == "current"
    assert group["current_status"] == "consistent"
    assert group["current_support_records"] == 1
    assert group["source_support"] == {
        "primary": "supported",
        "secondary": "not_supported",
    }
    assert group["reconciliation_signal"] == "primary_supported"
    assert group["records"][0]["freshness"]["captured_age_days"] == 29
    assert group["records"][0]["freshness"]["current_support_eligible"] is True


def test_stale_record_does_not_create_current_conflict_in_mixed_group() -> None:
    report = {
        "generated_at": "2026-09-22T00:00:00+09:00",
        "scope": {"canonical_mutated": False},
        "summary": {"official_evidence_records": 2},
        "official_evidence": [
            {
                "official": {
                    "evidence_id": "old-notice",
                    "evidence_group": "test:mixed:12m",
                    "institution": "테스트저축은행",
                    "official_product": "정기예금",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "base_rate": "3.90",
                    "max_rate": "3.90",
                    "captured_at": "2026-08-20T12:00:00+09:00",
                    "url": "https://example.invalid/old",
                },
                "sources": {
                    "primary": _source("mismatch"),
                    "secondary": _source("agree"),
                },
            },
            {
                "official": {
                    "evidence_id": "fresh-page",
                    "evidence_group": "test:mixed:12m",
                    "institution": "테스트저축은행",
                    "official_product": "정기예금",
                    "product": "정기예금",
                    "product_type": "term_deposit",
                    "term_months": 12,
                    "base_rate": "4.00",
                    "max_rate": "4.00",
                    "captured_at": "2026-09-21T12:00:00+09:00",
                    "url": "https://example.invalid/fresh",
                },
                "sources": {
                    "primary": _source("agree"),
                    "secondary": None,
                },
            },
        ],
    }

    annotated = annotate_official_evidence_policy(report)
    group = annotated["official_evidence_groups"][0]

    assert group["status"] == "conflict"
    assert group["conflict_fields"] == ["base_rate", "max_rate"]
    assert group["freshness_status"] == "mixed"
    assert group["current_status"] == "consistent"
    assert group["current_conflict_fields"] == []
    assert group["current_official_max_rates"] == ["4.00"]
    assert group["current_support_records"] == 1
    assert group["source_support"] == {
        "primary": "supported",
        "secondary": "not_matched",
    }
    assert group["reconciliation_signal"] == "primary_supported"
