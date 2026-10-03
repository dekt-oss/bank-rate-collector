// 화면에서 바로 수집을 시작한다 (명세서 v3.1 §12.5).
//
// NH가 독립 workflow로 분리됐으므로 관리자 버튼 하나는 core와 NH 두 실행을
// 함께 dispatch한다. 둘은 같은 rate-data-writer concurrency를 사용하므로
// canonical 상태를 동시에 쓰지 않는다.
//
// 화면을 내주는 Vercel이 같은 도메인에서 이 함수를 함께 내준다. GitHub 토큰은
// 여기 환경변수에 있고 **브라우저로 내려가지 않는다.**
//
// **암호는 여기에 두지 않는다.** GitHub Actions 시크릿
// `DASHBOARD_PASSWORD` 하나가 유일한 정답이고, 이 함수는 받은 값을 두
// workflow에 그대로 실어 보낸다. 각 workflow의 password step이 대조한다.

const CORE_WORKFLOW = "collect.yml";
const NH_WORKFLOW = "collect-nh.yml";
const WORKFLOWS = [CORE_WORKFLOW, NH_WORKFLOW];
const REF = "main";

// 마지막 실제 수집이 이 시간 안에 시작됐으면 거절한다. core와 NH를 따로
// 돌리더라도 관리자 버튼을 연속으로 눌러 같은 원천을 중복 수집하지 않게 한다.
const DEFAULT_MIN_INTERVAL_MINUTES = 30;

// 암호는 workflow에서 검사한다. 잘못된 암호도 core workflow_dispatch 한 건을
// 남기므로 core 실행만 세어 "한 번 누름 = 한 번의 암호 시도"로 유지한다.
const ATTEMPT_WINDOW_MINUTES = 60;
const MAX_ATTEMPTS_PER_WINDOW = 5;

const json = (res, status, body) => {
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.status(status).send(JSON.stringify(body));
};

const gh = async (token, path, init = {}) =>
  fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${token}`,
      "x-github-api-version": "2022-11-28",
      "content-type": "application/json",
      ...(init.headers || {}),
    },
  });

const runTime = (run) => {
  const value = Date.parse(run.run_started_at || run.created_at || "");
  return Number.isFinite(value) ? value : 0;
};

const loadWorkflowRuns = async (token, slug, workflow) => {
  const response = await gh(
    token,
    `/repos/${slug}/actions/workflows/${workflow}/runs?per_page=30`,
  );
  if (!response.ok) return { ok: false, status: response.status, runs: [] };
  const payload = await response.json();
  return { ok: true, status: response.status, runs: payload.workflow_runs || [] };
};

/**
 * 지금 돌릴 수 있는가. 못 돌리면 사람이 읽을 이유를 돌려준다.
 *
 * 독립 NH까지 함께 본다. core만 보고 "안 돈다"고 판단하면 NH가 3시간째
 * 수집 중인데 관리자 버튼으로 NH를 하나 더 만들 수 있다.
 */
const whyNot = async (token, slug, minIntervalMinutes) => {
  const groups = await Promise.all(
    WORKFLOWS.map((workflow) => loadWorkflowRuns(token, slug, workflow)),
  );
  const failed = groups.find((group) => !group.ok);
  if (failed) {
    return {
      code: 502,
      reason: `GitHub이 실행 목록을 주지 않았습니다 (${failed.status}).`,
    };
  }

  const coreRuns = groups[0].runs;
  const runs = groups.flatMap((group) => group.runs).sort((a, b) => runTime(b) - runTime(a));
  const minutesSince = (run) => {
    const started = runTime(run);
    return started ? (Date.now() - started) / 60000 : Infinity;
  };

  const active = runs.find(
    (run) => run.status === "in_progress" || run.status === "queued" || run.status === "waiting",
  );
  if (active) {
    return {
      code: 409,
      reason: "이미 수집이 돌고 있습니다. 끝난 뒤에 다시 눌러 주세요.",
      url: active.html_url,
    };
  }

  // 잘못된 암호 한 번이 core+NH 두 workflow를 만들지만, 사람의 시도 횟수는
  // core workflow_dispatch만 세어 한 번으로 본다.
  const attempts = coreRuns.filter(
    (run) => run.event === "workflow_dispatch" && minutesSince(run) < ATTEMPT_WINDOW_MINUTES,
  );
  if (attempts.length >= MAX_ATTEMPTS_PER_WINDOW) {
    return {
      code: 429,
      reason: "시도가 너무 잦습니다. 잠시 뒤에 다시 눌러 주세요.",
    };
  }

  // main push는 수집이 아니라 발행뿐이다. core/NH 중 실제 성공 수집의 가장
  // 최근 실행을 기준으로 간격을 계산한다.
  const lastCollect = runs.find(
    (run) => run.event !== "push" && run.conclusion === "success",
  );
  if (lastCollect) {
    const minutes = minutesSince(lastCollect);
    if (minutes < minIntervalMinutes) {
      const wait = Math.ceil(minIntervalMinutes - minutes);
      return {
        code: 429,
        reason: `방금 수집했습니다. ${wait}분 뒤에 다시 눌러 주세요.`,
        url: lastCollect.html_url,
      };
    }
  }
  return null;
};

/**
 * 화면이 보낸 값을 각 workflow 입력으로 옮긴다. 아는 이름/값만 통과시킨다.
 */
const SCOPES = ["전국", "수도권", "부산"];
const FLAGS = [
  "skip_kfcc", "skip_fsb", "skip_cu",
  "skip_finlife_bank", "skip_bok", "publish_only",
];

const buildInputs = (body) => {
  const password = String(body.password);
  const core = { password };
  const nh = { password };

  for (const name of FLAGS) {
    if (body[name] === true) core[name] = "true";
  }
  if (SCOPES.includes(body.kfcc_scope)) core.kfcc_scope = body.kfcc_scope;
  if (SCOPES.includes(body.nh_local_scope)) nh.nh_local_scope = body.nh_local_scope;
  return { core, nh };
};

const dispatchWorkflow = (token, slug, workflow, inputs) => gh(
  token,
  `/repos/${slug}/actions/workflows/${workflow}/dispatches`,
  { method: "POST", body: JSON.stringify({ ref: REF, inputs }) },
);

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return json(res, 405, { ok: false, error: "POST로 불러 주세요." });
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const owner = process.env.VERCEL_GIT_REPO_OWNER;
  const repo = process.env.VERCEL_GIT_REPO_SLUG;
  const slug = process.env.GITHUB_REPOSITORY
    || (owner && repo ? `${owner}/${repo}` : null);

  const missing = [
    !token && "GITHUB_DISPATCH_TOKEN",
    !slug && "GITHUB_REPOSITORY (또는 Vercel 시스템 환경변수 노출)",
  ].filter(Boolean);
  if (missing.length) {
    return json(res, 503, {
      ok: false,
      configured: false,
      error: `수집 시작이 아직 설정되지 않았습니다 (${missing.join(", ")}).`,
    });
  }

  let body = req.body;
  if (typeof body === "string") {
    try {
      body = JSON.parse(body);
    } catch {
      body = null;
    }
  }
  if (!body || typeof body !== "object") {
    return json(res, 400, { ok: false, error: "요청을 읽지 못했습니다." });
  }

  if (!body.password) {
    return json(res, 401, { ok: false, error: "수집 암호를 넣어 주세요." });
  }

  const minInterval =
    Number(process.env.COLLECT_MIN_INTERVAL_MINUTES) || DEFAULT_MIN_INTERVAL_MINUTES;
  const blocked = await whyNot(token, slug, minInterval);
  if (blocked) {
    return json(res, blocked.code, { ok: false, error: blocked.reason, url: blocked.url });
  }

  const inputs = buildInputs(body);
  const [coreDispatch, nhDispatch] = await Promise.all([
    dispatchWorkflow(token, slug, CORE_WORKFLOW, inputs.core),
    dispatchWorkflow(token, slug, NH_WORKFLOW, inputs.nh),
  ]);

  const failed = [
    [CORE_WORKFLOW, coreDispatch],
    [NH_WORKFLOW, nhDispatch],
  ].filter(([, response]) => !response.ok);

  if (failed.length) {
    const partial = failed.length !== WORKFLOWS.length;
    const detail = failed.map(([workflow, response]) => `${workflow}: ${response.status}`).join(", ");
    return json(res, 502, {
      ok: false,
      partial,
      error: partial
        ? `수집 일부만 시작됐습니다. GitHub 실행 목록을 확인해 주세요 (${detail}).`
        : `수집을 시작하지 못했습니다 (${detail}).`,
      url: `https://github.com/${slug}/actions`,
    });
  }

  return json(res, 202, {
    ok: true,
    message: "일반 수집과 농·축협 독립 수집을 시작했습니다."
      + " 암호가 맞으면 같은 writer 대기열에서 순서대로 돌고,"
      + " 틀리면 두 실행 모두 바로 빨간 X로 끝납니다.",
    url: `https://github.com/${slug}/actions`,
  });
}
