# 2026-08-30 site auth hotfix evidence

- Main auth implementation merged in PR #258.
- Existing long-running NH writer blocked the normal publish-only rate-data refresh.
- Auth runtime files were therefore copied directly to the rate-data branch as an emergency deployment-only hotfix; no DB/data payload files were modified.
- Final activation commit on rate-data: `694edbf335f0ac59f31cc08ca10211c7e65601c7`.
- GitHub/Vercel status for that commit reported `Deployment has completed` with state `success`.
- This branch adds an anonymous production boundary smoke so future checks assert `/` redirects to `/__login` and `/api/health` returns 401 without credentials.

The normal writers in main already publish the same auth runtime, so subsequent latest-main publishes retain the gate.
