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
    '''    if issue_type == "schema_warning" and message.startswith("우대금리 행:"):\n        return "PREFERENCE_RATE_ROW", "info"\n    if issue_type == "schema_warning":\n        return "SCHEMA_WARNING", "warning"\n''',
    '''    if issue_type == "schema_warning" and message.startswith("우대금리 행:"):\n        return "PREFERENCE_RATE_ROW", "info"\n    if issue_type == "schema_warning" and message == "행이 0건이다. 조회 조건을 확인한다":\n        # 지역/상품 조각 하나가 비는 것은 실제 원천에서 반복되는 정상 형태다.\n        # 실행 전체가 비었는지는 `_run_signal`의 parsed_count=0 gate가 따로 잡는다.\n        return "EMPTY_QUERY_RESULT", "info"\n    if issue_type == "schema_warning" and message.startswith("금리 필드가 없는 행:"):\n        # FSB가 상품 행은 주지만 해당 상품의 금리 필드를 주지 않는 경우.\n        # 다른 금리 행은 정상 수집되므로 source failure가 아니라 coverage note다.\n        return "RATELESS_SOURCE_ROW", "info"\n    if (\n        issue_type == "schema_warning"\n        and message.endswith("가 없다. 값 없이 진행한다")\n    ):\n        # parser가 명시적으로 optional로 선언한 필드의 부재. 신규/필수 필드\n        # 이상은 이 패턴이 아니므로 아래 actionable SCHEMA_WARNING으로 남는다.\n        return "OPTIONAL_FIELD_MISSING", "info"\n    if issue_type == "schema_warning":\n        return "SCHEMA_WARNING", "warning"\n''',
)
replace_once(
    "src/rate_monitor/services/source_health_service.py",
    '''def _row_warning_reason(message: str) -> str:\n    """관측 행 자체의 validation warning을 운영 reason으로 정규화한다."""\n    if "계약기간을 읽지 못했다" in message:\n        return "TERM_PARSE_AMBIGUOUS"\n    return "ROW_VALIDATION_WARNING"\n''',
    '''def _row_warning_reason(message: str) -> tuple[str, str]:\n    """관측 행 자체의 validation warning을 운영 reason으로 정규화한다."""\n    if message == "계약기간을 읽지 못했다: '-'":\n        # NH 원천이 계약기간을 '-'로 주는 실데이터가 반복된다. 기간을\n        # 지어내지 않고 unknown으로 남긴다는 coverage 정보이지 수집 장애는 아니다.\n        return "TERM_NOT_PROVIDED", "info"\n    return "ROW_VALIDATION_WARNING", "warning"\n''',
)
replace_once(
    "src/rate_monitor/services/source_health_service.py",
    '''    for row in row_warnings:\n        code = _row_warning_reason(row["validation_message"] or "")\n        counter[(code, "warning")] += int(row["count"] or 0)\n''',
    '''    for row in row_warnings:\n        code, level = _row_warning_reason(row["validation_message"] or "")\n        counter[(code, level)] += int(row["count"] or 0)\n''',
)
replace_once(
    "src/rate_monitor/services/source_health_service.py",
    '''    status = latest["status"]\n    if status == "running":\n''',
    '''    status = latest["status"]\n    # expected INFO warning을 green으로 낮추더라도 실행 전체가 비어 있으면\n    # 절대 정상으로 보이지 않는다. 원천이 전부 빈 응답을 줬을 때의 안전망이다.\n    if (\n        status in {"success", "partial"}\n        and int(latest.get("raw_count") or 0) > 0\n        and int(latest.get("parsed_count") or 0) == 0\n    ):\n        return "red", "파싱 결과 0건", infos, warnings, errors\n    if status == "running":\n''',
)

# Tests: import the taxonomy helpers and align expected known-source shapes to INFO.
replace_once(
    "tests/test_collection_health.py",
    '''from rate_monitor.services.source_health_service import _reason_counts, build_collection_health\n''',
    '''from rate_monitor.services.source_health_service import (\n    _reason_counts,\n    _review_reason,\n    _row_warning_reason,\n    build_collection_health,\n)\n''',
)
replace_once(
    "tests/test_collection_health.py",
    '''            message="계약기간을 읽지 못했다: '-'", payload_json={},\n''',
    '''            message="새로운 스키마 경고", payload_json={},\n''',
)
replace_once(
    "tests/test_collection_health.py",
    '''def test_row_validation_warning_is_actionable_even_without_review_item() -> None:\n    """행 validation warning만 남는 parser 경로도 초록불로 숨기지 않는다."""\n''',
    '''def test_known_missing_term_is_info_even_without_review_item() -> None:\n    """원천이 '-'로 주는 기간은 숨기지 않되 수집 장애로 취급하지 않는다."""\n''',
)
replace_once(
    "tests/test_collection_health.py",
    '''    assert reasons == [\n        {"code": "TERM_PARSE_AMBIGUOUS", "severity": "warning", "count": 1}\n    ]\n''',
    '''    assert reasons == [\n        {"code": "TERM_NOT_PROVIDED", "severity": "info", "count": 1}\n    ]\n''',
)

p = ROOT / "tests/test_collection_health.py"
text = p.read_text(encoding="utf-8")
text += r'''


def test_known_source_shape_warnings_are_info_but_new_schema_warning_is_actionable() -> None:
    assert _review_reason(
        "schema_warning", "warning", "행이 0건이다. 조회 조건을 확인한다"
    ) == ("EMPTY_QUERY_RESULT", "info")
    assert _review_reason(
        "schema_warning", "warning", "금리 필드가 없는 행: '310009'"
    ) == ("RATELESS_SOURCE_ROW", "info")
    assert _review_reason(
        "schema_warning", "warning", "SWEETENER가 없다. 값 없이 진행한다"
    ) == ("OPTIONAL_FIELD_MISSING", "info")
    assert _review_reason(
        "schema_warning", "warning", "새로운 알 수 없는 구조"
    ) == ("SCHEMA_WARNING", "warning")
    assert _row_warning_reason("계약기간을 읽지 못했다: '-'") == (
        "TERM_NOT_PROVIDED", "info"
    )
    assert _row_warning_reason("최고금리 변환 실패: '문의'") == (
        "ROW_VALIDATION_WARNING", "warning"
    )


def test_all_empty_success_is_red_even_if_empty_pages_are_info(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s)
        _run(s)
        run = s.get(m.CollectionRun, "r1")
        run.parsed_count = 0
        run.valid_count = 0
        s.add(m.ReviewItem(
            run_id="r1", issue_type="schema_warning", severity="warning",
            message="행이 0건이다. 조회 조건을 확인한다", payload_json={},
            created_at=datetime(2026, 8, 10),
        ))
    card = _health(path)["sources"][0]
    assert card["signal"] == "red"
    assert card["run_health"]["label"] == "파싱 결과 0건"
    assert card["latest_attempt"]["info_count"] == 1
    engine.dispose()
'''
p.write_text(text, encoding="utf-8")

# Planning doc records the evidence-backed taxonomy rather than generic candidates.
plan = ROOT / "docs/plans/20260810-p1-observability-collection-health.md"
if plan.exists():
    text = plan.read_text(encoding="utf-8")
    marker = "## Warning Taxonomy와 함께 하는 이유\n"
    note = (
        "### 운영 R2 실측으로 확정한 INFO 패턴\n\n"
        "- `PREFERENCE_RATE_ROW`: NH e-joy 우대금리 carrier row\n"
        "- `TERM_NOT_PROVIDED`: NH 계약기간 `-` (기간은 추정하지 않음)\n"
        "- `EMPTY_QUERY_RESULT`: CU 지역/상품 조회 조각의 0건 응답\n"
        "- `RATELESS_SOURCE_ROW`: FSB 상품 행에 금리 필드가 없는 경우\n"
        "- `OPTIONAL_FIELD_MISSING`: parser가 optional로 선언한 필드 부재\n\n"
        "이 패턴은 INFO로 보이되 source 신호를 노랑으로 만들지 않는다. 다만 실행 전체 `parsed_count=0`은 RED로 별도 차단한다.\n\n"
    )
    if marker in text and "### 운영 R2 실측으로 확정한 INFO 패턴" not in text:
        text = text.replace(marker, marker + "\n" + note, 1)
        plan.write_text(text, encoding="utf-8")

print("final health taxonomy applied")
