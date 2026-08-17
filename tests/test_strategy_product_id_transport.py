"""Strategy stable product_id는 내부로만 운반하고 public table 계약은 유지한다."""

import json
from pathlib import Path

from rate_monitor.services.site_service import DEFAULT_STRATEGY_TEMPLATE, TABLE_FILE, build_site
from tests.test_site_service import TEMPLATE, db as site_db  # noqa: F401


def test_strategy_gate_keeps_public_table_bytes_identical(
    site_db: Path, tmp_path: Path
) -> None:
    off = tmp_path / "off"
    on = tmp_path / "on"

    build_site(site_db, TEMPLATE, off)
    build_site(
        site_db,
        TEMPLATE,
        on,
        strategy_template_path=DEFAULT_STRATEGY_TEMPLATE,
    )

    assert (off / TABLE_FILE).read_bytes() == (on / TABLE_FILE).read_bytes()

    public = json.loads((on / TABLE_FILE).read_text(encoding="utf-8"))
    strategy = json.loads(
        (on / "data/strategy-table.json").read_text(encoding="utf-8")
    )
    assert "product_id" not in public["columns"]
    assert "product_id" not in public["lookups"]
    assert "product_id" in strategy["columns"]
    assert "product_id" in strategy["lookups"]
    product_id_index = strategy["columns"].index("product_id")
    assert strategy["rows"]
    assert all(row[product_id_index] is not None for row in strategy["rows"])
