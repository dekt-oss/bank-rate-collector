from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


# ---------------------------------------------------------------------------
# Common checkpoint service: persist resumable source state on recoverable
# failure and report the source-specific sealed terminal reason when present.
# ---------------------------------------------------------------------------
replace_once(
    "src/rate_monitor/services/resumable_acquisition.py",
    '''    def mark_recoverable_failed(\n        self,\n        manifest: AcquisitionManifest,\n        *,\n        reason_code: str,\n        reason: str,\n    ) -> AcquisitionManifest:\n''',
    '''    def mark_recoverable_failed(\n        self,\n        manifest: AcquisitionManifest,\n        *,\n        reason_code: str,\n        reason: str,\n        guard_state: dict[str, Any] | None = None,\n    ) -> AcquisitionManifest:\n''',
)
replace_once(
    "src/rate_monitor/services/resumable_acquisition.py",
    '''        updated = self._next_manifest(\n            manifest,\n            status="recoverable_failed",\n            terminal_reason_code=reason_code,\n            terminal_reason=reason,\n        )\n''',
    '''        updated = self._next_manifest(\n            manifest,\n            status="recoverable_failed",\n            guard_state=guard_state,\n            terminal_reason_code=reason_code,\n            terminal_reason=reason,\n        )\n''',
)
replace_once(
    "src/rate_monitor/services/resumable_acquisition.py",
    '''    return RecoveryDecision(\n        False,\n        reason_by_status.get(manifest.status, "UNKNOWN_FATAL"),\n''',
    '''    return RecoveryDecision(\n        False,\n        manifest.terminal_reason_code\n        or reason_by_status.get(manifest.status, "UNKNOWN_FATAL"),\n''',
)

# NH integration file cleanup + preserve original request cap semantics.
replace_once(
    "src/rate_monitor/collectors/nh_local/resumable.py",
    "    BASE_URL,\n",
    "",
)
replace_once(
    "src/rate_monitor/collectors/nh_local/resumable.py",
    "                requests_made = max(0, manifest.completed_work_count - 1)\n",
    "                # Existing MAX_REQUESTS includes the directory request. A resume\n"
    "                # therefore starts from all durable completed work, not details only.\n"
    "                requests_made = manifest.completed_work_count\n",
)

# ---------------------------------------------------------------------------
# rate-monitor CLI: enable checkpointed NH only when explicitly requested.
# Default remains the existing direct adapter path.
# ---------------------------------------------------------------------------
replace_once(
    "src/rate_monitor/cli.py",
    "from rate_monitor.collectors.nh_local.adapter import NhLocalAdapter\n",
    "from rate_monitor.collectors.nh_local.adapter import NhLocalAdapter\n"
    "from rate_monitor.collectors.nh_local.resumable import NhResumableAdapter\n",
)
replace_once(
    "src/rate_monitor/cli.py",
    "from rate_monitor.services.validation_service import run_validations\n",
    "from rate_monitor.services.validation_service import run_validations\n\n\n"
    "def _checkpoint_store():\n"
    "    config = R2Config.from_env()\n"
    "    if config is None:\n"
    "        raise StorageError(\n"
    "            \"NH checkpoint mode에는 R2 설정이 모두 필요하다. \"\n"
    "            + \", \".join(R2Config.ENV_KEYS)\n"
    "        )\n"
    "    return open_store(config)\n",
)
replace_once(
    "src/rate_monitor/cli.py",
    '''    result = asyncio.run(\n        collect_source(adapter_cls(), request, factory, raw_root=Path(args.raw_root))\n    )\n''',
    '''    if args.resume != "off":\n        if args.source != "nh_local":\n            print("--resume은 현재 nh_local에서만 지원한다", file=sys.stderr)\n            return 2\n        if not args.cycle_date:\n            print("NH checkpoint mode에는 --cycle-date가 필요하다", file=sys.stderr)\n            return 2\n        adapter = NhResumableAdapter(\n            _checkpoint_store(),\n            cycle_date_kst=args.cycle_date,\n            resume_mode=args.resume,\n        )\n    else:\n        adapter = adapter_cls()\n\n    result = asyncio.run(\n        collect_source(adapter, request, factory, raw_root=Path(args.raw_root))\n    )\n''',
)
replace_once(
    "src/rate_monitor/cli.py",
    '''    collect.add_argument(\n        "--scope", default=None,\n        help="지역 기반 수집원 전용. config/regions.yaml의 수집 범위 이름 "\n             "(전국·부산·수도권). 생략하면 config의 default_scope",\n    )\n    collect.set_defaults(func=_collect)\n''',
    '''    collect.add_argument(\n        "--scope", default=None,\n        help="지역 기반 수집원 전용. config/regions.yaml의 수집 범위 이름 "\n             "(전국·부산·수도권). 생략하면 config의 default_scope",\n    )\n    collect.add_argument(\n        "--resume", choices=["off", "auto", "fresh"], default="off",\n        help="NH durable checkpoint. off=기존 경로, auto=같은 cycle 재개, fresh=새 세션",\n    )\n    collect.add_argument(\n        "--cycle-date", default=None,\n        help="checkpoint source 전용 KST cycle YYYY-MM-DD. workflow run_started_at에서 계산",\n    )\n    collect.set_defaults(func=_collect)\n''',
)

# ---------------------------------------------------------------------------
# Checkpoint CLI: prepare exact same source/cycle/fingerprint context before
# source execution. Explicit cycle is useful for tests/manual controlled runs;
# workflow default resolves the exact current run_started_at via GitHub API.
# ---------------------------------------------------------------------------
replace_once(
    "src/rate_monitor/checkpoint_cli.py",
    "import argparse\nimport sys\n",
    "import argparse\nimport json\nimport sys\n",
)
replace_once(
    "src/rate_monitor/checkpoint_cli.py",
    "from pathlib import Path\n\n",
    "from pathlib import Path\n\n"
    "from rate_monitor.collectors.nh_local.resumable import build_nh_checkpoint_context\n"
    "from rate_monitor.domain.schemas import CollectionRequest\n",
)
replace_once(
    "src/rate_monitor/checkpoint_cli.py",
    "from rate_monitor.services.storage_service import (\n",
    "from rate_monitor.services.storage_service import (\n",
)
replace_once(
    "src/rate_monitor/checkpoint_cli.py",
    ")\n\n\ndef _store(local_root: str | None):\n",
    ")\nfrom rate_monitor.services.workflow_context import resolve_cycle_date_kst\n\n\ndef _store(local_root: str | None):\n",
)
prepare_fn = '''\n\ndef _prepare_context(args: argparse.Namespace) -> int:\n    if args.source != "nh_local":\n        raise ValueError("prepare-context는 현재 nh_local만 지원한다")\n    cycle_date = args.cycle_date or resolve_cycle_date_kst()\n    options = {"scope": args.scope} if args.scope else {}\n    request = CollectionRequest(source_id="nh_local", options=options)\n    context = build_nh_checkpoint_context(request, cycle_date_kst=cycle_date)\n    body = json.dumps(context.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\\n"\n    if args.json:\n        path = Path(args.json)\n        path.parent.mkdir(parents=True, exist_ok=True)\n        path.write_text(body, encoding="utf-8")\n    sys.stdout.write(body)\n    return 0\n'''
replace_once(
    "src/rate_monitor/checkpoint_cli.py",
    "\n\ndef _recovery_decision(args: argparse.Namespace) -> int:\n",
    prepare_fn + "\n\ndef _recovery_decision(args: argparse.Namespace) -> int:\n",
)
replace_once(
    "src/rate_monitor/checkpoint_cli.py",
    '''    sub = parser.add_subparsers(dest="action", required=True)\n\n    recovery = sub.add_parser(\n''',
    '''    sub = parser.add_subparsers(dest="action", required=True)\n\n    prepare = sub.add_parser(\n        "prepare-context",\n        help="NH checkpoint source command와 recovery decision이 공유할 identity를 만든다",\n    )\n    prepare.add_argument("--source", required=True, choices=["nh_local"])\n    prepare.add_argument("--scope", default=None)\n    prepare.add_argument(\n        "--cycle-date", default=None,\n        help="생략하면 GitHub current run의 run_started_at을 KST 날짜로 변환",\n    )\n    prepare.add_argument("--json", default=None)\n    prepare.set_defaults(func=_prepare_context)\n\n    recovery = sub.add_parser(\n''',
)

# ---------------------------------------------------------------------------
# Health API: a skipped recovery must not overwrite the first attempt, while
# a real recovery result must supersede it within the same workflow run.
# ---------------------------------------------------------------------------
replace_once(
    "web/api/health.js",
    '  "Collect NH local": "nh_local",\n};\n',
    '  "Collect NH local": "nh_local",\n  "Recover NH local": "nh_local",\n};\n',
)
replace_once(
    "web/api/health.js",
    '''      if (SOURCE_STEPS[step.name]) sourceSteps[SOURCE_STEPS[step.name]] = stepView(step);\n''',
    '''      if (SOURCE_STEPS[step.name]) {\n        const sourceId = SOURCE_STEPS[step.name];\n        const view = stepView(step);\n        // Source steps are ordered. Recovery should supersede a failed first\n        // attempt only when it actually ran; a skipped recovery preserves it.\n        if (view.conclusion !== "skipped" || !sourceSteps[sourceId]) {\n          sourceSteps[sourceId] = view;\n        }\n      }\n''',
)

# ---------------------------------------------------------------------------
# Workflow: prepare exact run context, first checkpointed NH attempt, explicit
# recovery decision, then at most one immediate same-workflow recovery.
# ---------------------------------------------------------------------------
workflow = Path(".github/workflows/collect.yml")
text = workflow.read_text(encoding="utf-8")
old_nh = '''      - name: Collect NH local\n        if: ${{ inputs.skip_nh_local != true && env.PUBLISH_ONLY != 'true'\n          && env.KFCC_ONLY != 'true' }}\n        continue-on-error: true\n        env:\n          SCOPE: ${{ inputs.nh_local_scope }}\n          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}\n          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}\n          R2_ACCOUNT_ID: ${{ vars.R2_ACCOUNT_ID }}\n          R2_BUCKET: ${{ vars.R2_BUCKET }}\n          R2_ENDPOINT: ${{ vars.R2_ENDPOINT }}\n          R2_REGION: ${{ vars.R2_REGION }}\n        run: |\n          uv run rate-monitor collect \\\n            --source nh_local \\\n            --db work/rate_monitor.sqlite3 \\\n            --raw-root data/raw \\\n            ${SCOPE:+--scope "$SCOPE"}\n'''
new_nh = '''      - name: Prepare NH checkpoint context\n        id: nh_checkpoint\n        if: ${{ inputs.skip_nh_local != true && env.PUBLISH_ONLY != 'true'\n          && env.KFCC_ONLY != 'true' }}\n        env:\n          SCOPE: ${{ inputs.nh_local_scope }}\n          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n        run: |\n          set -euo pipefail\n          mkdir -p work\n          uv run rate-monitor-checkpoint prepare-context \\\n            --source nh_local \\\n            ${SCOPE:+--scope "$SCOPE"} \\\n            --json work/nh-checkpoint-context.json >/dev/null\n          CYCLE_DATE=$(python -c \"import json; print(json.load(open('work/nh-checkpoint-context.json'))['cycle_date_kst'])\")\n          FINGERPRINT=$(python -c \"import json; print(json.load(open('work/nh-checkpoint-context.json'))['request_fingerprint'])\")\n          CONTRACT=$(python -c \"import json; print(json.load(open('work/nh-checkpoint-context.json'))['acquisition_contract_version'])\")\n          echo \"cycle_date=$CYCLE_DATE\" >> \"$GITHUB_OUTPUT\"\n          echo \"fingerprint=$FINGERPRINT\" >> \"$GITHUB_OUTPUT\"\n          echo \"contract_version=$CONTRACT\" >> \"$GITHUB_OUTPUT\"\n\n      - name: Collect NH local\n        id: collect_nh_local\n        if: ${{ inputs.skip_nh_local != true && env.PUBLISH_ONLY != 'true'\n          && env.KFCC_ONLY != 'true' }}\n        continue-on-error: true\n        env:\n          SCOPE: ${{ inputs.nh_local_scope }}\n          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}\n          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}\n          R2_ACCOUNT_ID: ${{ vars.R2_ACCOUNT_ID }}\n          R2_BUCKET: ${{ vars.R2_BUCKET }}\n          R2_ENDPOINT: ${{ vars.R2_ENDPOINT }}\n          R2_REGION: ${{ vars.R2_REGION }}\n        run: |\n          uv run rate-monitor collect \\\n            --source nh_local \\\n            --resume auto \\\n            --cycle-date \"${{ steps.nh_checkpoint.outputs.cycle_date }}\" \\\n            --db work/rate_monitor.sqlite3 \\\n            --raw-root data/raw \\\n            ${SCOPE:+--scope "$SCOPE"}\n\n      - name: Decide NH recovery\n        id: decide_nh_recovery\n        if: ${{ steps.collect_nh_local.outcome == 'failure' }}\n        continue-on-error: true\n        env:\n          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}\n          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}\n          R2_ACCOUNT_ID: ${{ vars.R2_ACCOUNT_ID }}\n          R2_BUCKET: ${{ vars.R2_BUCKET }}\n          R2_ENDPOINT: ${{ vars.R2_ENDPOINT }}\n          R2_REGION: ${{ vars.R2_REGION }}\n        run: |\n          set -euo pipefail\n          uv run rate-monitor-checkpoint recovery-decision \\\n            --source nh_local \\\n            --cycle-date \"${{ steps.nh_checkpoint.outputs.cycle_date }}\" \\\n            --request-fingerprint \"${{ steps.nh_checkpoint.outputs.fingerprint }}\" \\\n            --acquisition-contract-version \"${{ steps.nh_checkpoint.outputs.contract_version }}\" \\\n            --attempt-failed \\\n            --json work/nh-recovery-decision.json >/dev/null\n          ELIGIBLE=$(python -c \"import json; print(str(json.load(open('work/nh-recovery-decision.json'))['eligible']).lower())\")\n          REASON=$(python -c \"import json; print(json.load(open('work/nh-recovery-decision.json'))['reason_code'])\")\n          echo \"eligible=$ELIGIBLE\" >> \"$GITHUB_OUTPUT\"\n          echo \"reason=$REASON\" >> \"$GITHUB_OUTPUT\"\n          echo \"NH recovery eligible=$ELIGIBLE reason=$REASON\"\n\n      - name: Recover NH local\n        id: recover_nh_local\n        if: ${{ steps.collect_nh_local.outcome == 'failure'\n          && steps.decide_nh_recovery.outcome == 'success'\n          && steps.decide_nh_recovery.outputs.eligible == 'true' }}\n        continue-on-error: true\n        env:\n          SCOPE: ${{ inputs.nh_local_scope }}\n          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}\n          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}\n          R2_ACCOUNT_ID: ${{ vars.R2_ACCOUNT_ID }}\n          R2_BUCKET: ${{ vars.R2_BUCKET }}\n          R2_ENDPOINT: ${{ vars.R2_ENDPOINT }}\n          R2_REGION: ${{ vars.R2_REGION }}\n        run: |\n          uv run rate-monitor collect \\\n            --source nh_local \\\n            --resume auto \\\n            --cycle-date \"${{ steps.nh_checkpoint.outputs.cycle_date }}\" \\\n            --db work/rate_monitor.sqlite3 \\\n            --raw-root data/raw \\\n            ${SCOPE:+--scope "$SCOPE"}\n'''
if text.count(old_nh) != 1:
    raise SystemExit("collect.yml NH source block mismatch")
workflow.write_text(text.replace(old_nh, new_nh, 1), encoding="utf-8")

# PR A workflow contract was intentionally 'no integration yet'. On PR B, keep
# that boundary only for KFCC and assert the NH recovery graph explicitly.
t = Path("tests/test_checkpoint_workflow_contract.py")
text = t.read_text(encoding="utf-8")
text = text.replace(
    '''def test_common_infrastructure_does_not_enable_checkpoint_collection_yet() -> None:\n    """PR A alone must not change live source behavior.\n\n    Adapter loops do not consume the checkpoint service until NH/KFCC integration PRs.\n    Therefore workflow source commands must not pass a resume/checkpoint flag yet.\n    """\n    for name in ("Collect NH local", "Collect KFCC"):\n        body = _step(name)["run"]\n        assert "--resume" not in body\n        assert "checkpoint" not in body.lower()\n\n\ndef test_common_infrastructure_does_not_install_recovery_steps_early() -> None:\n    names = {str(step.get("name") or "") for step in _steps()}\n    assert not any(name.startswith("Decide NH recovery") for name in names)\n    assert not any(name.startswith("Recover NH local") for name in names)\n    assert not any(name.startswith("Decide KFCC recovery") for name in names)\n    assert not any(name.startswith("Recover KFCC") for name in names)\n''',
    '''def test_kfcc_is_still_outside_checkpoint_integration_pr_b() -> None:\n    body = _step("Collect KFCC")["run"]\n    assert "--resume" not in body\n    names = {str(step.get("name") or "") for step in _steps()}\n    assert not any(name.startswith("Decide KFCC recovery") for name in names)\n    assert not any(name.startswith("Recover KFCC") for name in names)\n\n\ndef test_nh_checkpoint_recovery_graph_is_bounded_to_one_attempt() -> None:\n    names = [str(step.get("name") or "") for step in _steps()]\n    assert names.count("Prepare NH checkpoint context") == 1\n    assert names.count("Collect NH local") == 1\n    assert names.count("Decide NH recovery") == 1\n    assert names.count("Recover NH local") == 1\n\n    first = _step("Collect NH local")\n    decision = _step("Decide NH recovery")\n    recovery = _step("Recover NH local")\n    assert first["continue-on-error"] is True\n    assert "--resume auto" in first["run"]\n    assert "steps.collect_nh_local.outcome == 'failure'" in str(decision["if"])\n    assert "--attempt-failed" in decision["run"]\n    condition = str(recovery["if"])
    assert "steps.collect_nh_local.outcome == 'failure'" in condition\n    assert "steps.decide_nh_recovery.outcome == 'success'" in condition\n    assert "steps.decide_nh_recovery.outputs.eligible == 'true'" in condition\n    assert recovery["continue-on-error"] is True\n    assert "--resume auto" in recovery["run"]\n''',
)
t.write_text(text, encoding="utf-8")
