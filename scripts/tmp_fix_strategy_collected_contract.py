from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected 1 match, got {count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


service = Path("src/rate_monitor/services/strategy_contract_service.py")
replace_once(
    service,
    'STRATEGY_MAX_RATE_ENABLED_SECTORS = frozenset(STRATEGY_CANDIDATE_SECTORS)\n',
    'STRATEGY_MAX_RATE_ENABLED_SECTORS = frozenset(STRATEGY_CANDIDATE_SECTORS)\n'
    'STRATEGY_SOURCE_MAX_RATE_SECTORS = frozenset({"savings_bank", "cu", "nh_local"})\n',
)
replace_once(
    service,
    '                "max_rate_rows": term_rate_rows,\n',
    '                "max_rate_rows": term_rate_rows,  # compatibility alias\n'
    '                "strategy_rate_rows": term_rate_rows,\n',
)
replace_once(
    service,
    '            "max_rate_capability": True,\n            "strategy_rate_capability": True,\n',
    '            "max_rate_capability": sector in STRATEGY_SOURCE_MAX_RATE_SECTORS,\n'
    '            "strategy_rate_capability": True,\n',
)
replace_once(
    service,
    '            "max_rate_rows": rate_rows,\n',
    '            "max_rate_rows": rate_rows,  # compatibility alias\n'
    '            "strategy_rate_rows": rate_rows,\n',
)

html = Path("web/templates/strategy.html")
replace_once(
    html,
    'Number(t.max_rate_rows||0)',
    'Number(t.strategy_rate_rows??t.max_rate_rows??0)',
)
replace_once(
    html,
    '!meta?.max_rate_capability?"수집 데이터 기준 비교금리 미지원"',
    '!meta?.strategy_rate_capability?"수집 데이터 기준 비교금리 미지원"',
)

page_test = Path("tests/test_strategy_dashboard.py")
replace_once(
    page_test,
    '    assert "product_id" not in canonical["columns"]\n'
    '    assert strategy_table["columns"][-1] == "product_id"\n',
    '    assert "product_id" not in canonical["columns"]\n'
    '    assert "strategy_rate_basis" not in canonical["columns"]\n'
    '    assert "product_id" in strategy_table["columns"]\n'
    '    assert "strategy_rate_basis" in strategy_table["columns"]\n',
)

contract_test = Path("tests/test_strategy_contract_service.py")
replace_once(
    contract_test,
    '    assert sectors["kfcc"]["rate_basis_counts"] == {"collected_base_rate": 1}\n',
    '    assert sectors["kfcc"]["max_rate_capability"] is False\n'
    '    assert sectors["kfcc"]["strategy_rate_capability"] is True\n'
    '    assert sectors["kfcc"]["strategy_rate_rows"] == 1\n'
    '    assert sectors["kfcc"]["rate_basis_counts"] == {"collected_base_rate": 1}\n',
)

smoke = Path("scripts/strategy_preview_smoke.js")
text = smoke.read_text(encoding="utf-8")
smoke.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
