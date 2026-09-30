from __future__ import annotations

import pytest

from scripts.morning_failure_recovery_plan import (
    MorningRecoveryPlanError,
    determine_start_stage,
)


def _jobs(*, nh: str | None, funding: str | None, market: str | None):
    rows = []
    for name, conclusion in (
        ("nh / surface", nh),
        ("funding / collect", funding),
        ("market / collect", market),
    ):
        if conclusion is not None:
            rows.append({"name": name, "conclusion": conclusion})
    return rows


@pytest.mark.parametrize(
    ("jobs", "expected"),
    [
        (_jobs(nh="failure", funding=None, market=None), "nh"),
        (_jobs(nh="success", funding="failure", market=None), "funding"),
        (_jobs(nh="success", funding="success", market="failure"), "market"),
        (_jobs(nh="cancelled", funding=None, market=None), "nh"),
        (_jobs(nh="success", funding=None, market=None), "funding"),
        (_jobs(nh="success", funding="success", market=None), "market"),
    ],
)
def test_first_non_success_stage_is_recovered(jobs, expected) -> None:
    start_stage, conclusions = determine_start_stage(jobs)

    assert start_stage == expected
    assert set(conclusions) == {"nh", "funding", "market"}


def test_all_success_fails_closed_instead_of_replaying_collection() -> None:
    with pytest.raises(MorningRecoveryPlanError, match="all succeeded"):
        determine_start_stage(_jobs(nh="success", funding="success", market="success"))


def test_duplicate_stage_evidence_fails_closed() -> None:
    jobs = _jobs(nh="success", funding="failure", market=None)
    jobs.append({"name": "funding / collect", "conclusion": "success"})

    with pytest.raises(MorningRecoveryPlanError, match="ambiguous"):
        determine_start_stage(jobs)
