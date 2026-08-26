"""서로 다른 조회에 같은 응답이 와도 잃지 않는다.

2026-08-06 전 원천 실행에서 새마을금고 경남 186장이 통째로 사라졌다.
관측 93,741 → 86,467건(7,274건 손실)인데 **오류 0 · 경고 0**이었고 물량
게이트도 통과했다. 아무도 몰랐다.

원인은 `raw_artifacts`의 유일성이 `(run_id, sha256)`이었던 것이다. 금리
화면에는 금고 이름도 주소도 없어서 취급 상품과 금리가 같은 두 금고는 응답
바이트가 완전히 같아진다. 수집기가 제약에 걸리지 않으려고 뒤에 온 금고를
버렸고, **버려진 금고는 DB에 아예 안 생겼다.**

이 파일은 그 손실이 다시 나지 않는지, 그리고 이제는 조용하지 않은지 본다.
"""

from rate_monitor.collectors.repeat_guard import (
    MAX_CONSECUTIVE_REPEATS,
    RepeatGuard,
)


def test_the_same_body_from_different_queries_is_not_dropped() -> None:
    """되풀이는 세되 막지 않는다. 막는 것은 한도를 넘을 때뿐이다."""
    guard = RepeatGuard()
    for i in range(MAX_CONSECUTIVE_REPEATS):
        guard.observe(b"same", where=f"gmgoCd={i}")

    assert guard.total == MAX_CONSECUTIVE_REPEATS
    assert guard.repeats == MAX_CONSECUTIVE_REPEATS - 1


def test_a_whole_region_of_identical_answers_trips_the_guard() -> None:
    """경남은 186장 연속이었다. 그 수준이면 원천이 조회를 무시하는 것이다."""
    guard = RepeatGuard()
    for i in range(186):
        guard.observe(b"generic page", where=f"gmgoCd={i}")

    assert guard.tripped, "한도를 넘었는데 아무 표시가 없다"
    assert "연속" in guard.tripped
    assert guard.longest_run > MAX_CONSECUTIVE_REPEATS
    assert "중단" in guard.summary()


def test_the_real_gyeongnam_shape_is_caught(  # noqa: D103 — 아래 docstring 참조
) -> None:
    """**처음에는 이걸 못 잡았다.**

    수집기는 축을 둘 돈다 — 금고마다 예금(13)·적금(14)을 번갈아 받는다.
    그래서 경남처럼 통째로 같은 답이 와도 순서가 `A13, A14, B13, B14…`라
    바로 앞과는 늘 달랐고, 연속이 1로 끊겨 정상 실행과 구별되지 않았다.

        고치기 전: 응답 186장 · 되풀이 184장 · **최장 연속 1**

    축마다 따로 세면 93장 연속이 된다.
    """
    guard = RepeatGuard()
    for i in range(93):
        for group in ("13", "14"):
            guard.observe(
                f"generic-{group}".encode(),
                where=f"gmgoCd={i} gubuncode={group}",
                stream=group,
            )

    assert guard.tripped, "축을 갈라 세지 않으면 경남을 또 놓친다"
    assert guard.longest_run > MAX_CONSECUTIVE_REPEATS


def test_tripping_never_throws_away_what_was_already_collected() -> None:
    """예외를 던지면 그때까지 받은 두 시간치가 통째로 버려진다.

    그건 원래 고치려던 손실과 같은 일이다. 사유만 남기고 수집기가 그만
    받는다.
    """
    guard = RepeatGuard(limit=2)
    for i in range(10):
        guard.observe(b"same", where=f"{i}")   # 예외가 안 난다

    assert guard.tripped
    assert guard.total == 10


def test_every_collector_tells_the_guard_which_axis_it_is_on() -> None:
    """축을 안 주면 두 축을 도는 수집기에서 연속이 조용히 끊긴다."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "rate_monitor" / "collectors"
    for name in ("kfcc", "cu", "fsb", "nh_local"):
        source = (root / name / "adapter.py").read_text(encoding="utf-8")
        assert "stream=" in source, f"{name}이 조회 축을 안 알려준다"
        assert "guard.tripped" in source, f"{name}이 한도를 넘어도 계속 받는다"


def test_normal_variety_never_trips_the_guard() -> None:
    """금고마다 취급 상품이 달라 같은 값이 길게 이어지지 않는다.

    표준 상품이 몇십 곳 섞여 있어도 **같은 축 안에서** 다른 응답이 끼면
    연속이 끊긴다. 이게 안 끊기면 정상 실행이 멈춘다.
    """
    guard = RepeatGuard()
    for i in range(500):
        guard.observe(b"standard" if i % 3 else f"{i}".encode(),
                      where=f"{i}", stream="13")
    assert not guard.tripped

    assert guard.repeats > 0, "되풀이 자체는 정상적으로 생긴다"
    assert guard.longest_run <= 2


def test_the_summary_is_written_even_when_nothing_repeated() -> None:
    """0건일 때 침묵하면 "검사를 안 했나"와 구별되지 않는다.

    경남이 사라졌을 때 로그에도 실행 기록에도 흔적이 정확히 0이었다.
    """
    guard = RepeatGuard()
    guard.observe(b"a", where="1")
    guard.observe(b"b", where="2")

    note = guard.summary()
    assert "응답 2장" in note
    assert "되풀이 0장" in note


def test_every_outlet_level_collector_watches_for_repeats() -> None:
    """점포·금고마다 따로 받는 원천은 전부 같은 결함을 갖는다.

    농·축협은 지금 부산 120점포뿐이라 안 드러났을 뿐이고, 전국 4,871점포로
    넓히면 새마을금고에서 난 일이 그대로 난다.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "rate_monitor" / "collectors"
    for name in ("kfcc", "cu", "fsb", "nh_local"):
        source = (root / name / "adapter.py").read_text(encoding="utf-8")
        assert "RepeatGuard()" in source, f"{name}에 되풀이 감시가 없다"
        assert "guard.summary()" in source, f"{name}이 되풀이 요약을 안 만든다"
        assert "self.fetch_note" in source, f"{name}이 실행 메모를 안 남긴다"
        # 조용히 버리던 코드가 되살아나지 않았는지.
        assert "seen_bodies" not in source, f"{name}이 아직 응답을 버린다"


# ── 저장 계층: 같은 바이트여도 조회가 사라지지 않는다 ───────────────────


def test_identical_responses_share_one_row_but_no_query_is_lost(tmp_path) -> None:
    """`zip(artifacts, saved, strict=True)`가 짝을 맞춘다.

    저장 계층이 하나라도 빼면 그 조회가 통째로 파싱에서 사라진다. 예전에는
    수집기가 아예 버려서 그 일이 났다 — 경남 186장, 관측 7,274건.

    바이트가 같은 응답끼리는 원본 행 **하나**를 함께 가리킨다.
    `UNIQUE(run_id, sha256)`을 어기지 않으면서 조회는 다 남는다.
    """
    from datetime import UTC, datetime

    from sqlalchemy import select

    from rate_monitor.db import models as m
    from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
    from rate_monitor.domain.schemas import RawArtifactData
    from rate_monitor.services.collection_service import save_raw_artifacts

    engine = create_db_engine(tmp_path / "t.sqlite3")
    m.Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    now = datetime.now(UTC).replace(tzinfo=None)

    def artifact(filename: str, body: bytes) -> RawArtifactData:
        return RawArtifactData(
            artifact_type="html", content=body, filename=filename,
            request_meta={"gmgoCd": filename}, schema_fingerprint="f",
            source_role="primary_official", trust_level="official_direct",
        )

    # 금고 셋 중 둘이 바이트가 같다.
    artifacts = [
        artifact("rate_1203_13.html", b"<html>same</html>"),
        artifact("rate_1204_13.html", b"<html>same</html>"),
        artifact("rate_1205_13.html", b"<html>other</html>"),
    ]

    with session_scope(factory) as session:
        session.add(m.Source(
            id="kfcc", name="kfcc", sector="kfcc", mode="http",
            source_role="primary_official", trust_level="official_direct",
            priority=10, enabled=True, policy_status="review",
            coverage_status="partial", created_at=now, updated_at=now,
        ))
        run = m.CollectionRun(
            id="run-1", source_id="kfcc", mode="http", started_at=now, status="running",
        )
        session.add(run)
        session.flush()
        saved = save_raw_artifacts(session, run, artifacts, tmp_path / "raw", now)

        # **조회 수만큼 돌려준다.** 짝짓기가 깨지면 안 된다.
        assert len(saved) == len(artifacts)
        # 같은 바이트는 원본 행 하나를 공유한다.
        assert saved[0] is saved[1]
        assert saved[2] is not saved[0]
        assert len({r.id for r in saved}) == 2

    # 파일은 조회마다 남는다 — 원본 증거는 조회 단위다.
    written = sorted(p.name for p in (tmp_path / "raw").rglob("*.html"))
    assert written == ["rate_1203_13.html", "rate_1204_13.html", "rate_1205_13.html"]

    # **공유된 행은 함께 가리키는 조회를 전부 적는다.**
    #
    # 안 적으면 그 행이 첫 조회(1203)만 가리켜서, 1204의 관측이 남의 이름을
    # 단 원본을 가리키게 된다 — 추적이 이 사고의 경우에만 끊긴다.
    with session_scope(factory) as session:
        raw_rows = session.scalars(select(m.RawArtifact)).all()
        assert all("\\" not in row.relative_path for row in raw_rows)
        rows = {
            row.relative_path.rsplit("/", 1)[-1]: row.request_meta_json
            for row in raw_rows
        }
        assert rows["rate_1203_13.html"]["shared_with"] == ["rate_1204_13.html"]
        assert "shared_with" not in rows["rate_1205_13.html"]


def test_a_tripped_run_is_not_recorded_as_success(factory=None, tmp_path=None) -> None:
    """경남이 사라진 실행은 **오류 0으로 성공**이었다.

    그게 이 사고의 핵심이다. 데이터가 없어졌는데 실행 기록도, 상태도,
    검수항목도 그 사실을 말하지 않았다. 이제는 `partial`로 끝나고
    검수항목이 남는다.
    """
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "rate_monitor" / "services" / "collection_service.py"
    ).read_text(encoding="utf-8")

    assert 'issue_type="repeated_response"' in source
    # 되풀이가 있으면 success가 아니다.
    assert re.search(r"complete = .*not alert", source), (
        "되풀이가 있어도 success로 끝난다"
    )
    # 받은 것은 버리지 않는다 — fetch 중 예외로 실행을 죽이지 않는다.
    assert "except RepeatedResponseError" not in source
