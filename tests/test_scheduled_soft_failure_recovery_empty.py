"""soft-recovery 계획이 "success인데 파싱 0건"을 확인된 수집으로 보지 않는 계약.

2026-09-10 19:57 UTC 복구 run 34523472120은 직전 정기 수집(34518603334)의
summary에서 신협 status=success(raw 136 / parsed 0)를 보고 target_count=0을 냈다.
그 뒤 정상 수집은 10시간 뒤 다른 이유(은행권 경량 수집 실패)의 복구로 우연히 됐다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path("scripts/scheduled_soft_failure_recovery.py")
SPEC = importlib.util.spec_from_file_location("scheduled_soft_failure_recovery_empty", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

build_recovery_plan = MODULE.build_recovery_plan
GENERAL_WORKFLOW = MODULE.GENERAL_WORKFLOW

PARENT_START = "2026-09-10T19:08:26+00:00"


def _run(source_id: str, status: str, started: str, *, raw: int, parsed: int) -> dict:
    return {
        "source_id": source_id,
        "status": status,
        "started_at": started,
        "raw_count": raw,
        "parsed_count": parsed,
    }


def _summary_2026_09_11_04_14() -> dict:
    return {
        "runs": [
            _run("cu", "success", "2026-09-11T04:11:59+09:00", raw=136, parsed=0),
            _run("fsb", "success", "2026-09-11T04:11:07+09:00", raw=13, parsed=3_754),
            _run("bok_ecos_macro", "no_change", "2026-09-11T04:11:02+09:00", raw=19, parsed=861),
            _run("bok_ecos", "no_change", "2026-09-11T04:11:00+09:00", raw=1, parsed=398),
            _run("finlife_bank", "success", "2026-09-11T04:10:58+09:00", raw=2, parsed=333),
        ]
    }


def test_success_with_raw_but_zero_parse_is_a_soft_failure_and_retries_cu_once() -> None:
    plan = build_recovery_plan(
        _summary_2026_09_11_04_14(),
        workflow=GENERAL_WORKFLOW,
        run_started_at=PARENT_START,
        kfcc_only=False,
    )

    assert plan["failed_sources"] == ["cu"]
    assert plan["targets"] == ["신협만"]
    assert plan["evidence"]["cu"] == {
        "attempted": True,
        "status": "success",
        "started_at": "2026-09-11T04:11:59+09:00",
        "empty_result": True,
    }


def test_healthy_success_is_still_confirmed() -> None:
    summary = _summary_2026_09_11_04_14()
    summary["runs"][0] = _run("cu", "success", "2026-09-11T15:30:54+09:00", raw=702, parsed=30_482)

    plan = build_recovery_plan(
        summary, workflow=GENERAL_WORKFLOW, run_started_at=PARENT_START, kfcc_only=False
    )

    assert plan["failed_sources"] == []
    assert plan["targets"] == []
    assert plan["evidence"]["cu"]["empty_result"] is False


def test_runs_without_counts_keep_the_status_only_contract() -> None:
    summary = {
        "runs": [
            {"source_id": s, "status": "success", "started_at": "2026-09-11T04:11:00+09:00"}
            for s in ("cu", "fsb", "bok_ecos", "bok_ecos_macro", "finlife_bank")
        ]
    }
    plan = build_recovery_plan(
        summary, workflow=GENERAL_WORKFLOW, run_started_at=PARENT_START, kfcc_only=False
    )
    assert plan["targets"] == []
