"""신협 파서·저장 검증 — 실물 fixture로 계약을 못박는다.

fixture는 2026-08-05에 공식 화면에서 받은 실제 응답이다. 네트워크를
호출하지 않는다.

    tests/fixtures/cu/findInrst15_busan.json   거치식예금 부산 12개월 50건
    tests/fixtures/cu/findInrst17_busan.json   적립식예금 부산 12개월 50건
"""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from rate_monitor.collectors.base import SchemaChangedError
from rate_monitor.collectors.cu import parser
from rate_monitor.collectors.cu.adapter import CuAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.enums import (
    InterestMethod,
    ProductType,
    RateScope,
    RunStatus,
    Sector,
)
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_source

FIXTURES = Path(__file__).parent / "fixtures" / "cu"


def _rows(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def deposit() -> list[dict]:
    return _rows("findInrst15_busan.json")


@pytest.fixture(scope="module")
def savings() -> list[dict]:
    return _rows("findInrst17_busan.json")


def _artifact(name: str, screen: str) -> RawArtifactData:
    return RawArtifactData(
        artifact_type="json",
        content=(FIXTURES / name).read_bytes(),
        filename=name,
        request_meta={
            "screen": screen, "sido": "04", "sido_name": "부산",
            "term_months": 12, "page_offset": 0,
        },
        schema_fingerprint=f"fp-{screen}",
        source_role=CuAdapter.source_role,
        trust_level=CuAdapter.trust_level,
    )


# ── fixture 자체 모양 ───────────────────────────────────────────────────


def test_fixture_shape_is_pinned(deposit: list[dict], savings: list[dict]) -> None:
    assert len(deposit) == 50
    assert len(savings) == 50
    assert parser.total_count(deposit) == 279
    assert parser.total_count(savings) == 287


# ── 이 원천의 핵심 가치 ─────────────────────────────────────────────────


def test_both_base_and_max_rate_are_present(deposit: list[dict]) -> None:
    """지역과 최고 우대금리를 동시에 주는 유일한 원천이다.

    새마을금고는 우대금리 열 자체가 없고, 저축은행은 본점 기준이라 지역이
    없다. 신협만 둘 다 준다.
    """
    rows, _ = parser.parse(deposit, screen="findInrst15", sido="04", sido_name="부산")
    assert all(r.base_rate is not None for r in rows)
    assert all(r.max_rate is not None for r in rows)
    # 우대조건이 있는 상품은 최고금리가 기본금리보다 높다.
    higher = [r for r in rows if r.max_rate > r.base_rate]
    assert higher, "fixture에 우대금리가 붙은 상품이 있어야 검사가 성립한다"


def test_rate_is_parsed_from_a_percent_string(deposit: list[dict]) -> None:
    """`"3.40%"` 형태로 온다. 문자열을 그대로 저장하면 비교가 안 된다."""
    assert deposit[0]["baseRate"].endswith("%")
    rows, _ = parser.parse(deposit, screen="findInrst15", sido="04", sido_name="부산")
    assert isinstance(rows[0].base_rate, Decimal)
    assert str(rows[0].base_rate) == deposit[0]["baseRate"].rstrip("%")


def test_region_comes_from_the_query_not_the_row(deposit: list[dict]) -> None:
    """응답 행에 지역이 없다. 조회 조건에서 온 값임을 분명히 한다."""
    assert "sido" not in deposit[0]
    rows, _ = parser.parse(deposit, screen="findInrst15", sido="04", sido_name="부산")
    assert {r.sido for r in rows} == {"부산"}
    # 점포 주소가 아니므로 시군구와 주소는 비운다. 지어내지 않는다.
    assert {r.sigungu for r in rows} == {None}
    assert {r.address for r in rows} == {None}


def test_rate_scope_is_institution(deposit: list[dict]) -> None:
    """금리는 조합 단위 공시다. 점포별 적용금리가 아니다."""
    rows, _ = parser.parse(deposit, screen="findInrst15", sido="04", sido_name="부산")
    assert {r.rate_scope for r in rows} == {RateScope.INSTITUTION}
    assert {r.sector for r in rows} == {Sector.CU}


def test_product_type_comes_from_the_screen(
    deposit: list[dict], savings: list[dict]
) -> None:
    depo, _ = parser.parse(deposit, screen="findInrst15", sido="04")
    inst, _ = parser.parse(savings, screen="findInrst17", sido="04")
    assert {r.product_type for r in depo} == {ProductType.TERM_DEPOSIT}
    assert {r.product_type for r in inst} == {ProductType.INSTALLMENT_SAVINGS}


def test_interest_method_is_not_guessed(deposit: list[dict]) -> None:
    """화면이 단리·복리를 구분해 주지 않는다. 추측하면 거짓이 된다."""
    rows, _ = parser.parse(deposit, screen="findInrst15", sido="04")
    assert {r.interest_method for r in rows} == {InterestMethod.UNKNOWN}


def test_channel_comes_from_the_official_field(deposit: list[dict]) -> None:
    rows, _ = parser.parse(deposit, screen="findInrst15", sido="04")
    assert {r.join_channel for r in rows} <= {"branch", "internet", "mobile", "any"}


def test_effective_date_comes_from_the_page(deposit: list[dict]) -> None:
    rows, _ = parser.parse(deposit, screen="findInrst15", sido="04")
    assert all(r.source_effective_at is not None for r in rows)


def test_contact_number_is_not_stored(deposit: list[dict]) -> None:
    """`ownTelNo`에 담당자 연락처가 온다. 저장하지 않는다."""
    assert deposit[0]["ownTelNo"]
    rows, _ = parser.parse(deposit, screen="findInrst15", sido="04")
    blob = json.dumps([r.extra for r in rows], ensure_ascii=False)
    assert deposit[0]["ownTelNo"] not in blob


def test_record_hash_ignores_paging_fields(deposit: list[dict]) -> None:
    """페이지를 다르게 넘겼다고 금리가 바뀐 것으로 잡히면 안 된다."""
    record = deposit[0]
    repaged = dict(record, rnum=999, listTotalCount=1)
    assert parser._record_hash(record) == parser._record_hash(repaged)

    moved = dict(record, baseRate="9.99%")
    assert parser._record_hash(record) != parser._record_hash(moved)


def test_page_offset_shifts_the_locator(deposit: list[dict]) -> None:
    rows, _ = parser.parse(deposit, screen="findInrst15", sido="04", page_offset=50)
    assert rows[0].base_source_locator == "$[50].baseRate"


def test_parsing_is_deterministic(deposit: list[dict]) -> None:
    a, _ = parser.parse(deposit, screen="findInrst15", sido="04")
    b, _ = parser.parse(deposit, screen="findInrst15", sido="04")
    assert a == b


# ── 구조 변화 ───────────────────────────────────────────────────────────


def test_missing_required_field_is_breaking(deposit: list[dict]) -> None:
    broken = [{k: v for k, v in deposit[0].items() if k != "cuIngno"}]
    with pytest.raises(SchemaChangedError, match="cuIngno"):
        parser.check_schema(broken)


def test_missing_optional_field_is_only_a_warning(deposit: list[dict]) -> None:
    softened = [{k: v for k, v in deposit[0].items() if k != "highRate"}]
    assert any("highRate" in w for w in parser.check_schema(softened))


def test_unreadable_rate_becomes_error_not_a_silent_null(deposit: list[dict]) -> None:
    bad = [dict(deposit[0], baseRate="조합문의")]
    rows, _ = parser.parse(bad, screen="findInrst15", sido="04")
    assert rows[0].base_rate is None
    assert rows[0].validation_status == "error"


# ── 어댑터 계약 ─────────────────────────────────────────────────────────


def test_all_is_not_an_empty_string() -> None:
    """빈 문자열로 보내면 조용히 0건이 온다. 화면 기본값은 AA다."""
    adapter = CuAdapter()
    body = adapter._rate_body(page=1, sido="AA", term=12)
    assert body["subSido"] == "AA"
    assert body["tretChlTy"] == "A"
    # 쉼표가 빠지면 역시 0건이 온다.
    assert body["highLimtAmt"] == "10,000,000"


def test_region_names_resolve_to_screen_codes() -> None:
    adapter = CuAdapter()
    assert adapter._resolve_sidos(
        CollectionRequest(source_id="cu", regions=("부산",))
    ) == ["04"]
    # 지역을 안 주면 전체 한 번으로 끝낸다.
    assert adapter._resolve_sidos(CollectionRequest(source_id="cu")) == ["AA"]


def test_unknown_region_is_rejected() -> None:
    adapter = CuAdapter()
    with pytest.raises(ValueError, match="신협 화면에 없는 지역"):
        adapter._resolve_sidos(
            CollectionRequest(source_id="cu", regions=("부산광역시",))
        )


# ── 저장 경로 ───────────────────────────────────────────────────────────


class FixtureAdapter(CuAdapter):
    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [
            _artifact("findInrst15_busan.json", "findInrst15"),
            _artifact("findInrst17_busan.json", "findInrst17"),
        ]


@pytest.fixture
def factory(tmp_path: Path):
    engine = create_db_engine(tmp_path / "cu.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def run_collect(factory, raw_root: Path):
    return asyncio.run(
        collect_source(
            FixtureAdapter(),
            CollectionRequest(source_id="cu", regions=("부산",)),
            factory,
            raw_root=raw_root,
        )
    )


def test_collect_stores_every_parsed_row(factory, tmp_path) -> None:
    result = run_collect(factory, tmp_path / "raw")
    assert result.status == RunStatus.SUCCESS
    assert result.parsed_count == 100
    assert result.error_count == 0

    with session_scope(factory) as session:
        assert session.scalar(
            select(func.count()).select_from(m.RateObservation)
        ) == 100


def test_source_row_uses_cu_metadata(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        source = session.get(m.Source, "cu")
        assert source.name == "신협 전자공시 금리비교"
        assert source.sector == Sector.CU
        assert source.policy_status == "review"


def test_institution_key_carries_the_sector(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        links = session.scalars(
            select(m.SourceEntityLink).where(
                m.SourceEntityLink.entity_type == "institution"
            )
        ).all()
        assert links
        assert all(link.source_entity_key.startswith("cu:") for link in links)


def test_max_rate_survives_storage(factory, tmp_path) -> None:
    """최고금리가 저장까지 살아남는지. 이 원천의 존재 이유다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        filled = session.scalar(
            select(func.count())
            .select_from(m.RateObservation)
            .where(m.RateObservation.max_rate.is_not(None))
        )
        assert filled == 100


def test_no_duplicate_observations_within_one_run(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        dupes = session.execute(
            select(m.RateObservation.run_id, m.RateObservation.variant_id, func.count())
            .group_by(m.RateObservation.run_id, m.RateObservation.variant_id)
            .having(func.count() > 1)
        ).all()
        assert dupes == []


def test_recollect_does_not_duplicate_canonical_entities(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        before = {
            "institutions": session.scalar(
                select(func.count()).select_from(m.Institution)
            ),
            "products": session.scalar(select(func.count()).select_from(m.Product)),
            "variants": session.scalar(
                select(func.count()).select_from(m.ProductVariant)
            ),
        }

    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        for key, table in (
            ("institutions", m.Institution),
            ("products", m.Product),
            ("variants", m.ProductVariant),
        ):
            assert session.scalar(select(func.count()).select_from(table)) == before[key]


# ── 지역 코드 ───────────────────────────────────────────────────────────


def test_sido_codes_match_the_screen_subregions() -> None:
    """코드↔시도 대응이 실측과 맞는지.

    처음에는 하위지역 **개수**만 보고 맞췄다가 18개 중 7개를 틀렸다.
    경북 데이터가 "충북"으로, 전남이 "경남"으로 나가고 있었다. 개수는
    여러 시도가 우연히 같을 수 있어 근거가 되지 못한다.

    아래 지명은 2026-08-05에 `findInrstSido.do`가 돌려준 하위지역이고,
    각각 그 시도에만 있는 이름이다.
    """
    from rate_monitor.collectors.cu.adapter import SIDO_NAMES

    anchors = {
        "01": ("서울", "관악"), "02": ("경기", "남양주"), "03": ("인천", "미추홀"),
        "04": ("부산", "기장"), "05": ("대구", "달성"), "06": ("광주", "광산"),
        "07": ("대전", "유성"), "09": ("울산", "울주"), "10": ("강원", "속초"),
        "11": ("경북", "경산"), "12": ("경남", "거제"), "13": ("충북", "괴산"),
        "14": ("충남", "계룡"), "15": ("전북", "고창"), "16": ("전남", "고흥"),
        "17": ("제주", "서귀포"),
    }
    for code, (name, _anchor) in anchors.items():
        assert SIDO_NAMES[code] == name, f"{code}가 {name}이어야 한다"

    # 08은 화면에 없다. 넣어두면 없는 지역을 조회하게 된다.
    assert "08" not in SIDO_NAMES
    # 18은 광주와 전남이 섞여 있어 시도 하나로 부를 수 없다.
    assert SIDO_NAMES["18"] == "광주·전남"


def test_every_sido_name_is_unique() -> None:
    """이름이 겹치면 --regions로 코드를 되찾을 때 하나가 사라진다."""
    from rate_monitor.collectors.cu.adapter import SIDO_NAMES

    assert len(set(SIDO_NAMES.values())) == len(SIDO_NAMES)
