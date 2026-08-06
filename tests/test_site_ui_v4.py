"""공개 화면 개편 (v4 §10, PR 7-3).

화면 자체는 브라우저에서 돌지만, **화면이 기대하는 데이터가 실제로 나가는지**와
**금지사항을 어기지 않는지**는 여기서 못 박는다.

브라우저 확인은 별도로 했다 (2026-08-06, Chromium + Playwright, 발행 DB).

    1차 (137,422행)  첫 렌더 1.5초, 업권 탭 5개, 부산 구·군 16개,
                     참고카드 2장, 우대조건 펼치기, 콘솔 오류 0건

    2차 (133,764행, 조회 조건 개편 뒤)
        업권 탭 6개 — 전체·저축은행·새마을금고·지역농축협·신협·은행
        지역에서 부산을 켜니 구·군 16개가 그 자리에서 펼쳐졌다
        동구를 고르니 15,822 → 1,537건
        부산을 끄니 구·군이 접히고 133,764건으로 돌아왔다
        7~12개월 구간 45,736건
        우대금리 기준으로 바꾸니 금리칸 이름이 «최고금리 이상 (%)»로 바뀌었다
        시중은행 탭 333건. **서울 시도를 걸어도 333건 그대로**였고
        보이는 100행 전부에 «전국 공시» 배지가 붙었다
        콘솔 오류 0건
"""

import json
import re
from pathlib import Path

import pytest

from rate_monitor.services.site_service import (
    INLINE_KEYS,
    build_site,
    split_summary,
)

TEMPLATE = Path(__file__).resolve().parents[1] / "web" / "templates" / "site.html"
SOURCE = TEMPLATE.read_text(encoding="utf-8")


@pytest.fixture()
def factory(tmp_path: Path):
    from rate_monitor.db import models as m
    from rate_monitor.db.session import create_db_engine, make_session_factory

    engine = create_db_engine(tmp_path / "kfcc.sqlite3")
    m.Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture()
def db(tmp_path: Path, factory) -> Path:
    from tests.test_kfcc_collection import run_collect

    run_collect(factory, tmp_path / "raw")
    return tmp_path / "kfcc.sqlite3"


# ── 참고카드가 화면까지 닿는가 ──────────────────────────────────────────


def test_benchmarks_reach_the_page(db: Path, tmp_path: Path) -> None:
    """참고카드는 표를 받기 전에 그려야 하므로 인라인에 실려야 한다."""
    assert "benchmarks" in INLINE_KEYS

    out = tmp_path / "site"
    build_site(db, TEMPLATE, out)
    html = (out / "index.html").read_text(encoding="utf-8")
    marker = '<script id="rate-monitor-data" type="application/json">'
    body = html[html.find(marker) + len(marker) : html.find("</script>", html.find(marker))]
    inline = json.loads(body.replace("<\\/", "</"))
    assert "benchmarks" in inline


def test_the_page_hides_an_empty_benchmark_card() -> None:
    """값이 없으면 카드를 통째로 숨긴다. 빈 카드는 "0%"로 읽힌다."""
    assert 'id="marks" hidden' in SOURCE
    assert '$("marks").hidden = false;' in SOURCE


# ── 금지사항 ────────────────────────────────────────────────────────────


def _visible(text: str) -> str:
    """주석을 걷어낸 것. 화면에 나가는 글자만 남긴다.

    주석에는 "이 단어를 쓰지 마라"고 적혀 있을 수 있다. 그걸 위반으로 세면
    규칙을 설명하지 못하게 된다.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def test_the_page_never_computes_a_spread_against_the_base_rate() -> None:
    """기준금리와 예금금리의 차이를 "수익"이나 "마진"으로 부르지 않는다.

    v4 §7.4. 그 뺄셈에 이름을 붙이는 순간 참고지표가 아니라 투자 권유가 된다.
    """
    visible = _visible(SOURCE)
    for word in ("수익", "마진", "스프레드"):
        assert word not in visible, f"화면에 {word}이(가) 들어갔다"


def test_the_forbidden_phrases_are_absent() -> None:
    """v4 §17. 이 화면이 원천 공시처럼 보이면 안 된다."""
    visible = _visible(SOURCE)
    for phrase in ("부산 저축은행 금리", "부산 지역별 최고금리",
                   "부산에서 가입 가능한 최고상품"):
        assert phrase not in visible


def test_the_head_office_notice_is_still_there() -> None:
    """저축은행 값이 지점 금리로 오해되면 안 된다 (v3.1 §6.4)."""
    assert "저축은행 공시금리 — 전국 본점 기준 참고값" in SOURCE


# ── 업권 탭 ─────────────────────────────────────────────────────────────


def test_the_commercial_bank_has_a_tab_by_explicit_decision() -> None:
    """시중은행도 메인 비교표에 선다 (v4 §6.4 정정, 2026-08-06).

    한때 이 테스트는 정반대를 못박고 있었다. 사용자가 넣기로 정했다.
    """
    match = re.search(r"const MAIN_SECTORS = \[([^\]]+)\]", SOURCE)
    assert match, "MAIN_SECTORS를 찾지 못했다"
    assert "bank" in [s.strip().strip('"') for s in match.group(1).split(",")]


def test_nationwide_rows_survive_a_sido_filter() -> None:
    """전국 공시 행은 시도를 골라도 남는다 (v4 §6.4 정정 조건 2).

    시중은행 행은 `region_sido`가 비어 있다. 그대로 두면 시도를 고르는
    순간 전부 사라져서 "그 지역에 해당 상품이 없다"고 말하는 셈이 된다.
    구·군의 `GU_EXACT` 규칙과 같은 취지다.
    """
    assert 'NATIONWIDE_GEO = new Set(["nationwide"])' in SOURCE
    assert 'g.key === "region" && NATIONWIDE_GEO.has(r.geo)' in SOURCE


def test_the_nationwide_badge_still_exists() -> None:
    """배지 없이 섞는 것이 §17의 금지다. 배지가 사라지면 결정이 무너진다."""
    assert 'nationwide: "전국 공시"' in SOURCE


def test_unknown_sectors_are_not_dropped_from_the_tabs() -> None:
    """새 수집원이 늘었는데 화면에서 통째로 사라지면 안 된다."""
    assert "!MAIN_SECTORS.includes(s)" in SOURCE


# ── 부산 구·군 ──────────────────────────────────────────────────────────


def test_busan_districts_come_from_a_list_not_the_data() -> None:
    """데이터에서 뽑으면 점포가 없는 구가 화면에서 사라진다.

    실측으로 농·축협은 영도구·중구에 점포가 없다. 그 두 구가 목록에서
    빠지면 "없다"가 아니라 "안 봤다"로 읽힌다.
    """
    from rate_monitor.services.region_service import BUSAN_DISTRICTS

    match = re.search(r"const BUSAN = \[(.*?)\];", SOURCE, re.S)
    assert match
    listed = tuple(s.strip().strip('"') for s in match.group(1).split(",") if s.strip())
    assert listed == BUSAN_DISTRICTS, "화면 목록이 region_service와 다르다"


def test_the_district_filter_only_applies_to_address_based_regions() -> None:
    """조회조건·본점 기준 지역을 구 단위 정확 필터로 쓰면 거짓이 된다.

    신협의 '부산'은 조회조건이고 저축은행의 '부산'은 본점 소재지다. 그걸
    "해운대구" 필터로 거르면 그 구에 없는 지점을 있다고 말하는 셈이다.
    """
    assert 'const GU_EXACT = new Set(["outlet_address"]);' in SOURCE
    assert "GU_EXACT.has(r.geo)" in SOURCE


# ── 우대조건 ────────────────────────────────────────────────────────────


def test_missing_preference_is_not_shown_as_none() -> None:
    """원천이 우대금리 열 자체를 안 주는 곳이 있다.

    새마을금고 93,819행과 농·축협 4,920행이다. 그걸 "없음"으로 적으면
    우대가 없는 상품처럼 보인다 — "원천 미제공"과 구별해야 한다.
    """
    assert "원천 미제공" in SOURCE


def test_the_table_keeps_a_stable_row_key_for_expanding() -> None:
    """필터·정렬이 바뀌어도 펼친 행이 따라가야 한다."""
    assert "(r, _i) => ({" in SOURCE and "_i," in SOURCE


# ── 정렬 ────────────────────────────────────────────────────────────────


def test_null_max_rate_never_leads_the_sort() -> None:
    """`max_rate IS NULL`을 기본금리로 대체해 순위를 만들지 않는다 (v4 §10.3).

    새마을금고 93,819행과 농·축협 4,920행이 전부 NULL이므로, 이 규칙이 곧
    화면의 정직함이다. 방향을 뒤집어도 NULL은 뒤로 간다.
    """
    assert re.search(r"if \(x == null\) return 1;\s*//", SOURCE), (
        "빈 값을 뒤로 보내는 규칙이 사라졌다"
    )


def test_the_split_still_keeps_the_table_out_of_the_page() -> None:
    """참고카드를 인라인에 더했다고 금리표까지 들어가면 안 된다."""
    page, table = split_summary(
        {"totals": {"a": 1}, "benchmarks": {"x": 1}, "table": {"rows": [[1]]}}
    )
    assert "benchmarks" in page
    assert "table" not in page
    assert table["rows"] == [[1]]


# ── 원천이 실패했을 때 ──────────────────────────────────────────────────


def _fail_the_last_run(db: Path, source_id: str = "kfcc") -> None:
    import datetime as dt
    import sqlite3

    now = dt.datetime.now(dt.UTC).replace(tzinfo=None).isoformat(sep=" ")
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO collection_runs (id, source_id, mode, started_at, finished_at,"
        " status, query_context_json, raw_count, parsed_count, valid_count,"
        " warning_count, error_count, fallback_used)"
        " VALUES ('run-failed', ?, 'http', ?, ?, 'failed', '{}', 0, 0, 0, 0, 0, 0)",
        (source_id, now, now),
    )
    conn.commit()
    conn.close()


def test_a_failed_source_does_not_empty_the_screen(db: Path) -> None:
    """실패한 실행을 "이번에 확인한 금리"로 취급하면 그 원천이 통째로 사라진다.

    2026-08-06 재현: 정상 수집 뒤 78행 → 그 원천이 실패한 뒤 **0행**.
    어제 확인한 금리는 DB에 멀쩡히 있는데도 그랬다. `volume_gate`는 실패
    실행을 빼고 비교하므로 급감으로도 안 잡혀, 아무도 모르는 채 발행된다.
    """
    import sqlite3

    from rate_monitor.services.dashboard_service import build_rate_table, latest_run_ids

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    before = len(build_rate_table(conn, latest_run_ids(conn))["rows"])
    conn.close()
    assert before > 0

    _fail_the_last_run(db)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    after = len(build_rate_table(conn, latest_run_ids(conn))["rows"])
    conn.close()
    assert after == before, "원천이 실패하자 화면이 비었다"


def test_the_screen_says_which_source_failed(db: Path) -> None:
    """직전 값을 보여주되 **조용히** 그러면 안 된다."""
    from rate_monitor.services.dashboard_service import build_summary

    assert build_summary(db)["stale_sources"] == []

    _fail_the_last_run(db)
    stale = build_summary(db)["stale_sources"]
    assert len(stale) == 1
    assert stale[0]["source_id"] == "kfcc"
    # 언제 실패했고 지금 보이는 값이 언제 것인지 둘 다 있어야 한다.
    assert stale[0]["failed_at"] and stale[0]["showing_from"]


def test_the_stale_notice_starts_hidden() -> None:
    """실패가 없으면 경고가 안 보여야 한다."""
    assert 'id="stale-notice" hidden' in SOURCE
    assert '$("stale-notice").hidden = false;' in SOURCE


# ── 조회 조건 개편 (2026-08-06) ─────────────────────────────────────────
#
# 아래는 실제 브라우저(Chromium)에서 한 번 돌려 확인한 동작을 소스에 못박는
# 것이다. 실측 결과는 커밋 메시지에 있다. 여기서는 그 동작을 만드는 코드가
# 사라지지 않았는지만 본다 — 이 파일은 JS를 실행하지 않는다.


def test_the_busan_districts_open_inside_the_region_filter() -> None:
    """구·군은 지역 조건 안에서 펼친다.

    예전에는 표 위에 `부산으로 보기` 버튼과 구 버튼 줄이 따로 있었다. 같은
    축(지역)을 두 곳에서 켜면 어느 쪽이 이겼는지 화면으로 알 수 없다.
    """
    assert 'id="busan-gu"' not in SOURCE, "구·군 목록이 아직 지역 조건 밖에 있다"
    assert "const busanGuBoxes = () =>" in SOURCE
    assert 'g.key === "region" ? busanGuBoxes() : ""' in SOURCE


def test_unchecking_busan_also_clears_the_districts() -> None:
    """안 보이는 조건이 살아남으면 왜 적게 나오는지 알 수 없다."""
    assert "if (!busanOn()) state.gu.clear();" in SOURCE


def test_busan_leads_the_region_list() -> None:
    """이 제품의 중심이 부산이라 건수 순서에 묻히면 안 된다.

    서울이 17,818건으로 부산 15,489건보다 많아서, 정렬을 그대로 두면
    부산이 둘째 줄로 밀린다.
    """
    assert "if (a === BUSAN_SIDO) return -1;" in SOURCE


def test_the_term_filter_is_bucketed_with_measured_edges() -> None:
    """46종을 그대로 늘어놓으면 고를 수 없다.

    경계 옆에 실측 몫이 주석으로 붙어 있어야 한다. 근거 없이 정한 경계는
    나중에 데이터가 그 경계를 넘어설 때 조용히 깨진다.
    """
    assert "const TERM_BUCKETS = [" in SOURCE
    assert '{ id: "37+"' in SOURCE
    # 60개월 초과는 0건이라 칸을 두지 않았다. 그 근거가 남아 있어야 한다.
    assert "60개월 초과는 **0건**" in SOURCE


def test_the_disclosure_date_takes_a_range() -> None:
    """"최근 것만"으로는 "작년 6월에 무엇이 있었나"를 물을 수 없다."""
    assert 'id="dto"' in SOURCE
    assert "state.dto != null && !(r.asOf && r.asOf <= state.dto)" in SOURCE


def test_the_rate_basis_moves_both_the_filter_and_the_sort() -> None:
    """한쪽만 옮기면 최고금리로 걸러 놓고 기본금리로 정렬된다."""
    assert 'const rateOf = (r) => (state.basis === "max" ? r.max : r.base);' in SOURCE
    assert "if (state.rmin != null && !(rateOf(r) >= state.rmin)) return false;" in SOURCE
    assert 'if (state.sort === "base" || state.sort === "max") state.sort = state.basis;' \
        in SOURCE


def test_the_average_never_hides_its_denominator() -> None:
    """최고금리는 전체의 27.6%에만 있다.

    없는 것을 0으로 세면 평균이 통째로 거짓이 된다. 분모를 값 옆에 적는다.
    """
    assert "원천 미제공" in SOURCE
    assert "건 기준" in SOURCE
    assert "const average = (rows, pick) =>" in SOURCE


def test_the_average_is_computed_over_the_filtered_set_not_the_page() -> None:
    """보이는 100건으로 내면 정렬을 바꿀 때마다 평균이 움직인다."""
    assert "const base = average(current, (r) => r.base);" in SOURCE
    assert "average(ALL" not in SOURCE


# ── 수집원 주석 · 수집 실행 링크 (2026-08-06) ───────────────────────────


def test_every_collected_source_has_a_footnote() -> None:
    """표의 «수집원» 칸에는 `fsb` 같은 코드가 그대로 찍힌다.

    그게 무엇이고 어디서 온 값인지가 화면 어디에도 없었다. 수집기가 있는
    원천은 전부 설명이 있어야 한다.
    """
    from rate_monitor.cli import ADAPTERS, INDICATOR_ADAPTERS

    match = re.search(r"const SOURCE_NOTE = \{(.*?)\n  \};", SOURCE, re.S)
    assert match, "SOURCE_NOTE를 찾지 못했다"
    described = set(re.findall(r"^\s{4}(\w+):", match.group(1), re.M))
    missing = (set(ADAPTERS) | set(INDICATOR_ADAPTERS)) - described
    assert not missing, f"설명 없는 수집원: {sorted(missing)}"


def test_the_footnote_says_what_each_region_means() -> None:
    """같은 «부산»이라도 어디서 온 값인지가 원천마다 다르다.

    이걸 안 적으면 신협의 조회조건과 새마을금고의 점포 주소가 같은 값으로
    읽힌다 (v4 §4.1).
    """
    assert "본점 소재지" in SOURCE      # fsb
    assert "조회 조건" in SOURCE        # cu
    assert "점포 주소" in SOURCE        # kfcc · nh_local


def test_the_footnote_does_not_repeat_the_collection_mode() -> None:
    """수집 방식은 DB의 `mode`가 말한다. 두 곳에 적으면 겹쳐 나온다."""
    assert "const MODE_KO = { api:" in SOURCE
    match = re.search(r"const SOURCE_NOTE = \{(.*?)\n  \};", SOURCE, re.S)
    assert "오픈API\"" not in match.group(1), "설명에 수집 방식이 또 들어갔다"


def test_a_source_with_no_observations_is_not_described() -> None:
    """없는 것을 설명하면 화면에 있는 줄 알게 된다."""
    assert "s.observation_count > 0" in SOURCE


def test_the_collect_link_carries_no_token_and_hides_without_a_repo() -> None:
    """정적 사이트라 페이지 안에서 수집을 돌릴 수 없다.

    링크만 건다 — 실행 권한이 있는 사람만 실제로 돌릴 수 있다. 저장소
    이름은 빌드 때 환경에서 받고, 없으면 버튼을 통째로 숨긴다.
    """
    assert 'id="collect" hidden' in SOURCE
    assert "if (data.collect_workflow_url) {" in SOURCE
    # 주소를 화면에 박지 않는다. 포크나 로컬 빌드가 엉뚱한 곳을 가리킨다.
    assert "github.com/dekt-oss" not in SOURCE


def test_the_collect_url_comes_from_the_build_environment() -> None:
    """저장소 이름을 코드에 박으면 포크가 원본을 가리킨다."""
    import os

    from rate_monitor.services.dashboard_service import _collect_workflow_url

    before = os.environ.get("GITHUB_REPOSITORY")
    try:
        os.environ["GITHUB_REPOSITORY"] = "dekt-oss/bank-rate-collector"
        assert _collect_workflow_url() == (
            "https://github.com/dekt-oss/bank-rate-collector"
            "/actions/workflows/collect.yml"
        )
        # 값이 없거나 모양이 아니면 링크를 만들지 않는다.
        os.environ["GITHUB_REPOSITORY"] = ""
        assert _collect_workflow_url() is None
        os.environ["GITHUB_REPOSITORY"] = "이름만있음"
        assert _collect_workflow_url() is None
    finally:
        if before is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = before


# ── 우대조건 필터 (2026-08-06) ──────────────────────────────────────────


def test_the_three_preference_states_stay_distinct() -> None:
    """미제공 · 명시적 없음 · 있음. 셋을 뭉개면 화면이 거짓말을 한다.

    실측(발행 DB 150,311건)으로 미제공이 72.6%다. 새마을금고는 공식 화면에
    우대금리 열 자체가 없어서 그렇다. 그걸 "없음"으로 적으면 우대금리가
    없는 상품처럼 보인다 (v4 §3.3).
    """
    assert 'present: "우대조건 있음"' in SOURCE
    assert "none: \"우대조건 없음(원천 명시)\"" in SOURCE
    assert 'missing: "원천 미제공"' in SOURCE


def test_the_detail_conditions_open_only_under_present() -> None:
    """미제공·없음 행에는 붙일 분류가 없다.

    켜 둔 채로 두면 조건을 걸수록 결과가 비는 것처럼 보인다.
    """
    assert 'if (!state.picked.prefStatus.has("present")) return "";' in SOURCE
    assert 'if (!state.picked.prefStatus.has("present")) state.prefTags.clear();' in SOURCE


def test_the_top_conditions_lead_but_nothing_starts_checked() -> None:
    """상위 분류를 앞에 세우되 기본 체크는 비운다.

    처음부터 켜 두면 첫 화면이 이미 걸러진 상태가 되고, 그걸 전체 목록으로
    오해한다. 순서는 실측 상위이고 «기타»는 언제나 맨 끝이다.
    """
    assert "const PREF_TOP = [" in SOURCE
    assert 'counts.has("OTHER") ? ["OTHER"] : []' in SOURCE
    assert "prefTags: new Set()," in SOURCE


def test_the_detail_filter_is_an_or_not_an_and() -> None:
    """조건은 여러 개가 함께 붙는다. 전부 만족을 요구하면 거의 안 남는다."""
    assert "if (r.prefTags.has(code)) hit = true;" in SOURCE
