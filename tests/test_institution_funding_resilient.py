from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from rate_monitor.collectors.data_go_funding import resilient as rz
from rate_monitor.collectors.data_go_funding.collector import (
    CONTRACTS,
    FundingTransportError,
)
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.schemas import RawArtifactData


def _contract():
    return next(contract for contract in CONTRACTS if contract.sector == "savings_bank")


def _prepare_db(path: Path) -> None:
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)


def _rows(bas_ym: str, amount: str) -> list[dict[str, str]]:
    return [
        {
            "basYm": bas_ym,
            "fncoCd": f"001{bas_ym[-3:]}",
            "fncoNm": f"테스트저축은행-{bas_ym}",
            "crno": "",
            "dpsdbtDcd": "A11",
            "dpsdbtDcdNm": "예수부채",
            "dpsdbtClsfAmt": amount,
        }
    ]


def _artifact(bas_ym: str) -> RawArtifactData:
    raw = ("{" + f'"basYm":"{bas_ym}"' + "}").encode()
    return RawArtifactData(
        artifact_type="json",
        content=raw,
        filename=f"{bas_ym}.json",
        request_meta={"basYm": bas_ym},
        schema_fingerprint=bas_ym,
        source_role="secondary_official",
        trust_level="official_direct",
    )


def test_source_month_checkpoint_recovers_only_failed_month(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite3"
    raw_root = tmp_path / "raw"
    _prepare_db(db_path)
    calls: dict[str, int] = {}

    monkeypatch.setattr(
        rz,
        "candidate_months",
        lambda *_args, **_kwargs: ["202606", "202603"],
    )
    monkeypatch.setattr(rz, "_service_key", lambda _contract: "key")

    def fake_fetch(_client, *, bas_ym, **_kwargs):
        calls[bas_ym] = calls.get(bas_ym, 0) + 1
        if bas_ym == "202606" and calls[bas_ym] == 1:
            raise FundingTransportError("timeout")
        return _rows(bas_ym, "1000000"), [_artifact(bas_ym)]

    monkeypatch.setattr(rz, "_fetch_month", fake_fetch)

    result = rz.collect_source_resilient(
        _contract(),
        db_path=db_path,
        raw_root=raw_root,
        periods=2,
        required=True,
    )

    assert result.status == "success"
    assert result.completed_months == ("202606", "202603")
    assert result.failed_months == ()
    assert result.retry_recovered_months == ("202606",)
    assert calls == {"202606": 2, "202603": 1}

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        observations = session.scalar(
            select(func.count()).select_from(InstitutionFundingObservation)
        )
        artifacts = session.scalar(select(func.count()).select_from(m.RawArtifact))
    assert observations == 2
    assert artifacts == 2


def test_source_month_checkpoint_preserves_success_when_other_month_fails(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "db.sqlite3"
    raw_root = tmp_path / "raw"
    _prepare_db(db_path)

    monkeypatch.setattr(
        rz,
        "candidate_months",
        lambda *_args, **_kwargs: ["202606", "202603"],
    )
    monkeypatch.setattr(rz, "_service_key", lambda _contract: "key")

    def fake_fetch(_client, *, bas_ym, **_kwargs):
        if bas_ym == "202606":
            raise FundingTransportError("timeout")
        return _rows(bas_ym, "2000000"), [_artifact(bas_ym)]

    monkeypatch.setattr(rz, "_fetch_month", fake_fetch)

    result = rz.collect_source_resilient(
        _contract(),
        db_path=db_path,
        raw_root=raw_root,
        periods=2,
        required=True,
    )

    assert result.status == "partial"
    assert result.completed_months == ("202603",)
    assert result.failed_months == ("202606",)
    assert rz.required_failures([result]) == [result]

    engine = create_db_engine(db_path)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        rows = list(session.scalars(select(InstitutionFundingObservation)))
        runs = list(session.scalars(select(m.CollectionRun)))
    assert len(rows) == 1
    assert rows[0].source_effective_month == "2026-03"
    assert runs[-1].status == "partial"


def test_requested_month_mismatch_fails_closed():
    try:
        rz._validate_requested_month(_rows("202603", "1000000"), "202606")
    except rz.FundingContractError as exc:
        assert "basYm 필터 계약 불일치" in str(exc)
    else:
        raise AssertionError("mismatched basYm must fail closed")
