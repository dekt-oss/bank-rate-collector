#!/usr/bin/env python3
"""DH저축은행 12개월 예금 source discrepancy를 runner-local에서 재현한다.

Production DB는 workflow에서 복사본으로만 복원한다. 이 스크립트는 그 SQLite와
이번 실행이 새로 받은 raw artifact, 은행 직접 공시 HTML을 읽어서 provenance를
한 JSON으로 묶을 뿐 canonical/source authority를 변경하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONFIRMED_RUN_STATUSES = ("success", "partial", "no_change")
TARGET_SOURCES = ("fsb", "finlife_savings_bank")
TARGET_INSTITUTION = "DH저축은행"
TARGET_PRODUCTS = {"정기예금", "정기예금(비대면)"}
TARGET_TERM = 12


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_raw_path(relative_path: str, raw_root: Path) -> Path | None:
    candidates = [Path(relative_path), raw_root / relative_path]
    if relative_path.startswith("data/raw/"):
        candidates.append(raw_root / relative_path.removeprefix("data/raw/"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _latest_runs(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    placeholders = ",".join("?" for _ in CONFIRMED_RUN_STATUSES)
    runs: dict[str, dict[str, Any]] = {}
    for source_id in TARGET_SOURCES:
        row = conn.execute(
            "SELECT id, source_id, started_at, finished_at, status, raw_count, parsed_count, "
            "       valid_count, warning_count, error_count "
            "FROM collection_runs "
            "WHERE source_id = ? "
            f"AND status IN ({placeholders}) "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            (source_id, *CONFIRMED_RUN_STATUSES),
        ).fetchone()
        if row is not None:
            runs[source_id] = dict(row)
    return runs


def _current_rows(conn: sqlite3.Connection, run_ids: list[str]) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    cursor = conn.execute(
        "SELECT lr.source_id, o.id AS observation_id, o.run_id, o.last_run_id, "
        "       i.canonical_name AS institution, p.name AS product, p.product_type, "
        "       pv.term_months, pv.join_channel, pv.interest_method, pv.payment_method, "
        "       o.base_rate, o.max_rate, o.source_effective_at, o.last_seen_at, "
        "       o.base_source_locator, o.option_source_locator, o.source_record_hash, "
        "       ra.relative_path AS first_seen_raw_artifact_path, "
        "       ra.sha256 AS first_seen_raw_artifact_sha256 "
        "FROM rate_observations o "
        "JOIN collection_runs lr ON lr.id = o.last_run_id "
        "JOIN product_variants pv ON pv.id = o.variant_id "
        "JOIN products p ON p.id = pv.product_id "
        "JOIN institutions i ON i.id = p.institution_id "
        "JOIN raw_artifacts ra ON ra.id = o.raw_artifact_id "
        f"WHERE o.last_run_id IN ({placeholders}) "
        "  AND o.validation_status = 'valid' "
        "  AND o.valid_to IS NULL "
        "  AND i.sector = 'savings_bank'",
        run_ids,
    )
    columns = [item[0] for item in cursor.description]
    rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    return [
        row
        for row in rows
        if row.get("institution") == TARGET_INSTITUTION
        and row.get("product") in TARGET_PRODUCTS
        and row.get("term_months") == TARGET_TERM
    ]


def _fresh_run_artifacts(
    conn: sqlite3.Connection, runs: dict[str, dict[str, Any]], raw_root: Path
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for source_id, run in runs.items():
        cursor = conn.execute(
            "SELECT relative_path, sha256, content_length, captured_at "
            "FROM raw_artifacts WHERE run_id = ? ORDER BY relative_path",
            (run["id"],),
        )
        artifacts: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            relative_path = str(row[0])
            path = _resolve_raw_path(relative_path, raw_root)
            actual_sha = _sha256(path) if path else None
            artifacts.append(
                {
                    "relative_path": relative_path,
                    "expected_sha256": row[1],
                    "content_length": row[2],
                    "captured_at": row[3],
                    "resolved": path is not None,
                    "actual_sha256": actual_sha,
                    "sha256_matches_db": actual_sha == row[1] if actual_sha else False,
                }
            )
        output[source_id] = artifacts
    return output


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _scan_finlife(payload: dict[str, Any], relative_path: str) -> list[dict[str, Any]]:
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    bases = result.get("baseList") or []
    options = result.get("optionList") or []
    target_bases: dict[tuple[str, str], dict[str, Any]] = {}
    for base in bases:
        if not isinstance(base, dict):
            continue
        if base.get("kor_co_nm") != TARGET_INSTITUTION:
            continue
        if base.get("fin_prdt_nm") not in TARGET_PRODUCTS:
            continue
        key = (str(base.get("fin_co_no")), str(base.get("fin_prdt_cd")))
        target_bases[key] = base

    rows: list[dict[str, Any]] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        key = (str(option.get("fin_co_no")), str(option.get("fin_prdt_cd")))
        base = target_bases.get(key)
        if base is None or str(option.get("save_trm")) != str(TARGET_TERM):
            continue
        rows.append(
            {
                "source_id": "finlife_savings_bank",
                "raw_path": relative_path,
                "fin_co_no": base.get("fin_co_no"),
                "fin_prdt_cd": base.get("fin_prdt_cd"),
                "product": base.get("fin_prdt_nm"),
                "join_way": base.get("join_way"),
                "source_effective_at": base.get("dcls_strt_day"),
                "interest_method": option.get("intr_rate_type_nm"),
                "term_months": option.get("save_trm"),
                "base_rate": option.get("intr_rate"),
                "max_rate": option.get("intr_rate2"),
            }
        )
    return rows


def _is_dh_fsb_record(record: dict[str, Any]) -> bool:
    bank_name = str(record.get("BANK_NAME") or "").strip().upper()
    url = str(record.get("URL") or "").lower()
    product = str(record.get("PRODUCT_NAME") or "").strip()
    return (
        (bank_name in {"DH", "디에이치"} or "dhsavingsbank" in url)
        and product in TARGET_PRODUCTS
    )


def _scan_fsb(payload: Any, relative_path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        rec = payload.get("REC")
        if isinstance(rec, list):
            records = [item for item in rec if isinstance(item, dict)]
    output: list[dict[str, Any]] = []
    for record in records:
        if not _is_dh_fsb_record(record):
            continue
        output.append(
            {
                "source_id": "fsb",
                "raw_path": relative_path,
                "finan_comp_code": record.get("FINAN_COMP_CODE"),
                "finan_prod_code": record.get("FINAN_PROD_CODE"),
                "product": str(record.get("PRODUCT_NAME") or "").strip(),
                "product_url": record.get("PRODUCT_URL"),
                "source_effective_at": record.get("START_DATE"),
                "term_months": TARGET_TERM,
                "simple_rate": record.get("JUNG_12M_DAN"),
                "simple_max_rate": record.get("TOP_12M_DAN"),
                "compound_rate": record.get("JUNG_12M_BOK"),
                "compound_max_rate": record.get("TOP_12M_BOK"),
            }
        )
    return output


def _scan_fresh_raw(
    artifacts: dict[str, list[dict[str, Any]]], raw_root: Path
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {source_id: [] for source_id in TARGET_SOURCES}
    for source_id, source_artifacts in artifacts.items():
        for artifact in source_artifacts:
            relative_path = str(artifact["relative_path"])
            path = _resolve_raw_path(relative_path, raw_root)
            if path is None or path.suffix.lower() != ".json":
                continue
            try:
                payload = _load_json(path)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if source_id == "finlife_savings_bank" and isinstance(payload, dict):
                output[source_id].extend(_scan_finlife(payload, relative_path))
            elif source_id == "fsb":
                output[source_id].extend(_scan_fsb(payload, relative_path))
    return output


def _official_evidence(path: Path, url: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "url": url,
        "path": str(path),
        "resolved": path.is_file(),
    }
    if not path.is_file():
        return result
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    contexts: list[str] = []
    start = 0
    while len(contexts) < 5:
        index = text.find("12개월", start)
        if index < 0:
            break
        contexts.append(text[max(0, index - 120) : index + 220])
        start = index + len("12개월")
    result.update(
        {
            "sha256": _sha256(path),
            "content_length": path.stat().st_size,
            "twelve_month_contexts": contexts,
        }
    )
    return result


def build_report(
    db_path: Path,
    raw_root: Path,
    *,
    official_branch_html: Path,
    official_branch_url: str,
    official_mobile_html: Path,
    official_mobile_url: str,
) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        runs = _latest_runs(conn)
        rows = _current_rows(conn, [item["id"] for item in runs.values()])
        artifacts = _fresh_run_artifacts(conn, runs, raw_root)
    finally:
        conn.close()

    rows.sort(
        key=lambda row: (
            str(row.get("source_id") or ""),
            str(row.get("product") or ""),
            str(row.get("join_channel") or ""),
            str(row.get("interest_method") or ""),
        )
    )
    fresh_raw = _scan_fresh_raw(artifacts, raw_root)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "mode": "runner_local_read_only_forensic",
            "production_state_mutated": False,
            "canonical_mutated": False,
            "source_precedence_changed": False,
            "authority_selected": False,
            "target": "DH저축은행 정기예금/정기예금(비대면) 12개월",
        },
        "latest_runs": runs,
        "current_rows": rows,
        "fresh_run_artifacts": artifacts,
        "fresh_raw_target_records": fresh_raw,
        "official_bank_direct": {
            "branch": _official_evidence(official_branch_html, official_branch_url),
            "mobile": _official_evidence(official_mobile_html, official_mobile_url),
        },
        "summary": {
            "current_rows": len(rows),
            "fresh_finlife_records": len(fresh_raw.get("finlife_savings_bank", [])),
            "fresh_fsb_records": len(fresh_raw.get("fsb", [])),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--official-branch-html", type=Path, required=True)
    parser.add_argument("--official-branch-url", required=True)
    parser.add_argument("--official-mobile-html", type=Path, required=True)
    parser.add_argument("--official-mobile-url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = build_report(
        args.db,
        args.raw_root,
        official_branch_html=args.official_branch_html,
        official_branch_url=args.official_branch_url,
        official_mobile_html=args.official_mobile_html,
        official_mobile_url=args.official_mobile_url,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
