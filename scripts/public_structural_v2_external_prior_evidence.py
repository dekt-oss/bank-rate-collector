from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.services.public_structural_v2_external_prior_evidence import (
    PRIMARY_RATE_CODE,
    build_external_prior_evidence,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Public Structural v2 Stage I 공개자료 Evidence Gate"
    )
    parser.add_argument("--db", required=True, help="read-only 분석 대상 SQLite DB")
    parser.add_argument("--json-out", required=True, help="상세 JSON artifact 경로")
    parser.add_argument("--md-out", required=True, help="요약 Markdown artifact 경로")
    return parser.parse_args()


def _summary(evidence: dict[str, Any]) -> dict[str, Any]:
    coverage = evidence.get("coverage") or {}
    rate_coverage = (coverage.get("rate_signals") or {}).get(PRIMARY_RATE_CODE) or {}
    screens = evidence.get("temporal_oos_screen") or {}
    repo = (evidence.get("repo_market_history") or {}).get("sectors") or {}
    return {
        "version": evidence.get("version"),
        "status": evidence.get("status"),
        "coefficient_change": (evidence.get("gate") or {}).get("coefficient_change"),
        "public_prior_role": (evidence.get("gate") or {}).get("public_prior_role"),
        "primary_rate_months": rate_coverage.get("point_count", 0),
        "primary_rate_first_month": rate_coverage.get("first_month"),
        "primary_rate_last_month": rate_coverage.get("last_month"),
        "sector_temporal_screens": {
            sector: {
                "aligned_pairs": details.get("best_primary_rate_aligned_pair_count"),
                "aggregate_temporal_split_feasible": details.get(
                    "aggregate_temporal_split_feasible"
                ),
            }
            for sector, details in screens.items()
        },
        "repo_market_distinct_months": {
            sector: details.get("distinct_calendar_months") for sector, details in repo.items()
        },
        "blocking_reasons": (evidence.get("gate") or {}).get("blocking_reasons", []),
    }


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Public Structural v2 Stage I — External Prior Evidence",
        "",
        f"- status: `{summary.get('status')}`",
        f"- coefficient change: **{summary.get('coefficient_change')}**",
        f"- public prior role: `{summary.get('public_prior_role')}`",
        (
            "- primary bank rate coverage: "
            f"{summary.get('primary_rate_months')} months "
            f"({summary.get('primary_rate_first_month')} ~ "
            f"{summary.get('primary_rate_last_month')})"
        ),
        "",
        "## Aggregate temporal screen",
        "",
    ]
    for sector, details in (summary.get("sector_temporal_screens") or {}).items():
        lines.append(
            f"- {sector}: aligned pairs={details.get('aligned_pairs')}, "
            "24m+12m split feasible="
            f"{details.get('aggregate_temporal_split_feasible')}"
        )
    lines.extend(
        [
            "",
            "## Repository market-history coverage",
            "",
        ]
    )
    for sector, months in (summary.get("repo_market_distinct_months") or {}).items():
        lines.append(f"- {sector}: distinct calendar months={months}")
    lines.extend(["", "## Blocking reasons", ""])
    for reason in summary.get("blocking_reasons") or []:
        lines.append(f"- `{reason}`")
    lines.extend(
        [
            "",
            "> 이 결과는 공개 집계시계열의 기술적 context다. 인과효과, 은행별 탄력성, "
            "신규자금/재예치 계수의 추정 또는 검증을 의미하지 않는다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = _args()
    db_path = Path(args.db)
    if not db_path.is_file():
        raise SystemExit(f"DB가 없다: {db_path}")

    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        evidence = build_external_prior_evidence(conn)
    finally:
        conn.close()

    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = _summary(evidence)
    md_out.write_text(_markdown(summary), encoding="utf-8")
    print("STAGE_I_EXTERNAL_PRIOR_SUMMARY=" + json.dumps(summary, ensure_ascii=False))

    if (evidence.get("gate") or {}).get("coefficient_change") != "NO_GO":
        raise SystemExit("Stage I는 검증되지 않은 coefficient 변경을 허용하지 않는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
