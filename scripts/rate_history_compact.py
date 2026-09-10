#!/usr/bin/env python3
"""Compact redundant rate history on a restored/local SQLite copy.

A new observation is supposed to represent a semantic change. Rows that are
consecutive for the same variant/source and carry the same base rate, max rate,
and raw preference text are redundant history. The source effective date is
provenance, not part of the semantic value.

Safety properties:
- dry-run is the default and never mutates main tables;
- ``--apply`` requires ``--vacuum-into`` and writes a separate compacted file;
- references to rows scheduled for deletion fail closed;
- current semantic values are fingerprinted before/after;
- integrity_check and foreign_key_check must pass before success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

OBSERVATION_TYPES = {
    "observation",
    "rate_observation",
    "rate_observations",
}


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _semantic_hash(base_rate: object, max_rate: object, preference: object) -> str:
    payload = "|".join(str(value) for value in (base_rate, max_rate, preference or ""))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_fingerprint(conn: sqlite3.Connection) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    rows = conn.execute(
        """
        SELECT variant_id, base_rate, max_rate, raw_preference_text,
               source_effective_at, COALESCE(last_run_id, run_id)
        FROM rate_observations
        WHERE valid_to IS NULL
        ORDER BY variant_id, id
        """
    )
    for row in rows:
        count += 1
        encoded = json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":"))
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return count, digest.hexdigest()


def _create_plan(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS temp._compact_groups;
        DROP TABLE IF EXISTS temp._compact_map;
        CREATE TEMP TABLE _compact_groups (
          variant_id TEXT NOT NULL,
          grp INTEGER NOT NULL,
          keep_id TEXT NOT NULL,
          last_id TEXT NOT NULL,
          rows_in_group INTEGER NOT NULL,
          total_seen_count INTEGER NOT NULL,
          PRIMARY KEY (variant_id, grp)
        );
        CREATE TEMP TABLE _compact_map (
          delete_id TEXT PRIMARY KEY,
          keep_id TEXT NOT NULL
        );

        INSERT INTO _compact_groups(
          variant_id, grp, keep_id, last_id, rows_in_group, total_seen_count
        )
        WITH ordered AS (
          SELECT
            ro.*,
            cr.source_id,
            LAG(ro.id) OVER w AS prev_id,
            LAG(ro.base_rate) OVER w AS prev_base_rate,
            LAG(ro.max_rate) OVER w AS prev_max_rate,
            LAG(ro.raw_preference_text) OVER w AS prev_preference,
            LAG(cr.source_id) OVER w AS prev_source_id
          FROM rate_observations ro
          JOIN collection_runs cr ON cr.id = ro.run_id
          WINDOW w AS (
            PARTITION BY ro.variant_id
            ORDER BY ro.valid_from, ro.observed_at, ro.id
          )
        ), marked AS (
          SELECT *,
            CASE
              WHEN prev_id IS NOT NULL
               AND base_rate IS prev_base_rate
               AND max_rate IS prev_max_rate
               AND raw_preference_text IS prev_preference
               AND source_id IS prev_source_id
              THEN 0 ELSE 1
            END AS group_start
          FROM ordered
        ), grouped AS (
          SELECT *,
            SUM(group_start) OVER (
              PARTITION BY variant_id
              ORDER BY valid_from, observed_at, id
              ROWS UNBOUNDED PRECEDING
            ) AS grp
          FROM marked
        ), ranked AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY variant_id, grp
              ORDER BY valid_from, observed_at, id
            ) AS rn_first,
            ROW_NUMBER() OVER (
              PARTITION BY variant_id, grp
              ORDER BY valid_from DESC, observed_at DESC, id DESC
            ) AS rn_last,
            COUNT(*) OVER (PARTITION BY variant_id, grp) AS rows_in_group,
            SUM(COALESCE(seen_count, 1)) OVER (
              PARTITION BY variant_id, grp
            ) AS total_seen_count
          FROM grouped
        )
        SELECT
          variant_id,
          grp,
          MAX(CASE WHEN rn_first = 1 THEN id END) AS keep_id,
          MAX(CASE WHEN rn_last = 1 THEN id END) AS last_id,
          MAX(rows_in_group),
          MAX(total_seen_count)
        FROM ranked
        WHERE rows_in_group > 1
        GROUP BY variant_id, grp;

        INSERT INTO _compact_map(delete_id, keep_id)
        WITH ordered AS (
          SELECT
            ro.id,
            ro.variant_id,
            ro.valid_from,
            ro.observed_at,
            cr.source_id,
            ro.base_rate,
            ro.max_rate,
            ro.raw_preference_text,
            LAG(ro.id) OVER w AS prev_id,
            LAG(ro.base_rate) OVER w AS prev_base_rate,
            LAG(ro.max_rate) OVER w AS prev_max_rate,
            LAG(ro.raw_preference_text) OVER w AS prev_preference,
            LAG(cr.source_id) OVER w AS prev_source_id
          FROM rate_observations ro
          JOIN collection_runs cr ON cr.id = ro.run_id
          WINDOW w AS (
            PARTITION BY ro.variant_id
            ORDER BY ro.valid_from, ro.observed_at, ro.id
          )
        ), marked AS (
          SELECT *,
            CASE
              WHEN prev_id IS NOT NULL
               AND base_rate IS prev_base_rate
               AND max_rate IS prev_max_rate
               AND raw_preference_text IS prev_preference
               AND source_id IS prev_source_id
              THEN 0 ELSE 1
            END AS group_start
          FROM ordered
        ), grouped AS (
          SELECT *,
            SUM(group_start) OVER (
              PARTITION BY variant_id
              ORDER BY valid_from, observed_at, id
              ROWS UNBOUNDED PRECEDING
            ) AS grp
          FROM marked
        )
        SELECT g.id, c.keep_id
        FROM grouped g
        JOIN _compact_groups c
          ON c.variant_id = g.variant_id AND c.grp = g.grp
        WHERE g.id <> c.keep_id;

        CREATE INDEX _compact_map_keep ON _compact_map(keep_id);
        """
    )


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _reference_blockers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for table in _table_names(conn):
        quoted_table = _quote_identifier(table)
        for fk in conn.execute(f"PRAGMA foreign_key_list({quoted_table})"):
            referenced_table = str(fk[2])
            child_column = str(fk[3])
            if referenced_table != "rate_observations":
                continue
            quoted_column = _quote_identifier(child_column)
            count = _scalar(
                conn,
                f"SELECT COUNT(*) FROM {quoted_table} child "
                f"JOIN _compact_map m ON m.delete_id = child.{quoted_column}",
            )
            if count:
                blockers.append(
                    {
                        "kind": "foreign_key",
                        "table": table,
                        "column": child_column,
                        "rows": count,
                    }
                )

    generic_refs = (
        ("manual_overrides", "target_type", "target_id"),
        ("review_items", "entity_type", "entity_id"),
        ("source_entity_links", "entity_type", "entity_id"),
    )
    tables = set(_table_names(conn))
    for table, type_column, id_column in generic_refs:
        if table not in tables:
            continue
        quoted_table = _quote_identifier(table)
        quoted_type = _quote_identifier(type_column)
        quoted_id = _quote_identifier(id_column)
        placeholders = ",".join("?" for _ in OBSERVATION_TYPES)
        sql = (
            f"SELECT COUNT(*) FROM {quoted_table} child "
            f"JOIN _compact_map m ON m.delete_id = child.{quoted_id} "
            f"WHERE LOWER(COALESCE(child.{quoted_type}, '')) IN ({placeholders})"
        )
        count = int(conn.execute(sql, tuple(sorted(OBSERVATION_TYPES))).fetchone()[0])
        if count:
            blockers.append(
                {
                    "kind": "generic_reference",
                    "table": table,
                    "column": id_column,
                    "rows": count,
                }
            )
    return blockers


def _candidate_counts_by_source(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        str(source_id): int(count)
        for source_id, count in conn.execute(
            """
            SELECT cr.source_id, COUNT(*)
            FROM _compact_map m
            JOIN rate_observations ro ON ro.id = m.delete_id
            JOIN collection_runs cr ON cr.id = ro.run_id
            GROUP BY cr.source_id
            ORDER BY COUNT(*) DESC
            """
        )
    }


def _apply_plan(conn: sqlite3.Connection) -> None:
    conn.create_function("rate_semantic_hash", 3, _semantic_hash)
    conn.execute(
        """
        UPDATE rate_observations AS keep
        SET
          last_run_id = (
            SELECT COALESCE(last.last_run_id, last.run_id)
            FROM _compact_groups grp
            JOIN rate_observations last ON last.id = grp.last_id
            WHERE grp.keep_id = keep.id
          ),
          last_seen_at = (
            SELECT MAX(member.last_seen_at)
            FROM _compact_map map
            JOIN rate_observations member ON member.id = map.delete_id
            WHERE map.keep_id = keep.id
          ),
          seen_count = (
            SELECT grp.total_seen_count
            FROM _compact_groups grp
            WHERE grp.keep_id = keep.id
          ),
          valid_to = (
            SELECT last.valid_to
            FROM _compact_groups grp
            JOIN rate_observations last ON last.id = grp.last_id
            WHERE grp.keep_id = keep.id
          ),
          as_of = (
            SELECT last.as_of
            FROM _compact_groups grp
            JOIN rate_observations last ON last.id = grp.last_id
            WHERE grp.keep_id = keep.id
          ),
          source_effective_at = (
            SELECT last.source_effective_at
            FROM _compact_groups grp
            JOIN rate_observations last ON last.id = grp.last_id
            WHERE grp.keep_id = keep.id
          ),
          content_hash = rate_semantic_hash(
            keep.base_rate, keep.max_rate, keep.raw_preference_text
          )
        WHERE keep.id IN (SELECT keep_id FROM _compact_groups)
        """
    )
    conn.execute("DELETE FROM rate_observations WHERE id IN (SELECT delete_id FROM _compact_map)")


def _integrity(conn: sqlite3.Connection) -> tuple[str, int]:
    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    return integrity, foreign_keys


def compact_rate_history(
    db_path: Path,
    *,
    apply: bool = False,
    vacuum_into: Path | None = None,
) -> dict[str, Any]:
    if apply and vacuum_into is None:
        raise ValueError("--apply requires --vacuum-into so the compacted artifact is separate")
    if vacuum_into is not None and vacuum_into.exists():
        raise FileExistsError(f"vacuum target already exists: {vacuum_into}")

    before_bytes = db_path.stat().st_size
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA temp_store=FILE")
        before_total = _scalar(conn, "SELECT COUNT(*) FROM rate_observations")
        before_current, before_fingerprint = _current_fingerprint(conn)
        _create_plan(conn)
        candidate_rows = _scalar(conn, "SELECT COUNT(*) FROM _compact_map")
        groups = _scalar(conn, "SELECT COUNT(*) FROM _compact_groups")
        blockers = _reference_blockers(conn)
        by_source = _candidate_counts_by_source(conn)

        report: dict[str, Any] = {
            "database": str(db_path),
            "mode": "apply" if apply else "dry-run",
            "before_file_bytes": before_bytes,
            "before_rate_observations": before_total,
            "before_current_observations": before_current,
            "candidate_rows": candidate_rows,
            "candidate_groups": groups,
            "candidate_rows_by_source": by_source,
            "estimated_rate_observations_after": before_total - candidate_rows,
            "reference_blockers": blockers,
        }
        if not apply:
            return report
        if blockers:
            raise RuntimeError(f"compaction blocked by observation references: {blockers}")

        conn.execute("BEGIN IMMEDIATE")
        _apply_plan(conn)
        after_total = _scalar(conn, "SELECT COUNT(*) FROM rate_observations")
        after_current, after_fingerprint = _current_fingerprint(conn)
        integrity, foreign_key_errors = _integrity(conn)
        if after_total != before_total - candidate_rows:
            raise RuntimeError("observation count mismatch after compaction")
        if after_current != before_current or after_fingerprint != before_fingerprint:
            raise RuntimeError("current rate surface changed during compaction")
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError(
                f"database validation failed: integrity={integrity} fk={foreign_key_errors}"
            )
        conn.commit()

        target = vacuum_into.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        literal = str(target).replace("'", "''")
        conn.execute(f"VACUUM INTO '{literal}'")
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()

    compacted = sqlite3.connect(f"file:{vacuum_into}?mode=ro", uri=True)
    try:
        compacted_total = _scalar(compacted, "SELECT COUNT(*) FROM rate_observations")
        compacted_current, compacted_fingerprint = _current_fingerprint(compacted)
        integrity, foreign_key_errors = _integrity(compacted)
    finally:
        compacted.close()

    if compacted_total != before_total - candidate_rows:
        raise RuntimeError("vacuumed artifact observation count mismatch")
    if compacted_current != before_current or compacted_fingerprint != before_fingerprint:
        raise RuntimeError("vacuumed artifact current rate surface mismatch")
    if integrity != "ok" or foreign_key_errors:
        raise RuntimeError("vacuumed artifact failed integrity checks")

    after_bytes = vacuum_into.stat().st_size
    report.update(
        {
            "after_rate_observations": compacted_total,
            "after_current_observations": compacted_current,
            "after_file_bytes": after_bytes,
            "bytes_reclaimed": before_bytes - after_bytes,
            "size_ratio": round(after_bytes / before_bytes, 6) if before_bytes else None,
            "integrity_check": integrity,
            "foreign_key_errors": foreign_key_errors,
            "compacted_sha256": _sha256(vacuum_into),
        }
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--vacuum-into", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = compact_rate_history(
        args.db,
        apply=args.apply,
        vacuum_into=args.vacuum_into,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
