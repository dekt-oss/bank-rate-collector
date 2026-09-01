"""Validate savings-bank identity remediation against a runner-local DB copy.

The script snapshots the latest active Data.go savings-bank population, applies
the production reconciler to that local copy, and proves that only identity
fields changed.  It never uploads or writes the database back to production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.collectors.data_go_funding.savings_bank_identity_reconciliation import (
    reconcile_latest_savings_bank_funding_identity,
)

SOURCE_ID = "data_go_savings_bank_funding"
SECTOR = "savings_bank"
AGGREGATE_KEY = "030350S"
IDENTITY_FIELDS = {"institution_id", "identity_status"}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _latest_month(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT MAX(source_effective_month)
        FROM institution_funding_observations
        WHERE source_id = ?
          AND sector = ?
          AND valid_to IS NULL
        """,
        (SOURCE_ID, SECTOR),
    ).fetchone()
    month = str(row[0] or "")
    if not month:
        raise RuntimeError("no active savings-bank funding observations")
    return month


def _rows(conn: sqlite3.Connection, month: str) -> list[dict[str, Any]]:
    result = conn.execute(
        """
        SELECT *
        FROM institution_funding_observations
        WHERE source_id = ?
          AND sector = ?
          AND source_effective_month = ?
          AND valid_to IS NULL
          AND source_institution_key <> ?
        ORDER BY source_institution_key, id
        """,
        (SOURCE_ID, SECTOR, month, AGGREGATE_KEY),
    ).fetchall()
    return [dict(row) for row in result]


def _aggregate_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM institution_funding_observations
            WHERE source_id = ?
              AND sector = ?
              AND source_institution_key = ?
              AND valid_to IS NULL
            """,
            (SOURCE_ID, SECTOR, AGGREGATE_KEY),
        ).fetchone()[0]
    )


def _funding_links(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, source_id, entity_type, source_entity_key, entity_id,
               source_name, source_payload_json, confidence, match_method,
               valid_from, valid_to, created_at, updated_at
        FROM source_entity_links
        WHERE source_id = ?
        ORDER BY id
        """,
        (SOURCE_ID,),
    ).fetchall()
    return [dict(row) for row in rows]


def _stable_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_stable_value,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _non_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in IDENTITY_FIELDS}


def _by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in rows}


def validate(
    db_path: Path,
    *,
    expected_population: int,
    expected_before_mapped: int,
    expected_new_mapped: int,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        latest_month = _latest_month(conn)
        before_rows = _rows(conn, latest_month)
        before_links = _funding_links(conn)
        before_aggregate = _aggregate_count(conn)

    before_mapped = sum(row["institution_id"] is not None for row in before_rows)
    before_unmapped = len(before_rows) - before_mapped
    assert len(before_rows) == expected_population, (
        len(before_rows),
        expected_population,
    )
    assert before_mapped == expected_before_mapped, (
        before_mapped,
        expected_before_mapped,
    )
    assert before_unmapped == expected_new_mapped, (
        before_unmapped,
        expected_new_mapped,
    )
    assert before_aggregate == 0, before_aggregate

    first = reconcile_latest_savings_bank_funding_identity(db_path)

    with _connect(db_path) as conn:
        after_rows = _rows(conn, latest_month)
        after_links = _funding_links(conn)
        after_aggregate = _aggregate_count(conn)

    assert first.latest_month == latest_month, first
    assert first.mapped == expected_new_mapped, first
    assert first.no_consensus == 0, first
    assert len(after_rows) == expected_population, len(after_rows)
    assert after_aggregate == 0, after_aggregate
    assert before_links == after_links, "reconciliation changed persistent funding links"

    before_by_id = _by_id(before_rows)
    after_by_id = _by_id(after_rows)
    assert before_by_id.keys() == after_by_id.keys(), "observation population changed"

    newly_mapped: list[dict[str, Any]] = []
    existing_mapped_changed: list[str] = []
    non_identity_changed: list[str] = []
    for observation_id, before in before_by_id.items():
        after = after_by_id[observation_id]
        if _non_identity(before) != _non_identity(after):
            non_identity_changed.append(observation_id)
        if before["institution_id"] is not None:
            if before["institution_id"] != after["institution_id"]:
                existing_mapped_changed.append(observation_id)
            continue
        if after["institution_id"] is not None:
            newly_mapped.append(
                {
                    "id": observation_id,
                    "source_institution_key": before["source_institution_key"],
                    "source_institution_name": before["source_institution_name"],
                    "source_crno": before["source_crno"],
                    "institution_id": after["institution_id"],
                    "identity_status": after["identity_status"],
                }
            )

    assert non_identity_changed == [], non_identity_changed
    assert existing_mapped_changed == [], existing_mapped_changed
    assert len(newly_mapped) == expected_new_mapped, len(newly_mapped)
    after_mapped = sum(row["institution_id"] is not None for row in after_rows)
    assert after_mapped == expected_population, (after_mapped, expected_population)

    second = reconcile_latest_savings_bank_funding_identity(db_path)
    assert second.mapped == 0, second
    assert second.eligible_unmapped == 0, second

    return {
        "latest_source_effective_month": latest_month,
        "source_population": len(before_rows),
        "before_mapped": before_mapped,
        "before_unmapped": before_unmapped,
        "first_reconciliation": {
            "scanned": first.scanned,
            "eligible_unmapped": first.eligible_unmapped,
            "mapped": first.mapped,
            "unchanged_mapped": first.unchanged_mapped,
            "no_consensus": first.no_consensus,
            "excluded_aggregate": first.excluded_aggregate,
        },
        "after_mapped": after_mapped,
        "after_unmapped": len(after_rows) - after_mapped,
        "second_reconciliation": {
            "scanned": second.scanned,
            "eligible_unmapped": second.eligible_unmapped,
            "mapped": second.mapped,
            "unchanged_mapped": second.unchanged_mapped,
            "no_consensus": second.no_consensus,
            "excluded_aggregate": second.excluded_aggregate,
        },
        "existing_mapped_identity_changes": len(existing_mapped_changed),
        "non_identity_changes": len(non_identity_changed),
        "aggregate_active_before": before_aggregate,
        "aggregate_active_after": after_aggregate,
        "persistent_funding_links_unchanged": before_links == after_links,
        "funding_links_fingerprint_before": _fingerprint(before_links),
        "funding_links_fingerprint_after": _fingerprint(after_links),
        "non_identity_fingerprint_before": _fingerprint(
            [_non_identity(row) for row in before_rows]
        ),
        "non_identity_fingerprint_after": _fingerprint(
            [_non_identity(row) for row in after_rows]
        ),
        "newly_mapped": newly_mapped,
        "production_write_back_performed": False,
    }


def render_markdown(result: dict[str, Any]) -> str:
    links_unchanged = str(result["persistent_funding_links_unchanged"]).lower()
    write_back = str(result["production_write_back_performed"]).lower()
    aggregate_before = result["aggregate_active_before"]
    aggregate_after = result["aggregate_active_after"]
    lines = [
        "# Savings-bank funding identity remediation — production-copy validation",
        "",
        "```yaml",
        f"latest_source_effective_month: {result['latest_source_effective_month']}",
        f"source_population: {result['source_population']}",
        f"before_mapped: {result['before_mapped']}",
        f"before_unmapped: {result['before_unmapped']}",
        f"after_mapped: {result['after_mapped']}",
        f"after_unmapped: {result['after_unmapped']}",
        f"non_identity_changes: {result['non_identity_changes']}",
        f"existing_mapped_identity_changes: {result['existing_mapped_identity_changes']}",
        f"persistent_funding_links_unchanged: {links_unchanged}",
        f"production_write_back_performed: {write_back}",
        "```",
        "",
        "## Newly mapped observations",
        "",
        "| fncoCd | Data.go name | CRNO | canonical institution id | status |",
        "|---|---|---|---|---|",
    ]
    for row in result["newly_mapped"]:
        lines.append(
            "| {source_institution_key} | {source_institution_name} | {source_crno} | "
            "{institution_id} | `{identity_status}` |".format(**row)
        )
    lines.extend(
        [
            "",
            "## Invariants",
            "",
            f"- non-identity fingerprint before: `{result['non_identity_fingerprint_before']}`",
            f"- non-identity fingerprint after: `{result['non_identity_fingerprint_after']}`",
            f"- funding-link fingerprint before: `{result['funding_links_fingerprint_before']}`",
            f"- funding-link fingerprint after: `{result['funding_links_fingerprint_after']}`",
            f"- aggregate active before/after: {aggregate_before} / {aggregate_after}",
            f"- second reconciliation mapped: {result['second_reconciliation']['mapped']}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--expected-population", type=int, required=True)
    parser.add_argument("--expected-before-mapped", type=int, required=True)
    parser.add_argument("--expected-new-mapped", type=int, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    result = validate(
        args.db,
        expected_population=args.expected_population,
        expected_before_mapped=args.expected_before_mapped,
        expected_new_mapped=args.expected_new_mapped,
    )
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_stable_value) + "\n",
        encoding="utf-8",
    )
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    print(
        "savings-bank identity copy validation",
        f"month={result['latest_source_effective_month']}",
        f"population={result['source_population']}",
        f"before={result['before_mapped']}/{result['source_population']}",
        f"after={result['after_mapped']}/{result['source_population']}",
        f"new={len(result['newly_mapped'])}",
        f"second_mapped={result['second_reconciliation']['mapped']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
