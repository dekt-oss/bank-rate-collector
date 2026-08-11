"""수집원별 운영 상태를 계산한다.

새 상태 테이블을 만들지 않는다. 이미 `collection_runs`, `collection_run_stats`,
`review_items`가 실행 사실을 갖고 있으므로 그 값을 읽어 신호등으로 번역한다.

서로 다른 질문을 섞지 않는다.

- run health: 마지막 시도 자체가 정상인가
- freshness: 마지막 정상 수집이 예정된 평일 주기에서 밀렸는가
- displayed from: 현재 화면 값이 어느 confirmed run에서 확인됐는가

최종 신호는 둘 중 더 나쁜 상태를 쓴다. 원천에 없는 사실은 만들지 않는다.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from rate_monitor.domain.timeutil import KST, kst_iso, now_kst, to_kst

NORMAL_STATUSES = ("success", "no_change")
DISPLAY_STATUSES = ("success", "partial", "no_change")
FAIL_STATUSES = ("failed", "blocked", "schema_changed")

# 평일 정기 cycle의 hard deadline은 08:00 KST다. core/KFCC 시작시각은
# 서로 다르지만 사용자가 요구하는 최신성 계약은 "같은 날 08시까지 성공"이다.
# 개별 source의 run health와 전체 cycle SLA는 별도로 표시한다.
EXPECTED_BY_HOUR_KST: dict[str, int] = {}
DEFAULT_EXPECTED_BY_HOUR_KST = 8

_SIGNAL_RANK = {"gray": 0, "green": 1, "blue": 2, "yellow": 3, "red": 4}


def _rows(
    conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params)
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def _one(
    conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()
) -> dict[str, Any] | None:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else None


def _previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def expected_collection_date(source_id: str, moment: datetime) -> date:
    """이 시각까지 완료됐어야 하는 가장 최근 평일 수집일."""
    local = moment.astimezone(KST) if moment.tzinfo else moment.replace(tzinfo=KST)
    cutoff = EXPECTED_BY_HOUR_KST.get(source_id, DEFAULT_EXPECTED_BY_HOUR_KST)
    if local.weekday() < 5 and local.hour >= cutoff:
        return local.date()
    return _previous_weekday(local.date())


def _missed_business_cycles(last_success: date, expected: date) -> int:
    if last_success >= expected:
        return 0
    missed = 0
    cursor = last_success + timedelta(days=1)
    while cursor <= expected:
        if cursor.weekday() < 5:
            missed += 1
        cursor += timedelta(days=1)
    return missed


def _freshness(
    source_id: str, last_success_at: str | datetime | None, moment: datetime
) -> dict[str, Any]:
    expected = expected_collection_date(source_id, moment)
    local = to_kst(last_success_at)
    if local is None:
        return {
            "signal": "red",
            "label": "정상 수집 이력 없음",
            "expected_date": expected.isoformat(),
            "missed_cycles": None,
        }
    missed = _missed_business_cycles(local.date(), expected)
    if missed == 0:
        signal, label = "green", "정상"
    elif missed == 1:
        signal, label = "yellow", "예정 수집 1회 지연"
    else:
        signal, label = "red", f"예정 수집 {missed}회 지연"
    return {
        "signal": signal,
        "label": label,
        "expected_date": expected.isoformat(),
        "missed_cycles": missed,
    }


def _review_reason(issue_type: str, severity: str, message: str) -> tuple[str, str]:
    """기존 review item을 운영자가 읽을 수 있는 최소 taxonomy로 번역한다.

    NH의 `우대금리 행`은 원천이 실제로 주는 carrier row다. 버릴 데이터도,
    parser 장애도 아니다. 과거 run에는 `schema_warning`으로 저장돼 있으므로
    읽는 자리에서 INFO로 재분류해 신호등을 오염시키지 않는다.
    """
    if issue_type == "schema_warning" and message.startswith("우대금리 행:"):
        return "PREFERENCE_RATE_ROW", "info"
    if issue_type == "schema_warning" and message == "행이 0건이다. 조회 조건을 확인한다":
        # 지역/상품 조각 하나가 비는 것은 실제 원천에서 반복되는 정상 형태다.
        # 실행 전체가 비었는지는 `_run_signal`의 parsed_count=0 gate가 따로 잡는다.
        return "EMPTY_QUERY_RESULT", "info"
    if issue_type == "schema_warning" and message.startswith("금리 필드가 없는 행:"):
        # FSB가 상품 행은 주지만 해당 상품의 금리 필드를 주지 않는 경우.
        # 다른 금리 행은 정상 수집되므로 source failure가 아니라 coverage note다.
        return "RATELESS_SOURCE_ROW", "info"
    if (
        issue_type == "schema_warning"
        and message.endswith("가 없다. 값 없이 진행한다")
    ):
        # parser가 명시적으로 optional로 선언한 필드의 부재. 신규/필수 필드
        # 이상은 이 패턴이 아니므로 아래 actionable SCHEMA_WARNING으로 남는다.
        return "OPTIONAL_FIELD_MISSING", "info"
    if issue_type == "schema_warning":
        return "SCHEMA_WARNING", "warning"
    known = {
        "duplicate": ("DUPLICATE_VARIANT", "warning"),
        "parse_error": ("PARSE_ERROR", "error"),
        "repeated_response": ("REPEATED_RESPONSE", "error"),
        "schema_changed": ("SCHEMA_CHANGED", "error"),
        "region_invalid_sigungu": ("INVALID_SIGUNGU", "warning"),
    }
    if issue_type in known:
        return known[issue_type]
    level = severity if severity in {"info", "warning", "error"} else "warning"
    return issue_type.upper(), level


def _row_warning_reason(message: str) -> tuple[str, str]:
    """관측 행 자체의 validation warning을 운영 reason으로 정규화한다."""
    if message == "계약기간을 읽지 못했다: '-'":
        # NH 원천이 계약기간을 '-'로 주는 실데이터가 반복된다. 기간을
        # 지어내지 않고 unknown으로 남긴다는 coverage 정보이지 수집 장애는 아니다.
        return "TERM_NOT_PROVIDED", "info"
    return "ROW_VALIDATION_WARNING", "warning"


def _reason_counts(conn: sqlite3.Connection, run_id: str | None) -> list[dict[str, Any]]:
    if not run_id:
        return []
    counter: Counter[tuple[str, str]] = Counter()
    rows = _rows(
        conn,
        "SELECT issue_type, severity, message FROM review_items WHERE run_id = ?",
        (run_id,),
    )
    for row in rows:
        code, level = _review_reason(
            row["issue_type"], row["severity"], row["message"] or ""
        )
        counter[(code, level)] += 1

    # 일부 parser warning은 ReviewItem이 아니라 observation validation에 남는다.
    # 예: NH의 기간 '-' 행. 이것을 안 보면 run.status=success인데 실제로는
    # 사람이 확인해야 할 행이 있어도 초록불이 된다. change-only 저장이므로
    # 이번 실행이 마지막으로 확인한 행(last_run_id)만 센다.
    row_warnings = _rows(
        conn,
        "SELECT validation_message, COUNT(*) AS count"
        "  FROM rate_observations"
        " WHERE last_run_id = ? AND validation_status = 'warning'"
        " GROUP BY validation_message",
        (run_id,),
    )
    for row in row_warnings:
        code, level = _row_warning_reason(row["validation_message"] or "")
        counter[(code, level)] += int(row["count"] or 0)

    return [
        {"code": code, "severity": severity, "count": count}
        for (code, severity), count in sorted(
            counter.items(), key=lambda x: (-_SIGNAL_RANK.get(
                {"info": "green", "warning": "yellow", "error": "red"}[x[0][1]], 0
            ), x[0][0])
        )
    ]


def _latest_run(
    conn: sqlite3.Connection, source_id: str, statuses: tuple[str, ...] | None = None
) -> dict[str, Any] | None:
    where = "source_id = ?"
    params: list[Any] = [source_id]
    if statuses:
        where += " AND status IN (" + ",".join("?" for _ in statuses) + ")"
        params.extend(statuses)
    return _one(
        conn,
        "SELECT id, source_id, status, started_at, finished_at, raw_count, parsed_count,"
        "       valid_count, warning_count, error_count, message, fallback_used,"
        "       query_context_json"
        f"  FROM collection_runs WHERE {where}"
        " ORDER BY started_at DESC LIMIT 1",
        tuple(params),
    )


def _run_stat(conn: sqlite3.Connection, run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    return _one(
        conn,
        "SELECT fetched_count, parsed_count, unchanged_count, changed_count,"
        "       new_variant_count, missing_variant_count, error_count"
        "  FROM collection_run_stats WHERE run_id = ?",
        (run_id,),
    )


def _source_effective_at(
    conn: sqlite3.Connection, source_id: str, visible_run_id: str | None
) -> str | None:
    if source_id == "bok_ecos":
        row = _one(
            conn,
            "SELECT MAX(source_effective_at) AS d FROM market_indicators WHERE source_id = ?",
            (source_id,),
        )
        return row["d"] if row else None
    if not visible_run_id:
        return None
    row = _one(
        conn,
        "SELECT MAX(source_effective_at) AS d FROM rate_observations WHERE last_run_id = ?",
        (visible_run_id,),
    )
    return row["d"] if row else None


def _run_signal(
    latest: dict[str, Any] | None, reasons: list[dict[str, Any]]
) -> tuple[str, str, int, int, int]:
    if latest is None:
        return "red", "실행 이력 없음", 0, 0, 0
    infos = sum(r["count"] for r in reasons if r["severity"] == "info")
    warnings = sum(r["count"] for r in reasons if r["severity"] == "warning")
    review_errors = sum(r["count"] for r in reasons if r["severity"] == "error")
    errors = max(int(latest.get("error_count") or 0), review_errors)
    status = latest["status"]
    # expected INFO warning을 green으로 낮추더라도 실행 전체가 비어 있으면
    # 절대 정상으로 보이지 않는다. 원천이 전부 빈 응답을 줬을 때의 안전망이다.
    if (
        status in {"success", "partial"}
        and int(latest.get("raw_count") or 0) > 0
        and int(latest.get("parsed_count") or 0) == 0
    ):
        return "red", "파싱 결과 0건", infos, warnings, errors
    if status == "running":
        return "blue", "실행 중", infos, warnings, errors
    if status in FAIL_STATUSES:
        return "red", status, infos, warnings, errors
    if status == "partial":
        return "yellow", "일부 확인 필요", infos, warnings, errors
    if status in NORMAL_STATUSES:
        if errors:
            return "red", "오류 확인 필요", infos, warnings, errors
        if warnings or latest.get("fallback_used"):
            return "yellow", "확인 필요", infos, warnings, errors
        return "green", "정상", infos, warnings, errors
    return "yellow", status or "상태 미상", infos, warnings, errors


def _worse(*signals: str) -> str:
    return max(signals, key=lambda s: _SIGNAL_RANK.get(s, 0))


def build_collection_health(
    conn: sqlite3.Connection, *, moment: datetime | None = None
) -> dict[str, Any]:
    """현재 DB가 말할 수 있는 source별 수집 건강상태."""
    moment = moment or now_kst()
    sources = _rows(
        conn,
        "SELECT id, name, enabled, mode, trust_level, coverage_status"
        "  FROM sources ORDER BY priority, id",
    )
    cards: list[dict[str, Any]] = []
    overall_reasons: Counter[tuple[str, str]] = Counter()

    for source in sources:
        latest = _latest_run(conn, source["id"])
        success = _latest_run(conn, source["id"], NORMAL_STATUSES)
        visible = _latest_run(conn, source["id"], DISPLAY_STATUSES)
        reasons = _reason_counts(conn, latest["id"] if latest else None)
        for reason in reasons:
            overall_reasons[(reason["code"], reason["severity"])] += reason["count"]

        run_signal, run_label, info_count, warning_count, error_count = _run_signal(
            latest, reasons
        )
        freshness = _freshness(
            source["id"],
            (success or {}).get("finished_at") or (success or {}).get("started_at"),
            moment,
        )
        if not source["enabled"]:
            overall = "gray"
            run_signal, run_label = "gray", "비활성"
            freshness = {**freshness, "signal": "gray", "label": "비활성"}
        else:
            overall = _worse(run_signal, freshness["signal"])

        cards.append(
            {
                "source_id": source["id"],
                "name": source["name"],
                "enabled": bool(source["enabled"]),
                "mode": source["mode"],
                "trust_level": source["trust_level"],
                "coverage_status": source["coverage_status"],
                "signal": overall,
                "run_health": {"signal": run_signal, "label": run_label},
                "freshness": freshness,
                "latest_attempt": None if latest is None else {
                    "run_id": latest["id"],
                    "status": latest["status"],
                    "started_at": kst_iso(latest["started_at"]),
                    "finished_at": kst_iso(latest["finished_at"]),
                    "raw_count": latest["raw_count"],
                    "parsed_count": latest["parsed_count"],
                    "valid_count": latest["valid_count"],
                    "raw_warning_count": latest["warning_count"],
                    "actionable_warning_count": warning_count,
                    "info_count": info_count,
                    "error_count": error_count,
                    "fallback_used": bool(latest["fallback_used"]),
                    "message": latest["message"],
                    "query_context": latest["query_context_json"],
                    "stats": _run_stat(conn, latest["id"]),
                },
                "last_success_at": None if success is None else kst_iso(
                    success["finished_at"] or success["started_at"]
                ),
                "showing_from_at": None if visible is None else kst_iso(
                    visible["finished_at"] or visible["started_at"]
                ),
                "source_effective_at": _source_effective_at(
                    conn, source["id"], visible["id"] if visible else None
                ),
                "reasons": reasons,
            }
        )

    counts = Counter(card["signal"] for card in cards)
    overall = _worse(*(card["signal"] for card in cards)) if cards else "gray"
    reason_counts = [
        {"code": code, "severity": severity, "count": count}
        for (code, severity), count in sorted(overall_reasons.items())
    ]
    return {
        "overall": overall,
        "counts": {key: counts.get(key, 0) for key in ("green", "yellow", "red", "blue", "gray")},
        "sources": cards,
        "reason_counts": reason_counts,
    }
