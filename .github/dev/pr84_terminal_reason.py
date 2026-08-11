from pathlib import Path

service = Path("src/rate_monitor/services/resumable_acquisition.py")
text = service.read_text(encoding="utf-8")
old = '        reason_by_status.get(manifest.status, "UNKNOWN_FATAL"),\n'
new = (
    '        manifest.terminal_reason_code\n'
    '        or reason_by_status.get(manifest.status, "UNKNOWN_FATAL"),\n'
)
if text.count(old) != 1:
    raise SystemExit("terminal recovery reason marker mismatch")
service.write_text(text.replace(old, new, 1), encoding="utf-8")

test = Path("tests/test_checkpoint_sealed_audit.py")
text = test.read_text(encoding="utf-8")
addition = '''\n\ndef test_contract_failed_preserves_specific_terminal_reason_code(tmp_path) -> None:\n    store, service = _service(tmp_path)\n    manifest = service.open()\n    service.mark_terminal(\n        manifest,\n        status="contract_failed",\n        reason_code="SOURCE_SCHEMA_CHANGED",\n        reason="directory schema changed",\n    )\n\n    decision = decide_recovery(store, _identity())\n    assert decision.eligible is False\n    assert decision.reason_code == "SOURCE_SCHEMA_CHANGED"\n    assert decision.manifest_status == "contract_failed"\n'''
if "def test_contract_failed_preserves_specific_terminal_reason_code" in text:
    raise SystemExit("test already present")
test.write_text(text.rstrip() + addition + "\n", encoding="utf-8")
