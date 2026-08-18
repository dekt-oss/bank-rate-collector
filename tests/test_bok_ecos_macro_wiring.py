"""Stage E0-3 `bok_ecos_macro` production wiring."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rate_monitor.collectors.bok_ecos import macro_cli

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/collect.yml"


def test_macro_cli_uses_its_own_indicator_source(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class FakeAdapter:
        source_id = "bok_ecos_macro"

    async def fake_collect(adapter, request, factory, *, raw_root):  # noqa: ANN001
        captured.update(
            adapter=adapter,
            request=request,
            factory=factory,
            raw_root=raw_root,
        )
        return SimpleNamespace(
            run_id="run",
            status="success",
            fetched=7,
            parsed=21,
            stored=21,
            unchanged=0,
            warnings=0,
            message="ok",
        )

    monkeypatch.setattr(macro_cli, "BokEcosMacroAdapter", FakeAdapter)
    monkeypatch.setattr(macro_cli, "create_db_engine", lambda path: ("engine", path))
    monkeypatch.setattr(macro_cli, "make_session_factory", lambda engine: ("factory", engine))
    monkeypatch.setattr(macro_cli, "collect_indicator", fake_collect)

    db = tmp_path / "db.sqlite3"
    raw = tmp_path / "raw"
    code = macro_cli.main(["--db", str(db), "--raw-root", str(raw)])

    assert code == 0
    assert captured["request"].source_id == "bok_ecos_macro"
    assert captured["raw_root"] == raw


def test_collect_workflow_keeps_base_rate_and_macro_runs_separate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    base_step = "- name: Collect BOK base rate"
    macro_step = "- name: Collect BOK deposit macro indicators"
    macro_command = "uv run python -m rate_monitor.collectors.bok_ecos.macro_cli"

    assert base_step in source
    assert macro_step in source
    assert macro_command in source
    assert source.index(base_step) < source.index(macro_step) < source.index("- name: Collect FSB")
    assert source.count("--source bok_ecos \\") == 1


def test_macro_wiring_uses_reference_only_or_general_collection_gate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index("- name: Collect BOK deposit macro indicators")
    end = source.index("- name: Collect FSB", start)
    block = source[start:end]

    assert "env.PUBLISH_ONLY != 'true'" in block
    assert "env.KFCC_ONLY != 'true'" in block
    assert "inputs.manual_target == '일반 전체'" in block
    assert "inputs.manual_target == '참고지표만'" in block
    assert "continue-on-error: true" in block
    assert "ECOS_API_KEY: ${{ secrets.ECOS_API_KEY }}" in block
    assert "--db work/rate_monitor.sqlite3" in block
    assert "--raw-root data/raw" in block


def test_main_push_still_publishes_only_and_does_not_collect_macro() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "PUBLISH_ONLY: ${{ github.event_name == 'push'" in source
    assert "# main 머지는 원천을 다시 긁지 않고 화면만 재발행한다." in source
