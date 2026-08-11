from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: postfix marker mismatch: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# In PR B, GitHub run metadata is resolved by the dedicated prepare step. The
# NH source/recovery steps themselves only need R2. KFCC still carries the PR A
# token wiring until its own integration changes it.
replace_once(
    "tests/test_checkpoint_workflow_contract.py",
    '''def test_checkpoint_workflow_can_read_its_authenticated_run_metadata() -> None:\n    workflow = _workflow()\n    assert workflow["permissions"]["actions"] == "read"\n    for name in ("Collect NH local", "Collect KFCC"):\n        env = _step(name).get("env") or {}\n        assert env.get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"\n''',
    '''def test_checkpoint_workflow_can_read_its_authenticated_run_metadata() -> None:\n    workflow = _workflow()\n    assert workflow["permissions"]["actions"] == "read"\n    nh_prepare = _step("Prepare NH checkpoint context").get("env") or {}\n    assert nh_prepare.get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"\n    kfcc = _step("Collect KFCC").get("env") or {}\n    assert kfcc.get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"\n''',
)
replace_once(
    "tests/test_checkpoint_workflow_contract.py",
    '''def test_long_running_source_steps_receive_complete_r2_configuration() -> None:\n    for name in ("Collect NH local", "Collect KFCC"):\n        env = _step(name).get("env") or {}\n        assert set(env) >= R2_ENV_KEYS, f"{name} checkpoint R2 env 누락"\n        assert env.get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"\n        assert env.get("SCOPE") is not None\n''',
    '''def test_long_running_source_steps_receive_complete_r2_configuration() -> None:\n    for name in ("Collect NH local", "Recover NH local", "Collect KFCC"):\n        env = _step(name).get("env") or {}\n        assert set(env) >= R2_ENV_KEYS, f"{name} checkpoint R2 env 누락"\n    assert (_step("Collect NH local").get("env") or {}).get("SCOPE") is not None\n    assert (_step("Recover NH local").get("env") or {}).get("SCOPE") is not None\n    assert (_step("Collect KFCC").get("env") or {}).get("SCOPE") is not None\n    decision_env = _step("Decide NH recovery").get("env") or {}\n    assert set(decision_env) >= R2_ENV_KEYS\n''',
)

# Publish-only contract is about collector steps. Preparation helpers also carry
# the same guard but are not collectors and must not enlarge the equality set.
replace_once(
    "tests/test_gate_contract.py",
    '''    skipped = {\n        s["name"] for s in steps\n        if "PUBLISH_ONLY != 'true'" in str(s.get("if") or "")\n    }\n''',
    '''    skipped = {\n        s["name"]\n        for s in steps\n        if str(s.get("name", "")).startswith("Collect ")\n        and "PUBLISH_ONLY != 'true'" in str(s.get("if") or "")\n    }\n''',
)
