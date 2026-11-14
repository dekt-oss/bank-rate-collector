import { next } from "@vercel/functions";

import { handleAuth } from "./auth-core.mjs";

export const config = {
  matcher: ["/((?!_vercel/).*)"],
};

export default function middleware(request) {
  return handleAuth(request, {
    password: process.env.DASHBOARD_PASSWORD,
    next,
  });
}
