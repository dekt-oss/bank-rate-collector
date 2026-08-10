"""부분 수집 게이트의 current-run 경계를 고정한다 (stabilization v1 P0-1)."""

import importlib.util
import sqlite3
from pathlib import Path


def _gate_module():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_gate.py'
    spec = importlib.util.spec_from_file_location('verify_gate_for_test', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(':memory:')
    conn.execute(
        'CREATE TABLE collection_runs ('
        'id TEXT PRIMARY KEY, source_id TEXT NOT NULL, status TEXT NOT NULL)'
    )
    conn.execute(
        'CREATE TABLE rate_observations ('
        'run_id TEXT NOT NULL, last_run_id TEXT NOT NULL, max_rate TEXT)'
    )
    return conn


def test_kfcc_only_workspace_does_not_select_historical_finlife(tmp_path: Path) -> None:
    """KFCC-only raw가 과거 finlife 관측을 current-run 검사로 끌어오면 안 된다."""
    gate = _gate_module()
    conn = _db()
    conn.executemany(
        'INSERT INTO collection_runs VALUES (?, ?, ?)',
        [
            ('old-finlife', 'finlife_savings_bank', 'success'),
            ('current-kfcc', 'kfcc', 'success'),
        ],
    )
    run_dir = tmp_path / '20260810_0600' / 'current-kfcc'
    run_dir.mkdir(parents=True)
    (run_dir / 'deposit.html').write_text('<html></html>', encoding='utf-8')

    files, runs, missing = gate._workspace_run_context(conn, tmp_path)

    assert len(files) == 1
    assert missing == []
    assert runs == [('current-kfcc', 'kfcc', 'success')]
    assert not [run for run in runs if run[1].startswith('finlife')]


def test_workspace_run_directory_must_exist_in_collection_runs(tmp_path: Path) -> None:
    """러너의 raw run_id를 DB에서 못 찾으면 조용히 current-run으로 인정하지 않는다."""
    gate = _gate_module()
    conn = _db()
    run_dir = tmp_path / '20260810_0600' / 'unknown-run'
    run_dir.mkdir(parents=True)
    (run_dir / 'deposit.html').write_text('<html></html>', encoding='utf-8')

    _, runs, missing = gate._workspace_run_context(conn, tmp_path)

    assert runs == []
    assert missing == ['unknown-run']


def test_finlife_current_state_uses_last_run_id_for_change_only_history() -> None:
    """안 바뀐 금리는 run_id가 옛 실행이어도 last_run_id가 현재 실행으로 움직인다."""
    gate = _gate_module()
    conn = _db()
    conn.executemany(
        'INSERT INTO rate_observations VALUES (?, ?, ?)',
        [
            ('first-seen-run', 'current-finlife', None),
            ('old-run', 'old-run', None),
            ('first-seen-run', 'current-finlife', '3.70'),
        ],
    )

    total, nulls = gate._finlife_observation_nulls(conn, ['current-finlife'])

    assert total == 2
    assert nulls == 1


def test_finlife_missing_rate_count_reads_only_finlife_json_shape(tmp_path: Path) -> None:
    """다른 수집원의 JSON이 섞여 있어도 optionList가 있는 finlife만 센다."""
    gate = _gate_module()
    finlife = tmp_path / 'finlife.json'
    finlife.write_text(
        '{"result":{"optionList":['
        '{"intr_rate2":null},{"intr_rate2":3.8},{"intr_rate2":null}]}}',
        encoding='utf-8',
    )
    other = tmp_path / 'cu.json'
    other.write_text('[{"intr_rate2":null}]', encoding='utf-8')

    file_count, missing = gate._finlife_source_missing([finlife, other])

    assert file_count == 1
    assert missing == 2
