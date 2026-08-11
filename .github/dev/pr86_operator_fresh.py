from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: marker mismatch: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# A same-day complete/terminal checkpoint intentionally blocks auto resume. Give a
# workflow_dispatch operator an explicit fresh escape hatch without weakening schedule.
replace_once(
    ".github/workflows/collect.yml",
    '''      nh_local_scope:
        description: "농·축협 수집 범위. 전국은 실측 3시간 37분입니다"
        type: choice
        required: false
        default: "전국"
        options: ["전국", "수도권", "부산"]
''',
    '''      nh_local_scope:
        description: "농·축협 수집 범위. 전국은 실측 3시간 37분입니다"
        type: choice
        required: false
        default: "전국"
        options: ["전국", "수도권", "부산"]
      nh_resume_mode:
        description: "농·축협 checkpoint. 보통 auto, 같은 날 새로 받으려면 fresh"
        type: choice
        required: false
        default: "auto"
        options: ["auto", "fresh"]
''',
)
replace_once(
    ".github/workflows/collect.yml",
    '''        env:
          SCOPE: ${{ inputs.nh_local_scope }}
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
''',
    '''        env:
          SCOPE: ${{ inputs.nh_local_scope }}
          RESUME_MODE: ${{ inputs.nh_resume_mode || 'auto' }}
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
''',
)
replace_once(
    ".github/workflows/collect.yml",
    '''          uv run rate-monitor collect \\
            --source nh_local \\
            --resume auto \\
            --cycle-date "${{ steps.nh_checkpoint.outputs.cycle_date }}" \\
''',
    '''          uv run rate-monitor collect \\
            --source nh_local \\
            --resume "$RESUME_MODE" \\
            --cycle-date "${{ steps.nh_checkpoint.outputs.cycle_date }}" \\
''',
)

# Keep recovery hard-coded auto. A fresh first attempt that failed with durable progress
# must resume that new session; running fresh again would abandon the progress.
t = Path("tests/test_checkpoint_workflow_contract.py")
text = t.read_text(encoding="utf-8")
marker = '''def test_nh_checkpoint_recovery_graph_is_bounded_to_one_attempt() -> None:
'''
addition = '''def test_manual_nh_fresh_is_operator_only_and_recovery_stays_auto() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    nh_mode = triggers["workflow_dispatch"]["inputs"]["nh_resume_mode"]
    assert nh_mode["type"] == "choice"
    assert nh_mode["default"] == "auto"
    assert nh_mode["options"] == ["auto", "fresh"]

    first = _step("Collect NH local")
    assert (first.get("env") or {}).get("RESUME_MODE") == "${{ inputs.nh_resume_mode || 'auto' }}"
    assert '--resume "$RESUME_MODE"' in first["run"]

    recovery = _step("Recover NH local")
    assert "RESUME_MODE" not in (recovery.get("env") or {})
    assert "--resume auto" in recovery["run"]


'''
if marker not in text:
    raise SystemExit("workflow test insertion marker mismatch")
t.write_text(text.replace(marker, addition + marker, 1), encoding="utf-8")
