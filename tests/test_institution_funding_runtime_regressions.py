from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from rate_monitor.collectors.data_go_funding.collector import CONTRACTS
from rate_monitor.collectors.data_go_funding.resilient import _save_month_artifacts
from rate_monitor.collectors.data_go_funding.transport import _select_target_table
from rate_monitor.db.models import Base, CollectionRun, RawArtifact, Source
from rate_monitor.domain.schemas import RawArtifactData


def _contract(sector: str):
    return next(contract for contract in CONTRACTS if contract.sector == sector)


def _savings_row(*, bank: str = "001") -> dict[str, str]:
    return {
        "basYm": "202603",
        "fncoCd": bank,
        "fncoNm": f"저축은행-{bank}",
        "dpsdbtDcd": "A11",
        "dpsdbtDcdNm": "예수부채",
        "dpsdbtClsfAmt": "1000000",
    }


def _table(title: str, rows: list[dict[str, str]]) -> dict:
    return {
        "title": title,
        "totalCount": len(rows),
        "items": {"item": rows},
    }


def test_savings_prefers_dedicated_deposit_liabilities_table_when_a11_is_duplicated():
    summary_row = _savings_row(bank="summary")
    dedicated_row = _savings_row(bank="dedicated")
    payload = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
            "body": {
                "tableList": [
                    _table(
                        "저축_재무현황_요약재무상태표(부채및자본)",
                        [summary_row],
                    ),
                    _table(
                        "저축_재무현황_부채부문별현황_예수부채",
                        [dedicated_row],
                    ),
                ]
            },
        }
    }

    title, total_count, rows = _select_target_table(
        payload,
        contract=_contract("savings_bank"),
        bas_ym="202603",
        target_title=None,
    )

    assert title == "저축_재무현황_부채부문별현황_예수부채"
    assert total_count == 1
    assert rows == [dedicated_row]


def _source(now: datetime) -> Source:
    return Source(
        id="data_go_agri_coop_funding",
        name="농축협 재무현황",
        sector="nh_local",
        mode="api",
        source_role="secondary_official",
        trust_level="official_direct",
        priority=100,
        enabled=True,
        policy_status="active",
        coverage_status="partial",
        parser_version="test",
        created_at=now,
        updated_at=now,
    )


def _artifact(filename: str, bas_ym: str) -> RawArtifactData:
    content = b'{"response":{"body":{"tableList":[]}}}'
    return RawArtifactData(
        artifact_type="json",
        content=content,
        filename=filename,
        request_meta={"basYm": bas_ym, "pageNo": 1},
        schema_fingerprint="same-empty-payload",
        source_role="secondary_official",
        trust_level="official_direct",
    )


def test_same_run_identical_empty_month_payload_reuses_raw_artifact(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    now = datetime(2026, 8, 28, 13, 37, tzinfo=UTC).replace(tzinfo=None)

    with factory.begin() as session:
        session.add(_source(now))
        run = CollectionRun(
            source_id="data_go_agri_coop_funding",
            mode="api",
            started_at=now,
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id
        first = _save_month_artifacts(
            session=session,
            run=run,
            artifacts=[_artifact("agri-202606-p001.json", "202606")],
            raw_root=tmp_path,
            now=now,
        )
        first_id = first[0].id

    with factory.begin() as session:
        run = session.get(CollectionRun, run_id)
        assert run is not None
        second = _save_month_artifacts(
            session=session,
            run=run,
            artifacts=[_artifact("agri-202106-p001.json", "202106")],
            raw_root=tmp_path,
            now=now,
        )
        assert second[0].id == first_id

    with factory() as session:
        rows = list(
            session.scalars(
                select(RawArtifact).where(RawArtifact.run_id == run_id)
            )
        )
        assert len(rows) == 1
        meta = rows[0].request_meta_json
        assert "agri-202106-p001.json" in meta["shared_with"]
        assert {item["basYm"] for item in meta["shared_requests"]} == {"202106"}

    assert len(list(tmp_path.rglob("agri-202606-p001.json"))) == 1
    assert len(list(tmp_path.rglob("agri-202106-p001.json"))) == 1
