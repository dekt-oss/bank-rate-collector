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

// 이 파일은 ES 모듈이다(`export default`). `require`를 섞으면 Node가 형식을
// 정하지 못하고 통째로 죽는다 — 실제로 그렇게 짰다가 잡았다.
import { timingSafeEqual } from "node:crypto";

const WORKFLOW = "collect.yml";
const REF = "main";

// 마지막 수집이 이 시간 안에 시작됐으면 거절한다.
//
// 전국 수집은 실측 3시간 41분이고 원천 9,743곳에 요청을 보낸다. 실수로 두 번
// 누르는 것과 일부러 도배하는 것을 같은 방법으로 막는다. `concurrency` 그룹이
// 줄을 세우므로 데이터가 깨지지는 않지만, 원천에 두 배로 가는 것은 막아야 한다.
const DEFAULT_MIN_INTERVAL_MINUTES = 30;

// 틀린 암호에 붙이는 지연. 추측을 초당 수천 번에서 초당 한 번으로 낮춘다.
// 맞은 요청에는 안 붙인다 — 사람이 기다릴 이유가 없다.
const WRONG_PASSWORD_DELAY_MS = 1000;

// 틀렸을 때 **왜** 틀렸는지 알려주지 않는다. "암호가 짧다"까지만 알려줘도
// 추측하는 쪽에는 큰 단서가 된다.
const REJECT = "수집 암호가 맞지 않습니다.";

const json = (res, status, body) => {
  res.setHeader("content-type", "application/json; charset=utf-8");
  // 이 함수는 같은 도메인에서만 부른다. 다른 곳에서 부를 이유가 없으므로
  // CORS를 열지 않는다.
  res.status(status).send(JSON.stringify(body));
};

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

/** 길이가 달라도 시간이 새지 않는 비교. */
const constantTimeEqual = (a, b) => {
  const left = Buffer.from(String(a ?? ""), "utf8");
  const right = Buffer.from(String(b ?? ""), "utf8");
  // timingSafeEqual은 길이가 다르면 던진다. 길이 자체는 어차피 응답 시간으로
  // 새지 않게 아래에서 한 번에 판정한다.
  const size = Math.max(left.length, right.length, 1);
  const padLeft = Buffer.alloc(size);
  const padRight = Buffer.alloc(size);
  left.copy(padLeft);
  right.copy(padRight);
  return timingSafeEqual(padLeft, padRight) && left.length === right.length;
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
  const res = await gh(token, `/repos/${slug}/actions/workflows/${WORKFLOW}/runs?per_page=20`);
  if (!res.ok) {
    return { code: 502, reason: `GitHub이 실행 목록을 주지 않았습니다 (${res.status}).` };
  }
  const runs = (await res.json()).workflow_runs || [];

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

  // main 푸시로 도는 실행은 수집이 아니라 발행이다(2분). 그것 때문에 수집을
  // 막으면, 머지한 직후에는 아무도 수집을 못 돌리게 된다.
  const lastCollect = runs.find((r) => r.event !== "push");
  if (lastCollect) {
    const startedAt = Date.parse(lastCollect.run_started_at || lastCollect.created_at);
    const minutes = (Date.now() - startedAt) / 60000;
    if (Number.isFinite(minutes) && minutes < minIntervalMinutes) {
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

const buildInputs = (body, password) => {
  const inputs = { password };
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

  const password = process.env.COLLECT_PASSWORD;
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const slug = process.env.GITHUB_REPOSITORY;
  // 반쯤 켜진 상태를 만들지 않는다. 셋 중 하나라도 없으면 «설정이 덜 됐다»고
  // 분명히 말한다 — 조용히 실패하면 암호가 틀린 줄 알고 계속 눌러 보게 된다.
  const missing = [
    !password && "COLLECT_PASSWORD",
    !token && "GITHUB_DISPATCH_TOKEN",
    !slug && "GITHUB_REPOSITORY",
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

  if (!constantTimeEqual(body.password, password)) {
    await sleep(WRONG_PASSWORD_DELAY_MS);
    return json(res, 401, { ok: false, error: REJECT });
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
    { method: "POST", body: JSON.stringify({ ref: REF, inputs: buildInputs(body, password) }) },
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
  return json(res, 202, {
    ok: true,
    message: "수집을 시작했습니다. 전국 한 바퀴는 약 3시간 40분 걸립니다.",
    url: `https://github.com/${slug}/actions/workflows/${WORKFLOW}`,
  });
}
