#!/usr/bin/env python3
"""대신저축은행 P1 24/36개월 원천 차이를 runner-local에서 재현한다.

이 스크립트는 DB나 외부 시스템을 수정하지 않는다. 이미 수집된 runner-local
SQLite와 raw artifact를 읽어, source product identity / variant / raw locator를
한 JSON에 묶는다. 네트워크 수집은 workflow에서 기존 collector가 담당한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rate_monitor.domain.normalization import normalize_product_name

CONFIRMED_RUN_STATUSES = ("success", "partial", "no_change")
TARGET_INSTITUTION = "대신저축은행"
TARGET_PRODUCT = normalize_product_name("정기적금")
TARGET_TERMS = {24, 36}
TARGET_SOURCES = ("fsb", "finlife_savings_bank")

_LOCATOR_TOKEN = re.compile(r"\.([A-Za-z0-9_]+)|\[([0-9]+)\]")


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


def _extract_locator(payload: Any, locator: str | None) -> Any:
    if not locator or not locator.startswith("$"):
        return None
    current = payload
    for key, index in _LOCATOR_TOKEN.findall(locator[1:]):
        if key:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        else:
            if not isinstance(current, list):
                return None
            idx = int(index)
            if idx < 0 or idx >= len(current):
                return None
            current = current[idx]
    return current


def _latest_runs(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    statuses = ",".join("?" for _ in CONFIRMED_RUN_STATUSES)
    runs: dict[str, dict[str, Any]] = {}
    for source_id in TARGET_SOURCES:
        row = conn.execute(
            "SELECT id, source_id, started_at, finished_at, status, raw_count, parsed_count, "
            "       valid_count, warning_count, error_count "
            "FROM collection_runs "
            "WHERE source_id = ? "
            f"AND status IN ({statuses}) "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            (source_id, *CONFIRMED_RUN_STATUSES),
        ).fetchone()
        if row is not None:
            runs[source_id] = dict(row)
    return runs


def _rows(conn: sqlite3.Connection, run_ids: list[str]) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    placeholders = ",".join("?" for _ in run_ids)
    cursor = conn.execute(
        "SELECT lr.source_id, o.id AS observation_id, o.run_id, o.last_run_id, "
        "       i.id AS institution_id, i.canonical_name AS institution, "
        "       p.id AS product_id, p.name AS product, p.product_type, "
        "       pv.term_months, pv.join_channel, pv.interest_method, pv.payment_method, "
        "       o.base_rate, o.max_rate, o.source_effective_at, o.last_seen_at, "
        "       o.base_source_locator, o.option_source_locator, o.source_record_hash, "
        "       ra.relative_path AS raw_artifact_path, ra.sha256 AS raw_artifact_sha256, "
        "       (SELECT group_concat(sel.source_entity_key, '|') "
        "          FROM source_entity_links sel "
        "         WHERE sel.source_id = lr.source_id "
        "           AND sel.entity_type = 'product' "
        "           AND sel.entity_id = p.id "
        "           AND sel.valid_to IS NULL) AS source_product_keys, "
        "       (SELECT group_concat(COALESCE(sel.source_name, ''), '|') "
        "          FROM source_entity_links sel "
        "         WHERE sel.source_id = lr.source_id "
        "           AND sel.entity_type = 'product' "
        "           AND sel.entity_id = p.id "
        "           AND sel.valid_to IS NULL) AS source_product_names "
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
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _target_row(row: dict[str, Any]) -> bool:
    return (
        str(row.get("institution") or "") == TARGET_INSTITUTION
        and normalize_product_name(str(row.get("product") or "")) == TARGET_PRODUCT
        and row.get("term_months") in TARGET_TERMS
    )


def _raw_evidence(row: dict[str, Any], raw_root: Path) -> dict[str, Any]:
    relative = str(row.get("raw_artifact_path") or "")
    raw_path = _resolve_raw_path(relative, raw_root)
    evidence: dict[str, Any] = {
        "path": relative or None,
        "expected_sha256": row.get("raw_artifact_sha256"),
        "resolved": raw_path is not None,
    }
    if raw_path is None:
        return evidence

    actual_sha = _sha256(raw_path)
    evidence["actual_sha256"] = actual_sha
    evidence["sha256_matches_db"] = actual_sha == row.get("raw_artifact_sha256")
    try:
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        evidence["parse_error"] = f"{type(exc).__name__}: {exc}"
        return evidence

    evidence["base_locator_value"] = _extract_locator(
        payload, row.get("base_source_locator")
    )
    evidence["option_locator_value"] = _extract_locator(
        payload, row.get("option_source_locator")
    )
    return evidence


def _official_evidence(path: Path | None, url: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    result: dict[str, Any] = {
        "url": url,
        "path": str(path),
        "resolved": path.is_file(),
    }
    if path.is_file():
        result["sha256"] = _sha256(path)
        result["content_length"] = path.stat().st_size
    return result


def build_report(
    db_path: Path,
    raw_root: Path,
    *,
    official_path: Path | None = None,
    official_url: str | None = None,
) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        runs = _latest_runs(conn)
        run_ids = [item["id"] for item in runs.values()]
        selected = [row for row in _rows(conn, run_ids) if _target_row(row)]
    finally:
        conn.close()

    selected.sort(
        key=lambda row: (
            str(row.get("source_id") or ""),
            int(row.get("term_months") or 0),
            str(row.get("join_channel") or ""),
            str(row.get("interest_method") or ""),
            str(row.get("payment_method") or ""),
        )
    )

    output_rows: list[dict[str, Any]] = []
    for row in selected:
        output_rows.append(
            {
                "source_id": row.get("source_id"),
                "observation_id": row.get("observation_id"),
                "run_id_first_seen_value": row.get("run_id"),
                "last_run_id": row.get("last_run_id"),
                "institution": row.get("institution"),
                "product_id": row.get("product_id"),
                "product": row.get("product"),
                "product_type": row.get("product_type"),
                "source_product_keys": (
                    str(row.get("source_product_keys")).split("|")
                    if row.get("source_product_keys")
                    else []
                ),
                "source_product_names": (
                    str(row.get("source_product_names")).split("|")
                    if row.get("source_product_names")
                    else []
                ),
                "term_months": row.get("term_months"),
                "join_channel": row.get("join_channel"),
                "interest_method": row.get("interest_method"),
                "payment_method": row.get("payment_method"),
                "base_rate": row.get("base_rate"),
                "max_rate": row.get("max_rate"),
                "source_effective_at": row.get("source_effective_at"),
                "last_seen_at": row.get("last_seen_at"),
                "base_source_locator": row.get("base_source_locator"),
                "option_source_locator": row.get("option_source_locator"),
                "source_record_hash": row.get("source_record_hash"),
                "raw": _raw_evidence(row, raw_root),
            }
        )

    finlife_rows = [row for row in output_rows if row["source_id"] == "finlife_savings_bank"]
    finlife_keys = sorted(
        {
            key
            for row in finlife_rows
            for key in row.get("source_product_keys", [])
            if key
        }
    )
    simple_keys = sorted(
        {
            key
            for row in finlife_rows
            if row.get("interest_method") == "simple"
            for key in row.get("source_product_keys", [])
            if key
        }
    )
    compound_keys = sorted(
        {
            key
            for row in finlife_rows
            if row.get("interest_method") == "compound"
            for key in row.get("source_product_keys", [])
            if key
        }
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "mode": "runner_local_read_only_forensic",
            "production_state_mutated": False,
            "canonical_mutated": False,
            "source_precedence_changed": False,
            "authority_selected": False,
            "target": "대신저축은행 정기적금 24/36개월",
        },
        "latest_runs": runs,
        "rows": output_rows,
        "summary": {
            "rows": len(output_rows),
            "finlife_rows": len(finlife_rows),
            "finlife_source_product_keys": finlife_keys,
            "finlife_simple_source_product_keys": simple_keys,
            "finlife_compound_source_product_keys": compound_keys,
            "simple_and_compound_use_same_source_product_key": simple_keys == compound_keys,
        },
        "official_bank_direct": _official_evidence(official_path, official_url),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--official-html", type=Path)
    parser.add_argument("--official-url")
    args = parser.parse_args()

    report = build_report(
        args.db,
        args.raw_root,
        official_path=args.official_html,
        official_url=args.official_url,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("summary:", json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    for row in report["rows"]:
        print(
            row["source_id"],
            row["term_months"],
            row["join_channel"],
            row["interest_method"],
            row["payment_method"],
            row["base_rate"],
            row["max_rate"],
            row["source_product_keys"],
            row["base_source_locator"],
            row["option_source_locator"],
            f"raw_sha_ok={row['raw'].get('sha256_matches_db')}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
