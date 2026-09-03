"""Fail-closed read model for the Strategy special-offer radar.

The registry deliberately distinguishes a source snapshot that says nothing about
special-sale status from explicit product-level evidence. The radar therefore uses
``resolve_special_offer_state`` and never treats ``unknown`` as a promotion. It is
a read-only Strategy payload; activating a public promotion benchmark remains a
separate release decision.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.services.special_offer_evidence_service import (
    CONFIRMED_NORMAL,
    CONFIRMED_SPECIAL,
    UNKNOWN,
    resolve_special_offer_state,
)

SOURCE_ID = "fsb"
RADAR_ACTIVATION = "off_until_confirmed_evidence_is_reviewed_and_separately_approved"
_CONFIRMED_RUN_STATUSES = ("success", "partial", "no_change")
_BATCH_SIZE = 400
_EMPTY_RATE = {
    "representative_rate": None,
    "rate_source_effective_at": None,
    "rate_last_seen_at": None,
    "term_months": None,
    "join_channel": None,
}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (name,),
        ).fetchone()
        is not None
    )


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "source_id": SOURCE_ID,
        "as_of": None,
        "known_at": None,
        "activation": RADAR_ACTIVATION,
        "counts": {
            UNKNOWN: 0,
            CONFIRMED_SPECIAL: 0,
            CONFIRMED_NORMAL: 0,
            "conflict": 0,
        },
        "offers": [],
        "policy": {
            "unknown_is_special": False,
            "heuristic_confirmation": False,
            "ranking_population_changed": False,
        },
    }


def _latest_context(
    conn: sqlite3.Connection,
    *,
    as_of: date | None,
    known_at: datetime | None,
) -> tuple[date, datetime] | None:
    row = conn.execute(
        "SELECT MAX(snapshot_as_of), MAX(observed_at) "
        "FROM product_special_offer_evidence WHERE source_id=?",
        (SOURCE_ID,),
    ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    resolved_as_of = as_of or date.fromisoformat(str(row[0]))
    resolved_known_at = known_at or datetime.fromisoformat(str(row[1]))
    return resolved_as_of, resolved_known_at


def _candidate_product_ids(
    conn: sqlite3.Connection,
    *,
    as_of: date,
    known_at: datetime,
) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT product_id FROM product_special_offer_evidence "
        "WHERE source_id=? AND observed_at<=? AND ("
        "snapshot_as_of=? OR ("
        "classification!='unknown' AND source_effective_from IS NOT NULL "
        "AND source_effective_from<=? "
        "AND (source_effective_to IS NULL OR source_effective_to>=?)"
        ")) ORDER BY product_id",
        (
            SOURCE_ID,
            known_at.isoformat(sep=" ", timespec="microseconds"),
            as_of.isoformat(),
            as_of.isoformat(),
            as_of.isoformat(),
        ),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _batches(values: Iterable[str], *, size: int = _BATCH_SIZE) -> Iterable[list[str]]:
    batch: list[str] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _product_contexts(
    conn: sqlite3.Connection, product_ids: list[str]
) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for batch in _batches(product_ids):
        placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            "SELECT p.id, p.name, p.product_type, i.id, i.canonical_name, i.sector "
            "FROM products p JOIN institutions i ON i.id=p.institution_id "
            f"WHERE p.id IN ({placeholders})",
            tuple(batch),
        ).fetchall()
        for row in rows:
            contexts[str(row[0])] = {
                "product_id": str(row[0]),
                "product_name": str(row[1]),
                "product_type": str(row[2]),
                "institution_id": str(row[3]),
                "institution_name": str(row[4]),
                "sector": str(row[5]),
            }
    return contexts


def _current_fsb_rates(
    conn: sqlite3.Connection, product_ids: list[str]
) -> dict[str, dict[str, Any]]:
    rates = {product_id: dict(_EMPTY_RATE) for product_id in product_ids}
    candidates: dict[str, list[tuple[float, str, Any, Any, Any]]] = {
        product_id: [] for product_id in product_ids
    }
    status_placeholders = ",".join("?" for _ in _CONFIRMED_RUN_STATUSES)
    for batch in _batches(product_ids):
        product_placeholders = ",".join("?" for _ in batch)
        rows = conn.execute(
            "SELECT pv.product_id, ro.max_rate, ro.base_rate, ro.source_effective_at, "
            "ro.last_seen_at, pv.term_months, pv.join_channel "
            "FROM product_variants pv "
            "JOIN rate_observations ro ON ro.variant_id=pv.id AND ro.valid_to IS NULL "
            "JOIN collection_runs cr ON cr.id=ro.last_run_id "
            f"WHERE pv.product_id IN ({product_placeholders}) AND cr.source_id=? "
            f"AND cr.status IN ({status_placeholders}) "
            "AND ro.validation_status='valid'",
            (*batch, SOURCE_ID, *_CONFIRMED_RUN_STATUSES),
        ).fetchall()
        for (
            product_id,
            max_rate,
            base_rate,
            source_effective_at,
            last_seen_at,
            term_months,
            join_channel,
        ) in rows:
            raw_rate = max_rate if max_rate is not None else base_rate
            if raw_rate is None:
                continue
            candidates[str(product_id)].append(
                (
                    float(raw_rate),
                    str(source_effective_at or ""),
                    last_seen_at,
                    term_months,
                    join_channel,
                )
            )
    for product_id, product_candidates in candidates.items():
        if not product_candidates:
            continue
        rate, effective, last_seen, term_months, join_channel = max(
            product_candidates,
            key=lambda item: (item[0], item[1], str(item[2] or "")),
        )
        rates[product_id] = {
            "representative_rate": rate,
            "rate_source_effective_at": effective or None,
            "rate_last_seen_at": str(last_seen) if last_seen is not None else None,
            "term_months": term_months,
            "join_channel": join_channel,
        }
    return rates


def build_special_offer_radar(
    db_path: Path,
    *,
    as_of: date | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the Strategy read model without inferring special-sale status.

    ``unknown`` is coverage information only. Only an FSB state resolved by the
    registry as ``confirmed_special`` is eligible for ``offers``.
    """

    if not db_path.exists():
        return _unavailable("database_missing")
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "product_special_offer_evidence"):
            return _unavailable("evidence_registry_missing")
        context = _latest_context(conn, as_of=as_of, known_at=known_at)
        if context is None:
            return _unavailable("no_special_offer_evidence")
        resolved_as_of, resolved_known_at = context
        product_ids = _candidate_product_ids(
            conn,
            as_of=resolved_as_of,
            known_at=resolved_known_at,
        )
        product_context = _product_contexts(conn, product_ids)
        rates = _current_fsb_rates(conn, product_ids)
    finally:
        conn.close()

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    session = factory()
    try:
        counts = {
            UNKNOWN: 0,
            CONFIRMED_SPECIAL: 0,
            CONFIRMED_NORMAL: 0,
            "conflict": 0,
        }
        offers: list[dict[str, Any]] = []
        for product_id in product_ids:
            state = resolve_special_offer_state(
                session,
                product_id=product_id,
                as_of=resolved_as_of,
                known_at=resolved_known_at,
                source_id=SOURCE_ID,
            )
            if state.conflict:
                counts["conflict"] += 1
                counts[UNKNOWN] += 1
                continue
            counts[state.classification] += 1
            if state.classification != CONFIRMED_SPECIAL:
                continue
            context_row = product_context.get(product_id)
            if context_row is None:
                continue
            offers.append(
                {
                    **context_row,
                    **rates[product_id],
                    "classification": state.classification,
                    "evidence_kind": state.evidence_kind,
                    "evidence_ref": state.evidence_ref,
                    "evidence_ids": list(state.evidence_ids),
                }
            )
    finally:
        session.close()
        engine.dispose()

    offers.sort(
        key=lambda item: (
            -(item["representative_rate"] if item["representative_rate"] is not None else -1.0),
            item["institution_name"],
            item["product_name"],
        )
    )
    status = "confirmed_evidence_available" if offers else "collecting_confirmed_evidence"
    return {
        "status": status,
        "reason": None if offers else "no_confirmed_special_at_snapshot",
        "source_id": SOURCE_ID,
        "as_of": resolved_as_of.isoformat(),
        "known_at": resolved_known_at.isoformat(),
        "activation": RADAR_ACTIVATION,
        "counts": counts,
        "offers": offers,
        "policy": {
            "unknown_is_special": False,
            "heuristic_confirmation": False,
            "ranking_population_changed": False,
        },
    }
