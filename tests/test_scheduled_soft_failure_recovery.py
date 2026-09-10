from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path("scripts/scheduled_soft_failure_recovery.py")
SPEC = importlib.util.spec_from_file_location("scheduled_soft_failure_recovery", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

build_recovery_plan = MODULE.build_recovery_plan
RecoveryPlanError = MODULE.RecoveryPlanError
GENERAL_WORKFLOW = MODULE.GENERAL_WORKFLOW
FAST_WORKFLOW = MODULE.FAST_WORKFLOW

PARENT_START = "2026-09-10T00:00:00+00:00"


def _summary(*runs: tuple[str, str, str]) -> dict:
    return {
        "runs": [
            {"source_id": source, "status": status, "started_at": started_at}
            for source, status, started_at in runs
        ]
    }


def test_clean_general_success_needs_no_recovery() -> None:
    summary = _summary(
        ("finlife_bank", "success", "2026-09-10T09:00:01+09:00"),
        ("bok_ecos", "success", "2026-09-10T09:00:02+09:00"),
        ("bok_ecos_macro", "no_change", "2026-09-10T09:00:03+09:00"),
        ("fsb", "partial", "2026-09-10T09:00:04+09:00"),
        ("cu", "success", "2026-09-10T09:00:05+09:00"),
    )

    plan = build_recovery_plan(
        summary,
        workflow=GENERAL_WORKFLOW,
        run_started_at=PARENT_START,
        kfcc_only=False,
    )

    assert plan["failed_sources"] == []
    assert plan["targets"] == []


def test_reference_soft_failure_gets_reference_only_recovery() -> None:
    summary = _summary(
        ("finlife_bank", "success", "2026-09-10T09:00:01+09:00"),
        ("bok_ecos", "failed", "2026-09-10T09:00:02+09:00"),
        ("bok_ecos_macro", "no_change", "2026-09-10T09:00:03+09:00"),
        ("fsb", "success", "2026-09-10T09:00:04+09:00"),
        ("cu", "success", "2026-09-10T09:00:05+09:00"),
    )

    plan = build_recovery_plan(
        summary,
        workflow=GENERAL_WORKFLOW,
        run_started_at=PARENT_START,
        kfcc_only=False,
    )

    assert plan["failed_sources"] == ["bok_ecos"]
    assert plan["targets"] == ["참고지표만"]


def test_multiple_non_kfcc_failure_groups_collapse_to_one_general_writer() -> None:
    summary = _summary(
        ("finlife_bank", "success", "2026-09-10T09:00:01+09:00"),
        ("bok_ecos", "success", "2026-09-10T09:00:02+09:00"),
        ("bok_ecos_macro", "success", "2026-09-10T09:00:03+09:00"),
        ("fsb", "failed", "2026-09-10T09:00:04+09:00"),
        ("cu", "failed", "2026-09-10T09:00:05+09:00"),
    )

    plan = build_recovery_plan(
        summary,
        workflow=GENERAL_WORKFLOW,
        run_started_at=PARENT_START,
        kfcc_only=False,
    )

    assert plan["failed_sources"] == ["cu", "fsb"]
    assert plan["targets"] == ["일반 전체"]


def test_kfcc_retry_success_supersedes_first_failed_attempt() -> None:
    summary = _summary(
        ("kfcc", "failed", "2026-09-10T09:00:01+09:00"),
        ("kfcc", "success", "2026-09-10T09:10:01+09:00"),
    )

    plan = build_recovery_plan(
        summary,
        workflow=GENERAL_WORKFLOW,
        run_started_at=PARENT_START,
        kfcc_only=True,
    )

    assert plan["failed_sources"] == []
    assert plan["targets"] == []


def test_kfcc_terminal_soft_failure_gets_kfcc_only_recovery() -> None:
    summary = _summary(("kfcc", "failed", "2026-09-10T09:00:01+09:00"))

    plan = build_recovery_plan(
        summary,
        workflow=GENERAL_WORKFLOW,
        run_started_at=PARENT_START,
        kfcc_only=True,
    )

    assert plan["failed_sources"] == ["kfcc"]
    assert plan["targets"] == ["새마을금고만"]


def test_fast_fsb_soft_failure_gets_savings_only_recovery() -> None:
    summary = _summary(("fsb", "failed", "2026-09-10T09:00:01+09:00"))

    plan = build_recovery_plan(
        summary,
        workflow=FAST_WORKFLOW,
        run_started_at=PARENT_START,
    )

    assert plan["failed_sources"] == ["fsb"]
    assert plan["targets"] == ["저축은행만"]


def test_missing_current_attempt_fails_closed_instead_of_becoming_false_green() -> None:
    summary = _summary(
        ("finlife_bank", "success", "2026-09-10T09:00:01+09:00"),
        ("bok_ecos", "success", "2026-09-10T09:00:02+09:00"),
        ("bok_ecos_macro", "success", "2026-09-10T09:00:03+09:00"),
        ("fsb", "success", "2026-09-10T09:00:04+09:00"),
        # CU row missing: treat it as a failed attempted source.
    )

    plan = build_recovery_plan(
        summary,
        workflow=GENERAL_WORKFLOW,
        run_started_at=PARENT_START,
        kfcc_only=False,
    )

    assert plan["failed_sources"] == ["cu"]
    assert plan["targets"] == ["신협만"]
    assert plan["evidence"]["cu"] == {"attempted": False, "status": None}


def test_old_failure_before_parent_start_is_not_current_run_evidence() -> None:
    summary = _summary(
        ("fsb", "failed", "2026-09-09T08:59:59+09:00"),
        ("fsb", "success", "2026-09-10T09:00:01+09:00"),
    )

    plan = build_recovery_plan(
        summary,
        workflow=FAST_WORKFLOW,
        run_started_at=PARENT_START,
    )

    assert plan["failed_sources"] == []
    assert plan["targets"] == []


def test_general_workflow_requires_explicit_schedule_scope() -> None:
    with pytest.raises(RecoveryPlanError, match="kfcc_only"):
        build_recovery_plan(
            {"runs": []},
            workflow=GENERAL_WORKFLOW,
            run_started_at=PARENT_START,
        )
