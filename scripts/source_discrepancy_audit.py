#!/usr/bin/env python3
"""FSB ↔ 금융상품한눈에 ↔ 개별 저축은행 공식 evidence 교차검증 JSON을 만든다."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from rate_monitor.services.official_evidence_policy import (
    annotate_official_evidence_policy,
    write_prepared_official_evidence,
)
from rate_monitor.services.source_discrepancy_ambiguity_census import (
    annotate_payment_method_ambiguity_census,
)
from rate_monitor.services.source_discrepancy_service import write_source_discrepancy_report
from rate_monitor.services.source_discrepancy_triage import annotate_discrepancy_triage
from rate_monitor.services.source_official_contradiction_triage import (
    annotate_official_contradictions,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="감사할 SQLite DB")
    parser.add_argument("--out", default="work/source-discrepancy-report.json")
    parser.add_argument(
        "--triage-out",
        default=None,
        help="중요도순 mismatch 조사 queue JSON. canonical 값은 수정하지 않는다.",
    )
    parser.add_argument(
        "--official-contradiction-out",
        default=None,
        help="공식 evidence와 중앙 원천의 모순 queue JSON. canonical 값은 수정하지 않는다.",
    )
    parser.add_argument(
        "--decision-attention-out",
        default=None,
        help="금리 판단 전 우선 검토할 P0/P1 queue JSON. source authority는 선택하지 않는다.",
    )
    parser.add_argument("--primary-source", default="fsb")
    parser.add_argument("--secondary-source", default="finlife_savings_bank")
    parser.add_argument(
        "--official-evidence",
        default=None,
        help="개별 금융사 공식 홈페이지 증거 JSON. DB에는 쓰지 않는다.",
    )
    return parser


def _build_report(args: argparse.Namespace) -> dict[str, object]:
    official_path = Path(args.official_evidence) if args.official_evidence else None
    if official_path is None:
        return write_source_discrepancy_report(
            Path(args.db),
            Path(args.out),
            primary_source=args.primary_source,
            secondary_source=args.secondary_source,
        )

    with tempfile.TemporaryDirectory(prefix="rate-monitor-official-evidence-") as temp_dir:
        prepared_path = Path(temp_dir) / "official-evidence.json"
        write_prepared_official_evidence(official_path, prepared_path)
        return write_source_discrepancy_report(
            Path(args.db),
            Path(args.out),
            primary_source=args.primary_source,
            secondary_source=args.secondary_source,
            official_evidence_path=prepared_path,
        )


def _rewrite_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _write_named_queue(
    path: Path,
    report: dict[str, object],
    *,
    key: str,
) -> None:
    payload = {
        "generated_at": report.get("generated_at"),
        "source_runs": report.get("source_runs"),
        key: report[key],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _write_decision_attention(path: Path, report: dict[str, object]) -> None:
    census = report.get("ambiguity_census")
    census = census if isinstance(census, dict) else {}
    indicator = census.get("queue_masking_indicator")
    indicator = indicator if isinstance(indicator, dict) else {}
    items = census.get("items")
    items = items if isinstance(items, list) else []

    high_bands = {"ge_0.20pp", "ge_0.50pp", "ge_1.00pp"}
    masked = [
        item
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("blocked_delta"), dict)
        and item["blocked_delta"].get("blocked_risk_band") in high_bands
    ]

    def delta_key(item: dict[str, object]) -> tuple[float, str, str, int]:
        blocked = item.get("blocked_delta")
        blocked = blocked if isinstance(blocked, dict) else {}
        raw = blocked.get("max_absolute_delta")
        try:
            value = float(str(raw))
        except (TypeError, ValueError):
            value = -1.0
        return (
            -value,
            str(item.get("institution") or ""),
            str(item.get("product") or ""),
            int(item.get("term_months") or 0),
        )

    masked.sort(key=delta_key)
    payload = {
        "generated_at": report.get("generated_at"),
        "source_runs": report.get("source_runs"),
        "decision_attention": report["decision_attention"],
        "masked_payment_method_risk": {
            "semantics": (
                "not P0/P1 and not a proven source error; payment-method ambiguity "
                "blocks comparable triage, so resolve the variant before using these "
                "candidate gaps for a rate decision"
            ),
            "queue_masking_indicator": indicator,
            "high_risk_threshold": "blocked candidate max-rate gap >= 0.20pp",
            "high_risk_count": len(masked),
            "items": masked,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = build_parser().parse_args()
    out_path = Path(args.out)
    report = annotate_official_evidence_policy(_build_report(args))
    report = annotate_official_contradictions(report)
    report = annotate_discrepancy_triage(report)
    report = annotate_payment_method_ambiguity_census(
        report,
        db_path=Path(args.db),
    )
    _rewrite_report(out_path, report)

    if args.triage_out:
        _write_named_queue(Path(args.triage_out), report, key="triage")
    if args.official_contradiction_out:
        _write_named_queue(
            Path(args.official_contradiction_out),
            report,
            key="official_contradictions",
        )
    if args.decision_attention_out:
        _write_decision_attention(Path(args.decision_attention_out), report)

    summary = report["summary"]
    triage = report["triage"]
    triage_summary = triage["summary"]
    contradictions = report["official_contradictions"]
    contradiction_summary = contradictions["summary"]
    decision_attention = report["decision_attention"]
    decision_summary = decision_attention["summary"]
    census = report["ambiguity_census"]
    census_summary = census["summary"]
    masking = census["queue_masking_indicator"]
    print(f"report                    : {args.out}")
    if args.triage_out:
        print(f"triage queue              : {args.triage_out}")
    if args.official_contradiction_out:
        print(f"official contradiction    : {args.official_contradiction_out}")
    if args.decision_attention_out:
        print(f"decision attention        : {args.decision_attention_out}")
    print(f"primary products          : {summary['primary_products']}")
    print(f"secondary products        : {summary['secondary_products']}")
    print(f"exact matches             : {summary['exact_matches']}")
    print(f"max agree                 : {summary['agree']}")
    print(f"max agree / date differs  : {summary['agree_rate_date_diff']}")
    print(f"max agree / date unknown  : {summary['agree_rate_date_unknown']}")
    print(f"max mismatch              : {summary['rate_mismatch']}")
    print(f"max mismatch / date differs: {summary['rate_mismatch_date_diff']}")
    print(f"max mismatch / date unknown: {summary['rate_mismatch_date_unknown']}")
    print(f"max incomplete            : {summary['incomplete_rate']}")
    print(f"base agree                : {summary['base_rate_agree']}")
    print(f"base mismatch             : {summary['base_rate_mismatch']}")
    print(f"base incomplete           : {summary['base_rate_incomplete']}")
    print(f"base both missing         : {summary['base_rate_both_missing']}")
    print(f"unmatched variant         : {summary['unmatched_variant']}")
    print(f"unmatched product         : {summary['unmatched_product']}")
    print(f"source only               : {summary['source_only']}")
    print(f"official evidence         : {summary['official_evidence_records']}")
    print(f"official evidence groups  : {summary['official_evidence_groups']}")
    print(f"official internal conflicts: {summary['official_evidence_conflicts']}")
    print(
        "triage priorities          :",
        f"P0={triage_summary['P0']}",
        f"P1={triage_summary['P1']}",
        f"P2={triage_summary['P2']}",
        f"P3={triage_summary['P3']}",
    )
    print(
        "decision attention         :",
        f"queue={decision_summary['queue_size']}",
        f"P0={decision_summary['P0']}",
        f"P1={decision_summary['P1']}",
        f"direct={decision_summary['direct_rate_decision_risk_count']}",
    )
    print(
        "payment ambiguity census   :",
        f"blocked={census_summary['ambiguity_blocked_count']}",
        f"counterpart={census_summary['counterpart_coverage']}",
        f"risk_bands={census_summary['blocked_risk_bands']}",
    )
    print(
        "queue masking              :",
        f"comparable={masking['comparable_mismatch_count']}",
        f"blocked={masking['ambiguity_blocked_count']}",
        f"blocked_ge_0.20pp={masking['blocked_ge_0_20pp_count']}",
    )
    print(
        "official contradictions    :",
        f"queue={contradiction_summary['queue_size']}",
        f"P0={contradiction_summary['P0']}",
        f"P1={contradiction_summary['P1']}",
        f"consensus={contradiction_summary['source_consensus_contradictions']}",
    )
    for item in decision_attention["queue"]:
        print(
            "decision-attention",
            f"#{item['decision_rank']}",
            item["priority"],
            f"triage_rank={item['triage_rank']}",
            f"score={item['score']}",
            item["classification"],
            item["institution"],
            item["product"],
            f"term={item['term_months']}",
            f"variant={item['join_channel']}/{item['interest_method']}",
            f"delta={item['max_rate']['absolute_delta']}",
            f"direct={item['direct_rate_decision_risk']}",
            f"flags={item['decision_risk_flags']}",
        )
    for item in triage["queue"][:10]:
        print(
            "triage",
            f"#{item['rank']}",
            item["priority"],
            f"score={item['score']}",
            item["classification"],
            item["institution"],
            item["product"],
            f"term={item['term_months']}",
            f"variant={item['join_channel']}/{item['interest_method']}",
            f"delta={item['max_rate']['absolute_delta']}",
        )
    for item in contradictions["queue"][:10]:
        print(
            "official-contradiction",
            f"#{item['rank']}",
            item["priority"],
            f"score={item['score']}",
            item["classification"],
            item["institution"],
            item["official_product"],
            f"term={item['term_months']}",
            f"official={item['official_max_rates']}",
            f"consensus={item['source_consensus_max_rate']}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
