#!/usr/bin/env python3
"""Read-only audit for rate-observation history growth.

The canonical contract stores a new ``rate_observations`` row only when the
rate value changes.  ``source_effective_at`` is provenance and may advance on
an otherwise unchanged quote, so this audit intentionally excludes it from the
semantic value comparison.

The script never writes to the database.  It reports how many consecutive rows
per variant/source carry the same semantic value and therefore look eligible
for a later, separately gated compaction.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _dbstat_bytes(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        rows = conn.execute(
            "SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY bytes DESC"
        ).fetchall()
    except sqlite3.DatabaseError:
        return {}
    return {str(name): int(size or 0) for name, size in rows}


def audit_rate_history(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        page_size = _scalar(conn, "PRAGMA page_size")
        page_count = _scalar(conn, "PRAGMA page_count")
        freelist_count = _scalar(conn, "PRAGMA freelist_count")
        total = _scalar(conn, "SELECT COUNT(*) FROM rate_observations")
        current = _scalar(
            conn, "SELECT COUNT(*) FROM rate_observations WHERE valid_to IS NULL"
        )
        variants = _scalar(conn, "SELECT COUNT(*) FROM product_variants")

        source_rows = {
            str(source_id): int(count)
            for source_id, count in conn.execute(
                "SELECT cr.source_id, COUNT(*) "
                "FROM rate_observations ro "
                "JOIN collection_runs cr ON cr.id = ro.run_id "
                "GROUP BY cr.source_id ORDER BY COUNT(*) DESC"
            )
        }

        # A redundant row is consecutive history for the same stable variant and
        # source with exactly the same rate/preference value.  Effective dates are
        # deliberately not part of the value: NH uses the query date and KFCC uses
        # the page's query-basis date, both of which can advance with unchanged rates.
        rows = conn.execute(
            """
            WITH ordered AS (
              SELECT
                cr.source_id AS source_id,
                ro.variant_id AS variant_id,
                ro.source_effective_at AS source_effective_at,
                LAG(ro.source_effective_at) OVER w AS prev_effective_at,
                CASE
                  WHEN ro.base_rate IS LAG(ro.base_rate) OVER w
                   AND ro.max_rate IS LAG(ro.max_rate) OVER w
                   AND ro.raw_preference_text IS LAG(ro.raw_preference_text) OVER w
                   AND cr.source_id IS LAG(cr.source_id) OVER w
                  THEN 1 ELSE 0
                END AS redundant
              FROM rate_observations ro
              JOIN collection_runs cr ON cr.id = ro.run_id
              WINDOW w AS (
                PARTITION BY ro.variant_id
                ORDER BY ro.valid_from, ro.observed_at, ro.id
              )
            )
            SELECT
              source_id,
              COUNT(*) AS rows,
              SUM(redundant) AS redundant_rows,
              SUM(
                CASE
                  WHEN redundant = 1
                   AND NOT (source_effective_at IS prev_effective_at)
                  THEN 1 ELSE 0
                END
              ) AS effective_date_only_rows
            FROM ordered
            GROUP BY source_id
            ORDER BY redundant_rows DESC, rows DESC
            """
        ).fetchall()

        by_source: dict[str, dict[str, int]] = {}
        redundant_total = 0
        effective_date_only_total = 0
        for source_id, count, redundant, effective_only in rows:
            redundant_count = int(redundant or 0)
            effective_only_count = int(effective_only or 0)
            redundant_total += redundant_count
            effective_date_only_total += effective_only_count
            by_source[str(source_id)] = {
                "rows": int(count),
                "redundant_consecutive_rows": redundant_count,
                "effective_date_only_rows": effective_only_count,
            }

        physical_bytes = page_size * page_count
        free_bytes = page_size * freelist_count
        report: dict[str, Any] = {
            "database": str(db_path),
            "file_bytes": db_path.stat().st_size,
            "sqlite_page_bytes": physical_bytes,
            "sqlite_free_bytes": free_bytes,
            "rate_observations": total,
            "current_observations": current,
            "product_variants": variants,
            "history_rows_per_variant": round(total / variants, 4) if variants else None,
            "source_rows": source_rows,
            "semantic_redundant_rows": redundant_total,
            "effective_date_only_rows": effective_date_only_total,
            "estimated_rows_after_semantic_compaction": total - redundant_total,
            "by_source": by_source,
            "dbstat_bytes": _dbstat_bytes(conn),
        }
        return report
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_rate_history(args.db)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
