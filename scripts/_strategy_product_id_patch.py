from pathlib import Path


def replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old[:120]
    return text.replace(old, new, 1)


dash = Path("src/rate_monitor/services/dashboard_service.py")
text = dash.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    if not run_ids:\n        return {"columns": list(TABLE_COLUMNS), "lookups": {}, "rows": []}\n\n    placeholders = ",".join("?" for _ in run_ids)''',
    '''    output_columns = (\n        *TABLE_COLUMNS, "product_id"\n    ) if include_product_id else TABLE_COLUMNS\n    if not run_ids:\n        return {"columns": list(output_columns), "lookups": {}, "rows": []}\n\n    placeholders = ",".join("?" for _ in run_ids)''',
)
text = replace_once(
    text,
    '''    if include_product_id:\n        indexed = (*indexed, "product_id")\n    output_columns = (\n        *TABLE_COLUMNS, "product_id"\n    ) if include_product_id else TABLE_COLUMNS\n    lookups: dict[str, list[Any]] = {name: [] for name in indexed}''',
    '''    if include_product_id:\n        indexed = (*indexed, "product_id")\n    lookups: dict[str, list[Any]] = {name: [] for name in indexed}''',
)
dash.write_text(text, encoding="utf-8")

site = Path("src/rate_monitor/services/site_service.py")
text = site.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    summary = build_summary(\n        db_path, include_product_id=strategy_template_path is not None\n    )\n    page_data, table_with_internal_id = split_summary(summary)''',
    '''    summary = (\n        build_summary(db_path, include_product_id=True)\n        if strategy_template_path is not None\n        else build_summary(db_path)\n    )\n    page_data, table_with_internal_id = split_summary(summary)''',
)
site.write_text(text, encoding="utf-8")
