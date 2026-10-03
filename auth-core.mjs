export const LOGIN_PATH = "/__login";
export const LOGOUT_PATH = "/__logout";
export const SESSION_COOKIE = "__Host-rate_monitor_auth_v2";
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 6;

const textEncoder = new TextEncoder();

const securityHeaders = {
  "cache-control": "no-store, max-age=0",
  "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
};

const escapeHtml = (value) => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#39;");

const digest = async (value) => new Uint8Array(
  await crypto.subtle.digest("SHA-256", textEncoder.encode(String(value))),
);

const base64Url = (bytes) => {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
};

const constantTimeEqual = async (left, right) => {
  const [a, b] = await Promise.all([digest(left), digest(right)]);
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) {
    difference |= a[index] ^ b[index];
  }
  return difference === 0;
};

const sessionToken = async (password) => base64Url(
  await digest(`bank-rate-collector:site-session:v1\0${password}`),
);

const parseCookie = (header, name) => {
  if (!header) return null;
  for (const part of header.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    const key = part.slice(0, separator).trim();
    if (key === name) return part.slice(separator + 1).trim();
  }
  return null;
};

export const safeReturnTo = (value) => {
  if (!value) return "/";
  try {
    const candidate = new URL(String(value), "https://rate-monitor.invalid");
    if (candidate.origin !== "https://rate-monitor.invalid") return "/";
    if (candidate.pathname === LOGIN_PATH || candidate.pathname === LOGOUT_PATH) return "/";
    return `${candidate.pathname}${candidate.search}${candidate.hash}`;
  } catch {
    return "/";
  }
};

const loginPage = (returnTo, error = "") => `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>금리 모니터 접근</title>
<style>
:root{color-scheme:light;font-family:Inter,Pretendard,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at 15% 15%,#eef6ff 0,transparent 38%),linear-gradient(145deg,#f7f8fb,#eef1f6);color:#18212f}.card{width:min(100%,390px);padding:30px;border:1px solid rgba(255,255,255,.88);border-radius:24px;background:rgba(255,255,255,.86);box-shadow:0 24px 70px rgba(43,55,74,.14);backdrop-filter:blur(18px)}.eyebrow{margin:0 0 8px;font-size:12px;font-weight:800;letter-spacing:.11em;color:#64748b}.title{margin:0;font-size:25px;line-height:1.25;letter-spacing:-.03em}.desc{margin:10px 0 24px;color:#64748b;font-size:14px;line-height:1.55}.field{display:block;margin-bottom:12px}.field span{display:block;margin:0 0 7px;font-size:13px;font-weight:700}.input{width:100%;height:48px;padding:0 14px;border:1px solid #d7dee8;border-radius:13px;background:#fff;color:#111827;font:inherit;outline:none;transition:.16s}.input:focus{border-color:#64748b;box-shadow:0 0 0 3px rgba(100,116,139,.12)}.button{width:100%;height:48px;border:0;border-radius:13px;background:#172033;color:#fff;font:inherit;font-weight:800;cursor:pointer}.button:hover{background:#232e43}.error{margin:0 0 12px;padding:10px 12px;border-radius:11px;background:#fff1f2;color:#be123c;font-size:13px;line-height:1.45}.foot{margin:16px 0 0;text-align:center;color:#94a3b8;font-size:12px}
</style>
</head>
<body>
<main class="card">
<p class="eyebrow">PRIVATE ACCESS</p>
<h1 class="title">금리 모니터</h1>
<p class="desc">등록된 비밀번호를 입력하면 현재 브라우저에서 6시간 동안 접근할 수 있습니다.</p>
${error ? `<p class="error" role="alert">${escapeHtml(error)}</p>` : ""}
<form method="post" action="${LOGIN_PATH}">
<input type="hidden" name="returnTo" value="${escapeHtml(returnTo)}">
<label class="field"><span>비밀번호</span><input class="input" type="password" name="password" autocomplete="current-password" required autofocus></label>
<button class="button" type="submit">들어가기</button>
</form>
<p class="foot">인증 정보는 브라우저 화면에 저장하지 않습니다.</p>
</main>
</body>
</html>`;

const htmlResponse = (body, status = 200, extraHeaders = {}) => new Response(body, {
  status,
  headers: {
    ...securityHeaders,
    "content-type": "text/html; charset=utf-8",
    ...extraHeaders,
  },
});

const jsonResponse = (status, body) => new Response(JSON.stringify(body), {
  status,
  headers: {
    ...securityHeaders,
    "content-type": "application/json; charset=utf-8",
  },
});

const configurationError = () => htmlResponse(
  "<!doctype html><html lang=\"ko\"><meta charset=\"utf-8\"><title>접근 설정 필요</title><body><h1>접근 설정이 완료되지 않았습니다.</h1><p>관리자가 Vercel 환경변수 DASHBOARD_PASSWORD를 설정해야 합니다.</p></body></html>",
  503,
);

const unauthorizedResponse = (request, url) => {
  const accept = request.headers.get("accept") || "";
  const navigation = request.method === "GET" && (
    request.headers.get("sec-fetch-mode") === "navigate" || accept.includes("text/html")
  );
  if (navigation) {
    const login = new URL(LOGIN_PATH, request.url);
    login.searchParams.set("returnTo", `${url.pathname}${url.search}`);
    return new Response(null, {
      status: 302,
      headers: { ...securityHeaders, location: login.toString() },
    });
  }
  return jsonResponse(401, { ok: false, error: "인증이 필요합니다." });
};

export async function handleAuth(request, { password, next }) {
  const expected = String(password || "");
  if (!expected) return configurationError();

  const url = new URL(request.url);

  if (url.pathname === LOGIN_PATH) {
    const returnToFromQuery = safeReturnTo(url.searchParams.get("returnTo"));
    if (request.method === "GET") return htmlResponse(loginPage(returnToFromQuery));
    if (request.method !== "POST") {
      return jsonResponse(405, { ok: false, error: "허용되지 않은 요청입니다." });
    }

    let form;
    try {
      form = await request.formData();
    } catch {
      return htmlResponse(loginPage(returnToFromQuery, "요청을 읽지 못했습니다."), 400);
    }
    const returnTo = safeReturnTo(form.get("returnTo"));
    const given = String(form.get("password") || "");
    if (!given || !(await constantTimeEqual(given, expected))) {
      return htmlResponse(loginPage(returnTo, "비밀번호가 맞지 않습니다."), 401);
    }

    const token = await sessionToken(expected);
    return new Response(null, {
      status: 303,
      headers: {
        ...securityHeaders,
        location: returnTo,
        "set-cookie": `${SESSION_COOKIE}=${token}; Path=/; Max-Age=${SESSION_MAX_AGE_SECONDS}; HttpOnly; Secure; SameSite=Strict`,
      },
    });
  }

  if (url.pathname === LOGOUT_PATH) {
    return new Response(null, {
      status: 303,
      headers: {
        ...securityHeaders,
        location: LOGIN_PATH,
        "set-cookie": `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict`,
      },
    });
  }

  const suppliedToken = parseCookie(request.headers.get("cookie"), SESSION_COOKIE);
  const expectedToken = await sessionToken(expected);
  if (suppliedToken && await constantTimeEqual(suppliedToken, expectedToken)) {
    return next();
  }

  return unauthorizedResponse(request, url);
}
