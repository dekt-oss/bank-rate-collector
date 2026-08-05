"""공용 계층 계약 검증 — 수집원이 둘 이상일 때 깨지던 가정들.

finlife 하나만 있을 때 굳어진 가정 넷을 풀었다. 이 파일은 그 넷이 실제로
풀렸는지 확인한다. 네트워크를 타지 않는다.

1. 권역(sector)을 rate_scope로 추측하지 않는다
2. 점포를 주는 원천은 outlet 행과 outlet_id를 갖는다
3. sources 행의 메타데이터를 어댑터에서 읽는다
4. 파싱 중 구조 변경이 예외로 튀지 않고 실행 상태로 끝난다
"""

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from rate_monitor.collectors.base import SchemaChangedError
from rate_monitor.collectors.finlife.adapter import FinlifeAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.domain.enums import (
    AvailabilityScope,
    CollectionMode,
    InterestMethod,
    JoinChannel,
    ProductType,
    RateScope,
    RunStatus,
    Sector,
    SourceRole,
    TrustLevel,
)
from rate_monitor.domain.identifiers import make_org_key
from rate_monitor.domain.schemas import (
    CollectionRequest,
    ParsedRateRow,
    RawArtifactData,
)
from rate_monitor.services import entity_service
from rate_monitor.services.collection_service import collect_source


@pytest.fixture
def factory(tmp_path: Path):
    engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path / 'test.sqlite3'}")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(tzinfo=None)


def _seed_source(factory, source_id: str = "kfcc") -> None:
    """source_entity_links가 sources를 FK로 참조하므로 먼저 만든다.

    실제 파이프라인에서는 ensure_source가 이 일을 한다. 엔터티 해석 함수만
    떼어 시험할 때는 여기서 대신 세운다.
    """
    from rate_monitor.db.session import session_scope

    now = _now()
    with session_scope(factory) as session:
        session.add(
            m.Source(
                id=source_id,
                name="테스트 원천",
                sector=Sector.KFCC,
                mode=CollectionMode.HTTP,
                source_role=SourceRole.PRIMARY_OFFICIAL,
                trust_level=TrustLevel.OFFICIAL_DIRECT,
                priority=10,
                base_reference="test",
                enabled=True,
                policy_status="review",
                coverage_status="partial",
                created_at=now,
                updated_at=now,
            )
        )


def _row(**overrides) -> ParsedRateRow:
    """새마을금고 모양의 행. 점포키와 권역을 가진다."""
    base = dict(
        source_id="kfcc",
        source_role=SourceRole.PRIMARY_OFFICIAL,
        trust_level=TrustLevel.OFFICIAL_DIRECT,
        sector=Sector.KFCC,
        source_institution_key="1203",
        source_outlet_key="1203:001",
        source_product_key=None,
        institution_name="대청",
        outlet_name="본점",
        institution_type="지역",
        sido="부산",
        sigungu="중구",
        address="부산 중구 대청로 101-1",
        product_type=ProductType.TERM_DEPOSIT,
        product_name="정기예탁금",
        term_months=12,
        term_days=None,
        join_channel=JoinChannel.BRANCH,
        interest_method=InterestMethod.SIMPLE,
        payment_method=None,
        amount_min=None,
        amount_max=None,
        customer_scope=None,
        availability_scope=AvailabilityScope.LOCAL_MEMBERS,
        rate_scope=RateScope.INSTITUTION,
        base_rate=Decimal("3.5000"),
        max_rate=None,
        preference_raw="",
        source_row_ref="1203/001/12",
        base_source_locator="table[0]/tr[1]",
        source_record_hash="sha256:test",
    )
    base.update(overrides)
    return ParsedRateRow(**base)


# ── 1. 권역을 추측하지 않는다 ────────────────────────────────────────────


def test_sector_comes_from_the_row_not_from_rate_scope(factory) -> None:
    """rate_scope=institution인 행이 bank로 판정되면 안 된다.

    예전 구현은 rate_scope가 head_office_reference가 아니면 무조건 bank를
    돌려줬다. 그 값이 make_org_key에 들어가 "bank:1203"이라는 틀린 키를
    만든다.
    """
    from rate_monitor.db.session import session_scope

    _seed_source(factory)
    with session_scope(factory) as session:
        institution = entity_service.resolve_institution(session, _row(), _now())
        assert institution.sector == Sector.KFCC

    expected = make_org_key(
        sector=Sector.KFCC, source_institution_key="1203", institution_name="대청"
    )
    assert expected == "kfcc:1203"
    assert not expected.startswith("bank:")


def test_finlife_still_reports_savings_bank() -> None:
    """회귀 확인. 저축은행 권역코드는 그대로 savings_bank여야 한다."""
    from rate_monitor.collectors.finlife import parser

    payload = {
        "result": {
            "err_cd": "000",
            "total_count": 1,
            "max_page_no": 1,
            "now_page_no": 1,
            "baseList": [
                {
                    "fin_co_no": "0010345",
                    "fin_prdt_cd": "X1",
                    "kor_co_nm": "테스트저축은행",
                    "fin_prdt_nm": "정기예금",
                    "join_way": "영업점",
                    "dcls_strt_day": "20260720",
                }
            ],
            "optionList": [
                {
                    "fin_co_no": "0010345",
                    "fin_prdt_cd": "X1",
                    "intr_rate_type": "S",
                    "save_trm": "12",
                    "intr_rate": "3.5",
                    "intr_rate2": "3.8",
                }
            ],
        }
    }
    rows, _ = parser.parse(payload, "depositProductsSearch", "030300")
    assert rows[0].sector == Sector.SAVINGS_BANK

    rows_bank, _ = parser.parse(payload, "depositProductsSearch", "020000")
    assert rows_bank[0].sector == Sector.BANK


# ── 2. 점포 ─────────────────────────────────────────────────────────────


def test_outlet_is_created_and_linked_to_the_variant(factory) -> None:
    from rate_monitor.db.session import session_scope

    _seed_source(factory)
    now = _now()
    with session_scope(factory) as session:
        row = _row()
        institution = entity_service.resolve_institution(session, row, now)
        outlet = entity_service.resolve_outlet(session, row, institution, now)
        product = entity_service.resolve_product(session, row, institution, now)
        variant = entity_service.resolve_variant(
            session, row, product, institution, outlet
        )

        assert outlet is not None
        assert outlet.name == "본점"
        assert outlet.address == "부산 중구 대청로 101-1"
        # 화면 파라미터를 행정구역 공식 코드로 쓰지 않는다.
        assert outlet.sido_code is None
        assert outlet.sigungu_code is None
        assert variant.outlet_id == outlet.id


def test_outlet_is_not_duplicated_on_recollection(factory) -> None:
    """같은 점포키를 두 번 처리해도 행이 하나여야 한다."""
    from rate_monitor.db.session import session_scope

    _seed_source(factory)
    now = _now()
    for _ in range(2):
        with session_scope(factory) as session:
            row = _row()
            institution = entity_service.resolve_institution(session, row, now)
            entity_service.resolve_outlet(session, row, institution, now)

    with session_scope(factory) as session:
        outlets = session.scalars(select(m.Outlet)).all()
        assert len(outlets) == 1


def test_source_without_outlet_key_creates_no_outlet(factory) -> None:
    """finlife처럼 점포키가 없는 원천은 점포를 만들지 않는다."""
    from rate_monitor.db.session import session_scope

    _seed_source(factory)
    now = _now()
    with session_scope(factory) as session:
        row = _row(source_outlet_key=None, outlet_name=None)
        institution = entity_service.resolve_institution(session, row, now)
        outlet = entity_service.resolve_outlet(session, row, institution, now)
        assert outlet is None

    with session_scope(factory) as session:
        assert session.scalars(select(m.Outlet)).all() == []


# ── 3. sources 메타데이터를 어댑터에서 읽는다 ──────────────────────────


class _StubAdapter(FinlifeAdapter):
    """메타데이터만 새마을금고처럼 바꾼 어댑터."""

    source_id = "kfcc"
    source_name = "새마을금고 금고위치안내"
    sector = Sector.KFCC
    mode = CollectionMode.HTTP
    priority = 10
    base_reference = "kfcc.co.kr/map"
    policy_status = "review"
    source_role = SourceRole.PRIMARY_OFFICIAL

    def __init__(self) -> None:
        super().__init__(api_key="dummy")

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return []


def test_ensure_source_reads_metadata_from_the_adapter(factory, tmp_path) -> None:
    """finlife 값이 하드코딩돼 있으면 이 테스트가 실패한다.

    특히 policy_status가 틀리면 안 된다. 새마을금고는 약관 미확인이라
    review여야 하는데 예전 구현은 무조건 allowed를 넣었다.
    """
    asyncio.run(
        collect_source(
            _StubAdapter(),
            CollectionRequest(source_id="kfcc"),
            factory,
            raw_root=tmp_path / "raw",
        )
    )
    from rate_monitor.db.session import session_scope

    with session_scope(factory) as session:
        source = session.get(m.Source, "kfcc")
        assert source is not None
        assert source.name == "새마을금고 금고위치안내"
        assert source.sector == Sector.KFCC
        assert source.mode == CollectionMode.HTTP
        assert source.priority == 10
        assert source.base_reference == "kfcc.co.kr/map"
        assert source.policy_status == "review"

        run = session.scalars(select(m.CollectionRun)).one()
        assert run.mode == CollectionMode.HTTP


# ── 4. 파싱 실패가 예외로 튀지 않는다 ───────────────────────────────────


class _SchemaBreakAdapter(FinlifeAdapter):
    """fetch는 성공하고 parse에서 구조 변경을 발견하는 어댑터."""

    def __init__(self) -> None:
        super().__init__(api_key="dummy")

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [
            RawArtifactData(
                artifact_type="json",
                content=b"{}",
                filename="broken.json",
                request_meta={"service": "depositProductsSearch", "topFinGrpNo": "030300"},
                schema_fingerprint="fp",
                source_role=self.source_role,
                trust_level=self.trust_level,
            )
        ]

    def parse_with_warnings(self, artifact: RawArtifactData):
        raise SchemaChangedError("baseList가 사라졌다")


def test_parse_time_schema_change_becomes_a_run_status(factory, tmp_path) -> None:
    """예전에는 이 예외가 호출자까지 올라가 CLI가 traceback으로 죽었다.

    HTML을 긁는 수집원에서는 구조 변경이 주된 실패 모드다.
    """
    result = asyncio.run(
        collect_source(
            _SchemaBreakAdapter(),
            CollectionRequest(source_id="finlife"),
            factory,
            raw_root=tmp_path / "raw",
        )
    )
    assert result.status == RunStatus.SCHEMA_CHANGED
    assert "baseList" in result.message

    from rate_monitor.db.session import session_scope

    with session_scope(factory) as session:
        run = session.scalars(select(m.CollectionRun)).one()
        assert run.status == RunStatus.SCHEMA_CHANGED
        # 실패한 실행은 관측값을 남기지 않는다 (v3 §10.3).
        assert session.scalars(select(m.RateObservation)).all() == []
