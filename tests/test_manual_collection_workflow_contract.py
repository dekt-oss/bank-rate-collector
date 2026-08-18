from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / ".github" / "workflows" / "collect.yml"
NH_PATH = ROOT / ".github" / "workflows" / "collect-nh.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def _dispatch_inputs(path: Path) -> dict:
    return _triggers(_load(path))["workflow_dispatch"]["inputs"]


def _step(workflow: dict, name: str) -> dict:
    return next(
        step for step in workflow["jobs"]["collect"]["steps"] if step.get("name") == name
    )


def test_core_manual_dispatch_uses_positive_presets() -> None:
    workflow = _load(CORE_PATH)
    inputs = _dispatch_inputs(CORE_PATH)

    assert workflow["name"] == "수집 — 일반·새마을금고"
    assert set(inputs) == {
        "password",
        "manual_target",
        "kfcc_scope",
        "kfcc_resume_mode",
        "accept_volume_drop",
    }
    assert inputs["manual_target"]["default"] == "일반 전체"
    assert inputs["manual_target"]["options"] == [
        "일반 전체",
        "저축은행만",
        "신협만",
        "새마을금고만",
        "참고지표만",
        "화면만 재발행",
    ]

    text = CORE_PATH.read_text(encoding="utf-8")
    assert "inputs.skip_" not in text
    assert "inputs.groups" not in text
    assert "inputs.publish_only" not in text
    assert "--groups 030300" in text


def test_core_manual_presets_route_to_expected_source_groups() -> None:
    workflow = _load(CORE_PATH)

    savings = str(_step(workflow, "Collect finlife savings bank")["if"])
    fsb = str(_step(workflow, "Collect FSB")["if"])
    cu = str(_step(workflow, "Collect CU")["if"])
    bank = str(_step(workflow, "Collect finlife bank")["if"])
    bok = str(_step(workflow, "Collect BOK base rate")["if"])
    kfcc = str(_step(workflow, "Collect KFCC")["if"])

    for condition in (savings, fsb):
        assert "일반 전체" in condition
        assert "저축은행만" in condition
    assert "일반 전체" in cu and "신협만" in cu
    for condition in (bank, bok):
        assert "일반 전체" in condition
        assert "참고지표만" in condition
    assert "SKIP_KFCC_THIS_RUN" in kfcc


def test_nh_manual_dispatch_is_separate_with_safe_defaults() -> None:
    workflow = _load(NH_PATH)
    inputs = _dispatch_inputs(NH_PATH)

    assert workflow["name"] == "수집 — 농·축협"
    assert set(inputs) == {
        "password",
        "nh_local_scope",
        "nh_resume_mode",
        "accept_volume_drop",
    }
    assert inputs["nh_local_scope"]["default"] == "전국"
    assert inputs["nh_local_scope"]["options"] == ["전국", "수도권", "부산"]
    assert inputs["nh_resume_mode"]["default"] == "auto"
    assert inputs["nh_resume_mode"]["options"] == ["auto", "fresh"]
    assert inputs["accept_volume_drop"]["default"] is False
