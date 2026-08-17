from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old[:120]
    return text.replace(old, new, 1)


dash = Path("src/rate_monitor/services/dashboard_service.py")
text = dash.read_text(encoding="utf-8")
text = replace_once(
    text,
    "def build_rate_table(\n    conn: sqlite3.Connection, run_ids: list[str]\n) -> dict[str, Any]:",
    "def build_rate_table(\n    conn: sqlite3.Connection, run_ids: list[str], *, include_product_id: bool = False\n) -> dict[str, Any]:",
)
text = replace_once(
    text,
    '        "       p.name                  AS product,"\n        "       p.product_type          AS product_type,"',
    '        "       p.name                  AS product,"\n        "       p.id                    AS product_id,"\n        "       p.product_type          AS product_type,"',
)
text = replace_once(
    text,
    '               "preference_status", "preference_tags")\n    lookups: dict[str, list[Any]] = {name: [] for name in indexed}',
    '               "preference_status", "preference_tags")\n    if include_product_id:\n        indexed = (*indexed, "product_id")\n    output_columns = (\n        *TABLE_COLUMNS, "product_id"\n    ) if include_product_id else TABLE_COLUMNS\n    lookups: dict[str, list[Any]] = {name: [] for name in indexed}',
)
text = replace_once(
    text,
    "        for column in TABLE_COLUMNS:",
    "        for column in output_columns:",
)
text = replace_once(
    text,
    '    return {"columns": list(TABLE_COLUMNS), "lookups": lookups, "rows": rows}',
    '    return {"columns": list(output_columns), "lookups": lookups, "rows": rows}',
)
text = replace_once(
    text,
    "def build_summary(db_path: Path) -> dict[str, Any]:",
    "def build_summary(\n    db_path: Path, *, include_product_id: bool = False\n) -> dict[str, Any]:",
)
text = replace_once(
    text,
    "        table = build_rate_table(conn, run_ids)",
    "        table = build_rate_table(\n            conn, run_ids, include_product_id=include_product_id\n        )",
)
dash.write_text(text, encoding="utf-8")

site = Path("src/rate_monitor/services/site_service.py")
text = site.read_text(encoding="utf-8")
anchor = '''def render(template_text: str, page_data: dict[str, Any]) -> str:\n'''
helper = '''def _without_internal_product_id(table: dict[str, Any]) -> dict[str, Any]:\n    """Strategy build용 stable id를 public canonical table에서 제거한다.\n\n    product_id는 전략 slice가 DB identity를 잃지 않도록 잠시 운반하는 내부 열이다.\n    검색·조회용 ``data/table.json``에는 노출하지 않는다.\n    """\n    columns = list(table.get("columns") or [])\n    if "product_id" not in columns:\n        return table\n    product_id_index = columns.index("product_id")\n    public_columns = [c for c in columns if c != "product_id"]\n    lookups = dict(table.get("lookups") or {})\n    lookups.pop("product_id", None)\n    rows = [\n        [*row[:product_id_index], *row[product_id_index + 1 :]]\n        for row in table.get("rows") or []\n    ]\n    return {**table, "columns": public_columns, "lookups": lookups, "rows": rows}\n\n\n'''
assert text.count(anchor) == 1
text = text.replace(anchor, helper + anchor, 1)
old = '''    summary = build_summary(db_path)\n    page_data, table = split_summary(summary)\n    strategy_table: dict[str, Any] | None = None\n    strategy_table_contract: dict[str, int] | None = None\n    if strategy_template_path is not None:\n        strategy_source = slice_strategy_table(table)\n        strategy_table, strategy_table_contract = augment_strategy_table(\n            db_path, strategy_source\n        )\n'''
new = '''    summary = build_summary(\n        db_path, include_product_id=strategy_template_path is not None\n    )\n    page_data, table_with_internal_id = split_summary(summary)\n    strategy_table: dict[str, Any] | None = None\n    strategy_table_contract: dict[str, int] | None = None\n    if strategy_template_path is not None:\n        strategy_source = slice_strategy_table(table_with_internal_id)\n        strategy_table, strategy_table_contract = augment_strategy_table(\n            db_path, strategy_source\n        )\n    table = _without_internal_product_id(table_with_internal_id)\n'''
text = replace_once(text, old, new)
site.write_text(text, encoding="utf-8")
