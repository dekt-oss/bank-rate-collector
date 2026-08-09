// 화면에서 바로 수집을 시작한다 (명세서 v3.1 §12.5).
//
// 이 사이트는 정적 파일이라 서버가 없었다. 그래서 «지금 수집하기»는 GitHub
// 실행 화면으로 보내는 링크였고, 누르면 거기서 입력칸을 다시 채워야 했다.
//
// 화면을 내주는 Vercel이 같은 도메인에서 이 함수를 함께 내준다. GitHub 토큰은
// 여기 환경변수에 있고 **브라우저로 내려가지 않는다.** 그것이 링크였던 이유를
// 없앤다.
//
// 이 파일은 저장소의 `web/api/`에 있고, 발행 단계가 `rate-data` 브랜치의
// `api/`로 복사한다 (`vercel.json`을 옮기는 것과 같은 방식). Vercel은 배포
// 루트의 `api/`만 함수로 잡기 때문이다.

// **암호는 여기에 두지 않는다.** GitHub Actions 시크릿
// `DASHBOARD_PASSWORD` 하나가 유일한 정답이고, 이 함수는 받은 값을 그대로
// 실어 보낸다. 워크플로의 `Check collect password`가 대조한다.
//
// 같은 값을 Vercel에도 넣어 두 곳에서 대조하는 쪽이 방어는 한 겹 두껍다.
// 그러나 암호를 두 곳에 두면 한쪽만 바뀌는 날이 오고, 그때 «맞는데 안 되는»
// 상태가 된다. 어느 쪽이 진짜인지 화면으로는 알 수 없다.
//
// 대신 틀린 값이 GitHub까지 가므로 **시도 자체를 세어 막는다** (아래
// MAX_ATTEMPTS_PER_WINDOW). 그게 없으면 이 주소가 곧 무제한 추측기가 된다.

const WORKFLOW = "collect.yml";
const REF = "main";

// 마지막 수집이 이 시간 안에 시작됐으면 거절한다.
//
// 전국 수집은 실측 3시간 41분이고 원천 9,743곳에 요청을 보낸다. 실수로 두 번
// 누르는 것과 일부러 도배하는 것을 같은 방법으로 막는다. `concurrency` 그룹이
// 줄을 세우므로 데이터가 깨지지는 않지만, 원천에 두 배로 가는 것은 막아야 한다.
const DEFAULT_MIN_INTERVAL_MINUTES = 30;

// 이 시간 안에 시작된 수동 실행이 이만큼 있으면 더 받지 않는다.
//
// 암호를 워크플로가 대조하므로 틀린 값도 실행을 하나 만든다. 그 실행은
// 암호 단계에서 10초쯤 만에 죽지만, 막지 않으면 이 주소가 그대로 무제한
// 추측기가 된다. 다섯 번이면 사람이 오타를 몇 번 내도 넉넉하고, 추측하는
// 쪽에는 시간당 다섯 번이라 쓸모가 없다.
const ATTEMPT_WINDOW_MINUTES = 60;
const MAX_ATTEMPTS_PER_WINDOW = 5;

const json = (res, status, body) => {
  res.setHeader("content-type", "application/json; charset=utf-8");
  // 이 함수는 같은 도메인에서만 부른다. 다른 곳에서 부를 이유가 없으므로
  // CORS를 열지 않는다.
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

/**
 * 지금 돌릴 수 있는가. 못 돌리면 사람이 읽을 이유를 돌려준다.
 *
 * 상태를 우리가 들고 있지 않는다 — 함수는 여러 벌 뜰 수 있어서, 우리 쪽
 * 카운터는 서로 다른 값을 본다. GitHub에 물으면 어느 벌이 답해도 같다.
 */
const whyNot = async (token, slug, minIntervalMinutes) => {
  const res = await gh(token, `/repos/${slug}/actions/workflows/${WORKFLOW}/runs?per_page=30`);
  if (!res.ok) {
    return { code: 502, reason: `GitHub이 실행 목록을 주지 않았습니다 (${res.status}).` };
  }
  const runs = (await res.json()).workflow_runs || [];
  const minutesSince = (r) => {
    const t = Date.parse(r.run_started_at || r.created_at);
    return Number.isFinite(t) ? (Date.now() - t) / 60000 : Infinity;
  };

  const active = runs.find(
    (r) => r.status === "in_progress" || r.status === "queued" || r.status === "waiting",
  );
  if (active) {
    return {
      code: 409,
      reason: "이미 수집이 돌고 있습니다. 끝난 뒤에 다시 눌러 주세요.",
      url: active.html_url,
    };
  }

  // 암호를 워크플로가 대조하므로 틀린 값도 실행을 하나 남긴다. 시도를 세지
  // 않으면 이 주소가 무제한 추측기가 된다. 성공·실패를 가리지 않고 센다 —
  // 실패만 세면 맞는 암호를 섞어 세탁할 수 있다.
  const attempts = runs.filter(
    (r) => r.event === "workflow_dispatch" && minutesSince(r) < ATTEMPT_WINDOW_MINUTES,
  );
  if (attempts.length >= MAX_ATTEMPTS_PER_WINDOW) {
    return {
      code: 429,
      reason: "시도가 너무 잦습니다. 잠시 뒤에 다시 눌러 주세요.",
    };
  }

  // 간격 제한은 **실제로 돈 수집**만 센다.
  //
  // 암호가 틀려 10초 만에 죽은 실행까지 세면, 오타 한 번에 30분을 기다리게
  // 된다. main 푸시로 도는 실행도 수집이 아니라 발행(2분)이라 빼야 한다 —
  // 그것 때문에 막으면 머지 직후에는 아무도 수집을 못 돌린다.
  const lastCollect = runs.find(
    (r) => r.event !== "push" && r.conclusion === "success",
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
 * 화면이 보낸 값을 워크플로 입력으로 옮긴다.
 *
 * **화면이 보낸 것을 그대로 믿지 않는다.** 아는 이름만 통과시키고, 아는
 * 값만 넣는다. 모르는 이름을 그대로 넘기면 화면 코드 한 줄로 워크플로의
 * 아무 입력이나 건드릴 수 있게 된다.
 */
const SCOPES = ["전국", "수도권", "부산"];
const FLAGS = [
  "skip_kfcc", "skip_fsb", "skip_cu", "skip_nh_local",
  "skip_finlife_bank", "skip_bok", "publish_only",
];

const buildInputs = (body) => {
  // 암호는 화면이 보낸 값을 그대로 실어 보낸다. 여기서 판단하지 않는다.
  const inputs = { password: String(body.password) };
  for (const name of FLAGS) {
    if (body[name] === true) inputs[name] = "true";
  }
  for (const name of ["kfcc_scope", "nh_local_scope"]) {
    if (SCOPES.includes(body[name])) inputs[name] = body[name];
  }
  return inputs;
};

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return json(res, 405, { ok: false, error: "POST로 불러 주세요." });
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  // 저장소 이름은 **손으로 넣지 않아도 된다.** Vercel이 어느 저장소에서
  // 배포했는지 알고 있고 그 값을 환경에 넣어 준다. 넣어야 할 것을 하나로
  // 줄이면 «설정이 반만 된» 상태도 그만큼 덜 생긴다.
  //
  // 다만 그 노출은 프로젝트 설정(System Environment Variables)에 달려 있어
  // 꺼져 있을 수 있다. 그래서 명시적으로 넣은 값을 먼저 보고, 없으면
  // Vercel이 준 값으로 맞춘다.
  const owner = process.env.VERCEL_GIT_REPO_OWNER;
  const repo = process.env.VERCEL_GIT_REPO_SLUG;
  const slug = process.env.GITHUB_REPOSITORY
    || (owner && repo ? `${owner}/${repo}` : null);

  // 반쯤 켜진 상태를 만들지 않는다. 하나라도 없으면 «설정이 덜 됐다»고
  // 분명히 말한다 — 조용히 실패하면 암호가 틀린 줄 알고 계속 눌러 보게 된다.
  //
  // 암호는 여기 없다. GitHub 시크릿 `DASHBOARD_PASSWORD` 하나가 정답이고
  // 워크플로가 대조한다 (맨 위 주석 참고).
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

  // 빈 암호는 여기서 끊는다. GitHub까지 보내 봐야 실행 하나만 버리고,
  // 그 실행이 아래 시도 계산에 들어가 진짜 시도를 막는다.
  if (!body.password) {
    return json(res, 401, { ok: false, error: "수집 암호를 넣어 주세요." });
  }

  const minInterval =
    Number(process.env.COLLECT_MIN_INTERVAL_MINUTES) || DEFAULT_MIN_INTERVAL_MINUTES;
  const blocked = await whyNot(token, slug, minInterval);
  if (blocked) {
    return json(res, blocked.code, { ok: false, error: blocked.reason, url: blocked.url });
  }

  const dispatch = await gh(
    token,
    `/repos/${slug}/actions/workflows/${WORKFLOW}/dispatches`,
    { method: "POST", body: JSON.stringify({ ref: REF, inputs: buildInputs(body) }) },
  );
  if (!dispatch.ok) {
    // GitHub이 준 본문을 그대로 흘리지 않는다. 토큰 범위 같은 것이 섞여 있다.
    return json(res, 502, {
      ok: false,
      error: `수집을 시작하지 못했습니다 (GitHub ${dispatch.status}).`,
    });
  }

  // dispatch는 실행 번호를 주지 않는다. 방금 만들어진 실행을 굳이 찾아
  // 헤매지 않고 목록 주소를 준다 — 몇 초 뒤에 거기 뜬다.
  //
  // **«시작했다»가 «암호가 맞았다»는 뜻은 아니다.** 대조는 그 실행 안에서
  // 일어나므로, 암호가 틀리면 몇 초 뒤 그 실행이 빨간 X로 끝난다. 그렇게
  // 적어야 보는 사람이 목록을 확인하러 간다.
  return json(res, 202, {
    ok: true,
    message: "수집을 시작했습니다. 암호가 맞으면 그대로 돌고,"
      + " 틀리면 실행 목록에서 바로 빨간 X로 끝납니다."
      + " 전국 한 바퀴는 약 3시간 40분 걸립니다.",
    url: `https://github.com/${slug}/actions/workflows/${WORKFLOW}`,
  });
}
