# 2026-08-18 NH writer queue incident

## Incident

- Scheduled workflow: `Collect NH rates` run `32043728406`
- Created: 2026-08-18 00:54:11 KST
- Terminal state: `cancelled`
- Jobs: 0
- Production dashboard therefore continued to show the previous successful NH run:
  `2026-08-17T04:48:41.862472+09:00` and freshness `예정 수집 1회 지연`.

## Root cause

All production state writers share `concurrency.group: rate-data-writer` with
`cancel-in-progress: false`, but the group used the default single-pending queue.
GitHub Actions cancels the existing pending run when a newer run enters the same
concurrency group. A main push/publish run can therefore replace a queued long NH run
before NH starts any job.

## Fix

Keep the single shared writer group and add `queue: max` to every workflow that can
write or migrate the canonical R2/rate-data state:

- `.github/workflows/collect.yml`
- `.github/workflows/collect-nh.yml`
- `.github/workflows/collect-savings-fast.yml`
- `.github/workflows/storage-check.yml`

This preserves serialization while allowing multiple pending writer runs to wait
instead of replacing one another.

## Non-goals

- No collector changes
- No DB/schema/migration changes
- No scheduling time changes
- No rate calculation changes
- No automatic rerun of the missed 2026-08-18 NH collection
