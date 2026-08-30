from __future__ import annotations

import json
import sys
from pathlib import Path

from rate_monitor.collectors.data_go_funding import cli


def _identity_payload(mapped: int) -> dict[str, object]:
    return {
        "source_id": "data_go_agri_coop_funding",
        "identity_contract": "exact_brc_plus_normalized_official_source_name",
        "scanned": 10,
        "eligible": 9,
        "mapped": mapped,
        "unchanged": 9 - mapped,
        "no_brc_link": 0,
        "name_mismatch": 0,
        "invalid_link": 0,
    }


def test_collect_reconciles_identity_before_and_after_collection(
    tmp_path: Path, monkeypatch
) -> None:
    db = tmp_path / "db.sqlite3"
    calls: list[str] = []
    payloads = iter([_identity_payload(9), _identity_payload(0)])

    def fake_identity(db_path: Path) -> dict[str, object]:
        assert db_path == db
        calls.append("identity")
        return next(payloads)

    def fake_collect(**kwargs):
        assert kwargs["db_path"] == db
        calls.append("collect")
        return []

    monkeypatch.setattr(cli, "_identity_payload", fake_identity)
    monkeypatch.setattr(cli, "_print_identity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "collect_operational", fake_collect)
    monkeypatch.setattr(
        cli,
        "operational_payload",
        lambda **_kwargs: {"mode": "incremental", "results": []},
    )
    monkeypatch.setattr(cli, "required_failures", lambda _results: [])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "funding-cli",
            "collect",
            "--db",
            str(db),
            "--mode",
            "incremental",
        ],
    )

    assert cli.main() == 0
    assert calls == ["identity", "collect", "identity"]


def test_standalone_identity_reconciliation_writes_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    db = tmp_path / "db.sqlite3"
    out = tmp_path / "identity.json"
    payload = _identity_payload(9)
    monkeypatch.setattr(cli, "_identity_payload", lambda _db: payload)
    monkeypatch.setattr(cli, "_print_identity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "funding-cli",
            "reconcile-nh-identity",
            "--db",
            str(db),
            "--json",
            str(out),
        ],
    )

    assert cli.main() == 0
    assert json.loads(out.read_text(encoding="utf-8")) == payload
