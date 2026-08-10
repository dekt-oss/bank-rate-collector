from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}")
    p.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "src/rate_monitor/services/source_health_service.py",
    '''def _reason_counts(conn: sqlite3.Connection, run_id: str | None) -> list[dict[str, Any]]:\n''',
    '''def _row_warning_reason(message: str) -> str:\n    """관측 행 자체의 validation warning을 운영 reason으로 정규화한다."""\n    if "계약기간을 읽지 못했다" in message:\n        return "TERM_PARSE_AMBIGUOUS"\n    return "ROW_VALIDATION_WARNING"\n\n\ndef _reason_counts(conn: sqlite3.Connection, run_id: str | None) -> list[dict[str, Any]]:\n''',
)
replace_once(
    "src/rate_monitor/services/source_health_service.py",
    '''    for row in rows:\n        code, level = _review_reason(\n            row["issue_type"], row["severity"], row["message"] or ""\n        )\n        counter[(code, level)] += 1\n    return [\n''',
    '''    for row in rows:\n        code, level = _review_reason(\n            row["issue_type"], row["severity"], row["message"] or ""\n        )\n        counter[(code, level)] += 1\n\n    # 일부 parser warning은 ReviewItem이 아니라 observation validation에 남는다.\n    # 예: NH의 기간 '-' 행. 이것을 안 보면 run.status=success인데 실제로는\n    # 사람이 확인해야 할 행이 있어도 초록불이 된다. change-only 저장이므로\n    # 이번 실행이 마지막으로 확인한 행(last_run_id)만 센다.\n    row_warnings = _rows(\n        conn,\n        "SELECT validation_message, COUNT(*) AS count"\n        "  FROM rate_observations"\n        " WHERE last_run_id = ? AND validation_status = 'warning'"\n        " GROUP BY validation_message",\n        (run_id,),\n    )\n    for row in row_warnings:\n        code = _row_warning_reason(row["validation_message"] or "")\n        counter[(code, "warning")] += int(row["count"] or 0)\n\n    return [\n''',
)

replace_once(
    "web/api/health.js",
    '''  "Build public site": "site",\n  "Volume gate": "volume_gate",\n  "Publish to rate-data branch": "publish",\n''',
    '''  "Build public site": "site",\n  "Verify P1-A gate": "p1a_gate",\n  "Size gate": "size_gate",\n  "Volume gate": "volume_gate",\n  "Publish to rate-data branch": "publish",\n''',
)

replace_once(
    "tests/test_collection_health.py",
    '''from datetime import datetime\nfrom pathlib import Path\n''',
    '''import sqlite3\nfrom datetime import datetime\nfrom pathlib import Path\n''',
)
replace_once(
    "tests/test_collection_health.py",
    '''from rate_monitor.services.source_health_service import build_collection_health\n''',
    '''from rate_monitor.services.source_health_service import _reason_counts, build_collection_health\n''',
)

p = ROOT / "tests/test_collection_health.py"
text = p.read_text(encoding="utf-8")
text += r'''


def test_row_validation_warning_is_actionable_even_without_review_item() -> None:
    """행 validation warning만 남는 parser 경로도 초록불로 숨기지 않는다."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript("""
            CREATE TABLE review_items (
                run_id TEXT, issue_type TEXT, severity TEXT, message TEXT
            );
            CREATE TABLE rate_observations (
                last_run_id TEXT, validation_status TEXT, validation_message TEXT
            );
            INSERT INTO rate_observations VALUES
                ('r1', 'warning', '계약기간을 읽지 못했다: -'),
                ('r1', 'valid', NULL),
                ('old', 'warning', '계약기간을 읽지 못했다: -');
        """)
        reasons = _reason_counts(conn, "r1")
    finally:
        conn.close()
    assert reasons == [
        {"code": "TERM_PARSE_AMBIGUOUS", "severity": "warning", "count": 1}
    ]
'''
p.write_text(text, encoding="utf-8")

p = ROOT / "tests/test_collection_health_ui.py"
text = p.read_text(encoding="utf-8")
text += r'''


def test_live_pipeline_includes_the_publish_gates() -> None:
    """수집만 성공하고 gate가 실패한 작업을 전체 정상으로 보이면 안 된다."""
    assert '"Verify P1-A gate": "p1a_gate"' in API
    assert '"Size gate": "size_gate"' in API
    assert '"Volume gate": "volume_gate"' in API
    assert '"Publish to rate-data branch": "publish"' in API
'''
p.write_text(text, encoding="utf-8")

# Planning note: batch metadata was considered but deliberately deferred in this minimal PR.
plan = ROOT / "docs/plans/20260810-p1-observability-collection-health.md"
if plan.exists():
    text = plan.read_text(encoding="utf-8")
    needle = "- live status: read-only `/api/health`\n"
    if needle in text and "batch identity metadata: deferred" not in text:
        text = text.replace(
            needle,
            needle
            + "- batch identity metadata: deferred — 이번 PR은 GitHub workflow 상태와 DB source 상태를 읽기 전용으로 병렬 표시하며 CLI/수집 계약은 바꾸지 않음\n",
            1,
        )
        plan.write_text(text, encoding="utf-8")

print("adversarial health fixes applied")
