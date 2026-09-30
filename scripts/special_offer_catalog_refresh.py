#!/usr/bin/env python3
"""Refresh the bank-direct special-offer catalog from configured official sources.

The command writes only official_special_offer_catalog_evidence. Canonical Product,
ProductVariant, and RateObservation counts are checked before/after and any change
fails the command. Individual source capture failures are reported fail-closed while
successful sources may still append evidence.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from rate_monitor.db.models import Product, ProductVariant, RateObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.special_offer_models import OfficialSpecialOfferCatalogEvidence
from rate_monitor.services.special_offer_catalog_service import import_capture_payload
from special_offer_official_capture import capture


def _counts(session) -> dict[str, int]:
    return {
        "products": int(session.scalar(select(func.count()).select_from(Product)) or 0),
        "variants": int(
            session.scalar(select(func.count()).select_from(ProductVariant)) or 0
        ),
        "rate_observations": int(
            session.scalar(select(func.count()).select_from(RateObservation)) or 0
        ),
        "catalog_evidence": int(
            session.scalar(
                select(func.count()).select_from(OfficialSpecialOfferCatalogEvidence)
            )
            or 0
        ),
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _canonical_unchanged(before: dict[str, int], after: dict[str, int]) -> bool:
    return all(
        before[key] == after[key]
        for key in ("products", "variants", "rate_observations")
    )


def refresh_catalog(
    *,
    db_path: Path,
    capture_payload: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    factory = make_session_factory(create_db_engine(db_path))
    with session_scope(factory) as session:
        before = _counts(session)

    imported = []
    import_error: str | None = None
    try:
        with session_scope(factory) as session:
            imported = import_capture_payload(session, capture_payload)
    except Exception as exc:  # noqa: BLE001 - report a fail-closed import result.
        import_error = f"{type(exc).__name__}: {exc}"

    with session_scope(factory) as session:
        after = _counts(session)

    coverage = dict(capture_payload.get("coverage") or {})
    captured = int(coverage.get("successful_captures") or 0)
    failures = list(capture_payload.get("failures") or [])
    availability_failures = list(capture_payload.get("availability_failures") or [])
    canonical_ok = _canonical_unchanged(before, after)
    inserted = max(0, after["catalog_evidence"] - before["catalog_evidence"])
    imported_count = len(imported)
    existing = max(0, imported_count - inserted)
    availability_counts = Counter(
        str(row.availability_status) for row in imported
    )

    if import_error or not canonical_ok or captured == 0:
        status = "failed"
        exit_code = 1
    elif failures or availability_failures:
        status = "partial"
        exit_code = 0
    else:
        status = "success"
        exit_code = 0

    report = {
        "status": status,
        "coverage": {
            "configured": int(coverage.get("configured_targets") or 0),
            "captured": captured,
            "failed": len(failures),
            "availability_failed": len(availability_failures),
        },
        "catalog": {
            "imported": imported_count,
            "inserted": inserted,
            "existing": existing,
            "confirmed_active": availability_counts.get("confirmed_active", 0),
            "confirmed_ended": availability_counts.get("confirmed_ended", 0),
            "unknown": availability_counts.get("unknown", 0),
        },
        "before": before,
        "after": after,
        "canonical_counts_unchanged": canonical_ok,
        "db_write_scope": "official_special_offer_catalog_evidence_only",
        "production_state_mutated_by_command": True,
        "source_failures": failures,
        "availability_failures": availability_failures,
        "import_error": import_error,
    }
    return report, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path)
    source.add_argument("--capture-input", type=Path)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw/special-offer-official"),
    )
    parser.add_argument("--capture-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    args = parser.parse_args()

    if args.capture_input is not None:
        capture_payload = json.loads(args.capture_input.read_text(encoding="utf-8"))
    else:
        assert args.config is not None
        config = json.loads(args.config.read_text(encoding="utf-8"))
        capture_payload = capture(config, args.raw_dir)
    _write(args.capture_out, capture_payload)
    report, exit_code = refresh_catalog(
        db_path=args.db,
        capture_payload=capture_payload,
    )
    _write(args.report_out, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
