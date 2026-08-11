// 관리자 수집 상태 조회. 읽기 전용이다.
// GitHub token은 서버 환경에만 있고 브라우저에는 내려가지 않는다.

const WORKFLOW = "collect.yml";
const ACTIVE = new Set(["in_progress", "queued", "waiting", "pending"]);

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const SCHEDULED_SOURCES = [
  "finlife_savings_bank", "finlife_bank", "bok_ecos", "fsb", "cu", "nh_local", "kfcc",
];
const FAILED_CONCLUSIONS = new Set(["failure", "cancelled", "timed_out", "action_required", "startup_failure"]);

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
const kstDateOfRun = (run) => {
  if (!run) return null;
  const reference = run.run_started_at || run.created_at;
  if (!reference) return null;
  const parts = kstParts(reference);
  return `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`;
};

export const cycleSla = (
  scheduledRun,
  publishCompletedAt,
  now = new Date(),
  sourceState = null,
) => {
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
  let status = timingStatus;
  if (sourceState && sourceStatus === "unknown") {
    status = "unknown";
  } else if (
    timingStatus !== "breached" && ["failed", "incomplete"].includes(sourceStatus)
  ) {
    status = "degraded";
  }

  return {
    cycle_date_kst: cycleDate,
    scheduled_sources: SCHEDULED_SOURCES,
    latest_publish_completed_at: publishCompletedAt || null,
    normal_target_at: normalTargetAt,
    sla_deadline_at: deadlineAt,
    timing_status: timingStatus,
    source_status: sourceStatus,
    failed_sources: sourceState?.failed_sources || [],
    missing_sources: sourceState?.missing_sources || [],
    status,
  };
};

const SOURCE_STEPS = {
  "Collect finlife savings bank": "finlife_savings_bank",
  "Collect finlife bank": "finlife_bank",
  "Collect BOK base rate": "bok_ecos",
  "Collect FSB": "fsb",
  "Collect CU": "cu",
  "Collect KFCC": "kfcc",
  "Collect NH local": "nh_local",
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
        // Source steps are ordered. Recovery should supersede a failed first
        // attempt only when it actually ran; a skipped recovery preserves it.
        if (view.conclusion !== "skipped" || !sourceSteps[sourceId]) {
          sourceSteps[sourceId] = view;
        }
      }
      if (PIPELINE_STEPS[step.name]) pipelineSteps[PIPELINE_STEPS[step.name]] = stepView(step);
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

  const [runsRes, scheduledRunsRes] = await Promise.all([
    gh(token, `/repos/${slug}/actions/workflows/${WORKFLOW}/runs?per_page=30`),
    gh(token, `/repos/${slug}/actions/workflows/${WORKFLOW}/runs?event=schedule&per_page=20`),
  ]);
  if (!runsRes.ok) {
    return json(res, 502, { ok: false, error: `GitHub 실행 상태를 읽지 못했습니다 (${runsRes.status}).` });
  }
  if (!scheduledRunsRes.ok) {
    return json(res, 502, {
      ok: false,
      error: `GitHub 정기 수집 이력을 읽지 못했습니다 (${scheduledRunsRes.status}).`,
    });
  }
  const runs = (await runsRes.json()).workflow_runs || [];
  const scheduledRuns = (await scheduledRunsRes.json()).workflow_runs || [];
  const collections = runs.filter((run) => run.event !== "push");
  const activeCollection = collections.find((run) => ACTIVE.has(run.status)) || null;
  const activePublish = runs.find((run) => run.event === "push" && ACTIVE.has(run.status)) || null;
  const latestCollection = collections[0] || null;
  const latestScheduled = scheduledRuns[0] || null;
  const latestPublish = runs.find((run) => run.conclusion === "success") || null;
  const detailRun = activeCollection || latestCollection;

  const detail = await loadRunSteps(token, slug, detailRun);
  const cycleDate = kstDateOfRun(latestScheduled);
  const cycleRuns = scheduledRuns.filter((run) => kstDateOfRun(run) === cycleDate);
  const cycleDetails = await Promise.all(cycleRuns.map(async (run) => (
    detailRun && run.id === detailRun.id ? detail : loadRunSteps(token, slug, run)
  )));
  const finisher = cycleDetails.find((entry) => {
    const step = entry.sourceSteps.kfcc;
    return step && step.conclusion !== "skipped";
  }) || null;
  const publishStep = finisher?.pipelineSteps.publish || null;
  const publishCompletedAt = publishStep?.conclusion === "success"
    ? publishStep.completed_at
    : null;
  const sourceState = cycleSourceState(cycleDetails, publishCompletedAt);
  const sla = cycleSla(latestScheduled, publishCompletedAt, new Date(), sourceState);

  return json(res, 200, {
    ok: true,
    latest_collection: runView(latestCollection),
    active_collection: runView(activeCollection),
    active_publish: runView(activePublish),
    latest_publish: runView(latestPublish),
    source_steps: detail.sourceSteps,
    pipeline_steps: detail.pipelineSteps,
    sla,
  });
}
