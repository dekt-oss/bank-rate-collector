from pathlib import Path

p = Path("src/rate_monitor/services/resumable_acquisition.py")
text = p.read_text(encoding="utf-8")
old = '''    if manifest.status == "collecting":
        if not attempt_failed:
            return RecoveryDecision(
                False,
                "CALLER_FAILURE_NOT_CONFIRMED",
                identity.source_id,
                identity.cycle_date_kst,
                manifest.session_id,
                manifest.status,
                manifest.completed_work_count,
            )
        eligible = manifest.completed_work_count > 0
        return RecoveryDecision(
            eligible,
            "RECOVERABLE_ABNORMAL_EXIT" if eligible else "NO_DURABLE_PROGRESS",
'''
new = '''    if manifest.status == "collecting":
        if manifest.completed_work_count <= 0:
            return RecoveryDecision(
                False,
                "NO_DURABLE_PROGRESS",
                identity.source_id,
                identity.cycle_date_kst,
                manifest.session_id,
                manifest.status,
                manifest.completed_work_count,
            )
        if not attempt_failed:
            return RecoveryDecision(
                False,
                "CALLER_FAILURE_NOT_CONFIRMED",
                identity.source_id,
                identity.cycle_date_kst,
                manifest.session_id,
                manifest.status,
                manifest.completed_work_count,
            )
        eligible = True
        return RecoveryDecision(
            eligible,
            "RECOVERABLE_ABNORMAL_EXIT",
'''
if text.count(old) != 1:
    raise SystemExit("collecting recovery block mismatch")
p.write_text(text.replace(old, new), encoding="utf-8")
