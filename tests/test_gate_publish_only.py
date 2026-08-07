"""발행만 하는 실행에서 게이트가 무엇을 검사하고 무엇을 건너뛰는가.

이 게이트는 "방금 수집했다"는 전제로 쓰였다. 2026-08-07에 수집을 건너뛰고
화면만 다시 내는 실행이 생기면서 전제가 깨졌다 — 러너 디스크의 `data/raw/`가
비어 있는 것이 정상인데, 게이트가 그걸 실패로 셌다. run 25·26이 거기서
멈춰 발행 단계까지 건너뛰었고, 머지해도 화면이 안 바뀌었다.

여기서 못박는 것은 두 가지다. 수집 없는 실행에서 그 항목들이 **건너뛴 것으로
표시되고**, 수집하는 실행에서는 **여전히 실패로 잡힌다**는 것. 둘 중 하나만
지키면 게이트가 장식이 된다 (v3.1 §12.4).
"""

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "verify_gate.py"

# 원본 파일을 봐야만 판정할 수 있는 항목들. 수집이 없으면 볼 것이 없다.
RAW_DEPENDENT = (
    "원본 보존",
    "max_rate 대조용 finlife 원본 확보",
    "max_rate NULL 규칙 — finlife (원본 대조)",
)


def _run_gate(tmp_path: Path, *extra: str) -> str:
    """빈 DB와 빈 원본 디렉터리로 게이트를 돌리고 출력을 돌려준다.

    다른 항목은 여기서 관심사가 아니다 — 원본을 보는 셋이 어떻게 찍히는지만
    본다. 그래서 종료 코드가 아니라 줄을 읽는다.
    """
    from rate_monitor.db.models import Base
    from rate_monitor.db.session import create_db_engine

    db = tmp_path / "publish.sqlite3"
    engine = create_db_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sqlite_sha256": "x", "row_counts": {}}), "utf-8")
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"totals": {}}), "utf-8")
    site = tmp_path / "index.html"
    site.write_text(
        '<script id="rate-monitor-data" type="application/json">'
        '{"totals": {}}</script>',
        "utf-8",
    )
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    done = subprocess.run(
        [sys.executable, str(GATE),
         "--db", str(db), "--manifest", str(manifest), "--summary", str(summary),
         "--site", str(site), "--raw-root", str(raw_root), *extra],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    return done.stdout


def test_a_publish_only_run_skips_the_checks_that_need_fresh_raw_files(
    tmp_path: Path,
) -> None:
    """수집을 안 했으면 원본이 없는 것이 정상이다."""
    out = _run_gate(tmp_path, "--no-collection")
    for name in RAW_DEPENDENT:
        assert f"[PASS] [건너뜀] {name}" in out, f"{name}이 건너뛴 것으로 안 찍혔다\n{out}"


def test_a_collecting_run_still_fails_when_the_raw_files_are_missing(
    tmp_path: Path,
) -> None:
    """깃발이 없으면 예전 그대로다. 이게 없으면 게이트를 그냥 끈 것이 된다."""
    out = _run_gate(tmp_path)
    assert "[FAIL] 원본 보존" in out, out
    assert "[건너뜀] 원본 보존" not in out, out


def test_the_skip_never_shows_up_as_a_plain_pass(tmp_path: Path) -> None:
    """건너뛴 것을 통과라고 적으면 읽는 사람이 검사가 돌았다고 믿는다.

    `0 == 0`으로 조용히 통과하던 finlife 대조가 특히 그랬다.
    """
    out = _run_gate(tmp_path, "--no-collection")
    for name in RAW_DEPENDENT:
        assert f"[PASS] {name} —" not in out, f"{name}이 그냥 통과로 찍혔다\n{out}"


def test_the_workflow_passes_the_flag_only_on_a_publish_only_run() -> None:
    """수집하는 실행에서 PUBLISH_ONLY는 빈 값이 아니라 문자열 "false"다.

    `${PUBLISH_ONLY:+--no-collection}`으로 쓰면 그때도 깃발이 붙어 원본
    검사가 통째로 사라진다. 값을 비교해야 한다.
    """
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
    )
    step = next(
        s for s in workflow["jobs"]["collect"]["steps"]
        if s.get("name") == "Verify P1-A gate"
    )
    body = step["run"]
    assert "--no-collection" in body
    assert '"${PUBLISH_ONLY}" = "true"' in body, body
    assert "${PUBLISH_ONLY:+" not in body, "빈 값 검사로는 false를 못 거른다"
