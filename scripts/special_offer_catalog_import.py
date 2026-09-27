#!/usr/bin/env python3
"""Import an R3-C capture JSON into the independent official special-offer catalog.

This command is intentionally DB-local. Production writers are not wired to it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

from rate_monitor.db.models import Product, ProductVariant, RateObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.db.special_offer_models import OfficialSpecialOfferCatalogEvidence
from rate_monitor.services.special_offer_catalog_service import import_capture_payload


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.capture.read_text(encoding="utf-8"))
    factory = make_session_factory(create_db_engine(args.db))
    with session_scope(factory) as session:
        before = _counts(session)
        imported = import_capture_payload(session, payload)
        after = _counts(session)

    report = {
        "before": before,
        "after": after,
        "imported_rows": len(imported),
        "canonical_counts_unchanged": all(
            before[key] == after[key]
            for key in ("products", "variants", "rate_observations")
        ),
        "production_write": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["canonical_counts_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
