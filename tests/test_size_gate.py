"""발행 전 파일 크기 검사 (선행 수정안 v1 §10).

이 검사의 값어치는 **막는 것**에 있다. 통과만 확인하면 있으나 마나이므로,
한도를 넘겼을 때 실제로 종료코드가 1이 되는지를 먼저 본다.
"""

from pathlib import Path

from scripts import size_gate as gate

MIB = gate.MIB


def _file(root: Path, relative: str, mib: float) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    # 실제 바이트를 쓴다. 크기를 흉내 내면 검사가 성립하는지 알 수 없다.
    with path.open("wb") as handle:
        handle.truncate(int(mib * MIB))
    return path


# ── 한도 배정 ───────────────────────────────────────────────────────────


def test_download_files_are_not_held_to_the_shard_limit() -> None:
    """같은 폴더에 있어도 성격이 다르다.

    화면 조각은 페이지를 여는 사람 전부가 기다리고, 내려받기 파일은 받겠다고
    누른 사람만 기다린다. 여기에 조각 한도를 들이대면 16.6 MiB CSV를 아무도
    못 받을 크기로 잘라야 한다.
    """
    assert gate.limits_for("site-public/data/table.json") == (
        gate.SHARD_WARN, gate.SHARD_FAIL
    )
    assert gate.limits_for("site-public/data/rates.csv") == (
        gate.GIT_FILE_WARN, gate.GIT_FILE_FAIL
    )


def test_the_state_db_has_its_own_limit() -> None:
    """한시 예외. R2로 옮기기 전까지는 지울 수 없다."""
    assert gate.limits_for(gate.STATE_DB) == (gate.STATE_DB_WARN, gate.STATE_DB_FAIL)
    # 그래도 GitHub의 진짜 벽(100 MB)보다는 앞에서 멈춰야 한다.
    assert gate.STATE_DB_FAIL < 100 * MIB


def test_every_limit_stays_under_the_github_wall() -> None:
    """어떤 한도도 100 MB를 넘지 않는다. 넘으면 게이트가 무의미하다."""
    for name, value in vars(gate).items():
        if name.endswith("_FAIL") and name != "TOTAL_FAIL":
            assert value < 100 * MIB, name


# ── 판정 ────────────────────────────────────────────────────────────────


def test_an_oversized_file_blocks_publishing(tmp_path: Path, capsys) -> None:
    """이게 이 검사의 전부다. 안 막으면 있으나 마나다."""
    _file(tmp_path, "latest/export/rates_20260806.json", 50.67)
    assert gate.main([str(tmp_path)]) == 1
    assert "발행하지 않는다" in capsys.readouterr().out


def test_a_healthy_tree_passes(tmp_path: Path) -> None:
    _file(tmp_path, "site-public/index.html", 0.15)
    _file(tmp_path, "site-public/data/table.json", 5.36)
    _file(tmp_path, "site-public/data/rates.csv", 16.57)
    assert gate.main([str(tmp_path)]) == 0


def test_the_state_db_passes_at_its_current_size(tmp_path: Path, capsys) -> None:
    """2026-08-06 실측 50.75 MiB. 일반 한도(40)는 넘지만 예외 한도(80) 안이다.

    이걸 통과시키지 않으면 PR 2 전에는 아무것도 발행할 수 없다.
    """
    _file(tmp_path, gate.STATE_DB, 50.75)
    assert gate.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    # 예외를 조용히 넘기지 않는다. 매번 적어야 잊히지 않는다.
    assert "한시 예외" in out
    assert "PR 2" in out


def test_the_state_db_still_blocks_before_the_github_wall(tmp_path: Path) -> None:
    """예외에도 끝이 있다. 90 MiB면 push가 거부되기 직전이다."""
    _file(tmp_path, gate.STATE_DB, 90)
    assert gate.main([str(tmp_path)]) == 1


def test_many_small_files_can_still_fail_on_the_total(tmp_path: Path) -> None:
    """개별로는 다 통과해도 합계가 브랜치를 키운다."""
    for i in range(11):
        _file(tmp_path, f"site-public/data/shard-{i:03d}.json", 19)
    findings = gate.inspect(tmp_path)
    assert all(f.level != "fail" for f in findings if f.path != "(전체)")
    assert next(f for f in findings if f.path == "(전체)").failed


def test_git_metadata_is_not_counted(tmp_path: Path) -> None:
    """`.git` 안은 발행물이 아니다. 세면 합계가 엉뚱해진다."""
    _file(tmp_path, ".git/objects/pack/huge.pack", 60)
    _file(tmp_path, "site-public/index.html", 0.15)
    assert [f.path for f in gate.inspect(tmp_path)] == ["site-public/index.html", "(전체)"]


def test_a_missing_directory_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """경로를 잘못 주면 조용히 통과하면 안 된다. 검사를 안 한 것이다."""
    assert gate.main([str(tmp_path / "없음")]) == 2
