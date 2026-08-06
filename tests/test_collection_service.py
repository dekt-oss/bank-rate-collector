"""수집 오케스트레이션 검증 — 실물 fixture로 저장 경로 전체를 관통한다.

네트워크를 타지 않는다. 어댑터의 fetch만 fixture로 대체하고 그 아래
파싱·정규화·엔터티 해석·저장은 실제 코드를 그대로 쓴다.
"""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.finlife.adapter import FinlifeAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.enums import RunStatus
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_source

FIXTURES = Path(__file__).parent / "fixtures" / "finlife"
REAL = FIXTURES / "deposit_savings_bank_page1.json"

EXPECTED_OPTION_ROWS = 647
EXPECTED_PRODUCTS = 100


def _artifact(path: Path, service: str = "depositProductsSearch", group: str = "030300"):
    return RawArtifactData(
        artifact_type="json",
        content=path.read_bytes(),
        filename=path.name,
        request_meta={
            "url": "http://finlife.fss.or.kr/finlifeapi/depositProductsSearch.json",
            "auth": "[REDACTED]",
            "service": service,
            "topFinGrpNo": group,
            "pageNo": 1,
        },
        schema_fingerprint="fp-test",
        source_role="secondary_official",
        trust_level="official_direct",
    )


class FixtureAdapter(FinlifeAdapter):
    """fetch만 fixture로 대체한다. 파싱 이하는 실제 코드."""

    def __init__(self, paths: list[Path]) -> None:
        super().__init__(api_key="dummy-key-for-offline-test")
        self._paths = paths

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [_artifact(p) for p in self._paths]


class BlockedAdapter(FinlifeAdapter):
    def __init__(self) -> None:
        super().__init__(api_key="dummy")

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        raise SourceBlockedError("403 차단")


@pytest.fixture()
def factory(tmp_path):
    engine = create_db_engine(tmp_path / "collect.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture()
def raw_root(tmp_path) -> Path:
    return tmp_path / "raw"


def run_collect(factory, raw_root, paths=None):
    adapter = FixtureAdapter(paths or [REAL])
    return asyncio.run(
        collect_source(
            adapter, CollectionRequest(source_id="finlife"), factory, raw_root=raw_root
        )
    )


# ── 1차 수집 ────────────────────────────────────────────────────────────

def test_collect_persists_every_option_row(factory, raw_root) -> None:
    result = run_collect(factory, raw_root)
    assert result.status == RunStatus.SUCCESS
    assert result.parsed_count == EXPECTED_OPTION_ROWS

    with factory() as s:
        assert s.scalar(select(func.count()).select_from(m.RateObservation)) == (
            EXPECTED_OPTION_ROWS
        )
        assert s.scalar(select(func.count()).select_from(m.Product)) == EXPECTED_PRODUCTS


def test_every_observation_traces_to_raw_artifact(factory, raw_root) -> None:
    """원본 추적률 100% (P1-A 게이트)."""
    run_collect(factory, raw_root)
    with factory() as s:
        missing = s.scalar(
            select(func.count()).select_from(m.RateObservation).where(
                m.RateObservation.raw_artifact_id.is_(None)
            )
        )
        assert missing == 0


def test_source_locators_never_missing(factory, raw_root) -> None:
    """행 단위 원본 추적 누락 0건 (v3.1 §7)."""
    run_collect(factory, raw_root)
    with factory() as s:
        rows = s.execute(
            text(
                "SELECT COUNT(*) FROM rate_observations "
                "WHERE base_source_locator IS NULL OR base_source_locator = '' "
                "   OR option_source_locator IS NULL "
                "   OR source_record_hash IS NULL OR source_record_hash = ''"
            )
        ).scalar()
        assert rows == 0


def test_raw_files_written_to_disk(factory, raw_root) -> None:
    run_collect(factory, raw_root)
    written = list(raw_root.rglob("*.json"))
    assert len(written) == 1
    with factory() as s:
        artifact = s.scalars(select(m.RawArtifact)).one()
        assert Path(artifact.relative_path).exists()
        assert artifact.content_length == REAL.stat().st_size


def test_request_meta_has_no_api_key(factory, raw_root) -> None:
    """인증키 노출 0건 (P1-A 게이트)."""
    run_collect(factory, raw_root)
    with factory() as s:
        blob = json.dumps(
            [a.request_meta_json for a in s.scalars(select(m.RawArtifact))], ensure_ascii=False
        )
    assert "dummy-key-for-offline-test" not in blob
    assert "[REDACTED]" in blob


def test_max_rate_never_backfilled_from_base(factory, raw_root) -> None:
    """max_rate를 base_rate로 메우지 않았는지 SQL로 확인 (v3 §8.4)."""
    run_collect(factory, raw_root)
    with factory() as s:
        payload = json.loads(REAL.read_text(encoding="utf-8"))
        source_nulls = sum(
            1 for o in payload["result"]["optionList"] if o.get("intr_rate2") is None
        )
        stored_nulls = s.scalar(
            select(func.count()).select_from(m.RateObservation).where(
                m.RateObservation.max_rate.is_(None)
            )
        )
        assert stored_nulls == source_nulls


def test_rate_values_survive_roundtrip(factory, raw_root) -> None:
    """저장된 금리가 원본 값과 같은지. 4자리 왕복 손실 0."""
    run_collect(factory, raw_root)
    payload = json.loads(REAL.read_text(encoding="utf-8"))
    expected = {Decimal(str(o["intr_rate"])) for o in payload["result"]["optionList"]}
    with factory() as s:
        stored = {r.base_rate for r in s.scalars(select(m.RateObservation))}
    assert stored == expected


def test_run_counters_are_real(factory, raw_root) -> None:
    result = run_collect(factory, raw_root)
    with factory() as s:
        run = s.scalars(select(m.CollectionRun)).one()
        assert run.raw_count == 1
        assert run.parsed_count == EXPECTED_OPTION_ROWS
        assert run.valid_count + run.error_count == EXPECTED_OPTION_ROWS
        assert run.finished_at is not None
        assert run.status == result.status


# ── 재수집 ──────────────────────────────────────────────────────────────

def test_recollect_does_not_duplicate_canonical_entities(factory, raw_root) -> None:
    """같은 표본 재수집 시 정규 엔터티 증가 0 (v3.1 §12.2).

    **관측도 늘지 않는다** (선행 수정안 §3.2). 예전에는 실행마다 다시 쌓였다.
    같은 3.10%가 날짜마다 한 줄씩 생겨, 평일 수집으로 1년을 돌면 약 19 GB가
    된다. 이제는 값이 바뀔 때만 행이 생기고, 같으면 seen_count가 오른다.
    """
    run_collect(factory, raw_root)
    with factory() as s:
        before = {
            "institutions": s.scalar(select(func.count()).select_from(m.Institution)),
            "products": s.scalar(select(func.count()).select_from(m.Product)),
            "variants": s.scalar(select(func.count()).select_from(m.ProductVariant)),
        }

    run_collect(factory, raw_root)
    with factory() as s:
        after = {
            "institutions": s.scalar(select(func.count()).select_from(m.Institution)),
            "products": s.scalar(select(func.count()).select_from(m.Product)),
            "variants": s.scalar(select(func.count()).select_from(m.ProductVariant)),
        }
        assert after == before
        assert s.scalar(select(func.count()).select_from(m.CollectionRun)) == 2
        # 값이 그대로이므로 행이 늘지 않는다.
        assert s.scalar(select(func.count()).select_from(m.RateObservation)) == (
            EXPECTED_OPTION_ROWS
        )
        # 대신 두 번 봤다는 사실이 남는다.
        assert s.scalar(select(func.min(m.RateObservation.seen_count))) == 2
        # 살아 있는 행은 비교 단위마다 하나뿐이다.
        assert s.scalar(
            select(func.count()).select_from(m.RateObservation).where(
                m.RateObservation.valid_to.is_(None)
            )
        ) == EXPECTED_OPTION_ROWS


def test_no_duplicate_observation_within_a_run(factory, raw_root) -> None:
    """같은 실행 안에서 (variant_id, run_id) 중복 0."""
    run_collect(factory, raw_root)
    with factory() as s:
        dupes = s.execute(
            text(
                "SELECT COUNT(*) FROM (SELECT variant_id, run_id FROM rate_observations "
                "GROUP BY variant_id, run_id HAVING COUNT(*) > 1)"
            )
        ).scalar()
        assert dupes == 0


# ── 검수항목 ────────────────────────────────────────────────────────────

def test_parser_warnings_become_review_items(factory, raw_root, tmp_path) -> None:
    """고아 옵션 경고가 조용히 사라지지 않고 검수항목으로 남는다."""
    edge = tmp_path / "edge.json"
    edge.write_bytes((FIXTURES / "edge_cases.json").read_bytes())
    run_collect(factory, raw_root, paths=[edge])
    with factory() as s:
        items = s.scalars(select(m.ReviewItem)).all()
        assert any("ORPHAN01" in i.message for i in items)


def test_error_rows_create_review_items(factory, raw_root, tmp_path) -> None:
    edge = tmp_path / "edge.json"
    edge.write_bytes((FIXTURES / "edge_cases.json").read_bytes())
    result = run_collect(factory, raw_root, paths=[edge])
    with factory() as s:
        warn_items = s.scalars(
            select(m.ReviewItem).where(m.ReviewItem.issue_type == "schema_warning")
        ).all()
        assert warn_items
    assert result.warning_count >= 1


# ── 실패 경로 ───────────────────────────────────────────────────────────

def test_blocked_source_writes_no_observations(factory, raw_root) -> None:
    """차단 시 관측값을 쓰지 않고 실행 상태만 남긴다 (v3 §10.3)."""
    adapter = BlockedAdapter()
    result = asyncio.run(
        collect_source(
            adapter, CollectionRequest(source_id="finlife"), factory, raw_root=raw_root
        )
    )
    assert result.status == RunStatus.BLOCKED
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(m.RateObservation)) == 0
        run = s.scalars(select(m.CollectionRun)).one()
        assert run.status == RunStatus.BLOCKED
        assert run.finished_at is not None


def test_failure_preserves_previous_good_values(factory, raw_root) -> None:
    """실패한 실행이 이전 정상값을 지우지 않는다."""
    run_collect(factory, raw_root)
    with factory() as s:
        before = s.scalar(select(func.count()).select_from(m.RateObservation))

    asyncio.run(
        collect_source(
            BlockedAdapter(), CollectionRequest(source_id="finlife"), factory,
            raw_root=raw_root,
        )
    )
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(m.RateObservation)) == before


# ── 어댑터 계약 ─────────────────────────────────────────────────────────

def test_adapter_requires_api_key(monkeypatch) -> None:
    from rate_monitor.collectors.base import CollectorError

    monkeypatch.delenv("FINLIFE_API_KEY", raising=False)
    with pytest.raises(CollectorError, match="FINLIFE_API_KEY"):
        FinlifeAdapter()


# ── 적금: 정액/자유 적립식 구분 (실제 수집에서 드러난 결함) ──────────────

SAVING = FIXTURES / "saving_savings_bank_page1.json"


def test_saving_reserve_types_are_distinct_variants(factory, raw_root) -> None:
    """정액적립식과 자유적립식은 다른 비교 단위다 (명세서 v3 §5.2).

    이 값이 키에 없으면 같은 상품·기간·이자방식의 두 옵션이 같은 키를 받아
    (variant_id, run_id) 유니크 제약에 걸린다. 2026-08-05 실제 수집에서
    적금 428행 중 12개 조합이 충돌해 수집이 중단됐다.
    """
    payload = json.loads(SAVING.read_text(encoding="utf-8"))
    options = payload["result"]["optionList"]

    adapter = FixtureAdapter([SAVING])
    adapter._paths = [SAVING]
    result = asyncio.run(
        collect_source(
            adapter, CollectionRequest(source_id="finlife"), factory, raw_root=raw_root
        )
    )
    assert result.status == RunStatus.SUCCESS
    # 옵션 1건당 관측 1건. 충돌로 버려진 행이 없어야 한다.
    assert result.parsed_count == len(options)
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(m.RateObservation)) == len(options)


def test_reserve_type_stored_as_stable_code(factory, raw_root) -> None:
    """적립유형은 한글 표기가 아니라 코드로 저장한다.

    비교단위 키에 들어가므로 표기가 바뀌어도 이력이 끊기면 안 된다.
    """
    adapter = FixtureAdapter([SAVING])
    asyncio.run(
        collect_source(
            adapter, CollectionRequest(source_id="finlife"), factory, raw_root=raw_root
        )
    )
    with factory() as s:
        methods = {
            v.payment_method for v in s.scalars(select(m.ProductVariant)) if v.payment_method
        }
    assert methods <= {"S", "F"}, f"코드가 아닌 값이 섞였다: {methods}"


def test_duplicate_guard_is_shared_across_artifacts(factory, raw_root) -> None:
    """중복 방지 집합은 실행 단위로 유지돼야 한다.

    아티팩트(페이지)마다 새로 만들면 페이지 경계를 넘는 중복을 놓쳐
    (variant_id, run_id) 유니크 제약에 걸린다. persist_rows를 두 번 호출해
    두 번째 호출이 중복을 걸러내는지 직접 확인한다.
    """
    from datetime import UTC, datetime

    from rate_monitor.services.collection_service import ensure_source, persist_rows

    adapter = FixtureAdapter([SAVING])
    now = datetime.now(UTC).replace(tzinfo=None)
    rows, _ = adapter.parse_with_warnings(_artifact(SAVING))

    with factory() as s:
        ensure_source(s, adapter, now)
        run = m.CollectionRun(
            # ensure_source가 만든 행을 가리켜야 한다. 이름을 못 박으면
            # 소스가 갈릴 때(v4 §6.2) 외래키가 깨진다.
            id="run-dup", source_id=adapter.source_id, mode="api",
            started_at=now, status="running",
        )
        artifact = m.RawArtifact(
            id="art-dup", run_id="run-dup", artifact_type="json", relative_path="p.json",
            sha256="c" * 64, content_length=1, captured_at=now,
        )
        s.add_all([run, artifact])
        s.flush()

        seen: set[str] = set()
        first_valid, _ = persist_rows(s, run, rows, artifact, now, seen)
        second_valid, _ = persist_rows(s, run, rows, artifact, now, seen)
        s.commit()

        assert first_valid == len(rows)
        assert second_valid == 0, "두 번째 호출은 전부 중복으로 걸러져야 한다"

        dupes = s.execute(
            text(
                "SELECT COUNT(*) FROM (SELECT variant_id, run_id FROM rate_observations "
                "GROUP BY variant_id, run_id HAVING COUNT(*) > 1)"
            )
        ).scalar()
        assert dupes == 0
        items = s.scalars(
            select(m.ReviewItem).where(m.ReviewItem.issue_type == "duplicate")
        ).all()
        assert len(items) == len(rows), "중복은 조용히 버리지 말고 검수항목으로 남겨야 한다"
