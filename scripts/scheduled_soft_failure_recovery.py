#!/usr/bin/env python3
"""Build a bounded recovery plan for soft-failed scheduled collectors.

Some collection steps intentionally use ``continue-on-error`` so one upstream outage
can preserve and publish the last confirmed value from that source while healthy
sources continue. A successful GitHub Actions job therefore does not prove every
attempted source succeeded.

This helper reads the immutable summary artifact produced by that exact scheduled
run, limits inspection to source attempts started during the parent workflow, and
maps any missing/unconfirmed soft source to the smallest authenticated recovery
scope. It never writes the canonical database itself.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIRMED_RUN_STATUSES = frozenset({"success", "partial", "no_change"})

GENERAL_WORKFLOW = "수집 — 일반·새마을금고"
FAST_WORKFLOW = "Collect bank rates fast"

GENERAL_SOFT_SOURCES = frozenset(
    {
        "finlife_bank",
        "bok_ecos",
        "bok_ecos_macro",
        "fsb",
        "cu",
    }
)
KFCC_SOFT_SOURCES = frozenset({"kfcc"})
FAST_SOFT_SOURCES = frozenset({"fsb"})

REFERENCE_SOURCES = frozenset({"finlife_bank", "bok_ecos", "bok_ecos_macro"})


class RecoveryPlanError(ValueError):
    """The parent evidence is insufficient to make a safe recovery decision."""


def _parse_time(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryPlanError(f"{label} must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryPlanError(f"{label} is not a valid ISO timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise RecoveryPlanError(f"{label} must include a timezone: {value!r}")
    return parsed


def _expected_sources(workflow: str, *, kfcc_only: bool | None) -> frozenset[str]:
    if workflow == FAST_WORKFLOW:
        return FAST_SOFT_SOURCES
    if workflow != GENERAL_WORKFLOW:
        raise RecoveryPlanError(f"unsupported workflow for soft recovery: {workflow!r}")
    if kfcc_only is None:
        raise RecoveryPlanError("general workflow requires an explicit kfcc_only decision")
    return KFCC_SOFT_SOURCES if kfcc_only else GENERAL_SOFT_SOURCES


def _targets_for_failures(failed_sources: set[str]) -> list[str]:
    targets: list[str] = []
    non_kfcc_groups: set[str] = set()

    if failed_sources & REFERENCE_SOURCES:
        non_kfcc_groups.add("reference")
    if "fsb" in failed_sources:
        non_kfcc_groups.add("savings")
    if "cu" in failed_sources:
        non_kfcc_groups.add("cu")

    known = set(REFERENCE_SOURCES) | {"fsb", "cu", "kfcc"}
    unknown = failed_sources - known
    if unknown:
        raise RecoveryPlanError(f"unmapped failed sources: {sorted(unknown)}")

    if len(non_kfcc_groups) > 1:
        # One general rerun is cheaper and safer than queueing several writers that
        # each restore and republish the same authoritative SQLite snapshot.
        targets.append("일반 전체")
    elif non_kfcc_groups == {"reference"}:
        targets.append("참고지표만")
    elif non_kfcc_groups == {"savings"}:
        targets.append("저축은행만")
    elif non_kfcc_groups == {"cu"}:
        targets.append("신협만")

    if "kfcc" in failed_sources:
        targets.append("새마을금고만")

    return targets


def build_recovery_plan(
    summary: dict[str, Any],
    *,
    workflow: str,
    run_started_at: str,
    kfcc_only: bool | None = None,
) -> dict[str, Any]:
    """Return failed sources and minimal workflow-dispatch recovery targets.

    Missing evidence is treated as a failure. If a soft collector crashed before it
    could persist its collection-run row, silently treating the absence as success
    would recreate the original blind spot.
    """

    parent_started = _parse_time(run_started_at, label="run_started_at")
    expected = _expected_sources(workflow, kfcc_only=kfcc_only)

    runs = summary.get("runs")
    if not isinstance(runs, list):
        raise RecoveryPlanError("summary.runs must be a list")

    attempts: dict[str, list[tuple[datetime, str, bool]]] = {
        source: [] for source in expected
    }
    for record in runs:
        if not isinstance(record, dict):
            continue
        source_id = record.get("source_id")
        if source_id not in expected:
            continue
        started = _parse_time(record.get("started_at"), label=f"{source_id}.started_at")
        if started < parent_started:
            continue
        status = record.get("status")
        if not isinstance(status, str) or not status:
            raise RecoveryPlanError(f"{source_id}.status is missing")
        raw_count = record.get("raw_count")
        parsed_count = record.get("parsed_count")
        empty_result = (
            isinstance(raw_count, int) and raw_count > 0
            and isinstance(parsed_count, int) and parsed_count == 0
        )
        attempts[source_id].append((started, status, empty_result))

    failed: set[str] = set()
    evidence: dict[str, dict[str, Any]] = {}
    for source_id in sorted(expected):
        source_attempts = sorted(attempts[source_id], key=lambda item: item[0])
        if not source_attempts:
            failed.add(source_id)
            evidence[source_id] = {"attempted": False, "status": None}
            continue

        latest_started, latest_status, latest_empty = source_attempts[-1]
        if latest_status not in CONFIRMED_RUN_STATUSES:
            failed.add(source_id)
        elif latest_empty:
            # 상태는 success인데 원본은 있고 파싱은 0건인 실행. 2026-09-11 04:14
            # KST 신협 136장 `[]`가 이 형태였고, 그때 이 계획은 "확인됨"으로
            # 보고 아무것도 재실행하지 않았다. 확인된 것이 아니다.
            failed.add(source_id)
        evidence[source_id] = {
            "attempted": True,
            "status": latest_status,
            "started_at": latest_started.isoformat(),
            "empty_result": latest_empty,
        }

    return {
        "workflow": workflow,
        "run_started_at": parent_started.isoformat(),
        "kfcc_only": kfcc_only,
        "expected_sources": sorted(expected),
        "failed_sources": sorted(failed),
        "targets": _targets_for_failures(failed),
        "evidence": evidence,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--run-started-at", required=True)
    parser.add_argument("--kfcc-only", choices=("true", "false"))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise RecoveryPlanError("summary root must be an object")
        kfcc_only = None if args.kfcc_only is None else args.kfcc_only == "true"
        plan = build_recovery_plan(
            summary,
            workflow=args.workflow,
            run_started_at=args.run_started_at,
            kfcc_only=kfcc_only,
        )
    except (OSError, json.JSONDecodeError, RecoveryPlanError) as exc:
        raise SystemExit(f"soft-failure recovery evidence invalid: {exc}") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
