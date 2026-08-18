import sqlite3

from rate_monitor.services import market_intelligence_service as service


def test_build_market_intelligence_restores_connection_row_factory(monkeypatch):
    conn = sqlite3.connect(":memory:")
    assert conn.row_factory is None

    monkeypatch.setattr(service, "_table_exists", lambda _conn, _table: True)
    monkeypatch.setattr(
        service,
        "_column_exists",
        lambda _conn, _table, _column: True,
    )
    monkeypatch.setattr(service, "_sector_run_times", lambda _conn, _sector: [])

    result = service.build_market_intelligence(conn)

    assert result["status"] == "insufficient_history"
    assert conn.row_factory is None
