import assert from "node:assert/strict";
import test from "node:test";

import { handleAuth, LOGIN_PATH, SESSION_COOKIE } from "../web/runtime/auth-core.mjs";

const PASSWORD = "correct horse battery staple";
const EXPECTED_COOKIE = "__Host-rate_monitor_auth=pI4VHUrcSgsvEcb_iLq3FS33SEwUTdMILI_cAvtvH8w";
const next = () => new Response("NEXT", { status: 200 });
const htmlRequest = (path = "/", cookie = "") => new Request(`https://rates.example${path}`, {
  headers: {
    accept: "text/html",
    "sec-fetch-mode": "navigate",
    ...(cookie ? { cookie } : {}),
  },
});

const login = async (password = PASSWORD, returnTo = "/strategy.html") => handleAuth(
  new Request(`https://rates.example${LOGIN_PATH}`, {
    method: "POST",
    body: new URLSearchParams({ password, returnTo }),
  }),
  { password: PASSWORD, next },
);

test("fails closed when DASHBOARD_PASSWORD is absent", async () => {
  const response = await handleAuth(htmlRequest(), { password: "", next });
  assert.equal(response.status, 503);
});

test("redirects unauthenticated page navigation to login and preserves return path", async () => {
  const response = await handleAuth(htmlRequest("/strategy.html?scope=busan"), {
    password: PASSWORD,
    next,
  });
  assert.equal(response.status, 302);
  const location = new URL(response.headers.get("location"));
  assert.equal(location.pathname, LOGIN_PATH);
  assert.equal(location.searchParams.get("returnTo"), "/strategy.html?scope=busan");
});

test("blocks direct JSON/data access instead of leaking content", async () => {
  const response = await handleAuth(new Request("https://rates.example/data/rates.json"), {
    password: PASSWORD,
    next,
  });
  assert.equal(response.status, 401);
  assert.match(await response.text(), /인증이 필요합니다/u);
});

test("rejects wrong password without issuing a cookie", async () => {
  const response = await login("wrong password");
  assert.equal(response.status, 401);
  assert.equal(response.headers.get("set-cookie"), null);
});

test("issues a secure HttpOnly session cookie after correct password", async () => {
  const response = await login();
  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), "/strategy.html");
  const cookie = response.headers.get("set-cookie");
  assert.equal(cookie.split(";", 1)[0], EXPECTED_COOKIE);
  assert.match(cookie, new RegExp(`^${SESSION_COOKIE}=`));
  assert.match(cookie, /HttpOnly/u);
  assert.match(cookie, /Secure/u);
  assert.match(cookie, /SameSite=Strict/u);
});

test("valid session reaches the existing static/function handler", async () => {
  const loginResponse = await login();
  const cookie = loginResponse.headers.get("set-cookie").split(";", 1)[0];
  const response = await handleAuth(new Request("https://rates.example/data/rates.json", {
    headers: { cookie },
  }), { password: PASSWORD, next });
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "NEXT");
});

test("changing the password invalidates existing sessions", async () => {
  const loginResponse = await login();
  const cookie = loginResponse.headers.get("set-cookie").split(";", 1)[0];
  const response = await handleAuth(htmlRequest("/", cookie), {
    password: `${PASSWORD}-rotated`,
    next,
  });
  assert.equal(response.status, 302);
});

test("prevents open redirects supplied through returnTo", async () => {
  const response = await login(PASSWORD, "//evil.example/phish");
  assert.equal(response.status, 303);
  assert.equal(response.headers.get("location"), "/");
});

test("logout clears the authentication cookie", async () => {
  const response = await handleAuth(new Request("https://rates.example/__logout"), {
    password: PASSWORD,
    next,
  });
  assert.equal(response.status, 303);
  assert.match(response.headers.get("set-cookie"), /Max-Age=0/u);
});
