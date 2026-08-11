"""새마을금고 저장 경로 검증 — fixture로 전 구간을 관통한다.

어댑터의 fetch만 fixture로 대체하고 그 아래 파싱·정규화·엔터티 해석·저장은
실제 코드를 그대로 쓴다. 네트워크를 호출하지 않는다.
"""

import asyncio
import dataclasses
from pathlib import Path

import pytest
from sqlalchemy import func, select

from rate_monitor.collectors.base import SourceBlockedError
from rate_monitor.collectors.kfcc.adapter import KfccAdapter
from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory, session_scope
from rate_monitor.domain.enums import RateScope, RunStatus, Sector
from rate_monitor.domain.schemas import CollectionRequest, RawArtifactData
from rate_monitor.services.collection_service import collect_source

FIXTURES = Path(__file__).parent / "fixtures" / "kfcc"

# tests/test_kfcc_parser.py가 고정한 실측값
EXPECTED_DEPOSIT_ROWS = 49
EXPECTED_SAVINGS_ROWS = 29
EXPECTED_TOTAL = EXPECTED_DEPOSIT_ROWS + EXPECTED_SAVINGS_ROWS

_OUTLET = {
    "gmgoCd": "1203",
    "gmgoNm": "대청",
    "name": "대청",
    "divCd": "001",
    "divNm": "본점",
    "gmgoType": "지역",
    "addr": "부산 중구 대청로 101-1",
    "r1": "부산",
    "r2": "중구",
    "telephone": "051-463-2166",
}


def _rate_artifact(group: str) -> RawArtifactData:
    path = FIXTURES / f"rate_1203_{group}.html"
    return RawArtifactData(
        artifact_type="html",
        content=path.read_bytes(),
        filename=path.name,
        request_meta={
            "kind": "rate",
            "gmgoCd": "1203",
            "gubuncode": group,
            "r1": "부산",
            "r2": "중구",
            "outlet": _OUTLET,
        },
        schema_fingerprint=f"fp-{group}",
        source_role=KfccAdapter.source_role,
        trust_level=KfccAdapter.trust_level,
    )


def _list_artifact() -> RawArtifactData:
    path = FIXTURES / "list_busan_junggu.html"
    return RawArtifactData(
        artifact_type="html",
        content=path.read_bytes(),
        filename=path.name,
        request_meta={"kind": "list", "r1": "부산", "r2": "중구"},
        schema_fingerprint="list",
        source_role=KfccAdapter.source_role,
        trust_level=KfccAdapter.trust_level,
    )


def _padded(n: int) -> RawArtifactData:
    """내용이 서로 다른 금리 아티팩트.

    `raw_artifacts`에 `UNIQUE(run_id, sha256)`이 있어 같은 바이트를 두 번
    저장할 수 없다. 주석 한 줄로 해시만 갈라 놓는다.
    """
    art = _rate_artifact("13" if n % 2 else "14")
    return dataclasses.replace(
        art,
        content=art.content + f"<!-- pad {n} -->".encode(),
        filename=f"pad_{n}.html",
    )


class FixtureAdapter(KfccAdapter):
    """fetch만 fixture로 대체한다. 파싱 이하는 실제 코드."""

    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        return [_list_artifact(), _rate_artifact("13"), _rate_artifact("14")]


class BlockedAdapter(KfccAdapter):
    async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
        raise SourceBlockedError("400 Request Blocked")


@pytest.fixture
def factory(tmp_path: Path):
    engine = create_db_engine(tmp_path / "kfcc.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


def run_collect(factory, raw_root: Path, adapter=None):
    return asyncio.run(
        collect_source(
            adapter or FixtureAdapter(),
            CollectionRequest(source_id="kfcc", regions=("부산",)),
            factory,
            raw_root=raw_root,
        )
    )


def _counts(session) -> dict[str, int]:
    return {
        name: session.scalar(select(func.count()).select_from(table))
        for name, table in (
            ("institutions", m.Institution),
            ("outlets", m.Outlet),
            ("products", m.Product),
            ("variants", m.ProductVariant),
            ("observations", m.RateObservation),
            ("runs", m.CollectionRun),
        )
    }


# ── 1차 수집 ────────────────────────────────────────────────────────────


def test_collect_stores_every_parsed_row(factory, tmp_path) -> None:
    result = run_collect(factory, tmp_path / "raw")
    assert result.status == RunStatus.SUCCESS
    assert result.parsed_count == EXPECTED_TOTAL
    assert result.error_count == 0

    with session_scope(factory) as session:
        counts = _counts(session)
        assert counts["observations"] == EXPECTED_TOTAL
        assert counts["runs"] == 1
        # 목록 아티팩트도 저장되지만 금리 행은 만들지 않는다.
        assert session.scalar(select(func.count()).select_from(m.RawArtifact)) == 3


def test_source_row_uses_kfcc_metadata(factory, tmp_path) -> None:
    """finlife 값이 새어 들어오면 안 된다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        source = session.get(m.Source, "kfcc")
        assert source.name == "새마을금고 금고위치안내"
        assert source.sector == Sector.KFCC
        # 약관 미확인이므로 allowed가 아니다.
        assert source.policy_status == "review"


def test_institution_key_is_not_polluted_by_a_guessed_sector(factory, tmp_path) -> None:
    """권역을 rate_scope로 추측하면 "bank:1203"이 된다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        link = session.scalars(
            select(m.SourceEntityLink).where(
                m.SourceEntityLink.entity_type == "institution"
            )
        ).one()
        assert link.source_entity_key == "kfcc:1203"

        institution = session.get(m.Institution, link.entity_id)
        assert institution.sector == Sector.KFCC
        assert institution.canonical_name == "대청"
        assert institution.address == "부산 중구 대청로 101-1"
        # 화면 파라미터를 행정구역 공식 코드로 쓰지 않는다.
        assert institution.sido_code is None
        assert institution.sigungu_code is None


def test_every_observation_is_traceable_to_its_source(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        rows = session.scalars(select(m.RateObservation)).all()
        assert len(rows) == EXPECTED_TOTAL
        assert all(r.raw_artifact_id is not None for r in rows)
        assert all(r.base_source_locator for r in rows)
        assert all(r.source_record_hash for r in rows)
        # 기준일이 페이지에 있으므로 전부 채워져야 한다.
        assert all(r.source_effective_at is not None for r in rows)


def test_max_rate_is_null_in_storage(factory, tmp_path) -> None:
    """공식 화면에 우대금리 열이 없다. base_rate로 메우면 안 된다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        filled = session.scalar(
            select(func.count())
            .select_from(m.RateObservation)
            .where(m.RateObservation.max_rate.is_not(None))
        )
        assert filled == 0


def test_rate_scope_is_institution_not_outlet(factory, tmp_path) -> None:
    """금리는 금고 단위 공시다. 점포별 적용금리가 아니다."""
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        scopes = {v.rate_scope for v in session.scalars(select(m.ProductVariant)).all()}
        assert scopes == {RateScope.INSTITUTION}


# ── 구·군 집계 — 이 절단의 목적 ────────────────────────────────────────


def test_dashboard_aggregates_by_district(factory, tmp_path) -> None:
    """구별 보기가 실제로 나오는지. 이게 안 되면 이 절단의 의미가 없다."""
    from rate_monitor.services.dashboard_service import build_summary

    run_collect(factory, tmp_path / "raw")
    summary = build_summary(tmp_path / "kfcc.sqlite3")

    districts = summary["by_district"]
    assert len(districts) == 1
    assert districts[0]["sigungu"] == "중구"
    assert districts[0]["sector"] == Sector.KFCC
    assert districts[0]["institutions"] == 1
    assert districts[0]["observations"] == EXPECTED_TOTAL

    top = summary["district_top"]
    assert [t["sigungu"] for t in top] == ["중구"]
    assert top[0]["term_months"] == 12


def test_district_needs_an_address_from_somewhere(factory, tmp_path) -> None:
    """주소가 하나도 없으면 구 집계에 나타나지 않는다.

    저축은행이 그 경우다. finlife는 기관 주소도 점포 명부도 주지 않으므로
    구 단위로 말할 수 없고, 조용히 '미상' 같은 칸에 몰아넣지도 않는다.
    """
    import dataclasses

    from rate_monitor.services.dashboard_service import build_summary

    class NoAddressAdapter(FixtureAdapter):
        def parse_with_warnings(self, artifact):
            rows, warnings = super().parse_with_warnings(artifact)
            return [
                dataclasses.replace(r, address=None, outlets=()) for r in rows
            ], warnings

    run_collect(factory, tmp_path / "raw", adapter=NoAddressAdapter())
    summary = build_summary(tmp_path / "kfcc.sqlite3")
    assert summary["by_district"] == []


def test_outlet_directory_is_stored_and_drives_the_district(factory, tmp_path) -> None:
    """점포 명부가 저장되고, 구 집계가 점포 주소를 쓴다.

    금리는 금고 단위지만 한 금고가 두 구에 점포를 두기도 한다. 기관 주소만
    쓰면 그 금고가 다른 구에서 통째로 사라진다 (부산 실측 3건).
    """
    import dataclasses

    from rate_monitor.services.dashboard_service import build_summary

    class TwoDistrictAdapter(FixtureAdapter):
        """대청금고에 서구 점포를 하나 더 붙인다."""

        def parse_with_warnings(self, artifact):
            rows, warnings = super().parse_with_warnings(artifact)
            if rows and rows[0].outlets:
                extra = {
                    "source_outlet_key": "1203:002",
                    "name": "서구지점",
                    "address": "부산 서구 구덕로 100",
                    "phone": "051-000-0000",
                }
                rows[0] = dataclasses.replace(
                    rows[0], outlets=(*rows[0].outlets, extra)
                )
            return rows, warnings

    run_collect(factory, tmp_path / "raw", adapter=TwoDistrictAdapter())

    with session_scope(factory) as session:
        outlets = session.scalars(select(m.Outlet)).all()
        assert {o.name for o in outlets} == {"본점", "서구지점"}
        assert {o.address for o in outlets} == {
            "부산 중구 대청로 101-1",
            "부산 서구 구덕로 100",
        }

    summary = build_summary(tmp_path / "kfcc.sqlite3")
    # 같은 금고가 두 구 모두에 나타난다.
    assert {d["sigungu"] for d in summary["by_district"]} == {"중구", "서구"}
    assert {t["sigungu"] for t in summary["district_top"]} == {"중구", "서구"}


def test_same_district_name_in_two_provinces_stays_apart(factory, tmp_path) -> None:
    """서울 중구와 부산 중구가 한 줄로 합쳐지면 안 된다.

    구 이름은 전국에서 겹친다. 중구만 해도 서울·부산·대구·인천·대전·울산에
    있다. 부산만 수집할 때는 드러나지 않던 문제이고, 전국 수집으로 넓히는
    순간 여섯 도시의 중구가 하나로 뭉쳐 최고금리가 뒤섞인다.
    """
    import dataclasses

    from rate_monitor.services.dashboard_service import build_summary

    class SeoulJungguAdapter(FixtureAdapter):
        """같은 '중구'인데 시도가 다른 점포를 하나 더 붙인다."""

        def parse_with_warnings(self, artifact):
            rows, warnings = super().parse_with_warnings(artifact)
            if rows and rows[0].outlets:
                extra = {
                    "source_outlet_key": "1203:900",
                    "name": "서울중구지점",
                    "address": "서울 중구 세종대로 100",
                    "phone": "02-000-0000",
                }
                rows[0] = dataclasses.replace(
                    rows[0], outlets=(*rows[0].outlets, extra)
                )
            return rows, warnings

    run_collect(factory, tmp_path / "raw", adapter=SeoulJungguAdapter())
    summary = build_summary(tmp_path / "kfcc.sqlite3")

    keys = {(d["sido"], d["sigungu"]) for d in summary["by_district"]}
    assert keys == {("부산", "중구"), ("서울", "중구")}
    assert {(t["sido"], t["sigungu"]) for t in summary["district_top"]} == keys

    # 목록은 다르다. 공시 한 건이 한 줄이고 기관 주소를 쓴다.
    # 점포를 조인하면 관측 하나가 점포 수만큼 복제된다.
    table = summary["table"]
    assert len(table["rows"]) == EXPECTED_TOTAL

    region_col = table["columns"].index("region")
    district_col = table["columns"].index("district")
    pairs = {
        (table["lookups"]["region"][r[region_col]],
         table["lookups"]["district"][r[district_col]])
        for r in table["rows"]
    }
    assert pairs == {("부산", "중구")}


def test_rate_table_has_one_row_per_observation(factory, tmp_path) -> None:
    """점포가 여럿인 기관의 금리가 점포 수만큼 복제되면 안 된다.

    예전에는 금리표가 점포를 조인해서, 관측 15,357건이 표에서 32,592행이
    됐다. 저축은행 하나가 지점 8곳을 두면 같은 금리가 8줄로 나오고 내려받기
    CSV도 그만큼 부풀었다.
    """
    import dataclasses
    import sqlite3

    from rate_monitor.services.dashboard_service import build_rate_table, latest_run_ids

    class ManyOutletsAdapter(FixtureAdapter):
        def parse_with_warnings(self, artifact):
            rows, warnings = super().parse_with_warnings(artifact)
            if rows and rows[0].outlets:
                extra = tuple(
                    {
                        "source_outlet_key": f"1203:9{n:02d}",
                        "name": f"지점{n}",
                        "address": f"부산 중구 대청로 {n}",
                        "phone": None,
                    }
                    for n in range(1, 6)
                )
                rows[0] = dataclasses.replace(
                    rows[0], outlets=(*rows[0].outlets, *extra)
                )
            return rows, warnings

    run_collect(factory, tmp_path / "raw", adapter=ManyOutletsAdapter())

    conn = sqlite3.connect(tmp_path / "kfcc.sqlite3")
    try:
        outlets = conn.execute("SELECT COUNT(*) FROM outlets").fetchone()[0]
        table = build_rate_table(conn, latest_run_ids(conn))
    finally:
        conn.close()

    assert outlets == 6, "검사가 성립하려면 점포가 여럿이어야 한다"
    assert len(table["rows"]) == EXPECTED_TOTAL


def test_long_and_short_sido_names_are_the_same_place(factory, tmp_path) -> None:
    """"부산"과 "부산광역시"가 두 줄로 갈라지면 안 된다.

    부산 실측에서 금고 한 곳이 주소를 "부산광역시 부산진구"로 적는다.
    시도 축을 넣자마자 부산진구가 두 줄이 됐다. 전국에서는 "경기"와
    "경기도"가 같은 화면에 함께 나온다.
    """
    import dataclasses

    from rate_monitor.services.dashboard_service import build_summary

    class LongNameAdapter(FixtureAdapter):
        """같은 중구인데 시도를 긴 이름으로 적는 점포를 붙인다."""

        def parse_with_warnings(self, artifact):
            rows, warnings = super().parse_with_warnings(artifact)
            if rows and rows[0].outlets:
                extra = {
                    "source_outlet_key": "1203:901",
                    "name": "긴이름지점",
                    "address": "부산광역시 중구 중앙대로 1",
                    "phone": "051-000-0001",
                }
                rows[0] = dataclasses.replace(
                    rows[0], outlets=(*rows[0].outlets, extra)
                )
            return rows, warnings

    run_collect(factory, tmp_path / "raw", adapter=LongNameAdapter())
    summary = build_summary(tmp_path / "kfcc.sqlite3")

    assert {(d["sido"], d["sigungu"]) for d in summary["by_district"]} == {
        ("부산", "중구")
    }
    table = summary["table"]
    region_col = table["columns"].index("region")
    assert {
        table["lookups"]["region"][r[region_col]] for r in table["rows"]
    } == {"부산"}


# ── 재수집 ──────────────────────────────────────────────────────────────


def test_recollect_does_not_duplicate_canonical_entities(factory, tmp_path) -> None:
    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        first = _counts(session)

    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        second = _counts(session)

    for key in ("institutions", "outlets", "products", "variants"):
        assert second[key] == first[key], key
    assert second["runs"] == first["runs"] + 1
    # 값이 그대로이므로 관측이 늘지 않는다 (선행 수정안 §3.2). 예전에는
    # 실행마다 두 배가 됐고, 그대로 두면 1년에 약 19 GB가 된다.
    assert second["observations"] == first["observations"]


# ── 실패 경로 ───────────────────────────────────────────────────────────


def test_blocked_writes_no_observations(factory, tmp_path) -> None:
    """차단은 우회하지 않고 상태만 남긴다 (v3 §0.2)."""
    result = run_collect(factory, tmp_path / "raw", adapter=BlockedAdapter())
    assert result.status == RunStatus.BLOCKED
    with session_scope(factory) as session:
        assert _counts(session)["observations"] == 0


# ── 어댑터 계약 ─────────────────────────────────────────────────────────


def test_list_artifact_produces_no_rate_rows() -> None:
    adapter = KfccAdapter()
    rows, warnings = adapter.parse_with_warnings(_list_artifact())
    assert rows == []
    assert warnings == []


def test_adapter_rejects_an_unknown_region() -> None:
    adapter = KfccAdapter()
    with pytest.raises(ValueError, match="config에 없는 지역"):
        adapter._load_regions(CollectionRequest(source_id="kfcc", regions=("부산광역시",)))


def test_adapter_rejects_an_unknown_scope() -> None:
    adapter = KfccAdapter()
    with pytest.raises(ValueError, match="config에 없는 수집 범위"):
        adapter._load_regions(
            CollectionRequest(source_id="kfcc", options={"scope": "영남권"})
        )


def test_adapter_defaults_to_the_whole_country() -> None:
    """기본값이 전국이다. 부산은 수집 단위가 아니라 범위 하나일 뿐이다."""
    adapter = KfccAdapter()
    regions = adapter._load_regions(CollectionRequest(source_id="kfcc"))
    assert len(regions) == 17
    assert {"부산", "서울", "제주"} <= set(regions)


def test_scope_narrows_the_regions() -> None:
    adapter = KfccAdapter()
    assert adapter._load_regions(
        CollectionRequest(source_id="kfcc", options={"scope": "부산"})
    ) == ["부산"]
    assert adapter._load_regions(
        CollectionRequest(source_id="kfcc", options={"scope": "수도권"})
    ) == ["서울", "경기", "인천"]


def test_explicit_regions_win_over_scope_and_dedupe() -> None:
    """같은 지역을 두 번 적어도 두 번 돌지 않는다."""
    adapter = KfccAdapter()
    regions = adapter._load_regions(
        CollectionRequest(
            source_id="kfcc", regions=("부산", "경남", "부산"), options={"scope": "전국"}
        )
    )
    assert regions == ["부산", "경남"]


def test_workplace_only_funds_are_excluded_from_the_headline(factory, tmp_path) -> None:
    """직장금고 금리를 '이 구의 최고금리'로 내세우면 안 된다.

    실측에서 강서구 10.00%와 부산진구 5.00%가 모두 직장금고였다. 일반
    이용자는 가입할 수 없으므로 대표값에서 빼고 개수만 따로 보여준다.
    """
    import dataclasses

    from rate_monitor.services.dashboard_service import build_summary

    class WorkplaceAdapter(FixtureAdapter):
        """같은 구에 직장금고를 하나 더 놓는다. 금리는 훨씬 높다."""

        async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
            base = await super().fetch(request)
            extra = _rate_artifact("13")
            meta = dict(extra.request_meta)
            meta["gmgoCd"] = "9999"
            meta["outlet"] = {**_OUTLET, "gmgoCd": "9999", "gmgoNm": "시험직장",
                              "gmgoType": "직장"}
            # 내용이 바이트 단위로 같으면 raw_artifacts의 UNIQUE(run_id, sha256)에
            # 걸린다. 금리를 올려 서로 다른 문서로 만든다.
            content = extra.content.replace("연3.2%".encode(), "연9.9%".encode())
            return [
                *base,
                dataclasses.replace(
                    extra,
                    request_meta=meta,
                    content=content,
                    filename="rate_9999_13.html",
                ),
            ]

    result = run_collect(factory, tmp_path / "raw", adapter=WorkplaceAdapter())
    assert result.status == RunStatus.SUCCESS
    summary = build_summary(tmp_path / "kfcc.sqlite3")

    district = summary["by_district"][0]
    assert district["workplace_institutions"] == 1
    # 대표값은 지역금고만, 별도 칸에는 직장금고까지 포함한 값이 남는다.
    assert district["base_max"] is not None
    assert summary["workplace_only"]
    assert all(
        w["institution"] == "시험직장" for w in summary["workplace_only"]
    )
    # 구별 최고상품에도 직장금고가 올라오면 안 된다.
    assert all(t["institution"] != "시험직장" for t in summary["district_top"])


def test_workplace_scope_is_taken_from_the_official_type(factory, tmp_path) -> None:
    """gmgoType이 '직장'이면 기관이 workplace_members여야 한다."""
    from rate_monitor.domain.enums import AvailabilityScope

    run_collect(factory, tmp_path / "raw")
    with session_scope(factory) as session:
        institution = session.scalars(select(m.Institution)).one()
        assert institution.institution_type == "지역"
        assert institution.availability_scope == AvailabilityScope.LOCAL_MEMBERS


def test_fetch_asks_each_region_once_with_an_empty_r2(monkeypatch) -> None:
    """`r2`를 비우면 지역 전체가 한 번에 온다.

    예전에는 부산 16개 구를 config에 적어두고 16회를 돌았다. 요청이 줄어드는
    것보다, 손으로 관리하는 구·군 목록이 없어지는 것이 중요하다.
    """
    calls: list[dict] = []
    list_html = (FIXTURES / "list_busan_junggu.html").read_bytes()
    rate_html = (FIXTURES / "rate_1203_13.html").read_bytes()

    async def fake_get(self, client, url, params):
        calls.append({"url": url, **params})
        return list_html if url.endswith("list.do") else rate_html

    monkeypatch.setattr(KfccAdapter, "_get", fake_get)
    monkeypatch.setattr(
        "rate_monitor.collectors.kfcc.adapter.REQUEST_INTERVAL_SECONDS", 0
    )

    adapter = KfccAdapter()
    artifacts = asyncio.run(
        adapter.fetch(
            CollectionRequest(
                source_id="kfcc", regions=("부산", "경남"), options={"groups": ("13",)}
            )
        )
    )

    lists = [c for c in calls if c["url"].endswith("list.do")]
    assert [(c["r1"], c["r2"]) for c in lists] == [("부산", ""), ("경남", "")]

    # fixture는 두 지역 모두에 같은 6금고를 돌려준다. 금고당 1회씩만 묻는다.
    rates = [c for c in calls if c["url"].endswith("goods_19.do")]
    assert len(rates) == 6
    assert {c["gubuncode"] for c in rates} == {"13"}

    # **바이트가 같아도 버리지 않는다.**
    #
    # 예전에는 여기서 걸렀다 — 유일성이 `(run_id, sha256)`이라 같은 내용을 두
    # 번 못 넣었기 때문이다. 그래서 이 시험도 "한 장만 남는다"를 기대했다.
    #
    # 그 규칙 때문에 2026-08-06 실행에서 경남 186장이 통째로 사라졌다. 금리
    # 화면에는 금고 이름이 없어서 취급 상품이 같은 두 금고는 응답이 똑같아
    # 지고, 뒤에 온 금고가 DB에 아예 안 생겼다.
    #
    # 이제 조회한 만큼 돌려주고, 같은 바이트는 저장 계층이 원본 행 하나를
    # 함께 가리키게 한다 (`save_raw_artifacts`).
    kinds = [a.request_meta["kind"] for a in artifacts]
    assert kinds.count("list") == 2, "지역 두 곳을 물었으면 목록도 두 장이다"
    assert kinds.count("rate") == 6, "금고 여섯 곳을 물었으면 금리도 여섯 장이다"

    # 되풀이를 세어 남긴다. 0건이어도 적어야 "검사를 안 했나"와 구별된다.
    assert "되풀이" in adapter.fetch_note


# ── 구조 어긋난 페이지 ──────────────────────────────────────────────────


def test_one_broken_page_does_not_discard_the_whole_run(factory, tmp_path) -> None:
    """페이지 한 장 때문에 실행 전체를 버리지 않는다.

    2026-08-05 전국 수집(2,520장)에서 한 장이 SchemaChangedError를 냈고,
    그 예외가 트랜잭션 밖으로 나가면서 **2시간치 원본이 통째로 롤백**됐다.
    raw_count가 0으로 남아 어느 금고의 어떤 페이지였는지조차 알 수 없게 됐다.
    """
    from rate_monitor.collectors.base import SchemaChangedError

    class OneBadPageAdapter(FixtureAdapter):
        """정상 아티팩트 여럿에 깨진 것 하나를 섞는다."""

        async def fetch(self, request):
            # 표본이 적으면 한 장도 넘기지 않으므로 충분히 늘린다.
            return [_list_artifact(), *(_padded(n) for n in range(23))]

        def parse_with_warnings(self, artifact):
            if artifact.filename == "pad_7.html":
                raise SchemaChangedError("금리 페이지에 .tbl-tit 상품 제목이 없다")
            return super().parse_with_warnings(artifact)

    result = run_collect(factory, tmp_path / "raw", adapter=OneBadPageAdapter())

    # 실행이 살아남는다. 다만 success가 아니라 partial이다 — 조용히 성공으로
    # 끝나면 그 금고가 통째로 빠진 것을 아무도 모른다.
    assert result.status == RunStatus.PARTIAL
    assert result.parsed_count > 0
    assert "건너뜀 1장" in result.message

    with session_scope(factory) as session:
        # 원본이 살아 있어야 나중에 그 페이지가 무엇이었는지 되짚을 수 있다.
        assert session.scalar(
            select(func.count()).select_from(m.RawArtifact)
        ) == 24
        # 어느 파일이 왜 어긋났는지 검수항목에 남는다.
        item = session.scalars(
            select(m.ReviewItem).where(m.ReviewItem.issue_type == "schema_changed")
        ).one()
        assert "pad_7.html" in item.message
        assert "tbl-tit" in item.message


def test_widespread_schema_failure_still_stops_the_run(factory, tmp_path) -> None:
    """여러 장이 한꺼번에 어긋나면 우리 파서가 틀린 것이다. 그때는 멈춘다.

    명세서 v3.1 §8의 "구조 변경은 멈춘다"를 버리지 않는다.
    """
    from rate_monitor.collectors.base import SchemaChangedError

    class AllBadAdapter(FixtureAdapter):
        async def fetch(self, request):
            return [_padded(n) for n in range(30)]

        def parse_with_warnings(self, artifact):
            raise SchemaChangedError("기본이율 표를 하나도 찾지 못했다")

    result = run_collect(factory, tmp_path / "raw", adapter=AllBadAdapter())
    assert result.status == RunStatus.SCHEMA_CHANGED
    with session_scope(factory) as session:
        assert _counts(session)["observations"] == 0


# ── 바이트가 같은 두 금고를 모두 살린다 ─────────────────────────────────


def test_two_gumgos_with_identical_pages_both_reach_the_database(factory, tmp_path):
    """**이것이 경남 186장을 잃은 결함이다.**

    금리 화면에는 금고 이름도 주소도 없다 (`parse_rates`가 금고 정보를
    `request_meta`의 `outlet`에서 받는 이유다). 그래서 취급 상품과 금리가
    같은 두 금고는 응답 바이트가 완전히 같아진다.

    예전에는 수집기가 뒤에 온 금고를 통째로 버렸고, 그 금고는 기관도 상품도
    금리도 안 생겼다. 2026-08-06 실행에서 관측 7,274건이 그렇게 사라졌는데
    오류도 경고도 0이었다.

    이제 응답은 그대로 두고, 저장 계층이 원본 행 하나를 함께 가리키게 한다.
    **두 금고 모두 DB에 생겨야 한다.**
    """
    import dataclasses

    base = _rate_artifact("13")

    class TwinAdapter(KfccAdapter):
        async def fetch(self, request: CollectionRequest) -> list[RawArtifactData]:
            twins = [
                dataclasses.replace(
                    base,
                    filename=f"rate_{code}_13.html",
                    # 내용은 **글자 하나 안 바꾼다.** 맥락만 금고마다 다르다.
                    request_meta={**base.request_meta,
                                  "gmgoCd": code,
                                  "outlet": {**base.request_meta["outlet"],
                                             "gmgoCd": code,
                                             "gmgoNm": f"금고{code}"}},
                )
                for code in ("9001", "9002")
            ]
            return [_list_artifact(), *twins]

    run_collect(factory, tmp_path / "raw", adapter=TwinAdapter())

    with session_scope(factory) as session:
        names = sorted(
            i.canonical_name for i in session.scalars(select(m.Institution)).all()
        )
        assert "금고9001" in names and "금고9002" in names, (
            f"바이트가 같은 금고가 사라졌다: {names}"
        )

        # 원본 행은 하나를 나눠 쓰되(UNIQUE(run_id, sha256)), 관측은 둘 다 있다.
        artifacts = session.scalars(select(m.RawArtifact)).all()
        assert len(artifacts) == 2, "목록 1장 + 같은 내용의 금리 1장"
        by_institution = {
            row.institution_id
            for row in session.scalars(select(m.Product)).all()
        }
        assert len(by_institution) == 2
