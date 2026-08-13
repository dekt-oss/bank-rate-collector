import json
import sqlite3
from pathlib import Path

from rate_monitor.services.dashboard_service import DATA_END, DATA_MARKER
from rate_monitor.services.site_service import DEFAULT_STRATEGY_TEMPLATE, build_site
from rate_monitor.services.strategy_contract_service import adapt_strategy_template
from tests.test_strategy_dashboard import collected_db


def _inline(html: str) -> dict:
    start = html.find(DATA_MARKER)
    end = html.find(DATA_END, start)
    return json.loads(html[start + len(DATA_MARKER) : end].replace("<\\/", "</"))


def test_strategy_template_adapter_uses_stable_id_and_preference_reference_date() -> None:
    html = adapt_strategy_template(DEFAULT_STRATEGY_TEMPLATE.read_text(encoding="utf-8"))

    assert 'productId:look("product_id"' in html
    assert "const key=r.productId?" in html
    assert "tagLatest:new Map" in html
    assert "latestAt:latest.get(code)||null" in html
    assert '원천 기준일 ${formatDate(topPref.latestAt)}' in html
    assert "최신 공시기준일" not in html


def test_strategy_build_adds_product_id_only_when_strategy_is_built(
    collected_db, tmp_path: Path
) -> None:
    db, _, _ = collected_db

    normal_out = tmp_path / "normal"
    build_site(db, out_dir=normal_out)
    normal_table = json.loads(
        (normal_out / "data/table.json").read_text(encoding="utf-8")
    )
    assert "product_id" not in normal_table["columns"]

    strategy_out = tmp_path / "strategy"
    build_site(
        db,
        out_dir=strategy_out,
        strategy_template_path=DEFAULT_STRATEGY_TEMPLATE,
    )
    strategy_table = json.loads(
        (strategy_out / "data/table.json").read_text(encoding="utf-8")
    )
    assert "product_id" in strategy_table["columns"]
    assert "product_id" in strategy_table["lookups"]
    assert len(strategy_table["rows"]) == len(normal_table["rows"])

    strategy_html = (strategy_out / "strategy.html").read_text(encoding="utf-8")
    inline = _inline(strategy_html)
    assert inline["strategy_table_contract"]["matched"] > 0
    assert inline["strategy_table_contract"]["unmatched"] >= 0


def test_strategy_table_contract_does_not_modify_database(collected_db, tmp_path: Path) -> None:
    db, _, _ = collected_db
    conn = sqlite3.connect(db)
    try:
        before = conn.execute("SELECT COUNT(*) FROM rate_observations").fetchone()[0]
    finally:
        conn.close()

    build_site(
        db,
        out_dir=tmp_path / "strategy",
        strategy_template_path=DEFAULT_STRATEGY_TEMPLATE,
    )

    conn = sqlite3.connect(db)
    try:
        after = conn.execute("SELECT COUNT(*) FROM rate_observations").fetchone()[0]
    finally:
        conn.close()
    assert after == before
