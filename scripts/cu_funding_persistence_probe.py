#!/usr/bin/env python3
"""Bounded live proof for CU disclosure funding persistence.

This creates a temporary SQLite DB with only two repository-captured CU exact
links, collects one latest reporting period from the official CU disclosure
site, reruns the same collection, and asserts value/provenance/idempotency.
No production DB or R2 object is opened.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from rate_monitor.collectors.cu.funding import (
    IDENTITY_STATUS,
    SOURCE_ID,
    SOURCE_UNIT,
    collect_cu_disclosure_funding,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope

OUT = Path("docs/source-recon/cu-funding-persistence-probe-20260829.json")
CONTROLS = (
    ("02002", "광안", "광안신협"),
    ("02022", "HJ중공업", "HJ중공업신협"),
)
EXPECTED = {
    ("02002", "2025-12"): "1720194.000000",
    ("02022", "2026-06"): "6460.000000",
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _source(now: datetime) -> m.Source:
    return m.Source(
        id="cu",
        name="신협 전자공시 금리비교",
        sector="cu",
        mode="http",
        source_role="primary_official",
        trust_level="official_direct",
        priority=10,
        base_reference="https://www.cu.co.kr/cu/ad/inrstCmpr",
        enabled=True,
        schedule_cron=None,
        policy_status="review",
        coverage_status="partial",
        parser_version="probe",
        created_at=now,
        updated_at=now,
    )


def _seed(factory) -> None:
    now = _now()
    with session_scope(factory) as session:
        session.add(_source(now))
        for cu_ingno, source_name, canonical_name in CONTROLS:
            institution = m.Institution(
                sector="cu",
                canonical_name=canonical_name,
                normalized_name=canonical_name,
                active=True,
                availability_scope="local_members",
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(institution)
            session.flush()
            session.add(
                m.SourceEntityLink(
                    source_id="cu",
                    entity_type="institution",
                    source_entity_key=f"cu:{cu_ingno}",
                    entity_id=institution.id,
                    source_name=source_name,
                    confidence=1.0,
                    match_method="exact_code",
                    valid_from=None,
                    valid_to=None,
                    created_at=now,
                    updated_at=now,
                )
            )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cu-funding-probe-") as temp:
        root = Path(temp)
        db_path = root / "probe.sqlite3"
        raw_root = root / "raw"
        engine = create_db_engine(db_path)
        m.Base.metadata.create_all(engine)
        factory = make_session_factory(engine)
        _seed(factory)

        wanted = {row[0] for row in CONTROLS}
        first = collect_cu_disclosure_funding(
            db_path=db_path,
            raw_root=raw_root,
            periods=1,
            only_cu_nos=wanted,
            request_interval=1.0,
        )
        if first.status != "success" or first.parsed_points != 2 or first.stored != 2:
            raise SystemExit(f"first CU funding probe failed: {first}")

        second = collect_cu_disclosure_funding(
            db_path=db_path,
            raw_root=raw_root,
            periods=1,
            only_cu_nos=wanted,
            request_interval=1.0,
        )
        if (
            second.status != "success"
            or second.parsed_points != 2
            or second.stored != 0
            or second.revisions != 0
            or second.unchanged != 2
        ):
            raise SystemExit(f"CU funding idempotency failed: {second}")

        with session_scope(factory) as session:
            observations = list(
                session.scalars(
                    select(InstitutionFundingObservation)
                    .where(
                        InstitutionFundingObservation.source_id == SOURCE_ID,
                        InstitutionFundingObservation.valid_to.is_(None),
                    )
                    .order_by(
                        InstitutionFundingObservation.source_institution_key,
                        InstitutionFundingObservation.source_effective_month,
                    )
                )
            )
            raw_count = len(
                list(
                    session.scalars(
                        select(m.RawArtifact)
                        .join(
                            m.CollectionRun,
                            m.RawArtifact.run_id == m.CollectionRun.id,
                        )
                        .where(m.CollectionRun.source_id == SOURCE_ID)
                    )
                )
            )

        if len(observations) != 2:
            raise SystemExit(
                f"unexpected active observation count: {len(observations)}"
            )

        rows = []
        for observation in observations:
            key = (
                observation.source_institution_key,
                observation.source_effective_month,
            )
            value = format(observation.value, "f")
            if EXPECTED.get(key) != value:
                raise SystemExit(f"unexpected CU funding value: {key}={value}")
            if (
                observation.source_unit != SOURCE_UNIT
                or observation.unit != "million_krw"
            ):
                raise SystemExit(
                    "CU funding unit contract mismatch: "
                    f"{observation.source_unit}/{observation.unit}"
                )
            if (
                observation.identity_status != IDENTITY_STATUS
                or observation.institution_id is None
            ):
                raise SystemExit(
                    "CU exact identity contract mismatch: "
                    f"{observation.source_institution_key}"
                )
            rows.append(
                {
                    "cu_ingno": observation.source_institution_key,
                    "source_effective_month": observation.source_effective_month,
                    "value_million_krw": value,
                    "source_unit": observation.source_unit,
                    "identity_status": observation.identity_status,
                    "revision": observation.revision,
                    "source_locator": observation.source_locator,
                }
            )

        payload = {
            "mode": "bounded_live_temp_db_no_r2",
            "controls": [
                {"cuIngno": cu, "source_name": name}
                for cu, name, _ in CONTROLS
            ],
            "first_run": first.__dict__,
            "second_run": second.__dict__,
            "active_observations": rows,
            "raw_artifact_rows_across_two_runs": raw_count,
            "integrity": "passed",
        }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
