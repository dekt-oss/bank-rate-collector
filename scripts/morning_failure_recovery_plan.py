"""Plan the remaining morning collection suffix from immutable parent job evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED_STAGE_JOBS = {
    "nh": "nh / surface",
    "funding": "funding / collect",
    "market": "market / collect",
}


class MorningRecoveryPlanError(RuntimeError):
    """Parent job evidence cannot prove a safe collection recovery suffix."""


def determine_start_stage(jobs: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    conclusions: dict[str, str] = {}

    for stage, job_name in EXPECTED_STAGE_JOBS.items():
        matches = [job.get("conclusion") for job in jobs if job.get("name") == job_name]
        if len(matches) > 1:
            raise MorningRecoveryPlanError(
                f"ambiguous morning recovery evidence: {job_name} count={len(matches)}"
            )
        conclusions[stage] = str(matches[0]) if matches and matches[0] else "not_run"

    if conclusions["nh"] != "success":
        return "nh", conclusions
    if conclusions["funding"] != "success":
        return "funding", conclusions
    if conclusions["market"] != "success":
        return "market", conclusions

    raise MorningRecoveryPlanError(
        "morning parent failed but nh/funding/market all succeeded; "
        "refusing unproven collection replay"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.jobs_json.read_text(encoding="utf-8"))
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise MorningRecoveryPlanError("GitHub jobs payload does not contain a jobs list")

    start_stage, conclusions = determine_start_stage(jobs)
    print(
        "morning recovery evidence="
        f"{json.dumps(conclusions, ensure_ascii=False, sort_keys=True)} "
        f"start_stage={start_stage}"
    )
    with args.github_output.open("a", encoding="utf-8") as fh:
        fh.write(f"start_stage={start_stage}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
