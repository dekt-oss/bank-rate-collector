"""Stage E0-2 exact ECOS series probe contracts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/e0_strategy_external_indicator_series_probe.py"
WORKFLOW = ROOT / ".github/workflows/e0-strategy-ecos-recon.yml"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("strategy_ecos_series_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_series_codes_match_trusted_discovery_evidence() -> None:
    module = _load_script()
    specs = {spec.key: spec for spec in module.SERIES}

    assert specs["bank_savings_deposit_rate"].stat_code == "121Y002"
    assert specs["bank_savings_deposit_rate"].item_code == "BEABAA2"
    assert specs["bank_savings_deposit_rate_ex_financial_bonds"].item_code == "BEABAA1"
    assert specs["bank_pure_savings_deposit_rate"].item_code == "BEABAA21"
    assert specs["bank_term_deposit_1y_rate"].item_code == "BEABAA2118"

    assert specs["savings_bank_deposit_balance"].stat_code == "111Y007"
    assert specs["savings_bank_deposit_balance"].item_code == "1120600"
    assert specs["credit_union_deposit_balance"].item_code == "1120700"
    assert specs["broad_mutual_finance_deposit_balance"].item_code == "1120800"
    assert specs["kfcc_deposit_balance"].item_code == "1121000"


def test_broad_mutual_finance_is_not_labelled_nh_local_one_to_one() -> None:
    module = _load_script()
    spec = next(
        item for item in module.SERIES if item.key == "broad_mutual_finance_deposit_balance"
    )

    assert spec.expected_name == "상호금융"
    assert spec.role == "broad_sector_balance_not_nh_local_1to1"


def test_row_validation_checks_identity_unit_and_month() -> None:
    module = _load_script()
    spec = next(item for item in module.SERIES if item.key == "bank_term_deposit_1y_rate")
    valid = {
        "STAT_CODE": "121Y002",
        "ITEM_CODE1": "BEABAA2118",
        "ITEM_NAME1": "정기예금(1년)",
        "UNIT_NAME": "연리%",
        "TIME": "202606",
        "DATA_VALUE": "2.80",
    }

    assert module.validate_rows(spec, [valid]) == []

    invalid = {**valid, "UNIT_NAME": "십억원", "TIME": "2026Q2"}
    warnings = module.validate_rows(spec, [invalid])
    assert any("UNIT_NAME" in warning for warning in warnings)
    assert any("monthly TIME" in warning for warning in warnings)


def test_probe_orders_months_instead_of_trusting_api_order() -> None:
    module = _load_script()
    rows = [{"TIME": "202606"}, {"TIME": "202301"}, {"TIME": "202512"}]

    ordered = module._ordered_rows(rows)

    assert [row["TIME"] for row in ordered] == ["202301", "202512", "202606"]


def test_series_probe_is_read_only_and_has_no_storage_path() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "StatisticSearch/" in source
    assert "market_indicators" not in source
    assert "sqlite" not in source.lower()
    assert "production DB" in source
    assert "evidence_run" in source
    assert "32135388199" in source


def test_workflow_runs_discovery_then_exact_series_probe() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    discovery = "uv run python scripts/e0_strategy_external_indicators_recon.py"
    series = "uv run python scripts/e0_strategy_external_indicator_series_probe.py"
    assert discovery in source
    assert series in source
    assert source.index(discovery) < source.index(series)
    assert "strategy-external-indicator-series-probe.json" in source
    assert "statuses: write" in source
    assert "context=strategy-ecos-recon" in source
