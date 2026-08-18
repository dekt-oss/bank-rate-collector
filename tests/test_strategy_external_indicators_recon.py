"""Stage E0 ECOS discovery probe contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/e0_strategy_external_indicators_recon.py"
WORKFLOW = ROOT / ".github/workflows/e0-strategy-ecos-recon.yml"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("strategy_ecos_recon", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_targets_find_expected_table_names_without_codes() -> None:
    module = _load_script()
    rows = [
        {"STAT_CODE": "A", "STAT_NAME": "예금은행 여수신 금리", "CYCLE": "M"},
        {"STAT_CODE": "B", "STAT_NAME": "비은행금융기관 기관별 수신", "CYCLE": "M"},
        {"STAT_CODE": "C", "STAT_NAME": "소비자물가지수", "CYCLE": "M"},
    ]

    bank = next(target for target in module.TARGETS if target.name == "bank_deposit_rate")
    nonbank = next(
        target for target in module.TARGETS if target.name == "nonbank_deposit_balance"
    )

    assert [row["STAT_CODE"] for row in module.candidate_tables(rows, bank)] == ["A"]
    assert [row["STAT_CODE"] for row in module.candidate_tables(rows, nonbank)] == ["B"]


def test_item_discovery_keeps_sector_candidates_separate() -> None:
    module = _load_script()
    target = next(
        target for target in module.TARGETS if target.name == "nonbank_deposit_balance"
    )
    rows = [
        {"ITEM_CODE": "1", "ITEM_NAME": "상호저축은행"},
        {"ITEM_CODE": "2", "ITEM_NAME": "신용협동조합"},
        {"ITEM_CODE": "3", "ITEM_NAME": "새마을금고"},
        {"ITEM_CODE": "4", "ITEM_NAME": "보험회사"},
    ]

    hits = module.candidate_items(rows, target)

    assert {row["ITEM_CODE"] for row in hits} == {"1", "2", "3"}


def test_mask_removes_ecos_key_from_persisted_text() -> None:
    module = _load_script()
    key = "secret-key"
    url = f"https://ecos.bok.or.kr/api/StatisticTableList/{key}/json/kr/1/1000"

    masked = module._mask(url, key)

    assert key not in masked
    assert "[REDACTED]" in masked


def test_probe_is_discovery_only_and_never_queries_statistic_search() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "StatisticTableList" in source
    assert "StatisticItemList" in source
    assert "StatisticSearch/" not in source
    assert "discovery_only_no_statistic_search" in source


def test_workflow_is_manual_read_only_and_checks_secret_leak() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in source
    assert "contents: read" in source
    assert "ECOS_API_KEY: ${{ secrets.ECOS_API_KEY }}" in source
    assert "e0_strategy_external_indicators_recon.py" in source
    assert "grep -qF \"$ECOS_API_KEY\"" in source
    assert "strategy-external-indicators-recon.json" in source
