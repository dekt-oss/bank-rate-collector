from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from rate_monitor.db.migrate import upgrade
from rate_monitor.db.models import CollectionRun, Institution, Product, ProductVariant, Source
from rate_monitor.db.session import create_session_factory
from rate_monitor.domain.enums import ProductType, RunStatus, Sector
from rate_monitor.services.site_service import (
    DEFAULT_STRATEGY_TEMPLATE,
    STRATEGY_ENABLED_ENV,
    build_site,
    strategy_dashboard_enabled,
)
from rate_monitor.services.strategy_service import build_strategy_summary


def test_strategy_dashboard_enabled_is_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv(STRATEGY_ENABLED_ENV, raising=False)
    assert strategy_dashboard_enabled() is False

    for value in ("0", "false", "off", "no", "unexpected", ""):
        monkeypatch.setenv(STRATEGY_ENABLED_ENV, value)
        assert strategy_dashboard_enabled() is False

    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv(STRATEGY_ENABLED_ENV, value)
        assert strategy_dashboard_enabled() is True


def test_strategy_dashboard_is_hidden_when_gate_is_off(collected_db, tmp_path, monkeypatch) -> None:
    db, _, _ = collected_db
    out = tmp_path / "site-public"
    monkeypatch.delenv(STRATEGY_ENABLED_ENV, raising=False)

    build_site(db, out_dir=out)

    assert not (out / "strategy.html").exists()
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "strategy.html" not in index
    assert "전략 대시보드" not in index


def test_strategy_dashboard_removes_stale_file_when_gate_turns_off(
    collected_db, tmp_path, monkeypatch
) -> None:
    db, _, _ = collected_db
    out = tmp_path / "site-public"
    monkeypatch.setenv(STRATEGY_ENABLED_ENV, "1")
    build_site(db, out_dir=out)
    assert (out / "strategy.html").exists()

    monkeypatch.delenv(STRATEGY_ENABLED_ENV, raising=False)
    build_site(db, out_dir=out)

    assert not (out / "strategy.html").exists()
    assert "strategy.html" not in (out / "index.html").read_text(encoding="utf-8")


def test_strategy_dashboard_builds_with_explicit_template_path(collected_db, tmp_path) -> None:
    db, _, _ = collected_db
    out = tmp_path / "site-public"

    build_site(db, out_dir=out, strategy_template_path=DEFAULT_STRATEGY_TEMPLATE)

    strategy = (out / "strategy.html").read_text(encoding="utf-8")
    index = (out / "index.html").read_text(encoding="utf-8")
    payload = _strategy_payload(strategy)

    assert "수신상품 전략 대시보드" in strategy
    assert "strategy.html" in index
    assert payload["strategy"]["market_changes"]["scope"]["rate_field"] == "max_rate"
    assert payload["strategy"]["rate_trend"]["scope"]["aggregation"] == (
        "product_representative_mean"
    )


def test_strategy_dashboard_builds_when_release_gate_is_on(
    collected_db, tmp_path, monkeypatch
) -> None:
    db, _, _ = collected_db
    out = tmp_path / "site-public"
    monkeypatch.setenv(STRATEGY_ENABLED_ENV, "true")

    build_site(db, out_dir=out)

    assert (out / "strategy.html").exists()
    assert "strategy.html" in (out / "index.html").read_text(encoding="utf-8")


def _strategy_payload(html: str) -> dict:
    marker = '<script id="rate-monitor-data" type="application/json">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end].replace("<\\/", "</"))


def _minimal_strategy_db(tmp_path: Path) -> Path:
    db = tmp_path / "strategy-dedupe.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sources (
          id TEXT PRIMARY KEY,
          sector TEXT NOT NULL
        );
        CREATE TABLE collection_runs (
          id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          status TEXT NOT NULL
        );
        CREATE TABLE institutions (
          id INTEGER PRIMARY KEY,
          canonical_name TEXT NOT NULL,
          sector TEXT NOT NULL
        );
        CREATE TABLE products (
          id INTEGER PRIMARY KEY,
          institution_id INTEGER NOT NULL,
          name TEXT NOT NULL,
          product_type TEXT NOT NULL
        );
        CREATE TABLE product_variants (
          id INTEGER PRIMARY KEY,
          product_id INTEGER NOT NULL,
          term_months INTEGER
        );
        CREATE TABLE rate_observations (
          id INTEGER PRIMARY KEY,
          variant_id INTEGER NOT NULL,
          run_id TEXT NOT NULL,
          valid_from TEXT NOT NULL,
          valid_to TEXT,
          max_rate REAL,
          validation_status TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO sources VALUES ('fsb', 'savings_bank')")
    conn.execute(
        "INSERT INTO institutions VALUES (1, '테스트저축은행', 'savings_bank')"
    )
    conn.execute("INSERT INTO products VALUES (1, 1, '테스트예금', 'term_deposit')")
    conn.executemany(
        "INSERT INTO product_variants VALUES (?, 1, 12)", [(101,), (102,)]
    )
    conn.executemany(
        "INSERT INTO collection_runs VALUES (?, 'fsb', ?, ?, 'success')",
        [
            ("run-0", "2026-08-01T00:00:00", "2026-08-01T00:01:00"),
            ("run-1", "2026-08-02T00:00:00", "2026-08-02T00:01:00"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO rate_observations
          (variant_id, run_id, valid_from, valid_to, max_rate, validation_status)
        VALUES (?, ?, ?, ?, ?, 'valid')
        """,
        [
            (101, "run-0", "2026-08-01T00:01:00", "2026-08-02T00:01:00", 3.0),
            (102, "run-0", "2026-08-01T00:01:00", "2026-08-02T00:01:00", 3.0),
            (101, "run-1", "2026-08-02T00:01:00", None, 3.2),
            (102, "run-1", "2026-08-02T00:01:00", None, 3.2),
        ],
    )
    conn.commit()
    conn.close()
    return db


def test_market_change_groups_same_product_variant_transition(tmp_path) -> None:
    db = _minimal_strategy_db(tmp_path)

    summary = build_strategy_summary(db)
    changes = summary["market_changes"]

    assert changes["count"] == 1
    assert changes["up_count"] == 1
    assert changes["down_count"] == 0
    assert changes["affected_variant_count"] == 2
    assert len(changes["items"]) == 1
    assert changes["items"][0]["variant_count"] == 2
    assert changes["items"][0]["previous_max_rate"] == 3.0
    assert changes["items"][0]["max_rate"] == 3.2
    assert summary["rate_trend"]["points"] == []


def test_rate_trend_restores_snapshots_and_our_bank_line(tmp_path) -> None:
    db = tmp_path / "strategy-trend.sqlite3"
    upgrade(db)
    session_factory = create_session_factory(db)

    with session_factory() as session:
        source = Source(
            id="fsb",
            sector=Sector.SAVINGS_BANK.value,
            name="저축은행중앙회",
            adapter="fsb",
        )
        session.add(source)
        our = Institution(canonical_name="고려저축은행", sector=Sector.SAVINGS_BANK.value)
        market = Institution(canonical_name="시장저축은행", sector=Sector.SAVINGS_BANK.value)
        session.add_all([our, market])
        session.flush()
        our_product = Product(
            institution_id=our.id,
            name="우리예금",
            product_type=ProductType.TERM_DEPOSIT.value,
        )
        market_product = Product(
            institution_id=market.id,
            name="시장예금",
            product_type=ProductType.TERM_DEPOSIT.value,
        )
        session.add_all([our_product, market_product])
        session.flush()
        our_variant = ProductVariant(product_id=our_product.id, term_months=12)
        market_variant = ProductVariant(product_id=market_product.id, term_months=12)
        session.add_all([our_variant, market_variant])
        session.flush()
        run1 = CollectionRun(
            id="run-1",
            source_id="fsb",
            started_at="2026-08-01T00:00:00",
            finished_at="2026-08-01T00:01:00",
            status=RunStatus.SUCCESS.value,
        )
        run2 = CollectionRun(
            id="run-2",
            source_id="fsb",
            started_at="2026-08-02T00:00:00",
            finished_at="2026-08-02T00:01:00",
            status=RunStatus.SUCCESS.value,
        )
        session.add_all([run1, run2])
        session.commit()

    conn = sqlite3.connect(db)
    conn.executemany(
        """
        INSERT INTO rate_observations
          (variant_id, run_id, valid_from, valid_to, max_rate, validation_status)
        VALUES (?, ?, ?, ?, ?, 'valid')
        """,
        [
            (our_variant.id, "run-1", "2026-08-01T00:01:00", "2026-08-02T00:01:00", 3.5),
            (market_variant.id, "run-1", "2026-08-01T00:01:00", "2026-08-02T00:01:00", 4.0),
            (our_variant.id, "run-2", "2026-08-02T00:01:00", None, 3.6),
            (market_variant.id, "run-2", "2026-08-02T00:01:00", None, 4.1),
        ],
    )
    conn.commit()
    conn.close()

    summary = build_strategy_summary(db)
    points = summary["rate_trend"]["points"]
    assert len(points) == 2
    assert points[0]["market_max_rate"] == 4.0
    assert points[0]["mean_max_rate"] == 3.75
    assert points[0]["our_company_max_rate"] == 3.5
    assert points[1]["market_max_rate"] == 4.1
    assert points[1]["mean_max_rate"] == 3.85
    assert points[1]["our_company_max_rate"] == 3.6


def test_inflow_ui_requires_explicit_assumptions_and_never_claims_prediction(
    collected_db, tmp_path
) -> None:
    db, _, _ = collected_db
    out = tmp_path / "site-public"
    build_site(db, out_dir=out, strategy_template_path=DEFAULT_STRATEGY_TEMPLATE)
    strategy_html = (out / "strategy.html").read_text(encoding="utf-8")

    assert "가정 기반 예상 월 수신액" in strategy_html
    assert "가정 입력 필요" in strategy_html
    assert "내부 실적 기반 예측모형이 아닙니다" in strategy_html
    assert "실제 유입을 보장하지 않습니다" in strategy_html
    assert 'baselineRaw!==""' in strategy_html
    assert 'sensitivityRaw!==""' in strategy_html


def test_simulator_term_buttons_and_actual_term_summary_are_present(
    collected_db, tmp_path
) -> None:
    db, _, _ = collected_db
    out = tmp_path / "site-public"
    build_site(db, out_dir=out, strategy_template_path=DEFAULT_STRATEGY_TEMPLATE)
    strategy_html = (out / "strategy.html").read_text(encoding="utf-8")

    for term in (6, 12, 24, 36):
        assert f'data-term="{term}"' in strategy_html
        assert f"{term}개월 평균" in strategy_html
    assert "aggregateProducts(simTerm)" in strategy_html
