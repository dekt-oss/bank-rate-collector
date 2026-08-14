"""검색 화면을 보존한 채 전략 화면을 병렬 빌드하는 계약."""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.collection_service import collect_source
from rate_monitor.services.dashboard_service import DATA_END, DATA_MARKER
from rate_monitor.services.site_service import (
    DEFAULT_STRATEGY_TEMPLATE,
    STRATEGY_ENABLED_ENV,
    STRATEGY_MAP_FILE,
    build_site,
)
from rate_monitor.services.strategy_service import build_strategy_summary
from tests.test_collection_service import REAL, FixtureAdapter


@pytest.fixture()
def collected_db(tmp_path: Path) -> tuple[Path, object, Path]:
    db = tmp_path / "strategy.sqlite3"
    engine = create_db_engine(db)
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    raw = tmp_path / "raw"
    asyncio.run(
        collect_source(
            FixtureAdapter([REAL]),
            CollectionRequest(source_id="finlife"),
            factory,
            raw_root=raw,
        )
    )
    engine.dispose()
    return db, factory, raw


def _inline(html: str) -> dict:
    start = html.find(DATA_MARKER)
    end = html.find(DATA_END, start)
    return json.loads(html[start + len(DATA_MARKER) : end].replace("<\\/", "</"))


def _bump_max_rate(out: Path, delta: float = 0.20) -> Path:
    payload = json.loads(REAL.read_text(encoding="utf-8"))
    changed = 0
    for option in payload["result"]["optionList"]:
        if option.get("intr_rate2") is not None:
            option["intr_rate2"] = round(float(option["intr_rate2"]) + delta, 2)
            changed += 1
    assert changed > 0
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


def test_strategy_release_gate_is_off_by_default(
    collected_db, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, _, _ = collected_db
    out = tmp_path / "site-public"
    out.mkdir()
    (out / "strategy.html").write_text("stale preview", encoding="utf-8")
    stale_map = out / STRATEGY_MAP_FILE
    stale_map.parent.mkdir(parents=True)
    stale_map.write_text("stale map", encoding="utf-8")
    monkeypatch.delenv(STRATEGY_ENABLED_ENV, raising=False)

    manifest = build_site(db, out_dir=out)
    index_html = (out / "index.html").read_text(encoding="utf-8")

    assert (out / "index.html").exists()
    assert not (out / "strategy.html").exists()
    assert not stale_map.exists()
    assert "strategy.html" not in manifest.files
    assert STRATEGY_MAP_FILE not in manifest.files
    assert 'href="strategy.html"' not in index_html


def test_release_gate_builds_strategy_page_without_replacing_index(
    collected_db, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, _, _ = collected_db
    out = tmp_path / "site-public"
    monkeypatch.setenv(STRATEGY_ENABLED_ENV, "1")
    manifest = build_site(db, out_dir=out)

    assert (out / "index.html").exists()
    assert (out / "strategy.html").exists()
    assert (out / STRATEGY_MAP_FILE).exists()
    assert "index.html" in manifest.files
    assert "strategy.html" in manifest.files
    assert STRATEGY_MAP_FILE in manifest.files

    index_html = (out / "index.html").read_text(encoding="utf-8")
    strategy_html = (out / "strategy.html").read_text(encoding="utf-8")

    assert "전국 예·적금 금리 비교" in index_html
    assert 'href="strategy.html"' in index_html
    assert "수신상품 전략 대시보드" in strategy_html
    assert 'href="./"' in strategy_html
    assert "신상품 기획 시뮬레이터" in strategy_html
    assert "최근 시장 변화" in strategy_html
    assert "우대조건 트렌드" in strategy_html
    assert "기간별 금리 추이" in strategy_html
    assert "시장 인사이트" in strategy_html
    assert 'href="assets/korea-sido.svg"' in strategy_html
    assert 'viewBox="0 0 800 759" role="img"' in strategy_html
    assert 'setAttribute("viewBox","0 0 800 759")' in strategy_html
    assert "M335 31C383" not in strategy_html


def test_strategy_page_reuses_canonical_table_without_inlining_rows(
    collected_db, tmp_path
) -> None:
    db, _, _ = collected_db
    out = tmp_path / "site-public"
    build_site(db, out_dir=out, strategy_template_path=DEFAULT_STRATEGY_TEMPLATE)

    strategy_html = (out / "strategy.html").read_text(encoding="utf-8")
    inline = _inline(strategy_html)

    assert inline["table_url"] == "data/table.json"
    assert "strategy" in inline
    assert "rows" not in inline
    assert '"rows":[[' not in strategy_html
    assert (out / "data" / "table.json").exists()


def test_market_changes_come_from_observation_history(collected_db, tmp_path) -> None:
    db, factory, raw = collected_db
    bumped = _bump_max_rate(tmp_path / "bumped.json")

    asyncio.run(
        collect_source(
            FixtureAdapter([bumped]),
            CollectionRequest(source_id="finlife"),
            factory,
            raw_root=raw,
        )
    )

    summary = build_strategy_summary(db)
    changes = summary["market_changes"]

    assert changes["window_days"] == 30
    assert changes["count"] > 0
    assert changes["up_count"] > 0
    assert changes["down_count"] == 0
    assert changes["affected_variant_count"] >= changes["count"]
    assert changes["items"]
    assert all(item["delta"] > 0 for item in changes["items"])
    assert all(item["term_months"] == 12 for item in changes["items"])
    assert all(item["variant_count"] >= 1 for item in changes["items"])


def test_rate_trend_uses_real_collection_snapshots(collected_db) -> None:
    db, _, _ = collected_db
    trend = build_strategy_summary(db)["rate_trend"]

    assert trend["window_days"] == 63
    assert trend["scope"]["aggregation"] == "product_representative_mean"
    assert trend["points"]
    assert all(point["product_count"] > 0 for point in trend["points"])
    assert all(point["mean_max_rate"] > 0 for point in trend["points"])
    assert all(point["market_max_rate"] >= point["mean_max_rate"] for point in trend["points"])


def test_market_changes_collapse_identical_variant_moves_to_one_product_event(
    tmp_path: Path,
) -> None:
    """같은 run에서 같은 상품의 두 variant가 같이 움직이면 화면은 한 건이다."""
    db = tmp_path / "dedupe.sqlite3"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE institutions (
                id TEXT PRIMARY KEY,
                sector TEXT NOT NULL,
                canonical_name TEXT NOT NULL
            );
            CREATE TABLE products (
                id TEXT PRIMARY KEY,
                institution_id TEXT NOT NULL,
                product_type TEXT NOT NULL,
                name TEXT NOT NULL
            );
            CREATE TABLE product_variants (
                id TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                term_months INTEGER
            );
            CREATE TABLE rate_observations (
                id TEXT PRIMARY KEY,
                variant_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                max_rate REAL,
                validation_status TEXT NOT NULL
            );

            INSERT INTO institutions VALUES ('i1', 'savings_bank', '테스트저축은행');
            INSERT INTO products VALUES ('p1', 'i1', 'term_deposit', '테스트 정기예금');
            INSERT INTO product_variants VALUES ('v1', 'p1', 12);
            INSERT INTO product_variants VALUES ('v2', 'p1', 12);

            INSERT INTO rate_observations
                VALUES ('o1', 'v1', 'run-old', datetime('now', '-2 day'), 3.00, 'valid');
            INSERT INTO rate_observations
                VALUES ('o2', 'v2', 'run-old', datetime('now', '-2 day'), 3.00, 'valid');
            INSERT INTO rate_observations
                VALUES ('o3', 'v1', 'run-new', datetime('now', '-1 day'), 3.20, 'valid');
            INSERT INTO rate_observations
                VALUES ('o4', 'v2', 'run-new', datetime('now', '-1 day'), 3.20, 'valid');
            """
        )
        conn.commit()
    finally:
        conn.close()

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
