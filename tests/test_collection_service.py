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

    관측은 실행별로 다시 쌓여야 한다. 이력이 남아야 하므로.
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
        assert s.scalar(select(func.count()).select_from(m.RateObservation)) == (
            EXPECTED_OPTION_ROWS * 2
        )


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
