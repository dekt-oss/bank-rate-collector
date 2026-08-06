"""관측 변경이력 (선행 수정안 §3.2).

예전에는 수집할 때마다 관측이 새로 쌓였다. 같은 3.10%가 날짜마다 한 줄씩
생겨, 네 원천 합계 48,924행/회를 평일마다 쌓으면 1년에 1,272만 행 — 약
19 GB가 된다.

이제는 값이 바뀔 때만 행이 생긴다. **바뀐 것을 놓치지 않으면서** 안 바뀐
것을 안 쌓는지가 여기서 갈린다.
"""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.schemas import CollectionRequest
from rate_monitor.services.collection_service import collect_source
from tests.test_collection_service import REAL, FixtureAdapter, _artifact


@pytest.fixture()
def factory(tmp_path):
    engine = create_db_engine(tmp_path / "history.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _collect(factory, raw_root, paths=None):
    return asyncio.run(
        collect_source(
            FixtureAdapter(paths or [REAL]),
            CollectionRequest(source_id="finlife"),
            factory,
            raw_root=raw_root,
        )
    )


def _bumped(fixture: Path, out: Path, delta: float) -> Path:
    """같은 표본에서 금리만 올린 사본. 값이 바뀐 것을 흉내낸다."""
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    for option in payload["result"]["optionList"]:
        if option.get("intr_rate") is not None:
            option["intr_rate"] = round(float(option["intr_rate"]) + delta, 2)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


class _BumpedAdapter(FixtureAdapter):
    async def fetch(self, request):
        return [_artifact(p) for p in self._paths]


def test_an_unchanged_rate_does_not_make_a_new_row(factory, tmp_path) -> None:
    _collect(factory, tmp_path / "raw")
    with factory() as s:
        first = s.scalar(select(func.count()).select_from(m.RateObservation))

    _collect(factory, tmp_path / "raw")
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(m.RateObservation)) == first
        # 두 번 봤다는 사실은 남는다.
        assert s.scalar(select(func.min(m.RateObservation.seen_count))) == 2
        # 아직 아무것도 안 끝났다.
        assert s.scalar(
            select(func.count()).select_from(m.RateObservation).where(
                m.RateObservation.valid_to.is_not(None)
            )
        ) == 0


def test_a_changed_rate_closes_the_old_row_and_opens_a_new_one(factory, tmp_path) -> None:
    """이력이 남아야 한다. 옛 값을 덮어쓰면 언제 바뀌었는지가 사라진다."""
    _collect(factory, tmp_path / "raw")
    with factory() as s:
        before = s.scalar(select(func.count()).select_from(m.RateObservation))

    bumped = _bumped(REAL, tmp_path / "bumped.json", 0.5)
    _collect(factory, tmp_path / "raw", [bumped])

    with factory() as s:
        after = s.scalar(select(func.count()).select_from(m.RateObservation))
        closed = s.scalar(
            select(func.count()).select_from(m.RateObservation).where(
                m.RateObservation.valid_to.is_not(None)
            )
        )
        live = s.scalar(
            select(func.count()).select_from(m.RateObservation).where(
                m.RateObservation.valid_to.is_(None)
            )
        )
        # 바뀐 만큼 늘고, 그만큼 닫힌다.
        assert after == before + closed
        assert closed > 0
        assert live == before

        # 닫힌 행의 valid_to가 새 행의 valid_from과 맞물린다.
        old = s.scalars(
            select(m.RateObservation).where(m.RateObservation.valid_to.is_not(None)).limit(1)
        ).one()
        new = s.scalars(
            select(m.RateObservation).where(
                m.RateObservation.variant_id == old.variant_id,
                m.RateObservation.valid_to.is_(None),
            )
        ).one()
        assert old.valid_to == new.valid_from
        assert old.base_rate != new.base_rate


def test_only_one_observation_is_alive_per_variant(factory, tmp_path) -> None:
    """살아 있는 행이 둘이면 화면에 같은 상품이 두 줄로 나온다."""
    _collect(factory, tmp_path / "raw")
    _collect(factory, tmp_path / "raw", [_bumped(REAL, tmp_path / "b1.json", 0.1)])
    _collect(factory, tmp_path / "raw", [_bumped(REAL, tmp_path / "b2.json", 0.2)])

    with factory() as s:
        rows = s.execute(
            select(m.RateObservation.variant_id, func.count())
            .where(m.RateObservation.valid_to.is_(None))
            .group_by(m.RateObservation.variant_id)
            .having(func.count() > 1)
        ).all()
        assert rows == []


def test_the_dashboard_still_sees_unchanged_rates(factory, tmp_path) -> None:
    """`run_id`로 걸면 안 바뀐 금리가 화면에서 통째로 사라진다.

    관측 행은 처음 본 실행에 묶여 있으므로, "이번 실행이 확인한 금리"는
    `last_run_id`로 물어야 한다.
    """
    import sqlite3

    from rate_monitor.services.dashboard_service import build_rate_table, latest_run_ids

    db = tmp_path / "history.sqlite3"
    _collect(factory, tmp_path / "raw")
    _collect(factory, tmp_path / "raw")  # 값이 그대로인 두 번째 실행

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    table = build_rate_table(conn, latest_run_ids(conn))
    conn.close()

    # 두 번째 실행이 아무 행도 안 만들었지만 화면은 그대로 보인다.
    assert len(table["rows"]) > 0


def test_run_stats_tell_unchanged_from_failed(factory, tmp_path) -> None:
    """4,010행을 받고 관측이 안 늘어난 것이 실패인지 무변동인지 구별한다."""
    _collect(factory, tmp_path / "raw")
    _collect(factory, tmp_path / "raw")

    with factory() as s:
        stats = s.scalars(
            select(m.CollectionRunStat).order_by(m.CollectionRunStat.created_at)
        ).all()
        assert len(stats) == 2
        # 첫 실행은 전부 새 비교 단위다.
        assert stats[0].new_variant_count > 0
        assert stats[0].unchanged_count == 0
        # 둘째 실행은 전부 그대로다. parsed_count는 여전히 크다.
        assert stats[1].unchanged_count == stats[0].new_variant_count
        assert stats[1].new_variant_count == 0
        assert stats[1].changed_count == 0
        assert stats[1].parsed_count == stats[0].parsed_count


def test_seen_count_never_loses_an_observation(factory, tmp_path) -> None:
    """행은 접혀도 몇 번 봤는지는 남는다. 마이그레이션의 불변식과 같다."""
    _collect(factory, tmp_path / "raw")
    _collect(factory, tmp_path / "raw")
    _collect(factory, tmp_path / "raw")

    with factory() as s:
        total_seen = s.scalar(select(func.sum(m.RateObservation.seen_count)))
        parsed = s.scalar(select(func.sum(m.CollectionRun.valid_count)))
        assert total_seen == parsed
