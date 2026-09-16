// 관리자 수집 상태 조회. 읽기 전용이다.
// GitHub token은 서버 환경에만 있고 브라우저에는 내려가지 않는다.

const MORNING_WORKFLOW = "collect-morning-cycle.yml";
const CORE_WORKFLOW = "collect.yml";
const NH_WORKFLOW = "collect-nh.yml";
const FUNDING_WORKFLOW = "collect-institution-funding.yml";
const ACTIVE = new Set(["in_progress", "queued", "waiting", "pending"]);

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const RESERVATION_HOUR = 14;
const RESERVATION_MINUTE = 50;
const ACTUAL_START_HOUR = 20;
const ACTUAL_START_MINUTE = 30;
const SCHEDULER_BUDGET_MINUTES = 6 * 60 + 41;
// 과거 약 10시간 지연까지 같은 nominal reservation에 귀속하되 다음 날
// reservation과 겹칠 정도로 늦은 run은 잘못된 cycle로 추정하지 않는다.
const MAX_SCHEDULE_ATTRIBUTION_DELAY_MINUTES = 18 * 60;
const SCHEDULED_SOURCES = [
  "finlife_savings_bank", "finlife_bank", "bok_ecos", "fsb", "cu", "nh_local", "kfcc",
];
const FAILED_CONCLUSIONS = new Set([
  "failure", "cancelled", "timed_out", "action_required", "startup_failure",
]);

const kstParts = (value) => {
  const shifted = new Date(new Date(value).getTime() + KST_OFFSET_MS);
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
  };
};
const pad2 = (value) => String(value).padStart(2, "0");
const kstDateKey = ({ year, month, day }) => (
  `${year}-${pad2(month)}-${pad2(day)}`
);
const kstIsoAt = ({ year, month, day }, hour, minute) => (
  `${year}-${pad2(month)}-${pad2(day)}T${pad2(hour)}:${pad2(minute)}:00+09:00`
);
const runTime = (run) => {
  const value = Date.parse(run?.run_started_at || run?.created_at || "");
  return Number.isFinite(value) ? value : 0;
};
const createdTime = (run) => {
  const value = Date.parse(run?.created_at || run?.run_started_at || "");
  return Number.isFinite(value) ? value : 0;
};
const mergeRuns = (...groups) => groups
  .flat()
  .sort((a, b) => runTime(b) - runTime(a));

const moveParts = (parts, days) => {
  const cursor = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  cursor.setUTCDate(cursor.getUTCDate() + days);
  return {
    year: cursor.getUTCFullYear(),
    month: cursor.getUTCMonth() + 1,
    day: cursor.getUTCDate(),
  };
};

const weekdayOfParts = (parts) => new Date(
  Date.UTC(parts.year, parts.month - 1, parts.day),
).getUTCDay();

// Parent cron은 KST 일~목에 예약되고 바로 다음 날짜(월~금)가 morning cycle이다.
const isReservationDay = (parts) => weekdayOfParts(parts) <= 4;
const cyclePartsForReservation = (reservationParts) => moveParts(reservationParts, 1);

const latestReservationParts = (instant) => {
  const nowMs = new Date(instant).getTime();
  let cursor = kstParts(instant);
  for (let offset = 0; offset < 8; offset += 1) {
    const candidate = moveParts(cursor, -offset);
    if (!isReservationDay(candidate)) continue;
    const candidateMs = Date.parse(kstIsoAt(candidate, RESERVATION_HOUR, RESERVATION_MINUTE));
    if (candidateMs <= nowMs) return candidate;
  }
  return null;
};

const reservationForScheduledRun = (run) => {
  const actualMs = createdTime(run);
  if (!actualMs) return null;
  const candidate = latestReservationParts(new Date(actualMs));
  if (!candidate) return null;
  const reservationMs = Date.parse(kstIsoAt(candidate, RESERVATION_HOUR, RESERVATION_MINUTE));
  const delayMinutes = Math.max(0, Math.floor((actualMs - reservationMs) / 60000));
  if (delayMinutes > MAX_SCHEDULE_ATTRIBUTION_DELAY_MINUTES) return null;
  return { parts: candidate, delayMinutes };
};

const cycleDateOfScheduledRun = (run) => {
  const reservation = reservationForScheduledRun(run);
  return reservation ? kstDateKey(cyclePartsForReservation(reservation.parts)) : null;
};

export const scheduleTriggerHealth = (scheduledRuns, now = new Date()) => {
  const nowDate = new Date(now);
  const nowMs = nowDate.getTime();
  const reservationParts = latestReservationParts(nowDate);
  if (!reservationParts) {
    return {
      cycle_date_kst: null,
      expected_count: 0,
      observed_count: 0,
      missing_count: 0,
      max_trigger_delay_minutes: null,
      scheduler_budget_minutes: SCHEDULER_BUDGET_MINUTES,
      reservation_at: null,
      actual_start_not_before_at: null,
      status: "unknown",
    };
  }

  const cycleParts = cyclePartsForReservation(reservationParts);
  const cycleDate = kstDateKey(cycleParts);
  const reservationAt = kstIsoAt(reservationParts, RESERVATION_HOUR, RESERVATION_MINUTE);
  const actualStartAt = kstIsoAt(reservationParts, ACTUAL_START_HOUR, ACTUAL_START_MINUTE);
  const deadlineAt = kstIsoAt(cycleParts, 8, 0);
  const reservationMs = Date.parse(reservationAt);
  const actualStartMs = Date.parse(actualStartAt);
  const deadlineMs = Date.parse(deadlineAt);

  const observed = scheduledRuns
    .filter((run) => cycleDateOfScheduledRun(run) === cycleDate)
    .sort((a, b) => createdTime(a) - createdTime(b));
  const run = observed[0] || null;
  const actualCreatedMs = run ? createdTime(run) : null;
  const delayMinutes = actualCreatedMs === null
    ? null
    : Math.max(0, Math.floor((actualCreatedMs - reservationMs) / 60000));
  const missingCount = run ? 0 : 1;

  let status;
  if (!run) {
    // 14:50 예약은 scheduler runway다. 실제 원천수집 시작 하한인 20:30 전에는
    // run 객체가 아직 없어도 운영상 미수집으로 경고하지 않는다.
    if (nowMs < actualStartMs) status = "pending";
    else if (nowMs < deadlineMs) status = "warning";
    else status = "breached";
  } else if (actualCreatedMs > deadlineMs) {
    status = "breached";
  } else if (actualCreatedMs > actualStartMs) {
    status = "warning";
  } else {
    status = "normal";
  }

  return {
    cycle_date_kst: cycleDate,
    expected_count: 1,
    observed_count: run ? 1 : 0,
    missing_count: missingCount,
    max_trigger_delay_minutes: delayMinutes,
    scheduler_budget_minutes: SCHEDULER_BUDGET_MINUTES,
    reservation_at: reservationAt,
    actual_start_not_before_at: actualStartAt,
    status,
  };
};

export const cycleSla = (
  scheduledRun,
  publishCompletedAt,
  now = new Date(),
  sourceState = null,
  scheduleState = null,
) => {
  if (!scheduledRun) return null;
  const reference = scheduledRun.created_at || scheduledRun.run_started_at;
  if (!reference) return null;
  const parts = kstParts(reference);
  const cycleDate = kstDateKey(parts);
  const normalTargetAt = kstIsoAt(parts, 7, 30);
  const deadlineAt = kstIsoAt(parts, 8, 0);
  const normalMs = Date.parse(normalTargetAt);
  const deadlineMs = Date.parse(deadlineAt);
  const completedMs = publishCompletedAt ? Date.parse(publishCompletedAt) : null;
  const nowMs = new Date(now).getTime();

  let timingStatus;
  if (completedMs !== null) {
    timingStatus = completedMs <= normalMs
      ? "normal"
      : (completedMs <= deadlineMs ? "warning" : "breached");
  } else {
    timingStatus = nowMs < normalMs
      ? "pending"
      : (nowMs < deadlineMs ? "warning" : "breached");
  }

  const sourceStatus = sourceState?.status || "not_checked";
  const scheduleStatus = scheduleState?.status || "not_checked";
  let status = timingStatus;
  if (sourceState && sourceStatus === "unknown") {
    status = "unknown";
  } else if (timingStatus === "breached" || scheduleStatus === "breached") {
    status = "breached";
  } else if (["failed", "incomplete"].includes(sourceStatus)) {
    status = "degraded";
  } else if (timingStatus === "warning" || scheduleStatus === "warning") {
    status = "warning";
  }

  return {
    cycle_date_kst: cycleDate,
    scheduled_sources: SCHEDULED_SOURCES,
    latest_publish_completed_at: publishCompletedAt || null,
    normal_target_at: normalTargetAt,
    sla_deadline_at: deadlineAt,
    timing_status: timingStatus,
    schedule_status: scheduleStatus,
    schedule_expected_count: scheduleState?.expected_count ?? null,
    schedule_observed_count: scheduleState?.observed_count ?? null,
    schedule_missing_count: scheduleState?.missing_count ?? null,
    schedule_max_delay_minutes: scheduleState?.max_trigger_delay_minutes ?? null,
    source_status: sourceStatus,
    failed_sources: sourceState?.failed_sources || [],
    missing_sources: sourceState?.missing_sources || [],
    status,
  };
};

// 상단 신호등은 "오늘 SLA 기록"이 아니라 "지금 조치가 필요한가"를 보여준다.
// 정기시각을 놓쳤거나 실패/미완료인데 아무 수집도 안 돌면 빨강,
// 같은 상태에서 현재 수집/복구가 진행 중이면 노랑이다. 정상 완료 후에는
// 늦게 끝났더라도 현재 신호는 초록으로 회복하고 SLA 지연 이력은 sla에 남긴다.
export const operationalSignal = (sla, activeCollection = null) => {
  const active = Boolean(activeCollection && ACTIVE.has(activeCollection.status));
  if (!sla || sla.status === "unknown" || sla.source_status === "unknown") {
    return {
      status: "unknown",
      reason: "health_evidence_unavailable",
      active_collection: active,
    };
  }

  const sourceBroken = ["failed", "incomplete"].includes(sla.source_status);
  const cycleFinished = Boolean(sla.latest_publish_completed_at) && !sourceBroken;
  if (cycleFinished) {
    return {
      status: "normal",
      reason: "cycle_complete",
      active_collection: active,
    };
  }

  const scheduleMissed = ["warning", "breached"].includes(sla.schedule_status);
  const completionLate = ["warning", "breached"].includes(sla.timing_status);
  const recoveryRequired = sourceBroken || scheduleMissed || completionLate;
  if (recoveryRequired) {
    return {
      status: active ? "warning" : "breached",
      reason: active ? "recovery_running" : "recovery_required_not_running",
      active_collection: active,
    };
  }

  return {
    status: "pending",
    reason: active ? "on_time_collection_running" : "awaiting_scheduled_cycle",
    active_collection: active,
  };
};

const SOURCE_STEPS = {
  "Collect finlife savings bank": "finlife_savings_bank",
  "Collect finlife bank": "finlife_bank",
  "Collect BOK base rate": "bok_ecos",
  "Collect FSB": "fsb",
  "Collect CU": "cu",
  "Collect KFCC": "kfcc",
  "Recover KFCC": "kfcc",
  "Collect NH local": "nh_local",
  // Historical runs before the independent fresh-runner workflow used this step.
  "Recover NH local": "nh_local",
};

const PIPELINE_STEPS = {
  "Snapshot": "snapshot",
  "Validate stored data": "validation",
  "Build dashboard": "dashboard",
  "Export full dataset": "export",
  "Build public site": "site",
  "Verify P1-A gate": "p1a_gate",
  "Size gate": "size_gate",
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

const loadRunSteps = async (token, slug, run) => {
  const sourceSteps = {};
  const pipelineSteps = {};
  if (!run) return { sourceSteps, pipelineSteps, evidenceAvailable: true };
  const jobsRes = await gh(token, `/repos/${slug}/actions/runs/${run.id}/jobs?per_page=20`);
  if (!jobsRes.ok) return { sourceSteps, pipelineSteps, evidenceAvailable: false };
  const jobs = (await jobsRes.json()).jobs || [];
  for (const job of jobs) {
    for (const step of job.steps || []) {
      if (SOURCE_STEPS[step.name]) {
        const sourceId = SOURCE_STEPS[step.name];
        const view = stepView(step);
        // Reusable NH attempts are ordered. A later real attempt supersedes an
        // earlier skipped collector step, just as the old recovery step did.
        if (view.conclusion !== "skipped" || !sourceSteps[sourceId]) {
          sourceSteps[sourceId] = view;
        }
      }
      if (PIPELINE_STEPS[step.name]) {
        pipelineSteps[PIPELINE_STEPS[step.name]] = stepView(step);
      }
    }
  }
  return { sourceSteps, pipelineSteps, evidenceAvailable: true };
};

const cycleSourceState = (cycleDetails, publishCompletedAt) => {
  if (cycleDetails.some((detail) => detail.evidenceAvailable === false)) {
    return {
      status: "unknown",
      failed_sources: [],
      missing_sources: [],
    };
  }

  const sourceSteps = {};
  for (const detail of cycleDetails) {
    for (const [sourceId, step] of Object.entries(detail.sourceSteps || {})) {
      if (step.conclusion === "skipped") continue;
      // cycleDetails는 최신 run부터 온다. 같은 source가 재실행됐으면 최신 결과를 쓴다.
      if (!sourceSteps[sourceId]) sourceSteps[sourceId] = step;
    }
  }

  const failedSources = SCHEDULED_SOURCES.filter((sourceId) => {
    const conclusion = sourceSteps[sourceId]?.conclusion;
    return conclusion && FAILED_CONCLUSIONS.has(conclusion);
  });
  const successfulSources = SCHEDULED_SOURCES.filter(
    (sourceId) => sourceSteps[sourceId]?.conclusion === "success",
  );
  const missingSources = SCHEDULED_SOURCES.filter(
    (sourceId) => !successfulSources.includes(sourceId) && !failedSources.includes(sourceId),
  );

  let status;
  if (failedSources.length) status = "failed";
  else if (publishCompletedAt && missingSources.length) status = "incomplete";
  else if (missingSources.length) status = "pending";
  else status = "healthy";

  return {
    status,
    failed_sources: failedSources,
    missing_sources: missingSources,
  };
};

const settings = () => {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const owner = process.env.VERCEL_GIT_REPO_OWNER;
  const repo = process.env.VERCEL_GIT_REPO_SLUG;
  const slug = process.env.GITHUB_REPOSITORY || (owner && repo ? `${owner}/${repo}` : null);
  return { token, slug };
};

const healthNow = () => {
  const override = process.env.RATE_MONITOR_HEALTH_NOW;
  if (!override) return new Date();
  const parsed = new Date(override);
  return Number.isFinite(parsed.getTime()) ? parsed : new Date();
};

const loadWorkflowRuns = async (token, slug, workflow, scheduledOnly = false) => {
  const suffix = scheduledOnly ? "?event=schedule&per_page=20" : "?per_page=30";
  const response = await gh(
    token,
    `/repos/${slug}/actions/workflows/${workflow}/runs${suffix}`,
  );
  if (!response.ok) {
    return { ok: false, status: response.status, workflow, runs: [] };
  }
  const body = await response.json();
  return { ok: true, status: response.status, workflow, runs: body.workflow_runs || [] };
};

// Canonical acquisition은 morning parent와 세 child workflow에서 보인다. 다만 운영 중
// one-shot 검증처럼 별도 caller가 production nh-attempt.yml을 재사용할 수도 있다.
// 그런 실행도 실제 canonical 수집 경로를 점유하므로 "현재 수집 없음"으로 숨기지 않는다.
const isIndirectNhAcquisitionRun = (run) => {
  const path = String(run?.path || "");
  if ([MORNING_WORKFLOW, CORE_WORKFLOW, NH_WORKFLOW, FUNDING_WORKFLOW]
    .some((workflow) => path === `.github/workflows/${workflow}`)) {
    return false;
  }
  return (run?.referenced_workflows || []).some((reference) =>
    String(reference?.path || "").includes("/.github/workflows/nh-attempt.yml@"));
};

const loadRecentRepositoryRuns = async (token, slug) => {
  try {
    const response = await gh(token, `/repos/${slug}/actions/runs?per_page=50`);
    if (!response.ok) return { ok: false, status: response.status, runs: [] };
    const body = await response.json();
    return { ok: true, status: response.status, runs: body.workflow_runs || [] };
  } catch {
    // 이 조회는 보조 신호다. 실패해도 canonical workflow 상태는 그대로 제공한다.
    return { ok: false, status: 0, runs: [] };
  }
};

const latestSuccessfulPublishCompletion = (cycleDetails) => {
  const completed = cycleDetails
    .map((detail) => detail.pipelineSteps?.publish)
    .filter((step) => step?.conclusion === "success" && step.completed_at)
    .map((step) => step.completed_at)
    .sort((a, b) => Date.parse(b) - Date.parse(a));
  return completed[0] || null;
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

  const [
    morningRunsResult,
    morningScheduledResult,
    coreRunsResult,
    nhRunsResult,
    fundingRunsResult,
    repositoryRunsResult,
  ] = await Promise.all([
    loadWorkflowRuns(token, slug, MORNING_WORKFLOW),
    loadWorkflowRuns(token, slug, MORNING_WORKFLOW, true),
    loadWorkflowRuns(token, slug, CORE_WORKFLOW),
    loadWorkflowRuns(token, slug, NH_WORKFLOW),
    loadWorkflowRuns(token, slug, FUNDING_WORKFLOW),
    loadRecentRepositoryRuns(token, slug),
  ]);
  const failed = [
    morningRunsResult,
    morningScheduledResult,
    coreRunsResult,
    nhRunsResult,
    fundingRunsResult,
  ].find((result) => !result.ok);
  if (failed) {
    return json(res, 502, {
      ok: false,
      error: `GitHub 수집 이력을 읽지 못했습니다 (${failed.workflow}: ${failed.status}).`,
    });
  }

  const runs = mergeRuns(
    morningRunsResult.runs,
    coreRunsResult.runs,
    nhRunsResult.runs,
    fundingRunsResult.runs,
  );
  const scheduledRuns = mergeRuns(morningScheduledResult.runs);
  const collections = runs.filter((run) => run.event !== "push");
  const indirectActiveCollections = repositoryRunsResult.ok
    ? repositoryRunsResult.runs.filter(
      (run) => ACTIVE.has(run.status) && isIndirectNhAcquisitionRun(run),
    )
    : [];
  const activeCollection = mergeRuns(collections, indirectActiveCollections)
    .find((run) => ACTIVE.has(run.status)) || null;
  const activePublish = runs.find((run) => run.event === "push" && ACTIVE.has(run.status)) || null;
  const latestCollection = collections[0] || null;
  const latestPublish = runs.find((run) => run.conclusion === "success") || null;
  const detailRun = activeCollection || latestCollection;

  const detail = await loadRunSteps(token, slug, detailRun);
  const now = healthNow();
  const scheduleState = scheduleTriggerHealth(scheduledRuns, now);
  const cycleDate = scheduleState.cycle_date_kst;
  const cycleRuns = cycleDate
    ? scheduledRuns.filter((run) => cycleDateOfScheduledRun(run) === cycleDate)
    : [];
  const cycleDetails = await Promise.all(cycleRuns.map(async (run) => (
    detailRun && run.id === detailRun.id ? detail : loadRunSteps(token, slug, run)
  )));

  // Parent run의 reusable children 안에서 마지막 canonical publish가 완료된 시각을 쓴다.
  // 특정 source(KFCC)를 "항상 finisher"로 가정하지 않는다.
  const publishCompletedAt = latestSuccessfulPublishCompletion(cycleDetails);
  const sourceState = cycleSourceState(cycleDetails, publishCompletedAt);
  const cycleAnchor = cycleDate
    ? { created_at: `${cycleDate}T00:00:00+09:00` }
    : null;
  const sla = cycleSla(cycleAnchor, publishCompletedAt, now, sourceState, scheduleState);
  const signal = operationalSignal(sla, activeCollection);

  return json(res, 200, {
    ok: true,
    latest_collection: runView(latestCollection),
    active_collection: runView(activeCollection),
    active_publish: runView(activePublish),
    latest_publish: runView(latestPublish),
    source_steps: detail.sourceSteps,
    pipeline_steps: detail.pipelineSteps,
    schedule: scheduleState,
    sla,
    signal,
  });
}
