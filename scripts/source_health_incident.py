#!/usr/bin/env python3
"""Synchronize source collection failures with one GitHub issue per source.

This is intentionally independent from the parent Actions conclusion. Local-source
collect steps are soft-fail so that one upstream outage does not suppress the other
sources; the incident issue is the durable operator signal for a failed source.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HEALTHY_STATUSES = {"success", "no_change"}
FAIL_STATUSES = {"failed", "blocked", "schema_changed"}


@dataclass(frozen=True)
class IncidentState:
    incident: bool
    code: str
    summary: str


def classify_run(run: dict[str, Any] | None) -> IncidentState:
    if run is None:
        return IncidentState(True, "NO_COLLECTION_RUN", "수집 실행 이력이 없다")

    status = str(run.get("status") or "").lower()
    raw_count = int(run.get("raw_count") or 0)
    parsed_count = int(run.get("parsed_count") or 0)
    message = str(run.get("message") or "").strip()

    if status in FAIL_STATUSES:
        code = "RUN_" + status.upper()
        if "SOURCE_EMPTY_RESULT" in message:
            code = "SOURCE_EMPTY_RESULT"
        elif "SOURCE_VOLUME_BELOW_MINIMUM" in message:
            code = "SOURCE_VOLUME_BELOW_MINIMUM"
        return IncidentState(True, code, message or f"collection run status={status}")

    # Backward-compatible guard for historical runs created before the runtime gate.
    if status in HEALTHY_STATUSES | {"partial"} and raw_count > 0 and parsed_count == 0:
        return IncidentState(
            True,
            "ZERO_PARSE_WHEN_RAW_EXISTS",
            f"raw={raw_count}인데 parsed=0이다",
        )

    return IncidentState(False, "HEALTHY", message or f"collection run status={status}")


def latest_run(db_path: Path, source_id: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, source_id, status, started_at, finished_at, raw_count, "
            "parsed_count, valid_count, warning_count, error_count, message "
            "FROM collection_runs WHERE source_id = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _request(method: str, url: str, token: str, payload: dict[str, Any] | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "bank-rate-collector-source-health",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} -> {exc.code}: {detail}") from exc


def _open_issue(repo: str, source_id: str, token: str) -> dict[str, Any] | None:
    title = f"[source-health] {source_id} collection incident"
    query = urllib.parse.urlencode({"state": "open", "per_page": 100})
    issues = _request("GET", f"https://api.github.com/repos/{repo}/issues?{query}", token)
    for issue in issues or []:
        if "pull_request" not in issue and issue.get("title") == title:
            return issue
    return None


def _workflow_url() -> str:
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


def _body(source_id: str, run: dict[str, Any] | None, state: IncidentState) -> str:
    run = run or {}
    workflow = _workflow_url()
    counts = (
        f"{run.get('raw_count', 0)} / {run.get('parsed_count', 0)} / "
        f"{run.get('valid_count', 0)}"
    )
    lines = [
        f"<!-- source-health:{source_id} -->",
        f"## {source_id} 수집 장애",
        "",
        f"- code: `{state.code}`",
        f"- status: `{run.get('status', 'missing')}`",
        f"- run_id: `{run.get('id', '-')}`",
        f"- raw / parsed / valid: `{counts}`",
        f"- warning / error: `{run.get('warning_count', 0)} / {run.get('error_count', 0)}`",
        f"- started_at: `{run.get('started_at', '-')}`",
        f"- finished_at: `{run.get('finished_at', '-')}`",
        "",
        state.summary or "상세 메시지 없음",
    ]
    if workflow:
        lines.extend(["", f"Actions evidence: {workflow}"])
    lines.extend([
        "",
        "이 이슈는 전체 workflow 성공/실패와 독립된 source-level 운영 신호다.",
        "최신 source run이 정상으로 확인되면 자동으로 닫힌다.",
    ])
    return "\n".join(lines)


def sync_issue(db_path: Path, source_id: str, repo: str, token: str) -> str:
    run = latest_run(db_path, source_id)
    state = classify_run(run)
    existing = _open_issue(repo, source_id, token)
    title = f"[source-health] {source_id} collection incident"

    if state.incident:
        body = _body(source_id, run, state)
        if existing is None:
            created = _request(
                "POST",
                f"https://api.github.com/repos/{repo}/issues",
                token,
                {"title": title, "body": body},
            )
            return f"opened #{created['number']} ({state.code})"
        _request(
            "PATCH",
            f"https://api.github.com/repos/{repo}/issues/{existing['number']}",
            token,
            {"body": body},
        )
        return f"updated #{existing['number']} ({state.code})"

    if existing is not None:
        number = existing["number"]
        recovery = (
            f"자동 복구 확인: latest run `{(run or {}).get('id', '-')}` "
            f"status=`{(run or {}).get('status', '-')}`."
        )
        _request(
            "POST",
            f"https://api.github.com/repos/{repo}/issues/{number}/comments",
            token,
            {"body": recovery},
        )
        _request(
            "PATCH",
            f"https://api.github.com/repos/{repo}/issues/{number}",
            token,
            {"state": "closed", "state_reason": "completed"},
        )
        return f"closed #{number} (recovered)"

    return "healthy; no open incident"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--source", action="append", dest="sources", required=True)
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.getenv("GITHUB_TOKEN", "")
    if not args.repo:
        print("GITHUB_REPOSITORY/--repo is required", file=sys.stderr)
        return 2
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    if not args.db.exists():
        print(f"database not found: {args.db}", file=sys.stderr)
        return 2

    for source_id in args.sources:
        result = sync_issue(args.db, source_id, args.repo, token)
        print(f"{source_id}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
