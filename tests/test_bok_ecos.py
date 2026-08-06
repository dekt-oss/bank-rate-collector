"""한국은행 기준금리 (v4 §7, PR 6).

실물 응답으로만 검증한다. 2026-08-06 Actions run 31098447877에서 받은 것이고,
계약은 `docs/source-recon/bok-ecos.md`에 있다.

**통계표 코드를 추정하지 않았다** — 정찰이 이름으로 찾아냈다 (§7.2).
"""

import asyncio
import json
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from rate_monitor.collectors.base import ParseError, SchemaChangedError
from rate_monitor.collectors.bok_ecos import parser
from rate_monitor.collectors.bok_ecos.adapter import BokEcosAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.indicator_service import collect_indicator

FIXTURES = Path(__file__).parent / "fixtures" / "bok_ecos"
DAILY = FIXTURES / "base_rate_daily.json"


def _payload() -> dict:
    return json.loads(DAILY.read_text(encoding="utf-8"))


class FixtureAdapter(BokEcosAdapter):
    """fetch만 fixture로 대체한다. 파싱 이하는 실제 코드."""

    def __init__(self) -> None:
        super().__init__(api_key="test-key")

    async def fetch(self, request):  # noqa: ANN001, ANN201
        return [
            RawArtifactData(
                artifact_type="json", content=DAILY.read_bytes(),
                filename="bok.json",
                request_meta={"url": "https://ecos.bok.or.kr/…/[REDACTED]/…",
                              "cycle": "D"},
                schema_fingerprint="fp",
                source_role=self.source_role, trust_level=self.trust_level,
            )
        ]


@pytest.fixture()
def factory(tmp_path: Path):
    engine = create_db_engine(tmp_path / "bok.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


# ── 계약 ────────────────────────────────────────────────────────────────


def test_the_codes_came_from_reconnaissance_not_a_guess() -> None:
    """정찰이 확인한 값. 근거 없이 바꾸면 다른 통계를 받게 된다."""
    assert parser.STAT_CODE == "722Y001"
    assert parser.ITEM_CODE == "0101000"
    assert parser.CYCLE == "D"
    # 실물 fixture가 그 코드를 담고 있어야 정찰과 코드가 맞물린다.
    row = _payload()["StatisticSearch"]["row"][0]
    assert row["STAT_CODE"] == parser.STAT_CODE
    assert row["ITEM_CODE1"] == parser.ITEM_CODE


def test_the_unit_is_pinned_to_percent() -> None:
    """원천은 「연%」로 준다. 저장 단위는 명세서가 percent로 고정한다."""
    points, _ = parser.parse(_payload())
    assert {p.unit for p in points} == {"percent"}
    assert _payload()["StatisticSearch"]["row"][0]["UNIT_NAME"] == parser.SOURCE_UNIT


def test_real_values_parse() -> None:
    points, warnings = parser.parse(_payload())
    assert len(points) == 10
    assert warnings == []
    assert points[0].value == Decimal("3.5")
    assert points[0].source_effective_at == date(2024, 1, 1)
    assert points[0].indicator_code == "bok_base_rate"


# ── 잘못된 것을 안 받는다 ───────────────────────────────────────────────


def test_another_statistic_is_refused() -> None:
    """다른 통계표가 섞이면 그 값이 화면에 "기준금리"로 뜬다."""
    payload = _payload()
    payload["StatisticSearch"]["row"][0]["STAT_CODE"] = "902Y006"
    points, warnings = parser.parse(payload)
    assert len(points) == 9
    assert any("다른 통계표" in w for w in warnings)


def test_a_changed_unit_is_refused() -> None:
    """단위가 바뀌면 화면의 숫자가 뜻을 잃는다."""
    payload = _payload()
    payload["StatisticSearch"]["row"][0]["UNIT_NAME"] = "%p"
    points, warnings = parser.parse(payload)
    assert len(points) == 9
    assert any("단위가 바뀌었다" in w for w in warnings)


def test_an_impossible_rate_is_refused() -> None:
    """한국은행 기준금리가 90%일 수는 없다. 원천이 다른 것을 주고 있다."""
    payload = _payload()
    payload["StatisticSearch"]["row"][0]["DATA_VALUE"] = "90"
    points, warnings = parser.parse(payload)
    assert len(points) == 9
    assert any("범위를 벗어났다" in w for w in warnings)


def test_an_error_body_with_status_200_is_not_silently_empty() -> None:
    """ECOS는 실패도 200으로 준다. 상태코드만 보면 빈 시계열이 정상이 된다."""
    with pytest.raises(ParseError, match="ECOS 오류"):
        parser.parse({"RESULT": {"CODE": "INFO-100", "MESSAGE": "인증키가 유효하지 않습니다"}})


def test_a_missing_field_stops_the_run() -> None:
    payload = _payload()
    del payload["StatisticSearch"]["row"][0]["DATA_VALUE"]
    with pytest.raises(SchemaChangedError):
        parser.parse(payload)


# ── 저장 ────────────────────────────────────────────────────────────────


def test_the_same_day_is_never_stored_twice(factory, tmp_path: Path) -> None:
    """기준금리는 몇 달씩 안 바뀐다. 매일 쌓으면 이력이 아니라 잡음이다 (§7.3)."""
    request = CollectionRequest(source_id="bok_ecos")
    first = asyncio.run(
        collect_indicator(FixtureAdapter(), request, factory, raw_root=tmp_path / "raw")
    )
    assert first.status == "success"
    assert first.stored == 10

    second = asyncio.run(
        collect_indicator(FixtureAdapter(), request, factory, raw_root=tmp_path / "raw")
    )
    # 받았고 읽었는데 새 값이 없다. 실패가 아니다.
    assert second.status == "no_change"
    assert (second.stored, second.unchanged) == (0, 10)

    conn = sqlite3.connect(tmp_path / "bok.sqlite3")
    assert conn.execute("SELECT COUNT(*) FROM market_indicators").fetchone()[0] == 10
    conn.close()


def test_the_rate_survives_the_roundtrip(factory, tmp_path: Path) -> None:
    """3.5가 3.4999…가 되면 안 된다."""
    asyncio.run(
        collect_indicator(
            FixtureAdapter(), CollectionRequest(source_id="bok_ecos"), factory,
            raw_root=tmp_path / "raw",
        )
    )
    with factory() as session:
        values = {r.value for r in session.query(m.MarketIndicator).all()}
    assert values == {Decimal("3.5000")}


def test_the_api_key_never_reaches_storage(factory, tmp_path: Path) -> None:
    """인증키가 **경로에** 들어가는 API다 (v3 §16.1)."""
    asyncio.run(
        collect_indicator(
            FixtureAdapter(), CollectionRequest(source_id="bok_ecos"), factory,
            raw_root=tmp_path / "raw",
        )
    )
    with factory() as session:
        blob = json.dumps(
            [a.request_meta_json for a in session.query(m.RawArtifact).all()],
            ensure_ascii=False,
        )
    assert "test-key" not in blob
    assert "[REDACTED]" in blob


def test_the_adapter_masks_the_key_in_the_url() -> None:
    adapter = BokEcosAdapter(api_key="SECRET123")
    assert "SECRET123" not in adapter._mask(
        "https://ecos.bok.or.kr/api/StatisticSearch/SECRET123/json"
    )


def test_a_key_with_stray_whitespace_is_trimmed(monkeypatch) -> None:
    """개행 하나가 `%0A`로 경로에 붙어 INFO-100이 된다.

    2026-08-06에 갈린 자리다. 같은 시크릿으로 정찰(run 31098447877)은 성공,
    수집(run 31101956888)은 `INFO-100: 인증키가 유효하지 않습니다`로 실패했고
    두 코드의 차이가 `.strip()` 하나였다.
    """
    monkeypatch.setenv("ECOS_API_KEY", "  SECRET123\n")
    adapter = BokEcosAdapter()
    assert adapter._api_key == "SECRET123"
    # 마스킹도 다듬은 값을 기준으로 돌아야 원본 주소에서 키가 지워진다.
    assert "SECRET123" not in adapter._mask(f"{'https://ecos.bok.or.kr/api'}/x/SECRET123/json")


def test_a_key_that_is_only_whitespace_is_no_key(monkeypatch) -> None:
    """공백만 든 시크릿은 "설정했다"로 보이지만 값이 없는 것이다."""
    from rate_monitor.collectors.base import CollectorError

    monkeypatch.setenv("ECOS_API_KEY", "   \n")
    with pytest.raises(CollectorError, match="ECOS_API_KEY"):
        BokEcosAdapter()


def test_the_adapter_needs_the_key_from_the_environment(monkeypatch) -> None:
    """인증키는 환경변수로만 받는다. 파일에 두지 않는다."""
    from rate_monitor.collectors.base import CollectorError

    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    with pytest.raises(CollectorError, match="ECOS_API_KEY"):
        BokEcosAdapter()


# ── 화면 ────────────────────────────────────────────────────────────────


def test_the_benchmark_card_reads_the_latest_applied_date(factory, tmp_path: Path) -> None:
    """수집일이 아니라 **적용일**로 고른다 — 바뀐 날짜가 값만큼 중요하다."""
    from rate_monitor.services.dashboard_service import build_benchmarks, latest_run_ids

    asyncio.run(
        collect_indicator(
            FixtureAdapter(), CollectionRequest(source_id="bok_ecos"), factory,
            raw_root=tmp_path / "raw",
        )
    )
    conn = sqlite3.connect(tmp_path / "bok.sqlite3")
    conn.row_factory = sqlite3.Row
    card = build_benchmarks(conn, latest_run_ids(conn))["bok_base_rate"]
    conn.close()

    assert card["value"] == 3.5
    assert card["unit"] == "percent"
    assert card["source_effective_at"] == "2024-01-10"  # fixture의 마지막 날
    assert card["name"] == "한국은행 기준금리"


def test_the_card_is_none_without_the_table(tmp_path: Path) -> None:
    """마이그레이션 전 DB로도 화면을 만들 수 있어야 한다."""
    from rate_monitor.services.dashboard_service import _latest_indicator

    db = tmp_path / "empty.sqlite3"
    sqlite3.connect(db).close()
    conn = sqlite3.connect(db)
    assert _latest_indicator(conn, "bok_base_rate") is None
    conn.close()


def test_a_parse_failure_ends_the_run_instead_of_leaving_it_running(
    factory, tmp_path: Path
) -> None:
    """2026-08-06 run 31101956888에서 실제로 걸린 것이다.

    ECOS가 인증키 오류를 **HTTP 200 본문**으로 줬다. fetch는 성공했고
    `parse_points`가 `ParseError`를 던졌는데, 그 구간이 try 밖이라 예외가
    그대로 올라가 `_finish`가 안 불렸다. `collection_runs` 행이 `running`으로
    남았고 — 그 원천이 화면에서 "지금도 돌고 있다"로 보인다.
    """

    class BrokenParseAdapter(FixtureAdapter):
        def parse_points(self, artifact):  # noqa: ANN001, ANN201
            raise ParseError("ECOS 오류 INFO-100: 인증키가 유효하지 않습니다")

    result = asyncio.run(
        collect_indicator(
            BrokenParseAdapter(), CollectionRequest(source_id="bok_ecos"), factory,
            raw_root=tmp_path / "raw",
        )
    )
    assert result.status == "failed"
    assert "INFO-100" in result.message

    with factory() as session:
        run = session.query(m.CollectionRun).one()
    assert run.status == "failed", "실행이 running으로 남으면 좀비 행이 쌓인다"
    assert run.finished_at is not None
    assert run.raw_count == 1  # 받기는 받았다는 사실은 남긴다


def test_the_run_timestamp_is_naive_utc_like_every_other_source(
    factory, tmp_path: Path
) -> None:
    """다른 수집원과 같은 자를 써야 한다.

    저장은 naive UTC다. 여기만 로컬 시각을 넣으면 두 곳이 깨진다 —
    `latest_run_ids`의 `MAX(started_at)` 비교가 원천 간에 어긋나고, 화면의
    KST 변환(`domain/timeutil`)이 9시간 틀린다.

    한국에서 만들었으므로 로컬 시각을 넣으면 실제로 9시간이다.
    """
    import datetime as dt

    asyncio.run(
        collect_indicator(
            FixtureAdapter(), CollectionRequest(source_id="bok_ecos"), factory,
            raw_root=tmp_path / "raw",
        )
    )
    with factory() as session:
        started = session.query(m.CollectionRun).one().started_at

    drift = abs((started - dt.datetime.now(dt.UTC).replace(tzinfo=None)).total_seconds())
    assert drift < 60, f"UTC에서 {drift:.0f}초 어긋났다"
