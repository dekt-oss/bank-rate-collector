from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"{path}: expected one match, got {text.count(old)}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# 1) Source health calculation: DB schema is reused; no migration.
(ROOT / "src/rate_monitor/services/source_health_service.py").write_text(r'''"""수집원별 운영 상태를 계산한다.

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

# 정기수집 완료를 기대하는 한국시간. UI에 24시간 같은 숫자를 박지 않고,
# 실제 workflow의 split schedule(02시 core / 06시 KFCC)을 기준으로 둔다.
# core 전국수집은 약 4시간, KFCC는 약 2시간이므로 완료 여유를 포함한다.
EXPECTED_BY_HOUR_KST = {
    "kfcc": 9,
}
DEFAULT_EXPECTED_BY_HOUR_KST = 7

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
''', encoding="utf-8")

# 2) Read-only live GitHub Actions status endpoint.
(ROOT / "web/api/health.js").write_text(r'''// 관리자 수집 상태 조회. 읽기 전용이다.
// GitHub token은 서버 환경에만 있고 브라우저에는 내려가지 않는다.

const WORKFLOW = "collect.yml";
const ACTIVE = new Set(["in_progress", "queued", "waiting", "pending"]);

const SOURCE_STEPS = {
  "Collect finlife savings bank": "finlife_savings_bank",
  "Collect finlife bank": "finlife_bank",
  "Collect BOK base rate": "bok_ecos",
  "Collect FSB": "fsb",
  "Collect CU": "cu",
  "Collect KFCC": "kfcc",
  "Collect NH local": "nh_local",
};

const PIPELINE_STEPS = {
  "Snapshot": "snapshot",
  "Validate stored data": "validation",
  "Build dashboard": "dashboard",
  "Export full dataset": "export",
  "Build public site": "site",
  "Volume gate": "volume_gate",
  "Publish to rate-data branch": "publish",
  "Upload state to R2": "r2",
};

const json = (res, status, body) => {
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.setHeader("cache-control", "no-store");
  res.status(status).send(JSON.stringify(body));
};

const gh = async (token, path) => fetch(`https://api.github.com${path}`, {
  headers: {
    accept: "application/vnd.github+json",
    authorization: `Bearer ${token}`,
    "x-github-api-version": "2022-11-28",
  },
});

const runView = (run) => run ? ({
  run_number: run.run_number,
  event: run.event,
  status: run.status,
  conclusion: run.conclusion,
  started_at: run.run_started_at || run.created_at,
  updated_at: run.updated_at,
  html_url: run.html_url,
}) : null;

const stepView = (step) => ({
  status: step.status,
  conclusion: step.conclusion,
  started_at: step.started_at,
  completed_at: step.completed_at,
});

const settings = () => {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const owner = process.env.VERCEL_GIT_REPO_OWNER;
  const repo = process.env.VERCEL_GIT_REPO_SLUG;
  const slug = process.env.GITHUB_REPOSITORY || (owner && repo ? `${owner}/${repo}` : null);
  return { token, slug };
};

export default async function handler(req, res) {
  if (req.method !== "GET") {
    return json(res, 405, { ok: false, error: "GET으로 불러 주세요." });
  }
  const { token, slug } = settings();
  if (!token || !slug) {
    return json(res, 503, {
      ok: false,
      configured: false,
      error: "수집 상태 조회가 아직 설정되지 않았습니다.",
    });
  }

  const runsRes = await gh(token, `/repos/${slug}/actions/workflows/${WORKFLOW}/runs?per_page=30`);
  if (!runsRes.ok) {
    return json(res, 502, { ok: false, error: `GitHub 실행 상태를 읽지 못했습니다 (${runsRes.status}).` });
  }
  const runs = (await runsRes.json()).workflow_runs || [];
  const collections = runs.filter((run) => run.event !== "push");
  const activeCollection = collections.find((run) => ACTIVE.has(run.status)) || null;
  const activePublish = runs.find((run) => run.event === "push" && ACTIVE.has(run.status)) || null;
  const latestCollection = collections[0] || null;
  const latestPublish = runs.find((run) => run.conclusion === "success") || null;
  const detailRun = activeCollection || latestCollection;

  const sourceSteps = {};
  const pipelineSteps = {};
  if (detailRun) {
    const jobsRes = await gh(token, `/repos/${slug}/actions/runs/${detailRun.id}/jobs?per_page=20`);
    if (jobsRes.ok) {
      const jobs = (await jobsRes.json()).jobs || [];
      for (const job of jobs) {
        for (const step of job.steps || []) {
          if (SOURCE_STEPS[step.name]) sourceSteps[SOURCE_STEPS[step.name]] = stepView(step);
          if (PIPELINE_STEPS[step.name]) pipelineSteps[PIPELINE_STEPS[step.name]] = stepView(step);
        }
      }
    }
  }

  return json(res, 200, {
    ok: true,
    latest_collection: runView(latestCollection),
    active_collection: runView(activeCollection),
    active_publish: runView(activePublish),
    latest_publish: runView(latestPublish),
    source_steps: sourceSteps,
    pipeline_steps: pipelineSteps,
  });
}
''', encoding="utf-8")

# 3) Dashboard summary includes the health payload.
replace_once(
    "src/rate_monitor/services/dashboard_service.py",
    "from rate_monitor.services.institution_matching import normalize_institution\n",
    "from rate_monitor.services.institution_matching import normalize_institution\n"
    "from rate_monitor.services.source_health_service import build_collection_health\n",
)
replace_once(
    "src/rate_monitor/services/dashboard_service.py",
    "        stale_sources = _stale_sources(conn)\n        table = build_rate_table(conn, run_ids)\n",
    "        stale_sources = _stale_sources(conn)\n"
    "        collection_health = build_collection_health(conn)\n"
    "        table = build_rate_table(conn, run_ids)\n",
)
replace_once(
    "src/rate_monitor/services/dashboard_service.py",
    '        "stale_sources": stale_sources,\n        "collect_workflow_url": _collect_workflow_url(),\n',
    '        "stale_sources": stale_sources,\n'
    '        "collection_health": collection_health,\n'
    '        "collect_workflow_url": _collect_workflow_url(),\n',
)

# 4) Static site gets the small health payload inline.
replace_once(
    "src/rate_monitor/services/site_service.py",
    '    "stale_sources",\n    # «지금 수집하기» 링크. 없으면 화면이 버튼을 통째로 숨긴다.\n',
    '    "stale_sources",\n'
    '    # source별 마지막 시도/정상 수집/freshness. 관리자 상태 패널이 쓴다.\n'
    '    "collection_health",\n'
    '    # «지금 수집하기» 링크. 없으면 화면이 버튼을 통째로 숨긴다.\n',
)

# 5) Main UI: status button + traffic-light panel + live GET.
replace_once(
    "web/templates/site.html",
    '''  .collect-alt {\n    width: 100%; font-size: 11px; color: var(--ink-3);\n    text-decoration: underline;\n  }\n''',
    '''  .collect-alt {\n    width: 100%; font-size: 11px; color: var(--ink-3);\n    text-decoration: underline;\n  }\n\n  /* ── 수집 상태 신호등 ───────────────────────────────────────── */\n  .health-panel {\n    margin-top: 12px; padding: 12px 14px; background: var(--surface);\n    border: 1px solid var(--line); border-radius: 8px;\n  }\n  .health-panel[hidden] { display: none; }\n  .health-head { display:flex; align-items:center; justify-content:space-between; gap:10px; }\n  .health-head b { font-size:13px; }\n  .health-summary { font-size:12px; color:var(--ink-2); margin-left:8px; }\n  .health-live {\n    margin-top:9px; padding:8px 10px; border-radius:6px;\n    background:var(--surface-2); font-size:12px; color:var(--ink-2); line-height:1.65;\n  }\n  .health-sources {\n    display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr));\n    gap:8px; margin-top:9px;\n  }\n  .health-src { border:1px solid var(--line-soft); border-radius:6px; padding:9px 10px; }\n  .health-src .ht { display:flex; align-items:center; gap:7px; font-weight:650; font-size:12.5px; }\n  .health-src .hm { margin-top:5px; font-size:11.5px; color:var(--ink-2); line-height:1.6; }\n  .health-dot { width:9px; height:9px; border-radius:50%; display:inline-block; flex:none; }\n  .health-dot.green { background:var(--ok); }\n  .health-dot.yellow { background:var(--warn); }\n  .health-dot.red { background:var(--crit); }\n  .health-dot.blue { background:var(--accent); }\n  .health-dot.gray { background:var(--ink-3); }\n  .health-refresh { font:inherit; font-size:11.5px; border:1px solid var(--line);\n    background:var(--surface); color:var(--ink-2); border-radius:5px; padding:4px 8px; cursor:pointer; }\n''',
)
replace_once(
    "web/templates/site.html",
    '''      <button type="button" class="icon-btn" id="copylink">링크 복사</button>\n      <div class="stamp" id="stamp"></div>\n''',
    '''      <button type="button" class="icon-btn" id="copylink">링크 복사</button>\n      <button type="button" class="icon-btn" id="health-open"\n              aria-expanded="false" aria-controls="health-panel">수집 상태</button>\n      <div class="stamp" id="stamp"></div>\n''',
)
replace_once(
    "web/templates/site.html",
    '''  <p class="notice" id="stale-notice" hidden></p>\n\n  <!-- 참고카드가 먼저다 (2026-08-07 순서 교체).\n''',
    '''  <p class="notice" id="stale-notice" hidden></p>\n\n  <section class="health-panel" id="health-panel" hidden aria-live="polite">\n    <div class="health-head">\n      <div><b>수집 시스템 상태</b><span class="health-summary" id="health-summary"></span></div>\n      <button type="button" class="health-refresh" id="health-refresh">새로고침</button>\n    </div>\n    <div class="health-live" id="health-live">마지막 발행본의 수집 상태를 표시합니다.</div>\n    <div class="health-sources" id="health-sources"></div>\n  </section>\n\n  <!-- 참고카드가 먼저다 (2026-08-07 순서 교체).\n''',
)
replace_once(
    "web/templates/site.html",
    '''  const COLLECT_ENDPOINT = "api/collect";\n\n  if (data.collect_workflow_url) {\n''',
    r'''  const COLLECT_ENDPOINT = "api/collect";
  const HEALTH_ENDPOINT = "api/health";
  const HEALTH_KO = { green: "정상", yellow: "확인 필요", red: "실패·지연",
                      blue: "진행 중", gray: "대상 아님" };
  const healthDate = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? esc(value)
      : d.toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit",
          hour: "2-digit", minute: "2-digit", hour12: false });
  };
  const healthDot = (signal) => `<span class="health-dot ${esc(signal || "gray")}"></span>`;
  const staticHealth = data.collection_health || { overall: "gray", counts: {}, sources: [] };

  const renderStaticHealth = () => {
    const c = staticHealth.counts || {};
    $("health-summary").innerHTML = `${healthDot(staticHealth.overall)} ${esc(HEALTH_KO[staticHealth.overall] || "미상")}`
      + ` · 정상 ${num(c.green || 0)} / 확인 ${num(c.yellow || 0)} / 실패 ${num(c.red || 0)}`;
    $("health-sources").innerHTML = (staticHealth.sources || []).map((s) => {
      const r = s.latest_attempt || {};
      const reasons = (s.reasons || []).filter((x) => x.severity !== "info");
      return `<div class="health-src"><div class="ht">${healthDot(s.signal)}`
        + `<span>${esc(s.name || s.source_id)}</span><span style="margin-left:auto;color:var(--ink-3)">`
        + `${esc(HEALTH_KO[s.signal] || s.signal)}</span></div>`
        + `<div class="hm">마지막 시도 ${healthDate(r.finished_at || r.started_at)} · ${esc(r.status || "없음")}<br>`
        + `마지막 정상 ${healthDate(s.last_success_at)} · 최신성 ${esc((s.freshness || {}).label || "—")}<br>`
        + `raw ${num(r.raw_count)} / valid ${num(r.valid_count)} / 경고 ${num(r.actionable_warning_count || 0)} / 오류 ${num(r.error_count || 0)}`
        + (r.info_count ? ` · 정보 ${num(r.info_count)}` : "")
        + (reasons.length ? `<br>이유 ${reasons.map((x) => `${esc(x.code)} ${num(x.count)}`).join(" · ")}` : "")
        + `</div></div>`;
    }).join("") || '<div class="hm">아직 수집 이력이 없습니다.</div>';
  };

  const runSignal = (run) => !run ? "gray"
    : (["in_progress", "queued", "waiting", "pending"].includes(run.status) ? "blue"
      : (run.conclusion === "success" ? "green" : "red"));
  const runLine = (label, run) => {
    if (!run) return `${label} 없음`;
    const sig = runSignal(run);
    const state = sig === "blue" ? "진행 중" : (run.conclusion === "success" ? "성공" : (run.conclusion || run.status));
    const text = `${healthDot(sig)} ${label} #${esc(run.run_number)} · ${esc(state)} · ${healthDate(run.started_at)}`;
    return run.html_url ? `<a href="${esc(run.html_url)}" target="_blank" rel="noopener">${text}</a>` : text;
  };
  const refreshLiveHealth = async () => {
    $("health-live").textContent = "GitHub Actions 상태 확인 중…";
    try {
      const res = await fetch(HEALTH_ENDPOINT, { cache: "no-store" });
      const body = await res.json().catch(() => null);
      if (!body || !body.ok) {
        $("health-live").textContent = (body && body.error) || "실시간 상태를 읽지 못했습니다. 위 source 카드는 마지막 발행본 기준입니다.";
        return;
      }
      const focus = body.active_collection || body.latest_collection;
      const steps = Object.entries(body.source_steps || {}).map(([id, step]) => {
        const sig = step.status === "in_progress" ? "blue" : (step.conclusion === "success" ? "green" : (step.conclusion === "skipped" ? "gray" : "red"));
        return `${healthDot(sig)} ${esc(id)} ${esc(step.conclusion || step.status || "—")}`;
      }).join(" · ");
      $("health-live").innerHTML = runLine("현재 수집", body.active_collection) + "<br>"
        + runLine("마지막 수집", body.latest_collection) + "<br>"
        + runLine("마지막 발행", body.latest_publish)
        + (body.active_publish ? "<br>" + runLine("현재 발행", body.active_publish) : "")
        + (focus && steps ? `<br><span style="color:var(--ink-3)">${steps}</span>` : "");
    } catch (err) {
      $("health-live").textContent = "실시간 상태에 연결하지 못했습니다. 위 source 카드는 마지막 발행본 기준입니다.";
    }
  };

  renderStaticHealth();
  $("health-open").addEventListener("click", () => {
    const panel = $("health-panel");
    panel.hidden = !panel.hidden;
    $("health-open").setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) refreshLiveHealth();
  });
  $("health-refresh").addEventListener("click", refreshLiveHealth);

  if (data.collect_workflow_url) {
''',
)

# 6) Functional service tests.
(ROOT / "tests/test_collection_health.py").write_text(r'''"""Source freshness / run health / warning taxonomy 회귀 테스트."""

from datetime import datetime
from pathlib import Path

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.timeutil import KST
from rate_monitor.services.source_health_service import build_collection_health


def _db(tmp_path: Path):
    path = tmp_path / "health.sqlite3"
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    return path, engine, factory


def _source(session, *, source_id="nh_local", enabled=True):
    session.add(m.Source(
        id=source_id, name=source_id, sector="nh_local", mode="http",
        source_role="secondary_official", trust_level="official_direct", priority=10,
        enabled=enabled, policy_status="allowed", coverage_status="nationwide",
        parser_version="1", created_at=datetime(2026, 8, 1), updated_at=datetime(2026, 8, 1),
    ))


def _run(session, *, source_id="nh_local", run_id="r1", status="success",
         started=datetime(2026, 8, 10, 0, 0), warnings=0, errors=0):
    session.add(m.CollectionRun(
        id=run_id, source_id=source_id, mode="http", started_at=started,
        finished_at=started, status=status, query_context_json={}, raw_count=10,
        parsed_count=100, valid_count=100, warning_count=warnings, error_count=errors,
        fallback_used=False,
    ))


def _health(path, moment=datetime(2026, 8, 10, 22, 0, tzinfo=KST)):
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        return build_collection_health(conn, moment=moment)
    finally:
        conn.close()


def test_recent_success_is_green(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s); _run(s)
    card = _health(path)["sources"][0]
    assert card["signal"] == "green"
    assert card["last_success_at"].startswith("2026-08-10T09:00")
    engine.dispose()


def test_partial_is_yellow_but_failed_is_red(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s)
        _run(s, run_id="ok", started=datetime(2026, 8, 10, 0, 0))
        _run(s, run_id="partial", status="partial", started=datetime(2026, 8, 10, 1, 0))
    assert _health(path)["sources"][0]["signal"] == "yellow"
    with session_scope(factory) as s:
        _run(s, run_id="bad", status="failed", started=datetime(2026, 8, 10, 2, 0))
    card = _health(path)["sources"][0]
    assert card["signal"] == "red"
    assert card["last_success_at"] is not None
    engine.dispose()


def test_bonus_rate_warning_is_info_not_yellow(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s); _run(s, warnings=1)
        s.add(m.ReviewItem(
            run_id="r1", issue_type="schema_warning", severity="warning",
            message="우대금리 행: e-joy 인터넷예금 우대금리 (0.1%)",
            payload_json={}, created_at=datetime(2026, 8, 10),
        ))
    card = _health(path)["sources"][0]
    assert card["signal"] == "green"
    assert card["latest_attempt"]["raw_warning_count"] == 1
    assert card["latest_attempt"]["actionable_warning_count"] == 0
    assert card["latest_attempt"]["info_count"] == 1
    assert card["reasons"] == [{"code": "PREFERENCE_RATE_ROW", "severity": "info", "count": 1}]
    engine.dispose()


def test_actionable_schema_warning_is_yellow(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s); _run(s, warnings=1)
        s.add(m.ReviewItem(
            run_id="r1", issue_type="schema_warning", severity="warning",
            message="계약기간을 읽지 못했다: '-'", payload_json={},
            created_at=datetime(2026, 8, 10),
        ))
    card = _health(path)["sources"][0]
    assert card["signal"] == "yellow"
    assert card["latest_attempt"]["actionable_warning_count"] == 1
    engine.dispose()


def test_business_day_freshness_handles_weekend_and_missed_cycles(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s)
        # 8/7 00:00 UTC = 금요일 09:00 KST
        _run(s, started=datetime(2026, 8, 7, 0, 0))
    # 월요일 06:30 KST: core cutoff(07시) 전이므로 금요일이 기대일 → 정상
    before = _health(path, datetime(2026, 8, 10, 6, 30, tzinfo=KST))["sources"][0]
    assert before["freshness"]["signal"] == "green"
    # 월요일 밤: 월요일 수집 1회를 놓침 → yellow
    after = _health(path, datetime(2026, 8, 10, 22, 0, tzinfo=KST))["sources"][0]
    assert after["freshness"]["signal"] == "yellow"
    # 화요일 밤까지 못 받음 → 2회 지연 red
    late = _health(path, datetime(2026, 8, 11, 22, 0, tzinfo=KST))["sources"][0]
    assert late["freshness"]["signal"] == "red"
    engine.dispose()


def test_disabled_source_is_gray(tmp_path) -> None:
    path, engine, factory = _db(tmp_path)
    with session_scope(factory) as s:
        _source(s, enabled=False)
    card = _health(path)["sources"][0]
    assert card["signal"] == "gray"
    engine.dispose()
''', encoding="utf-8")

# 7) Endpoint/UI contracts.
(ROOT / "tests/test_collection_health_ui.py").write_text(r'''"""관리자 수집 상태 UI와 read-only API의 배포 계약."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = (ROOT / "web/templates/site.html").read_text(encoding="utf-8")
API = (ROOT / "web/api/health.js").read_text(encoding="utf-8")
SITE_SERVICE = (ROOT / "src/rate_monitor/services/site_service.py").read_text(encoding="utf-8")


def test_health_payload_is_inlined_and_ui_has_a_manual_refresh() -> None:
    assert '"collection_health"' in SITE_SERVICE
    assert 'id="health-open"' in SITE
    assert 'id="health-panel"' in SITE
    assert 'id="health-refresh"' in SITE
    assert 'const HEALTH_ENDPOINT = "api/health"' in SITE


def test_traffic_light_has_text_as_well_as_color() -> None:
    for signal in ("green", "yellow", "red", "blue", "gray"):
        assert f".health-dot.{signal}" in SITE
    for label in ("정상", "확인 필요", "실패·지연", "진행 중", "대상 아님"):
        assert label in SITE


def test_health_api_is_read_only_and_sanitized() -> None:
    assert 'req.method !== "GET"' in API
    assert "GITHUB_DISPATCH_TOKEN" in API
    assert "workflow_runs" in API and "/jobs?per_page=20" in API
    assert "source_steps" in API and "pipeline_steps" in API
    assert "logs_url" not in API
    assert "authorization" in API  # server-side request only
    assert "token," not in API.split("return json(res, 200", 1)[-1]


def test_health_api_never_requires_or_returns_the_collect_password() -> None:
    assert "DASHBOARD_PASSWORD" not in API
    assert "password" not in API.lower()
''', encoding="utf-8")

# Keep planning doc aligned with actual branch boundary.
plan = ROOT / "docs/plans/20260810-p1-observability-collection-health.md"
if plan.exists():
    text = plan.read_text(encoding="utf-8")
    marker = "## 구현 경계\n"
    if marker in text and "implementation branch:" not in text:
        text = text.replace(marker, "## 구현 경계\n\n- implementation branch: `agent/p1-collection-health`\n- DB schema migration: 없음\n- live status: read-only `/api/health`\n\n", 1)
        plan.write_text(text, encoding="utf-8")

print("P1 collection health patch applied")
