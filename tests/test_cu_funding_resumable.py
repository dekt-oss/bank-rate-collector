from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from rate_monitor.collectors.cu.funding import (
    SOURCE_ID,
    DisclosureRecord,
    parse_summary_point,
)
from rate_monitor.collectors.cu.resumable_funding import (
    CuFundingTargetBundle,
    acquire_cu_funding_checkpoint,
    decode_target_bundle,
    encode_target_bundle,
    replay_cu_funding_checkpoint,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.schemas import RawArtifactData
from rate_monitor.services.resumable_acquisition import CheckpointIncompatibleError
from rate_monitor.services.storage_service import LocalObjectStore


def _raw(
    *, content: bytes, filename: str, request_meta: dict[str, object], artifact_type: str
) -> RawArtifactData:
    digest = hashlib.sha256(content).hexdigest()
    return RawArtifactData(
        artifact_type=artifact_type,
        content=content,
        filename=filename,
        request_meta=request_meta,
        schema_fingerprint=digest,
        source_role="primary_official",
        trust_level="official_direct",
    )


def _summary_html(year: int, amount: int) -> str:
    return f"""
    <html><body>
      <div>단위 : 백만원</div>
      <table>
        <tr><th>구분</th><th>{year}년도</th><th>{year - 1}년도</th><th>증감</th></tr>
        <tr>
          <td>예 수 부 채</td><td>{amount:,}</td><td>80.0</td>
          <td>{amount - 10:,}</td><td>79.0</td><td>10</td><td>1.0</td>
        </tr>
      </table>
    </body></html>
    """


def _seed(db_path, keys: tuple[str, ...]) -> None:
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 29, 1, 0, 0)
    with session_scope(factory) as session:
        session.add(
            m.Source(
                id="cu",
                name="CU rate directory",
                sector="cu",
                mode="http",
                source_role="primary_official",
                trust_level="official_direct",
                priority=10,
                enabled=True,
                policy_status="review",
                coverage_status="partial",
                parser_version="1",
                created_at=now,
                updated_at=now,
            )
        )
        for key in keys:
            institution = m.Institution(
                sector="cu",
                canonical_name=f"신협-{key}",
                normalized_name=f"신협-{key}",
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
                    source_entity_key=f"cu:{key}",
                    entity_id=institution.id,
                    source_name=f"신협-{key}",
                    confidence=1.0,
                    match_method="exact_code",
                    valid_from=None,
                    valid_to=None,
                    created_at=now,
                    updated_at=now,
                )
            )


def _fake_fetch_target(
    _client,
    *,
    cu_ingno: str,
    institution_id: str,
    institution_name: str,
    periods: int,
    request_interval: float,
):
    del periods, request_interval
    year = 2025
    disclosure_no = 20_000 + int(cu_ingno)
    disclosure = DisclosureRecord(
        cu_ingno=cu_ingno,
        disclosure_no=disclosure_no,
        disclosure_type="1",
        disclosure_name="2025년도 결산정기공시",
        reg_date="2026-03-01",
        short_file_name="summary.pdf",
        year=year,
        month=12,
    )
    amount = 10_000 + int(cu_ingno)
    html = _summary_html(year, amount)
    endpoint = f"https://example.test/{cu_ingno}/{disclosure_no}"
    point = parse_summary_point(
        html,
        disclosure=disclosure,
        institution_id=institution_id,
        institution_name=institution_name,
        source_locator=endpoint,
    )
    list_payload = {
        "list": [
            {
                "cuIngno": cu_ingno,
                "disclosureNo": disclosure_no,
                "disclosureTy": "1",
                "disclosureName": disclosure.disclosure_name,
                "regDate": disclosure.reg_date,
                "shortFileName": disclosure.short_file_name,
                "bogoTy": "Y",
                "chkYn3": "Y",
                "listTotalCount": 1,
            }
        ]
    }
    list_artifact = _raw(
        content=json.dumps(list_payload, ensure_ascii=False).encode(),
        filename=f"cu-funding-{cu_ingno}-list-p01.json",
        request_meta={
            "kind": "disclosure_list",
            "cuIngno": cu_ingno,
            "page": 1,
            "endpoint": "https://example.test/list",
        },
        artifact_type="json",
    )
    summary_artifact = _raw(
        content=html.encode(),
        filename=f"cu-funding-{cu_ingno}-2025-12-{disclosure_no}.html",
        request_meta={
            "kind": "summary_disclosure",
            "cuIngno": cu_ingno,
            "disclosure_no": disclosure_no,
            "disclosure_type": "1",
            "source_effective_month": "2025-12",
            "endpoint": endpoint,
        },
        artifact_type="html",
    )
    return [point], [list_artifact, summary_artifact], {disclosure_no: 1}, []


def test_bundle_roundtrip_and_hash_guard() -> None:
    artifact = _raw(
        content=b"exact-source-bytes",
        filename="source.bin",
        request_meta={"kind": "disclosure_list"},
        artifact_type="bin",
    )
    encoded = encode_target_bundle(
        CuFundingTargetBundle(
            cu_ingno="02002",
            institution_id="inst-1",
            institution_name="광안",
            periods=12,
            artifacts=(artifact,),
            warnings=("historical warning",),
        )
    )
    decoded = decode_target_bundle(encoded)
    assert decoded.cu_ingno == "02002"
    assert decoded.artifacts[0].content == b"exact-source-bytes"
    assert decoded.warnings == ("historical warning",)

    tampered = RawArtifactData(
        artifact_type=encoded.artifact_type,
        content=encoded.content + b"x",
        filename=encoded.filename,
        request_meta=encoded.request_meta,
        schema_fingerprint=encoded.schema_fingerprint,
        source_role=encoded.source_role,
        trust_level=encoded.trust_level,
    )
    with pytest.raises(CheckpointIncompatibleError, match="bundle hash"):
        decode_target_bundle(tampered)


def test_checkpoint_resumes_by_institution_and_replay_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "rate.sqlite3"
    raw_root = tmp_path / "raw"
    keys = ("01002", "02002", "03087")
    _seed(db_path, keys)
    store = LocalObjectStore(tmp_path / "checkpoint")

    first = acquire_cu_funding_checkpoint(
        store=store,
        db_path=db_path,
        periods=12,
        cycle_date_kst="2026-08-29",
        only_cu_nos=set(keys),
        max_new_targets=2,
        request_interval=0,
        fetch_target=_fake_fetch_target,
    )
    assert first.status == "collecting"
    assert first.completed_targets == 2
    assert first.newly_completed_targets == 2

    second = acquire_cu_funding_checkpoint(
        store=store,
        db_path=db_path,
        periods=12,
        cycle_date_kst="2026-08-29",
        only_cu_nos=set(keys),
        request_interval=0,
        fetch_target=_fake_fetch_target,
    )
    assert second.status == "complete"
    assert second.completed_targets == 3
    assert second.newly_completed_targets == 1

    third = acquire_cu_funding_checkpoint(
        store=store,
        db_path=db_path,
        periods=12,
        cycle_date_kst="2026-08-29",
        only_cu_nos=set(keys),
        request_interval=0,
        fetch_target=_fake_fetch_target,
    )
    assert third.status == "complete"
    assert third.newly_completed_targets == 0

    replay = replay_cu_funding_checkpoint(
        store=store,
        db_path=db_path,
        raw_root=raw_root,
        periods=12,
        cycle_date_kst="2026-08-29",
    )
    assert replay.target_count == 3
    assert replay.raw_artifacts == 6
    assert replay.parsed_points == 3
    assert replay.stored == 3
    assert replay.unchanged == 0
    assert replay.warning_count == 0

    replay_again = replay_cu_funding_checkpoint(
        store=store,
        db_path=db_path,
        raw_root=raw_root,
        periods=12,
        cycle_date_kst="2026-08-29",
    )
    assert replay_again.stored == 0
    assert replay_again.revisions == 0
    assert replay_again.unchanged == 3

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        observations = list(
            session.scalars(
                select(InstitutionFundingObservation).where(
                    InstitutionFundingObservation.source_id == SOURCE_ID,
                    InstitutionFundingObservation.valid_to.is_(None),
                )
            )
        )
    assert len(observations) == 3
    assert {row.value for row in observations} == {
        Decimal("11002.000000"),
        Decimal("12002.000000"),
        Decimal("13087.000000"),
    }


def test_replay_fails_if_exact_identity_link_drifted(tmp_path) -> None:
    db_path = tmp_path / "rate.sqlite3"
    key = "02002"
    _seed(db_path, (key,))
    store = LocalObjectStore(tmp_path / "checkpoint")
    acquired = acquire_cu_funding_checkpoint(
        store=store,
        db_path=db_path,
        periods=12,
        cycle_date_kst="2026-08-29",
        only_cu_nos={key},
        request_interval=0,
        fetch_target=_fake_fetch_target,
    )
    assert acquired.status == "complete"

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 29, 2, 0, 0)
    with session_scope(factory) as session:
        link = session.scalar(
            select(m.SourceEntityLink).where(
                m.SourceEntityLink.source_id == "cu",
                m.SourceEntityLink.source_entity_key == f"cu:{key}",
                m.SourceEntityLink.valid_to.is_(None),
            )
        )
        assert link is not None
        replacement = m.Institution(
            sector="cu",
            canonical_name="replacement",
            normalized_name="replacement",
            active=True,
            availability_scope="local_members",
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(replacement)
        session.flush()
        link.entity_id = replacement.id
        link.updated_at = now

    with pytest.raises(CheckpointIncompatibleError, match="current exact link"):
        replay_cu_funding_checkpoint(
            store=store,
            db_path=db_path,
            raw_root=tmp_path / "raw",
            periods=12,
            cycle_date_kst="2026-08-29",
        )
