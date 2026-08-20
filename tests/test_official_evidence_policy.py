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
