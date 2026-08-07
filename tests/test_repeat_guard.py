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

import pytest

from rate_monitor.collectors.repeat_guard import (
    MAX_CONSECUTIVE_REPEATS,
    RepeatedResponseError,
    RepeatGuard,
)


def test_the_same_body_from_different_queries_is_not_dropped() -> None:
    """되풀이는 세되 막지 않는다. 막는 것은 한도를 넘을 때뿐이다."""
    guard = RepeatGuard()
    for i in range(MAX_CONSECUTIVE_REPEATS):
        guard.observe(b"same", where=f"gmgoCd={i}")

    assert guard.total == MAX_CONSECUTIVE_REPEATS
    assert guard.repeats == MAX_CONSECUTIVE_REPEATS - 1


def test_a_whole_region_of_identical_answers_stops_the_run() -> None:
    """경남은 186장 연속이었다. 그 수준이면 원천이 조회를 무시하는 것이다."""
    guard = RepeatGuard()
    with pytest.raises(RepeatedResponseError) as stop:
        for i in range(186):
            guard.observe(b"generic page", where=f"gmgoCd={i}")

    assert "연속" in str(stop.value)
    assert guard.longest_run > MAX_CONSECUTIVE_REPEATS


def test_normal_variety_never_trips_the_guard() -> None:
    """금고마다 취급 상품이 달라 같은 값이 길게 이어지지 않는다.

    표준 상품이 몇십 곳 섞여 있어도 사이에 다른 응답이 끼면 연속이 끊긴다.
    """
    guard = RepeatGuard()
    for i in range(500):
        guard.observe(b"standard" if i % 3 else f"{i}".encode(), where=f"{i}")

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
        assert "self.fetch_note = guard.summary()" in source, f"{name}이 요약을 안 남긴다"
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
