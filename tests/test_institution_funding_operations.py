from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import httpx

from rate_monitor.collectors.data_go_funding import operations as ops
from rate_monitor.collectors.data_go_funding.collector import CONTRACTS
from rate_monitor.db import models as m
from rate_monitor.db.institution_funding_models import InstitutionFundingObservation
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope


def _contract(sector: str):
    return next(contract for contract in CONTRACTS if contract.sector == sector)


def test_operational_period_plans_cover_one_and_six_years():
    assert ops.periods_for_mode("incremental", "savings_bank") == 4
    assert ops.periods_for_mode("incremental", "cu") == 4
    assert ops.periods_for_mode("incremental", "nh_local") == 2
    assert ops.periods_for_mode("backfill", "savings_bank") == 24
    assert ops.periods_for_mode("backfill", "cu") == 24
    assert ops.periods_for_mode("backfill", "nh_local") == 12
    assert ops.periods_for_mode("custom", "savings_bank", 7) == 7


def test_transport_preflight_retries_transient_timeout_with_fresh_clients(monkeypatch):
    created = 0

    class Client:
        def __init__(self, *args, **kwargs):
            nonlocal created
            created += 1
            self.number = created

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, endpoint, *, params):
            request = httpx.Request("GET", endpoint, params=params)
            if self.number == 1:
                raise httpx.ReadTimeout("timeout", request=request)
            return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(ops, "_service_key", lambda _contract: "key")
    monkeypatch.setattr(ops.httpx, "Client", Client)
    monkeypatch.setattr(ops.time, "sleep", lambda _seconds: None)

    reachable, message = ops._transport_preflight(_contract("nh_local"))

    assert reachable is True
    assert created == 2
    assert "attempt=2/3" in message


def test_transport_preflight_exhausts_bounded_transient_retries(monkeypatch):
    created = 0

    class Client:
        def __init__(self, *args, **kwargs):
            nonlocal created
            created += 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, endpoint, *, params):
            request = httpx.Request("GET", endpoint, params=params)
            raise httpx.ConnectTimeout("timeout", request=request)

    monkeypatch.setattr(ops, "_service_key", lambda _contract: "key")
    monkeypatch.setattr(ops.httpx, "Client", Client)
    monkeypatch.setattr(ops.time, "sleep", lambda _seconds: None)

    reachable, message = ops._transport_preflight(_contract("savings_bank"))

    assert reachable is False
    assert created == ops.PREFLIGHT_ATTEMPTS == 3
    assert "retry exhausted" in message
    assert "ConnectTimeout" in message


def test_transport_preflight_does_not_retry_hard_4xx(monkeypatch):
    created = 0

    class Client:
        def __init__(self, *args, **kwargs):
            nonlocal created
            created += 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, endpoint, *, params):
            request = httpx.Request("GET", endpoint, params=params)
            return httpx.Response(401, json={"error": "bad key"}, request=request)

    monkeypatch.setattr(ops, "_service_key", lambda _contract: "key")
    monkeypatch.setattr(ops.httpx, "Client", Client)
    monkeypatch.setattr(ops.time, "sleep", lambda _seconds: None)

    reachable, message = ops._transport_preflight(_contract("savings_bank"))

    assert reachable is False
    assert created == 1
    assert "rejected status=401" in message
    assert "attempt=1/3" in message


def test_unknown_credit_union_finance_endpoint_skips_fanout():
    reachable, message = ops._transport_preflight(_contract("cu"))
    assert reachable is False
    assert "exact finance endpoint" in message


def test_coverage_summary_reports_historical_span(tmp_path):
    db_path = tmp_path / "db.sqlite3"
    engine = create_db_engine(db_path)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 8, 28, 6, 0, 0)

    with session_scope(factory) as session:
        source = m.Source(
            id="data_go_savings_bank_funding",
            name="funding",
            sector="savings_bank",
            mode="api",
            source_role="secondary_official",
            trust_level="official_direct",
            priority=40,
            enabled=True,
            policy_status="approved",
            coverage_status="partial",
            parser_version="1",
            created_at=now,
            updated_at=now,
        )
        session.add(source)
        run = m.CollectionRun(
            source_id=source.id,
            mode="api",
            started_at=now,
            status="success",
        )
        session.add(run)
        session.flush()
        raw = m.RawArtifact(
            run_id=run.id,
            artifact_type="json",
            relative_path="data/raw/history.json",
            sha256="c" * 64,
            content_length=2,
            captured_at=now,
        )
        session.add(raw)
        session.flush()
        for month, end in (
            ("2025-06", date(2025, 6, 30)),
            ("2026-06", date(2026, 6, 30)),
        ):
            session.add(
                InstitutionFundingObservation(
                    institution_id=None,
                    source_id=source.id,
                    source_institution_key="0010345",
                    source_institution_name="테스트저축은행",
                    sector="savings_bank",
                    metric_code="deposit_liabilities_total",
                    metric_name="예수부채",
                    source_effective_month=month,
                    period_start=date(end.year, end.month, 1),
                    period_end=end,
                    value=Decimal("1000000.000000"),
                    unit="million_krw",
                    source_value_text="1000000000000",
                    source_unit="krw",
                    observation_basis="reported_period_end",
                    statement_basis="source_reported_unspecified",
                    population_scope="savings_banks_all_source_reported",
                    identity_status="unmapped_no_exact_cross_source_code",
                    observed_at=now,
                    source_locator="https://example.test",
                    raw_artifact_id=raw.id,
                    content_hash=f"sha256:{month.replace('-', ''):0<64}"[:71],
                    revision=1,
                    valid_from=now,
                    valid_to=None,
                    created_at=now,
                )
            )

    summary = ops.coverage_summary(db_path)
    assert summary == {
        "sources": [
            {
                "source_id": "data_go_savings_bank_funding",
                "earliest_month": "2025-06",
                "latest_month": "2026-06",
                "reporting_months": 2,
                "institutions": 1,
                "active_observations": 2,
            }
        ]
    }
