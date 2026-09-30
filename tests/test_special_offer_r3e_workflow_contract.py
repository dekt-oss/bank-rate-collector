"""R3-E production writer activation contract.

The Radar current tab intentionally accepts only same-day confirmed_active evidence.
A daily writer is therefore the minimum schedule that can keep the operational
"currently on sale" surface populated without weakening freshness semantics.
"""

import datetime as dt
from pathlib import Path

import yaml

COLLECT = Path(".github/workflows/collect.yml")
REFRESH = Path(".github/workflows/special-offer-catalog-refresh.yml")


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML 1.1 may parse the key `on` as boolean True.
    return workflow.get("on", workflow.get(True))


def test_special_offer_refresh_reuses_single_writer_pipeline() -> None:
    collect = COLLECT.read_text(encoding="utf-8")
    refresh = REFRESH.read_text(encoding="utf-8")

    assert "SPECIAL_OFFER_ONLY: ${{ inputs.manual_target == '특판만' }}" in collect
    assert "scripts/special_offer_catalog_refresh.py" in collect
    assert "if: ${{ env.SPECIAL_OFFER_ONLY == 'true' }}" in collect
    assert 'if [ "${PUBLISH_ONLY}" = "true" ]; then' in collect
    assert 'elif [ "${SPECIAL_OFFER_ONLY}" = "true" ]; then' in collect
    assert (
        "if: steps.storage.outputs.backend != 'github_legacy' "
        "&& env.PUBLISH_ONLY != 'true'"
    ) in collect

    assert "uses: ./.github/workflows/collect.yml" in refresh
    assert 'manual_target: "특판만"' in refresh


def test_special_offer_refresh_runs_daily_at_0817_kst() -> None:
    triggers = _triggers(_workflow(REFRESH))
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    schedules = triggers["schedule"]
    assert [item["cron"] for item in schedules] == ["17 23 * * *"]

    kst = dt.timezone(dt.timedelta(hours=9))
    for day in range(1, 8):
        utc = dt.datetime(2026, 10, day, 23, 17, tzinfo=dt.UTC)
        local = utc.astimezone(kst)
        assert (local.hour, local.minute) == (8, 17)
        assert local.date() == (utc + dt.timedelta(days=1)).date()


def test_special_offer_manual_refresh_requires_and_forwards_password() -> None:
    refresh = _workflow(REFRESH)
    collect = _workflow(COLLECT)

    refresh_dispatch = _triggers(refresh)["workflow_dispatch"]
    password = refresh_dispatch["inputs"]["password"]
    assert password["required"] is True

    call_inputs = _triggers(collect)["workflow_call"]["inputs"]
    assert call_inputs["password"] == {
        "description": "wrapper workflow에서 전달하는 관리자 수집 암호",
        "type": "string",
        "required": False,
        "default": "",
    }
    assert call_inputs["require_password"] == {
        "description": "wrapper 수동 실행이면 관리자 수집 암호 검증을 강제",
        "type": "boolean",
        "required": False,
        "default": False,
    }

    refresh_with = refresh["jobs"]["refresh"]["with"]
    assert refresh_with["password"] == "${{ inputs.password || '' }}"
    assert refresh_with["require_password"] == "${{ github.event_name == 'workflow_dispatch' }}"
    assert refresh_with["manual_target"] == "특판만"

    collect_text = COLLECT.read_text(encoding="utf-8")
    assert (
        "if: ${{ github.event_name == 'workflow_dispatch' || inputs.require_password }}"
        in collect_text
    )
    assert "GIVEN: ${{ inputs.password }}" in collect_text
