"""농·축협 저장 경로 검증 — fixture로 전 구간을 관통한다 (v4 §5, PR 4).

어댑터의 `fetch`만 fixture로 대체하고 그 아래 파싱·정규화·엔터티 해석·저장은
실제 코드를 그대로 쓴다. **네트워크를 호출하지 않는다.**

범위 결정(`_load_prefixes`)과 CLI 인자 검사는 네트워크 없이 도는 부분이라
실물 config로 그대로 검사한다.
"""

import argparse
import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select

from rate_monitor.collectors.nh_local import parser as nh
from rate_monitor.collectors.nh_local.adapter import DEFAULT_PRODUCTS, NhLocalAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.enums import GeoBasis, ProductType, RateScope, RunStatus, Sector
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_source

FIXTURES = Path(__file__).parent / "fixtures" / "nh_local"

# tests/test_nh_local_parser.py가 고정한 실측값
EXPECTED_DEPOSIT_ROWS = 24
EXPECTED_SAVINGS_ROWS = 17
EXPECTED_TOTAL = EXPECTED_DEPOSIT_ROWS + EXPECTED_SAVINGS_ROWS

AS_OF = "2026-08-06"
_OUTLET = {
    "brc": "333072",
    "name": "강릉농협 강동지점",
    "address": "강원특별자치도 강릉시 강동면 와천로 463",
}


def _rate_artifact(filename: str, product_type: ProductType) -> RawArtifactData:
    path = FIXTURES / filename
    return RawArtifactData(
        artifact_type="html",
        content=path.read_bytes(),
        filename=path.name,
        request_meta={
            "kind": "rate",
            "screen": nh.SCREEN_BY_PRODUCT[product_type],
            "product_type": product_type.value,
            "as_of": AS_OF,
            "outlet": _OUTLET,
        },
        schema_fingerprint="fp",
        source_role=NhLocalAdapter.source_role,
        trust_level=NhLocalAdapter.trust_level,
    )


def _list_artifact() -> RawArtifactData:
    path = FIXTURES / "outlet_list_busan.html"
    return RawArtifactData(
        artifact_type="html",
        content=path.read_bytes(),
        filename=path.name,
        request_meta={"kind": "list", "screen": "SFDPW0161R"},
        schema_fingerprint="list",
        source_role=NhLocalAdapter.source_role,
        trust_level=NhLocalAdapter.trust_level,
    )


class FixtureAdapter(NhLocalAdapter):
    """fetch만 fixture로 대체한다. 파싱 이하는 실제 코드."""

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [
            _list_artifact(),
            _rate_artifact("deposit_detail_333072.html", ProductType.TERM_DEPOSIT),
            _rate_artifact(
                "saving_detail_333072.html", ProductType.INSTALLMENT_SAVINGS
            ),
        ]


@pytest.fixture()
def factory(tmp_path: Path):
    engine = create_db_engine(tmp_path / "nh.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def run_collect(factory, raw_root: Path):
    return asyncio.run(
        collect_source(
            FixtureAdapter(),
            CollectionRequest(source_id="nh_local", options={"scope": "부산"}),
            factory,
            raw_root=raw_root,
        )
    )


# ── 저장 ────────────────────────────────────────────────────────────────


def test_collect_stores_every_parsed_row(factory, tmp_path) -> None:
    result = run_collect(factory, tmp_path / "raw")
    assert result.status == RunStatus.SUCCESS
    assert result.parsed_count == EXPECTED_TOTAL
    assert result.error_count == 0

    with session_scope(factory) as session:
        observations = session.scalar(
            select(func.count()).select_from(m.RateObservation)
        )
        assert observations == EXPECTED_TOTAL
        # 명부 아티팩트도 저장되지만 금리 행은 만들지 않는다.
        assert session.scalar(select(func.count()).select_from(m.RawArtifact)) == 3


def test_source_row_carries_nh_metadata(factory, tmp_path) -> None:
    """다른 원천의 값이 새어 들어오면 안 된다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        source = session.get(m.Source, "nh_local")
        assert source.name == "농협 금융상품몰 농·축협별 예금금리"
        assert source.sector == Sector.NH_LOCAL
        # 사용자가 2026-08-06에 약관을 직접 확인했다.
        assert source.policy_status == "allowed"


def test_max_rate_is_never_filled(factory, tmp_path) -> None:
    """이 화면에 최고우대금리 열이 없다. base_rate로 메우면 안 된다 (v4 §3.3)."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        filled = session.scalar(
            select(func.count())
            .select_from(m.RateObservation)
            .where(m.RateObservation.max_rate.is_not(None))
        )
        assert filled == 0


def test_rates_are_scoped_to_the_outlet(factory, tmp_path) -> None:
    """금리가 점포 단위다. 조합마다 다르고 지점마다 다르다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        scopes = set(session.scalars(select(m.ProductVariant.rate_scope)).all())
        assert scopes == {RateScope.OUTLET}


def test_region_comes_from_the_outlet_address(factory, tmp_path) -> None:
    """지역은 파서가 아니라 저장 계층이 주소에서 뽑는다 (v4 §4).

    fixture 점포는 강원특별자치도다. 부산 범위로 돌렸다고 부산이 되면 안 된다.
    시도 이름은 `SIDO_ALIASES`가 통일한다 (강원특별자치도 → 강원).
    """
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        outlet = session.scalars(select(m.Outlet)).one()
        assert outlet.region_sido == "강원"
        assert outlet.region_sigungu == "강릉시"
        assert outlet.geo_basis == GeoBasis.OUTLET_ADDRESS
        # 주소를 파싱했다고 공식 행정구역 코드를 지어내지 않는다.
        assert outlet.sido_code is None and outlet.sigungu_code is None


def test_observations_are_traceable(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        rows = session.scalars(select(m.RateObservation)).all()
        assert len(rows) == EXPECTED_TOTAL
        assert all(r.raw_artifact_id is not None for r in rows)
        assert all(r.base_source_locator for r in rows)
        # 기준일은 조회일이다. 원천이 공시일을 따로 주지 않는다.
        assert {str(r.source_effective_at) for r in rows} == {AS_OF}


def test_no_phone_number_reaches_the_database(factory, tmp_path) -> None:
    """명부 HTML에 전화번호가 있지만 어느 칸에도 들어가면 안 된다."""
    assert "051-" in (FIXTURES / "outlet_list_busan.html").read_text(encoding="utf-8")
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        outlets = session.scalars(select(m.Outlet)).all()
        institutions = session.scalars(select(m.Institution)).all()
        persisted_text = [
            value
            for row in (*outlets, *institutions)
            for column in row.__table__.columns
            if column.name != "id" and not column.name.endswith("_id")
            if isinstance((value := getattr(row, column.name)), str)
        ]
        assert all("033-" not in value and "051-" not in value for value in persisted_text)


# ── 범위 ────────────────────────────────────────────────────────────────


def test_the_default_scope_is_nationwide_now() -> None:
    """기본이 전국이다 (2026-08-07 변경. 그 전에는 부산이었다).

    부산만 받는 동안 화면이 거짓 인상을 줬다. 농·축협 4,920행 대 새마을금고
    93,816행이라 "새마을금고가 압도적으로 많다"로 읽혔는데, **실제 점포는
    농·축협 4,871곳이 새마을금고 3,135곳보다 많다.** 적게 보인 이유는 우리가
    부산 120곳만 받았기 때문이다. 수집 범위가 만든 차이를 사람은 업권의
    차이로 읽는다.

    전국은 실측 3시간 37분이다(run 23의 부산 120점포 5분 20초 → 점포당
    2.67초 × 4,871점포). 그래서 같은 실행에서 새마을금고를 뺐다 — 둘을 한
    작업에 넣으면 6시간 3분이라 GitHub의 작업당 6시간 한도를 넘는다. 나눈
    자리는 `tests/test_gate_contract.py`가 지킨다.

    `None`은 "주소로 거르지 않는다" = 전국이다. 빈 목록과 다르다.
    """
    adapter = NhLocalAdapter()
    assert adapter._load_prefixes(CollectionRequest(source_id="nh_local")) is None


def test_busan_is_still_reachable_on_purpose() -> None:
    """기본이 전국이 됐다고 부산을 못 고르면 안 된다.

    화면 작업 중에 3시간 37분을 기다릴 이유가 없다.
    """
    adapter = NhLocalAdapter()
    request = CollectionRequest(source_id="nh_local", options={"scope": "부산"})
    assert adapter._load_prefixes(request) == ("부산광역시", "부산 ")


def test_nationwide_scope_filters_nothing() -> None:
    """`전국`은 빈 목록이 아니라 `None`이다 — 빈 목록이면 0건이 된다."""
    adapter = NhLocalAdapter()
    request = CollectionRequest(source_id="nh_local", options={"scope": "전국"})
    assert adapter._load_prefixes(request) is None


def test_an_unknown_scope_is_refused_not_ignored() -> None:
    """모르는 범위를 조용히 넘기면 0건 수집이 '금리가 없었다'처럼 보인다."""
    adapter = NhLocalAdapter()
    request = CollectionRequest(source_id="nh_local", options={"scope": "경상권"})
    with pytest.raises(ValueError, match="config에 없는 수집 범위"):
        adapter._load_prefixes(request)


def test_the_busan_scope_matches_the_roster_fixture() -> None:
    """config의 접두어가 실물 명부의 부산 주소를 실제로 잡는가."""
    adapter = NhLocalAdapter()
    prefixes = adapter._load_prefixes(
        CollectionRequest(source_id="nh_local", options={"scope": "부산"})
    )
    outlets = nh.parse_outlet_list(
        (FIXTURES / "outlet_list_busan.html").read_text(encoding="utf-8")
    )
    assert len(nh.outlets_in(outlets, prefixes)) == len(outlets) == 120


def test_the_input_type_screen_is_not_collected_yet() -> None:
    """입출금식 화면의 실물을 아직 못 봤다. 본 적 없는 표를 긁지 않는다."""
    assert ProductType.DEMAND_DEPOSIT not in DEFAULT_PRODUCTS
    assert set(DEFAULT_PRODUCTS) == {
        ProductType.TERM_DEPOSIT,
        ProductType.INSTALLMENT_SAVINGS,
    }


# ── CLI ─────────────────────────────────────────────────────────────────


def test_cli_refuses_regions_for_this_source() -> None:
    """원천에 지역 요청 인자가 없다. `--regions 부산`은 실행 이력을 속인다."""
    from rate_monitor.cli import REQUEST_BUILDERS

    args = argparse.Namespace(source="nh_local", regions=["부산"], scope=None)
    with pytest.raises(ValueError, match="--regions"):
        REQUEST_BUILDERS["nh_local"](args)

    ok = REQUEST_BUILDERS["nh_local"](
        argparse.Namespace(source="nh_local", regions=None, scope="부산")
    )
    assert ok.regions == () and ok.options == {"scope": "부산"}


def test_the_adapter_is_registered() -> None:
    from rate_monitor.cli import ADAPTERS

    assert ADAPTERS["nh_local"] is NhLocalAdapter
