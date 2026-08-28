// 관리자 수집 상태 조회. 읽기 전용이다.
// GitHub token은 서버 환경에만 있고 브라우저에는 내려가지 않는다.

const CORE_WORKFLOW = "collect.yml";
const NH_WORKFLOW = "collect-nh.yml";
const WORKFLOWS = [CORE_WORKFLOW, NH_WORKFLOW];
const ACTIVE = new Set(["in_progress", "queued", "waiting", "pending"]);

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const SCHEDULE_TRIGGER_GRACE_MINUTES = 10;
const SCHEDULE_SLOTS = [
  { id: "core", hour: 0, minute: 17 },
  { id: "nh", hour: 0, minute: 37 },
  { id: "kfcc", hour: 4, minute: 17 },
];
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

const kstDateOfRun = (run) => {
  if (!run) return null;
  // scheduled cycle 소속은 job 시작시각이 아니라 GitHub가 run을 만든 시각으로 본다.
  // writer queue 때문에 자정 뒤에 실제 job이 시작돼도 원래 cycle을 잃지 않는다.
  const reference = run.created_at || run.run_started_at;
  if (!reference) return null;
  return kstDateKey(kstParts(reference));
};

const previousBusinessDayParts = (parts) => {
  const cursor = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  do {
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  } while (cursor.getUTCDay() === 0 || cursor.getUTCDay() === 6);
  return {
    year: cursor.getUTCFullYear(),
    month: cursor.getUTCMonth() + 1,
    day: cursor.getUTCDate(),
  };
};

const expectedCycleParts = (now) => {
  const instant = new Date(now);
  const shifted = new Date(instant.getTime() + KST_OFFSET_MS);
  const parts = {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
  };
  const weekday = shifted.getUTCDay();
  const minuteOfDay = shifted.getUTCHours() * 60 + shifted.getUTCMinutes();
  const isWeekday = weekday >= 1 && weekday <= 5;
  // 첫 정기 cycle(00:17 KST)이 아직 오지 않은 평일 새벽은 직전 영업일을 본다.
  if (isWeekday && minuteOfDay >= 17) return parts;
  return previousBusinessDayParts(parts);
};

export const scheduleTriggerHealth = (scheduledRuns, now = new Date()) => {
  const nowDate = new Date(now);
  const nowMs = nowDate.getTime();
  const cycleParts = expectedCycleParts(nowDate);
  const cycleDate = kstDateKey(cycleParts);
  const today = kstDateKey(kstParts(nowDate));
  const isCurrentCycle = cycleDate === today;
  const deadlineMs = Date.parse(kstIsoAt(cycleParts, 8, 0));
  const graceMs = SCHEDULE_TRIGGER_GRACE_MINUTES * 60 * 1000;

  const dueSlots = SCHEDULE_SLOTS.filter((slot) => (
    !isCurrentCycle || nowMs >= Date.parse(kstIsoAt(cycleParts, slot.hour, slot.minute))
  ));
  const observed = scheduledRuns
    .filter((run) => kstDateOfRun(run) === cycleDate)
    .sort((a, b) => createdTime(a) - createdTime(b));
  const paired = dueSlots.map((slot, index) => {
    const expectedMs = Date.parse(kstIsoAt(cycleParts, slot.hour, slot.minute));
    const run = observed[index] || null;
    const actualMs = run ? createdTime(run) : null;
    return actualMs === null
      ? null
      : Math.max(0, Math.floor((actualMs - expectedMs) / 60000));
  });
  const missingCount = Math.max(0, dueSlots.length - observed.length);
  const delays = paired.filter((value) => value !== null);
  // 일부 trigger가 아예 없으면 남은 run을 어느 slot에 대응할지 확정할 수 없다.
  // 그 상태에서는 지연 분수를 지어내지 않고 missing 자체로 warning/red를 판정한다.
  const maxDelayMinutes = missingCount === 0 && delays.length
    ? Math.max(...delays)
    : null;
  const anyCreatedAfterDeadline = observed.some((run) => createdTime(run) > deadlineMs);
  const latestDueMs = dueSlots.length
    ? Date.parse(kstIsoAt(
      cycleParts,
      dueSlots[dueSlots.length - 1].hour,
      dueSlots[dueSlots.length - 1].minute,
    ))
    : null;

  let status = "normal";
  if (!dueSlots.length) {
    status = "pending";
  } else if (nowMs >= deadlineMs && (missingCount > 0 || anyCreatedAfterDeadline)) {
    status = "breached";
  } else if (
    missingCount > 0
    && latestDueMs !== null
    && nowMs >= latestDueMs + graceMs
  ) {
    status = "warning";
  } else if (
    maxDelayMinutes !== null
    && maxDelayMinutes > SCHEDULE_TRIGGER_GRACE_MINUTES
  ) {
    status = "warning";
  } else if (missingCount > 0) {
    status = "pending";
  }

  return {
    cycle_date_kst: cycleDate,
    expected_count: dueSlots.length,
    observed_count: Math.min(observed.length, dueSlots.length),
    missing_count: missingCount,
    max_trigger_delay_minutes: maxDelayMinutes,
    grace_minutes: SCHEDULE_TRIGGER_GRACE_MINUTES,
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

// 보통 수집은 위 두 canonical workflow에서 보인다. 다만 운영 중 one-shot
// 검증처럼 별도 caller가 production `nh-attempt.yml`을 재사용할 수도 있다.
// 그런 실행도 실제 canonical 수집 경로를 점유하므로 "현재 수집 없음"으로
// 숨기지 않는다. 완료된 임시 실행은 최신 수집 이력/SLA에는 섞지 않는다.
const isIndirectNhAcquisitionRun = (run) => {
  const path = String(run?.path || "");
  if (path === `.github/workflows/${CORE_WORKFLOW}`
      || path === `.github/workflows/${NH_WORKFLOW}`) {
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
    // 이 조회는 보조 신호다. 실패해도 canonical collect/collect-nh 상태는 그대로 제공한다.
    return { ok: false, status: 0, runs: [] };
  }
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
    coreRunsResult,
    coreScheduledResult,
    nhRunsResult,
    nhScheduledResult,
    repositoryRunsResult,
  ] = await Promise.all([
    loadWorkflowRuns(token, slug, CORE_WORKFLOW),
    loadWorkflowRuns(token, slug, CORE_WORKFLOW, true),
    loadWorkflowRuns(token, slug, NH_WORKFLOW),
    loadWorkflowRuns(token, slug, NH_WORKFLOW, true),
    loadRecentRepositoryRuns(token, slug),
  ]);
  const failed = [
    coreRunsResult,
    coreScheduledResult,
    nhRunsResult,
    nhScheduledResult,
  ].find((result) => !result.ok);
  if (failed) {
    return json(res, 502, {
      ok: false,
      error: `GitHub 수집 이력을 읽지 못했습니다 (${failed.workflow}: ${failed.status}).`,
    });
  }

  const runs = mergeRuns(coreRunsResult.runs, nhRunsResult.runs);
  const scheduledRuns = mergeRuns(coreScheduledResult.runs, nhScheduledResult.runs);
  const collections = runs.filter((run) => run.event !== "push");
  // 보조 탐색 실패는 canonical health 자체를 깨지 않는다. canonical workflow는
  // 기존 조회로 계속 보이고, indirect caller 감지만 잠시 빠질 뿐이다.
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
  const cycleRuns = scheduledRuns.filter((run) => kstDateOfRun(run) === cycleDate);
  const cycleDetails = await Promise.all(cycleRuns.map(async (run) => (
    detailRun && run.id === detailRun.id ? detail : loadRunSteps(token, slug, run)
  )));

  // KFCC remains the scheduled finisher. Its successful publish means core + NH
  // + KFCC have all had a chance to run in the writer queue for this cycle.
  const finisher = cycleDetails.find((entry) => {
    const step = entry.sourceSteps.kfcc;
    return step && step.conclusion !== "skipped";
  }) || null;
  const publishStep = finisher?.pipelineSteps.publish || null;
  const publishCompletedAt = publishStep?.conclusion === "success"
    ? publishStep.completed_at
    : null;
  const sourceState = cycleSourceState(cycleDetails, publishCompletedAt);
  const cycleAnchor = cycleDate
    ? { created_at: `${cycleDate}T00:17:00+09:00` }
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