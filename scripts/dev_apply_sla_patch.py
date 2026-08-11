from pathlib import Path
import re


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    hits = text.count(old)
    if hits != expected:
        raise SystemExit(f"{path}: expected {expected} hits, got {hits}: {old[:100]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


# 1) Schedule: keep split/single-writer, move starts early enough for 08:00 SLA.
p = Path(".github/workflows/collect.yml")
text = p.read_text(encoding="utf-8")
text = text.replace("0 17 * * 0-4", "17 15 * * 0-4")
text = text.replace("0 21 * * 0-4", "17 19 * * 0-4")
text = text.replace("02:00", "00:17").replace("17:00", "15:17")
text = text.replace("06:00", "04:17").replace("21:00", "19:17")
text = text.replace("05:57 KST쯤 끝난다", "04:14 KST쯤 끝난다")
p.write_text(text, encoding="utf-8")

# 2) Schedule contract test: verify both KST→UTC schedules and weekdays.
p = Path("tests/test_gate_contract.py")
text = p.read_text(encoding="utf-8")
pattern = re.compile(
    r"def test_the_schedule_is_every_weekday_at_two_am_kst\(\) -> None:\n.*?\n\ndef test_the_two_crons_split_the_work_so_neither_run_hits_six_hours",
    re.S,
)
new_block = '''def test_the_schedule_starts_early_enough_for_eight_am_sla() -> None:
    """평일 core 00:17 KST, KFCC 04:17 KST를 UTC cron으로 정확히 환산한다.

    두 실행 모두 한국시간 자정~새벽이므로 UTC에서는 전날 일~목에 걸린다.
    정각을 피하고, 08:00 hard deadline 앞에 queue/후처리 여유를 둔다.
    """
    import datetime as dt
    from pathlib import Path

    import yaml

    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "collect.yml"
    loaded = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    triggers = loaded.get("on", loaded.get(True))
    crons = [s["cron"] for s in triggers["schedule"]]
    assert crons == ["17 15 * * 0-4", "17 19 * * 0-4"]

    kst = dt.timezone(dt.timedelta(hours=9))
    cases = [(0, 17, 15), (4, 17, 19)]
    for local_hour, local_minute, utc_hour in cases:
        for day in range(10, 17):                  # 2026-08-10(월)~16(일)
            local = dt.datetime(
                2026, 8, day, local_hour, local_minute, tzinfo=kst
            )
            utc = local.astimezone(dt.UTC)
            assert (utc.hour, utc.minute) == (utc_hour, 17)
            cron_weekday = (utc.weekday() + 1) % 7  # Python 월=0 → cron 일=0
            caught = 0 <= cron_weekday <= 4
            weekday = local.weekday() < 5
            assert caught is weekday, f"{local:%m-%d %a %H:%M}가 어긋난다"


def test_the_two_crons_split_the_work_so_neither_run_hits_six_hours'''
text, count = pattern.subn(new_block, text)
if count != 1:
    raise SystemExit(f"tests/test_gate_contract.py: schedule test replacement count={count}")
text = text.replace(
    "02:00은 새마을금고 말고 전부, 06:00은 새마을금고만.",
    "00:17은 새마을금고 말고 전부, 04:17은 새마을금고만.",
)
p.write_text(text, encoding="utf-8")

# 3) Source freshness: all scheduled sources must have same-day success by 08:00.
replace_exact(
    "src/rate_monitor/services/source_health_service.py",
    '''# 정기수집 완료를 기대하는 한국시간. UI에 24시간 같은 숫자를 박지 않고,
# 실제 workflow의 split schedule(02시 core / 06시 KFCC)을 기준으로 둔다.
# core 전국수집은 약 4시간, KFCC는 약 2시간이므로 완료 여유를 포함한다.
EXPECTED_BY_HOUR_KST = {
    "kfcc": 9,
}
DEFAULT_EXPECTED_BY_HOUR_KST = 7
''',
    '''# 평일 정기 cycle의 hard deadline은 08:00 KST다. core/KFCC 시작시각은
# 서로 다르지만 사용자가 요구하는 최신성 계약은 "같은 날 08시까지 성공"이다.
# 개별 source의 run health와 전체 cycle SLA는 별도로 표시한다.
EXPECTED_BY_HOUR_KST: dict[str, int] = {}
DEFAULT_EXPECTED_BY_HOUR_KST = 8
''',
)

# 4) Freshness boundary regression around 08:00.
replace_exact(
    "tests/test_collection_health.py",
    '''    # 월요일 06:30 KST: core cutoff(07시) 전이므로 금요일이 기대일 → 정상
    before = _health(path, datetime(2026, 8, 10, 6, 30, tzinfo=KST))["sources"][0]
    assert before["freshness"]["signal"] == "green"
    # 월요일 밤: 월요일 수집 1회를 놓침 → yellow
    after = _health(path, datetime(2026, 8, 10, 22, 0, tzinfo=KST))["sources"][0]
    assert after["freshness"]["signal"] == "yellow"
    # 화요일 밤까지 못 받음 → 2회 지연 red
    late = _health(path, datetime(2026, 8, 11, 22, 0, tzinfo=KST))["sources"][0]
''',
    '''    # 월요일 07:45 KST: hard cutoff(08시) 전이므로 금요일이 기대일 → 정상
    before = _health(path, datetime(2026, 8, 10, 7, 45, tzinfo=KST))["sources"][0]
    assert before["freshness"]["signal"] == "green"
    # 월요일 08:05: 월요일 수집 1회를 놓침 → yellow
    after = _health(path, datetime(2026, 8, 10, 8, 5, tzinfo=KST))["sources"][0]
    assert after["freshness"]["signal"] == "yellow"
    # 화요일 08:05까지 못 받음 → 2회 지연 red
    late = _health(path, datetime(2026, 8, 11, 8, 5, tzinfo=KST))["sources"][0]
''',
)

# 5) Live health API: derive cycle SLA from the KFCC-only scheduled run publish step.
p = Path("web/api/health.js")
text = p.read_text(encoding="utf-8")
active_anchor = 'const ACTIVE = new Set(["in_progress", "queued", "waiting", "pending"]);\n'
helper = r'''
const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const SCHEDULED_SOURCES = [
  "finlife_savings_bank", "finlife_bank", "bok_ecos", "fsb", "cu", "nh_local", "kfcc",
];

const kstParts = (value) => {
  const shifted = new Date(new Date(value).getTime() + KST_OFFSET_MS);
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
  };
};
const pad2 = (value) => String(value).padStart(2, "0");
const kstIsoAt = ({ year, month, day }, hour, minute) => (
  `${year}-${pad2(month)}-${pad2(day)}T${pad2(hour)}:${pad2(minute)}:00+09:00`
);

export const cycleSla = (scheduledRun, publishCompletedAt, now = new Date()) => {
  if (!scheduledRun) return null;
  const reference = scheduledRun.run_started_at || scheduledRun.created_at;
  if (!reference) return null;
  const parts = kstParts(reference);
  const cycleDate = `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`;
  const normalTargetAt = kstIsoAt(parts, 7, 30);
  const deadlineAt = kstIsoAt(parts, 8, 0);
  const normalMs = Date.parse(normalTargetAt);
  const deadlineMs = Date.parse(deadlineAt);
  const completedMs = publishCompletedAt ? Date.parse(publishCompletedAt) : null;
  const nowMs = new Date(now).getTime();

  let status;
  if (completedMs !== null) {
    status = completedMs <= normalMs ? "normal" : (completedMs <= deadlineMs ? "warning" : "breached");
  } else {
    status = nowMs < normalMs ? "pending" : (nowMs < deadlineMs ? "warning" : "breached");
  }
  return {
    cycle_date_kst: cycleDate,
    scheduled_sources: SCHEDULED_SOURCES,
    latest_publish_completed_at: publishCompletedAt || null,
    normal_target_at: normalTargetAt,
    sla_deadline_at: deadlineAt,
    status,
  };
};
'''
if text.count(active_anchor) != 1:
    raise SystemExit("health.js: ACTIVE anchor missing/non-unique")
text = text.replace(active_anchor, active_anchor + helper, 1)

step_anchor = '''const stepView = (step) => ({
  status: step.status,
  conclusion: step.conclusion,
  started_at: step.started_at,
  completed_at: step.completed_at,
});
'''
load_steps = r'''
const loadRunSteps = async (token, slug, run) => {
  const sourceSteps = {};
  const pipelineSteps = {};
  if (!run) return { sourceSteps, pipelineSteps };
  const jobsRes = await gh(token, `/repos/${slug}/actions/runs/${run.id}/jobs?per_page=20`);
  if (!jobsRes.ok) return { sourceSteps, pipelineSteps };
  const jobs = (await jobsRes.json()).jobs || [];
  for (const job of jobs) {
    for (const step of job.steps || []) {
      if (SOURCE_STEPS[step.name]) sourceSteps[SOURCE_STEPS[step.name]] = stepView(step);
      if (PIPELINE_STEPS[step.name]) pipelineSteps[PIPELINE_STEPS[step.name]] = stepView(step);
    }
  }
  return { sourceSteps, pipelineSteps };
};
'''
if text.count(step_anchor) != 1:
    raise SystemExit("health.js: stepView anchor missing/non-unique")
text = text.replace(step_anchor, step_anchor + load_steps, 1)

old_handler = '''  const latestCollection = collections[0] || null;
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
'''
new_handler = '''  const latestCollection = collections[0] || null;
  const latestScheduled = collections.find((run) => run.event === "schedule") || null;
  const latestPublish = runs.find((run) => run.conclusion === "success") || null;
  const detailRun = activeCollection || latestCollection;

  const detail = await loadRunSteps(token, slug, detailRun);
  const scheduled = latestScheduled && detailRun && latestScheduled.id === detailRun.id
    ? detail
    : await loadRunSteps(token, slug, latestScheduled);
  const kfccStep = scheduled.sourceSteps.kfcc || null;
  const cycleFinisher = kfccStep && kfccStep.conclusion !== "skipped";
  const publishStep = scheduled.pipelineSteps.publish || null;
  const publishCompletedAt = cycleFinisher && publishStep && publishStep.conclusion === "success"
    ? publishStep.completed_at
    : null;
  const sla = cycleSla(latestScheduled, publishCompletedAt);

  return json(res, 200, {
'''
if text.count(old_handler) != 1:
    raise SystemExit("health.js: handler block missing/non-unique")
text = text.replace(old_handler, new_handler, 1)
return_old = '    source_steps: sourceSteps,\n    pipeline_steps: pipelineSteps,\n'
return_new = '    source_steps: detail.sourceSteps,\n    pipeline_steps: detail.pipelineSteps,\n    sla,\n'
if text.count(return_old) != 1:
    raise SystemExit("health.js: return block missing/non-unique")
text = text.replace(return_old, return_new, 1)
p.write_text(text, encoding="utf-8")

# 6) UI: show timing SLA separately from source-health summary.
p = Path("web/templates/site.html")
text = p.read_text(encoding="utf-8")
refresh_anchor = '  const refreshLiveHealth = async () => {\n'
sla_line = r'''  const slaLine = (sla) => {
    if (!sla) return "";
    const sig = sla.status === "normal" ? "green"
      : (sla.status === "warning" ? "yellow" : (sla.status === "breached" ? "red" : "blue"));
    const label = sla.status === "normal" ? "정상"
      : (sla.status === "warning" ? "마감 임박" : (sla.status === "breached" ? "08:00 초과" : "진행 중"));
    const done = sla.latest_publish_completed_at
      ? ` · 최종 발행 ${healthDate(sla.latest_publish_completed_at)}` : "";
    return `${healthDot(sig)} 08:00 SLA ${esc(label)} · 기준일 ${esc(sla.cycle_date_kst)}${done}`;
  };
'''
if text.count(refresh_anchor) != 1:
    raise SystemExit("site.html: refreshLiveHealth anchor missing/non-unique")
text = text.replace(refresh_anchor, sla_line + refresh_anchor, 1)
old_render = '''        + runLine("마지막 발행", body.latest_publish)
        + (body.active_publish ? "<br>" + runLine("현재 발행", body.active_publish) : "")
        + (focus && steps ? `<br><span style="color:var(--ink-3)">${steps}</span>` : "");
'''
new_render = '''        + runLine("마지막 발행", body.latest_publish)
        + (body.active_publish ? "<br>" + runLine("현재 발행", body.active_publish) : "")
        + (body.sla ? "<br>" + slaLine(body.sla) : "")
        + (focus && steps ? `<br><span style="color:var(--ink-3)">${steps}</span>` : "");
'''
if text.count(old_render) != 1:
    raise SystemExit("site.html: live health render block missing/non-unique")
p.write_text(text.replace(old_render, new_render, 1), encoding="utf-8")

# 7) UI/API contract checks.
p = Path("tests/test_collection_health_ui.py")
text = p.read_text(encoding="utf-8")
text += '''


def test_live_health_exposes_eight_am_cycle_sla() -> None:
    assert "export const cycleSla" in API
    assert "normal_target_at: normalTargetAt" in API
    assert "sla_deadline_at: deadlineAt" in API
    assert "latest_publish_completed_at: publishCompletedAt || null" in API
    assert 'collections.find((run) => run.event === "schedule")' in API
    assert "scheduled.pipelineSteps.publish" in API
    assert "08:00 SLA" in SITE
    assert 'body.sla ? "<br>" + slaLine(body.sla)' in SITE
'''
p.write_text(text, encoding="utf-8")

# 8) Executable 07:30 / 08:00 boundary tests against the JS helper.
Path("tests/test_collection_sla_api.py").write_text(r'''"""08:00 cycle SLA 경계값을 실제 Node helper로 검증한다."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEALTH_API = (ROOT / "web/api/health.js").as_uri()


def _sla(completed: str | None, now: str) -> dict:
    completed_js = json.dumps(completed)
    script = f"""
      import {{ cycleSla }} from {json.dumps(HEALTH_API)};
      const run = {{ run_started_at: '2026-08-10T19:17:00Z' }};
      console.log(JSON.stringify(cycleSla(run, {completed_js}, new Date({json.dumps(now)}))));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_publish_before_0730_is_normal() -> None:
    result = _sla("2026-08-10T22:20:00Z", "2026-08-10T22:20:00Z")
    assert result["cycle_date_kst"] == "2026-08-11"
    assert result["status"] == "normal"
    assert result["normal_target_at"].endswith("T07:30:00+09:00")
    assert result["sla_deadline_at"].endswith("T08:00:00+09:00")


def test_publish_between_0730_and_0800_is_warning() -> None:
    assert _sla("2026-08-10T22:45:00Z", "2026-08-10T22:45:00Z")["status"] == "warning"


def test_publish_after_0800_is_breached() -> None:
    assert _sla("2026-08-10T23:05:00Z", "2026-08-10T23:05:00Z")["status"] == "breached"


def test_unfinished_cycle_moves_pending_warning_breached() -> None:
    assert _sla(None, "2026-08-10T22:00:00Z")["status"] == "pending"
    assert _sla(None, "2026-08-10T22:45:00Z")["status"] == "warning"
    assert _sla(None, "2026-08-10T23:05:00Z")["status"] == "breached"
''', encoding="utf-8")
