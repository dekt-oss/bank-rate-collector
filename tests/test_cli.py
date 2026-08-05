"""CLI 명령을 실제로 불러 본다.

서비스 계층만 테스트하고 CLI는 얇으니 괜찮다고 두었더니, `snapshot`이
`manifest.sha256`을 읽는 채로 통과했다. 그런 필드는 없다 —
`Manifest.sqlite_sha256`이다. 워크플로우가 부르는 자리라 수집이 끝난 뒤
스냅샷 단계에서 죽었을 것이다.

서비스가 아니라 **워크플로우가 부르는 그 명령줄**을 그대로 부른다.
"""

import json
from pathlib import Path

import pytest

from rate_monitor.cli import main
from tests.test_snapshot_and_dashboard import TEMPLATE, collected_db  # noqa: F401


def test_snapshot_command_runs_and_prints(collected_db, tmp_path, capsys) -> None:  # noqa: F811
    publish = tmp_path / "publish" / "rate_monitor.sqlite3"
    manifest = tmp_path / "publish" / "manifest.json"
    code = main([
        "snapshot",
        "--db", str(collected_db),
        "--publish-db", str(publish),
        "--manifest", str(manifest),
    ])
    assert code == 0
    assert publish.exists()

    # 화면에 찍힌 해시가 manifest의 값과 같아야 한다. 필드 이름을 잘못
    # 읽으면 여기서 걸린다.
    printed = capsys.readouterr().out
    digest = json.loads(manifest.read_text(encoding="utf-8"))["sqlite_sha256"]
    assert digest[:16] in printed


def test_validate_command_passes_on_a_clean_db(collected_db, capsys) -> None:  # noqa: F811
    assert main(["validate", "--db", str(collected_db)]) == 0
    assert "통과" in capsys.readouterr().out


def test_build_dashboard_command_writes_both_outputs(collected_db, tmp_path) -> None:  # noqa: F811
    site = tmp_path / "site" / "index.html"
    summary = tmp_path / "publish" / "summary.json"
    code = main([
        "build-dashboard",
        "--db", str(collected_db),
        "--template", str(TEMPLATE),
        "--site", str(site),
        "--summary", str(summary),
    ])
    assert code == 0
    assert site.stat().st_size > 0
    assert json.loads(summary.read_text(encoding="utf-8"))["totals"]["observations"] > 0


def test_export_command_writes_files(collected_db, tmp_path, capsys) -> None:  # noqa: F811
    out = tmp_path / "export"
    assert main(["export", "--db", str(collected_db), "--out", str(out)]) == 0
    written = sorted(p.name for p in out.iterdir())
    assert len(written) == 2
    assert capsys.readouterr().out.strip()


def test_unknown_source_is_rejected(capsys) -> None:
    """choices에 없는 값은 argparse가 막는다."""
    with pytest.raises(SystemExit):
        main(["collect", "--source", "없는수집원"])


def test_scope_reaches_the_request() -> None:
    """--scope가 CollectionRequest까지 실제로 전달되는지.

    옵션만 만들고 request에 안 실으면 조용히 기본값으로 돈다.
    """
    from rate_monitor.cli import _default_request, build_parser

    args = build_parser().parse_args(
        ["collect", "--source", "kfcc", "--scope", "수도권"]
    )
    assert _default_request(args).options["scope"] == "수도권"

    args = build_parser().parse_args(["collect", "--source", "kfcc"])
    assert _default_request(args).options == {}


def test_scope_selects_the_real_config_regions() -> None:
    """config/regions.yaml의 실제 값으로 범위가 골라지는지."""
    from rate_monitor.collectors.kfcc.adapter import KfccAdapter
    from rate_monitor.domain.schemas import CollectionRequest

    adapter = KfccAdapter(Path("config/regions.yaml"))
    assert adapter._load_regions(
        CollectionRequest(source_id="kfcc", options={"scope": "부산"})
    ) == ["부산"]
    assert len(
        adapter._load_regions(CollectionRequest(source_id="kfcc"))
    ) == 17
