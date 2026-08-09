"""공개 화면 개편 (v4 §10, PR 7-3).

화면 자체는 브라우저에서 돌지만, **화면이 기대하는 데이터가 실제로 나가는지**와
**금지사항을 어기지 않는지**는 여기서 못 박는다.

브라우저 확인은 별도로 했다 (2026-08-06, Chromium + Playwright, 발행 DB).

    1차 (137,422행)  첫 렌더 1.5초, 업권 탭 5개, 부산 구·군 16개,
                     참고카드 2장, 우대조건 펼치기, 콘솔 오류 0건

    2차 (133,764행, 조회 조건 개편 뒤)
        업권 탭 6개, 지역에서 부산을 켜니 구·군 16개가 펼쳐짐
        동구 15,822 → 1,537건, 7~12개월 45,736건
        시중은행 333건 — 서울 시도를 걸어도 그대로, 전 행에 «전국 공시» 배지

    3차 (133,849행, 업권 탭을 뺀 뒤 · 2026-08-07)
        권역 체크박스 5개 — kfcc·cu·nh_local·savings_bank·bank
        부산 체크 → 구·군 16개 → 동구 1,537건 → 해제하니 133,849건 복귀
        은행만 333건, 서울 시도를 걸어도 333건 그대로, 배지 100행
        참고카드 5장 — 기준금리 2.75% · 시중은행 3.12%/3.85% ·
                       2금융권 3.27%(평균)/5.00%
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
    # 카드가 하나도 안 만들어지면 자리째 숨는다. 2026-08-07에 카드를 다시
    # 그리게 되면서(우리 회사를 바꾸면 첫 칸이 따라와야 한다) 조건이
    # «보이기»에서 «몇 장인가»로 바뀌었다.
    assert '$("marks").hidden = !cards.length;' in SOURCE


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


# ── 업권 ────────────────────────────────────────────────────────────────


def test_the_commercial_bank_is_a_main_sector_by_explicit_decision() -> None:
    """시중은행도 메인 비교표에 선다 (v4 §6.4 정정, 2026-08-06).

    한때 이 테스트는 정반대를 못박고 있었다. 사용자가 넣기로 정했다.
    """
    match = re.search(r"const MAIN_SECTORS = \[([^\]]+)\]", SOURCE)
    assert match, "MAIN_SECTORS를 찾지 못했다"
    assert "bank" in [s.strip().strip('"') for s in match.group(1).split(",")]


def test_the_sector_axis_lives_in_only_one_place() -> None:
    """업권을 고르는 곳이 둘이면 어느 쪽이 이겼는지 화면으로 알 수 없다.

    2026-08-07에 화면 위 «업권 탭»을 뺐다. 아래 조회 조건의 «권역»
    체크박스와 같은 축이라 중복이었다. 구·군을 지역 안으로 넣은 것과
    같은 이유다.
    """
    assert 'id="tabs"' not in SOURCE, "업권 탭이 되살아났다"
    assert "state.tab" not in SOURCE
    assert 'id="busan-go"' not in SOURCE, "부산 바로가기가 지역 축과 겹친다"


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


def test_unknown_sectors_are_not_dropped_from_the_screen() -> None:
    """새 수집원이 늘었는데 화면에서 통째로 사라지면 안 된다.

    권역 체크박스는 **데이터에 있는 값을 그대로** 그린다 (`countsOf`).
    목록에 없는 업권이 들어와도 칸이 생긴다 — 탭이 있던 시절에는
    `MAIN_SECTORS`에 없으면 뒤에 붙이는 별도 처리가 필요했다.
    """
    assert "const countsOf = (key) =>" in SOURCE
    assert 'const values = [...counts.keys()]' in SOURCE


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


def test_the_collect_form_carries_no_token_and_hides_without_a_repo() -> None:
    """화면에서 암호를 넣으면 그 자리에서 수집이 시작된다 (명세서 §12.5).

    **암호를 화면이 검사하지 않는다.** 페이지가 아는 순간 소스를 열면
    보인다. 화면은 받은 값을 같은 도메인의 함수로 보낼 뿐이고, 대조는
    함수와 워크플로가 각각 한 번씩 한다.
    """
    assert 'id="collect-box" hidden' in SOURCE
    assert "if (data.collect_workflow_url) {" in SOURCE
    assert 'COLLECT_ENDPOINT = "api/collect"' in SOURCE
    # 주소를 화면에 박지 않는다. 포크나 로컬 빌드가 엉뚱한 곳을 가리킨다.
    assert "github.com/dekt-oss" not in SOURCE


def test_the_screen_never_holds_the_password_itself() -> None:
    """화면이 «맞다/틀리다»를 판단하면 그 판단 근거가 화면 안에 있다는 뜻이다.

    실제로 그렇게 짜기 쉬운 자리다 — 틀린 암호를 서버까지 보내지 말자는
    생각이 자연스럽기 때문이다. 그러면 소스 보기 한 번으로 뚫린다.
    """
    for forbidden in ("COLLECT_PASSWORD", "DASHBOARD_PASSWORD", "GITHUB_DISPATCH_TOKEN"):
        assert forbidden not in SOURCE, forbidden
    # 화면이 하는 일은 보내고 받아 적는 것뿐이다.
    assert "method: \"POST\"" in SOURCE


def test_the_github_link_stays_as_a_fallback() -> None:
    """함수가 아직 설정되지 않은 배포에서 아무 길도 없으면 안 된다."""
    assert 'id="collect" hidden' in SOURCE
    assert "body.configured === false" in SOURCE


def test_the_screen_points_at_the_document_that_says_what_is_not_guaranteed() -> None:
    """「이 데이터를 믿어도 되나」에 답하려면 근거 문서까지 갈 수 있어야 한다.

    화면 안에 다 적으면 아무도 안 읽고, 어디에도 없으면 물어볼 곳이 없다.
    수집 링크와 같은 규칙으로 저장소 주소를 환경에서 받는다.
    """
    import os
    from pathlib import Path

    from rate_monitor.services.dashboard_service import _repo_file_url

    assert "data.data_trust_url" in SOURCE
    assert "이 데이터를 얼마나 믿을 수 있나" in SOURCE
    # 링크가 가리키는 문서가 실제로 있어야 한다.
    doc = Path(__file__).resolve().parents[1] / "docs" / "data-trust.md"
    assert doc.exists(), "화면이 없는 문서를 가리킨다"

    # **여기가 진짜 검사다.** 공개 화면은 `build_summary`를 통째로 싣지
    # 않는다. `INLINE_KEYS`에 적힌 것만 간다. 처음에 이 줄을 안 넣어서
    # 링크가 코드에도 문서에도 있는데 발행본에서만 조용히 사라졌다 —
    # 화면 소스만 보면 멀쩡해 보이는 종류의 결함이다.
    from rate_monitor.services.site_service import INLINE_KEYS

    assert "data_trust_url" in INLINE_KEYS, "발행본까지 안 실린다"

    before = os.environ.get("GITHUB_REPOSITORY")
    try:
        os.environ["GITHUB_REPOSITORY"] = "dekt-oss/bank-rate-collector"
        assert _repo_file_url("docs/data-trust.md") == (
            "https://github.com/dekt-oss/bank-rate-collector"
            "/blob/main/docs/data-trust.md"
        )
        os.environ["GITHUB_REPOSITORY"] = ""
        assert _repo_file_url("docs/data-trust.md") is None
    finally:
        if before is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = before


# ── 조회 화면 R1 (2026-08-07) ───────────────────────────────────────────


def test_the_charts_draw_without_any_library() -> None:
    """회사 PC 망분리 환경에서 CDN이 막히면 차트만 통째로 사라진다.

    그래서 SVG를 직접 그린다. 외부 주소가 하나라도 들어오면 이 규칙이
    깨진 것이다.
    """
    for bad in ("cdn.", "unpkg", "jsdelivr", "chart.js", "d3.v", "https://"):
        assert bad not in SOURCE.lower().replace("https://github.com", ""), bad
    for chart in ('id="hist"', 'id="terms"', 'id="reg"'):
        assert chart in SOURCE, chart


def test_chart_colours_come_from_css_variables_not_literals() -> None:
    """SVG에 색을 박으면 다크모드에서 안 따라온다.

    토글 뒤 차트만 밝은 색으로 남으면 «왜 여기만 안 바뀌나»가 된다.
    """
    assert 'getComputedStyle(document.documentElement)' in SOURCE
    # 차트를 그리는 코드에 16진 색이 있으면 안 된다. 흰 글자(#fff)는
    # 색 배지 위에 얹는 것이라 변수로 둘 수 없다 — 그것만 예외다.
    chart_src = SOURCE[SOURCE.index("── 차트 1"):SOURCE.index("── 조건을 주소에 담는다")]
    literals = [w for w in re.findall(r"#[0-9a-fA-F]{3,6}", chart_src) if w != "#fff"]
    assert not literals, f"차트에 박힌 색: {literals}"
    # 테마를 바꾸면 다시 그린다. 안 그리면 옛 색이 그대로 남는다.
    assert SOURCE.index("applyTheme(next)") < SOURCE.index("drawCharts();\n  });")


def test_a_chart_that_ignores_the_filters_says_so() -> None:
    """빼면 보는 사람이 차트와 표를 같은 모집단으로 믿는다.

    표 바로 위에 나란히 있으므로 제일 위험한 오해다.
    """
    # 배지는 상태에 따라 바뀐다(좁혔으면 «12개월 정기예금 기준»).
    # 초기 마크업이 «조회 조건 반영»이고 id로 갈아끼운다.
    assert '<span class="badge live" id="hist-badge">조회 조건 반영</span>' in SOURCE
    assert '<span class="badge live" id="terms-badge">조회 조건 반영</span>' in SOURCE

    # 권역 차트만 조건을 안 따른다. 막대가 전체 집계라 그래야 하고,
    # 그 사실을 배지·배경·캡션 셋으로 밝힌다.
    assert '<span class="badge">전체 기준</span>' in SOURCE
    assert "조회 조건과 무관한 전체 집계라 아래 표와\n        모집단이 다릅니다" in SOURCE
    assert 'class="card wide global"' in SOURCE
    # 조건을 따르게 된 차트에는 «다른 모집단» 표시가 남으면 안 된다.
    assert 'class="card global"' not in SOURCE


def test_the_representative_value_is_never_the_maximum() -> None:
    """우대 상품 한 건이 권역 전체를 대표하면 안 된다.

    권역 차트는 `base_p50`만 읽는다. `base_max`를 읽는 순간 강서구가
    직장금고 하나 때문에 10.00%로 선다.
    """
    chart = SOURCE[SOURCE.index("── 차트 3"):SOURCE.index("const drawCharts")]
    assert "base_p50" in chart
    assert "base_max" not in chart


def test_a_thin_sample_is_named_not_drawn() -> None:
    """96건과 1,284건의 중앙값은 같은 값이 아니다."""
    assert "REG_MIN_N" in SOURCE
    assert "표본 부족" in SOURCE
    assert "개사 · " in SOURCE, "막대마다 표본 크기를 적어야 한다"


def test_the_axis_says_it_does_not_start_at_zero() -> None:
    """권역 중앙값은 서로 0.15%p 안쪽이라 축을 압축해야 차이가 보인다.

    압축했으면 그 사실을 적어야 한다. 안 적으면 막대 높이 비율이 금리
    비율로 읽힌다.
    """
    assert "0부터가 아닙니다" in SOURCE
    # 여백을 위아래 같은 값으로 두면 위는 막대를 눕히고 아래는 우리 회사
    # 선을 바닥에 붙인다. 붙으면 3.20%인데도 «0에 가깝다»로 읽힌다.
    assert "- 0.10) * 100" in SOURCE


def test_our_company_is_one_colour_everywhere() -> None:
    """같은 대상을 화면 세 곳에서 다른 색으로 그리면 같은 것인지 알 수 없다.

    카드 왼쪽 선 · 히스토그램 세로선 · 권역 기준선이 모두 `--crit`이다.
    """
    assert "border-left: 4px solid var(--crit)" in SOURCE
    hist = SOURCE[SOURCE.index("── 차트 1"):SOURCE.index("── 차트 2")]
    assert 'css("--crit")' in hist
    reg = SOURCE[SOURCE.index("── 차트 3"):SOURCE.index("const drawCharts")]
    assert 'css("--crit")' in reg


def test_the_pinned_row_never_appears_twice() -> None:
    """같은 행이 고정과 본문에 둘 다 나오면 어느 쪽이 진짜인지 알 수 없다."""
    assert "current.filter((r) => r !== pinned)" in SOURCE
    assert "rows.unshift(withDetail(pinned, stats))" in SOURCE


def test_missing_from_the_filter_is_not_last_place() -> None:
    """0위나 «—»로 적으면 «우리가 꼴찌»로 읽힌다."""
    assert "조회 조건 안에 ${state.mine}이(가) 없습니다" in SOURCE
    assert "우리 회사를 지정하면 순위와 격차가 표시됩니다" in SOURCE
    # 지정 상태를 못 빠져나오면 안 된다.
    assert '<option value="">지정 안 함</option>' in SOURCE


def test_rank_and_gap_use_the_median_not_the_average() -> None:
    """금리 분포는 우대 상품 때문에 오른쪽 꼬리가 길다.

    평균은 «가운데»가 아니고, 시중은행 참고카드가 이미 중앙값을 쓴다.
    """
    stats = SOURCE[SOURCE.index("const mineStats"):SOURCE.index("const deltaHtml")]
    assert "median(rows.map(rateOf))" in stats
    assert "average(" not in stats
    # 동점은 경쟁 순위(1,2,2,4)다. 평균 순위는 보고서에 옮겨 적기 어렵다.
    assert "> value).length + 1" in stats


def test_the_second_tier_card_leads_with_the_median() -> None:
    """시중은행 카드가 중앙값인데 2금융권만 평균이면 나란히 못 놓는다."""
    card = SOURCE[SOURCE.index("const st = marks.second_tier_12m"):
                  SOURCE.index("// 4. 옆 시장")]
    assert "Number(st.median).toFixed(2)" in card
    assert "평균 ${Number(st.mean).toFixed(2)}" in card
    # 분모 표기는 지우지 않는다.
    assert "원천 미제공" in card


def test_history_that_does_not_exist_is_not_drawn() -> None:
    """이력이 없는데 선을 그리면 없는 과거를 지어내는 것이다."""
    assert "추이 — 스냅샷 축적 중" in SOURCE
    assert "spark-empty" in SOURCE


def test_the_our_company_list_is_short_and_defaults_to_the_first() -> None:
    """2,000개 기관을 전부 세우면 고를 수 없다 (2026-08-07 사용자 지정).

    목록을 데이터에서 뽑지 않는 것도 일부러다 — 수집 결과에 따라 흔들리면
    어제 고른 회사가 오늘 사라진다.
    """
    match = re.search(r"const MINE_CHOICES = \[(.*?)\];", SOURCE, re.S)
    assert match, "MINE_CHOICES를 찾지 못했다"
    names = [s.strip().strip('"') for s in match.group(1).split(",") if s.strip()]
    assert names == ["고려저축은행", "예가람저축은행", "동원제일저축은행"]
    # 첫 항목이 기본값이다.
    assert "MINE_CHOICES[0]" in SOURCE
    # 목록에 있어도 이번 데이터에 없으면 조용히 두지 않는다.
    assert "우리 회사 후보 중 이번 데이터에 없는 곳" in SOURCE


def test_turning_our_company_off_survives_a_revisit() -> None:
    """지우면 다음 방문에 기본값으로 되살아난다. 껐는데 켜져 있는 꼴이다."""
    assert "store.set(MINE_KEY, e.target.value)" in SOURCE
    assert "saved === null ? MINE_CHOICES[0] : saved" in SOURCE


def test_our_own_representative_rate_is_a_median_too() -> None:
    """우리 쪽만 최고값이면 «시장 중앙값 대비»가 서로 다른 것의 뺄셈이 된다.

    2026-08-07 변경. 그 전에는 `Math.max`가 대표값이었다. 최고값은 우대
    조건이 붙은 상품 한 건이 그 기관 전체를 대표해 버린다 — 권역 차트에서
    최고값을 안 쓰는 이유와 똑같다.
    """
    stats = SOURCE[SOURCE.index("const mineStats"):SOURCE.index("const deltaHtml")]
    assert "const value = median(values);" in stats
    # 최고값은 버리지 않는다. 분포 차트가 점선으로 함께 긋는다.
    assert "const best = Math.max(...values);" in stats
    hist = SOURCE[SOURCE.index("── 차트 1"):SOURCE.index("── 차트 2")]
    assert 'stroke-dasharray="3 3"' in hist, "최고값 점선이 없다"
    assert "중앙값 ${ours.toFixed(2)}%" in hist


def test_the_region_chart_covers_all_of_the_second_tier() -> None:
    """제목이 «2금융권»이면 데이터도 2금융권이어야 한다.

    저축은행만 담아 놓고 이름만 바꾸면 화면이 거짓말을 한다.
    """
    from rate_monitor.services.dashboard_service import (
        BENCHMARK_SECOND_TIER,
        SECOND_TIER_SECTOR,
    )

    assert f'const REG_SECTOR = "{SECOND_TIER_SECTOR}"' in SOURCE
    # 2026-08-07에 기간·유형을 12개월 정기예금으로 못박으면서 이름이 늘었다.
    assert "2금융권 12개월 정기예금 중앙값" in SOURCE
    assert "저축은행 기본금리 중앙값" not in SOURCE
    # 합산 이름이 실제 업권 코드와 겹치면 목록에 나란히 선다.
    assert SECOND_TIER_SECTOR not in BENCHMARK_SECOND_TIER


def test_the_pinned_row_can_expand_its_preference_text() -> None:
    """정작 제일 궁금한 행이 안 펼쳐지고 있었다 (2026-08-07).

    고정 행만 따로 그려서 원문 줄이 아예 안 붙었다. 같은 함수를 거치게 한다.
    """
    assert "rows.unshift(withDetail(pinned, stats))" in SOURCE
    assert "const rows = slice.map((r) => withDetail(r, null));" in SOURCE


def test_the_whole_preference_cell_opens_the_text() -> None:
    """단추 글자만 눌리게 두면 겨냥하기 어렵다.

    원문이 있는 행에만 붙인다 — 없는 행에 손 모양 커서를 띄우면 눌러도
    아무 일이 없어 고장으로 읽힌다.
    """
    assert 'data-pref-cell="${esc(r._i)}"' in SOURCE
    assert 'c.key === "pref" && r.pref' in SOURCE
    assert 'e.target.closest("[data-pref], [data-pref-cell]")' in SOURCE
    assert "td[data-pref-cell] { cursor: pointer; }" in SOURCE


def test_the_histogram_counts_bins_with_integers() -> None:
    """`Math.floor((v - lo) / 0.2)`는 0.2의 배수를 앞 구간으로 흘린다.

    IEEE754에서 `2.4 / 0.2 === 11.999...`다. 실측(133,849행)에서 여섯 경계가
    새면서 전체의 11.6%가 엉뚱한 칸에 들어갔고, 인접 구간이 −5,988 / +5,988로
    널뛰어 톱니가 됐다.

    아래는 그 실패를 파이썬으로 그대로 재현한 것이다. **화면 코드가 나눗셈으로
    되돌아가면 이 테스트가 먼저 깨져야 한다.**
    """
    import math

    step, lo = 0.2, 0.0
    leaked = [round(k * step, 1) for k in range(20)
              if math.floor((round(k * step, 1) - lo) / step) != k]
    assert leaked, "부동소수점 전제가 깨졌다 — 이 테스트를 다시 봐야 한다"
    assert 2.4 in leaked and 2.8 in leaked

    # 정수로 세면 하나도 안 샌다. 화면이 쓰는 식과 같은 모양이다.
    s100 = round(step * 100)
    assert not [k for k in range(20)
                if (round(round(k * step, 1) * 100) - round(lo * 100)) // s100 != k]

    hist = SOURCE[SOURCE.index("── 차트 1"):SOURCE.index("── 차트 2")]
    assert "Math.round(v * 100) - LO100" in hist, "구간을 정수로 세지 않는다"
    assert "Math.floor((v - lo) / HIST_STEP)" not in hist, "나눗셈으로 되돌아갔다"


def test_the_histogram_narrows_only_when_nothing_is_picked() -> None:
    """조건을 걸면 조건을 따라야 한다. 배지가 «조회 조건 반영»인 이유다.

    안 걸었을 때만 12개월 정기예금으로 좁힌다 — 13만 건을 통째로 그리면
    정기예금 1개월 1.00%와 12개월 3.40%가 한 그림에 겹쳐 분포가 아니게 된다.
    """
    assert "const noTermOrTypePicked = () =>" in SOURCE
    guard = SOURCE[SOURCE.index("const noTermOrTypePicked"):
                   SOURCE.index("const histogram = ()")]
    # 기간 체크박스·유형 체크박스·개월 직접 입력 넷을 모두 본다. 하나라도
    # 빠지면 사용자가 건 조건을 무시하고 좁힌다.
    for axis in ("state.picked.term.size", "state.picked.type.size",
                 "state.tmin == null", "state.tmax == null"):
        assert axis in guard, axis


def test_a_narrowed_histogram_says_so_and_names_the_whole() -> None:
    """그림 3.40%와 결과 바 2.50%가 동시에 보이는데 이유가 없으면,
    고치려던 혼란을 자리만 옮긴 것이 된다.
    """
    assert 'id="hist-badge"' in SOURCE
    assert '"12개월 정기예금 기준" : "조회 조건 반영"' in SOURCE
    hist = SOURCE[SOURCE.index("── 차트 1"):SOURCE.index("── 차트 2")]
    assert "좁혀 그렸습니다" in hist
    assert "전체의 ${label} 중앙값은" in hist, "표 전체 중앙값을 함께 적어야 한다"
    # 좁힌 집합에서 우리 회사 선을 다시 낸다. 전체에서 낸 값을 얹으면
    # 선이 분포 밖에 서거나 «이 구간»이 딴 칸을 가리킨다.
    assert "stats = mineStats(source)" in hist


def test_a_narrow_filter_never_leaves_the_chart_empty() -> None:
    """좁혔는데 20건도 안 남으면 좁히지 않는다. 빈 그림보다 섞인 그림이 낫다."""
    # 판단은 `screenBasis()`가 한 곳에서 한다 (차트 1 앞에 있다).
    basis = SOURCE[SOURCE.index("const screenBasis = () =>"):
                   SOURCE.index("const wholeBasis = () =>")]
    assert "rows.length >= HIST_MIN_ROWS" in basis
    assert "{ rows: current, narrowed: false }" in basis


def test_the_region_chart_is_pinned_to_the_same_basis_as_the_card() -> None:
    """참고카드는 12개월 정기예금인데 권역 차트가 전체면 1%p 가까이 벌어진다.

    실제로 그랬다 — 카드 3.40%, 권역 2.4~2.5%. 같은 화면의 두 숫자가 다른데
    이유가 어디에도 없었다.
    """
    assert "2금융권 12개월 정기예금 중앙값" in SOURCE
    assert "위 참고카드와 같은 기준" in SOURCE


def test_our_company_number_is_decided_in_one_place() -> None:
    """세 곳이 «고려저축은행 중앙값»이라 적는데 값이 달랐다 (2026-08-07).

    카드 3.00%(전 상품군) · 분포 3.90%(12개월 정기예금) · 권역선 3.00%.
    **권역 차트가 제일 나빴다** — 막대는 12개월 기준인데 기준선만 전체
    기준이라, 서로 다른 것을 비교해 «우리가 전 권역보다 낮다»고 보였다.
    12개월로 재면 3.90%라 정반대다.
    """
    assert "const screenBasis = () =>" in SOURCE
    assert "const wholeBasis = () =>" in SOURCE

    # 카드·순위줄·분포는 화면 기준 하나를 공유한다.
    assert SOURCE.count("mineStats(screenBasis().rows)") == 2   # render + 카드
    assert "const stats = mineStats(source);" in SOURCE          # 분포

    # 권역 차트는 «전체 기준»이라 조건을 안 따른다. 막대와 같은 잣대여야
    # «전 권역보다 높다/낮다»가 참이 된다.
    assert "regionBars(mineStats(wholeBasis()))" in SOURCE
    assert "mineStats(current)" not in SOURCE, "옛 잣대가 남아 있다"


def test_a_different_denominator_says_what_it_is() -> None:
    """결과 바의 건수(133,849)와 순위 분모(16,689)가 다른데 이유가 없으면
    둘 중 뭐가 맞는지 알 수 없다.
    """
    assert "const basisLabel = () =>" in SOURCE
    assert 'class="on"' in SOURCE
    # 카드 제목도 같은 이름을 쓴다.
    assert '${basisLabel() || "조회 조건 기준"}' in SOURCE


def test_the_charts_use_the_real_pixel_width() -> None:
    """viewBox를 1160으로 못박으면 좁은 화면에서 그만큼 눌린다.

    모바일 실측(390px 뷰포트)에서 권역 차트가 배율 0.288로 눌려 글자가
    2.7~3.3px이 됐다 — 본문 14.5px의 5분의 1이라 읽을 수가 없다.
    실제 폭을 viewBox로 쓰면 배율이 1이라 font-size가 곧 픽셀이다.
    """
    assert "const chartWidth = (id, fallback) =>" in SOURCE
    for chart in ('chartWidth("hist"', 'chartWidth("terms"', 'chartWidth("reg"'):
        assert chart in SOURCE, chart
    # 폭이 바뀌면 다시 그려야 한다. 안 그리면 창을 돌렸을 때 옛 폭이 남는다.
    assert 'window.addEventListener("resize"' in SOURCE
    # 높이만 바뀔 때는 안 그린다 — 모바일 주소창이 접힐 때마다 다시 그리면
    # 13만 행이 딸려 스크롤이 끊긴다.
    assert "if (window.innerWidth === lastWidth) return;" in SOURCE


def test_the_region_chart_lies_down_when_the_screen_is_narrow() -> None:
    """세로 막대 아홉을 340px에 세우면 막대당 37px이다.

    «인천·경기»도 «271개사 · 2,603건»도 안 들어간다.
    """
    reg = SOURCE[SOURCE.index("── 차트 3"):SOURCE.index("const drawCharts")]
    assert "const wide = W >= 900;" in reg
    assert "가로축은 ${lo.toFixed(2)}%부터 시작합니다" in reg, "눕혀도 축을 밝힌다"
    assert "세로축은 ${lo.toFixed(2)}%부터 시작합니다" in reg
    # 어느 배치든 표본 크기는 적는다.
    assert reg.count("개사 · ${num(d.n)}건") == 2


def test_the_url_replaces_instead_of_pushing() -> None:
    """`pushState`면 체크박스 하나에 뒤로가기가 한 칸씩 쌓인다.

    그러면 화면을 빠져나갈 수 없다.
    """
    assert "history.replaceState" in SOURCE
    assert "history.pushState" not in SOURCE


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


# ── 참고카드: 2금융권 (2026-08-07) ──────────────────────────────────────


def test_the_second_tier_card_is_separate_from_the_bank_card() -> None:
    """전국 공시와 점포 기준을 한 숫자에 섞지 않는다 (v4 §4.1).

    합치면 그 값이 무엇의 평균인지 말할 수 없게 된다.
    """
    from rate_monitor.services.dashboard_service import (
        BENCHMARK_BANK,
        BENCHMARK_SECOND_TIER,
    )

    assert BENCHMARK_BANK == ("bank",)
    assert set(BENCHMARK_SECOND_TIER) == {"savings_bank", "kfcc", "cu", "nh_local"}
    assert not set(BENCHMARK_BANK) & set(BENCHMARK_SECOND_TIER)
    assert "second_tier_12m" in SOURCE


def test_the_second_tier_top_rate_shows_its_denominator() -> None:
    """새마을금고·농·축협은 원천에 우대금리 열 자체가 없다.

    그 상단은 최고금리를 준 기관에서만 나온 값이므로 분모를 함께 적어야
    한다. 안 적으면 2천 곳 전체의 상단으로 읽힌다.
    """
    assert "max_record_count" in SOURCE
    assert "원천 미제공" in SOURCE


def test_the_second_tier_card_says_which_statistic_it_shows() -> None:
    """평균과 중앙값은 다른 질문에 답한다. 어느 쪽인지 적는다.

    2026-08-07에 **큰 숫자가 평균에서 중앙값으로 바뀌었다.** 시중은행
    카드가 이미 중앙값을 쓰는데 2금융권만 평균이라 두 카드를 나란히 놓고
    비교할 수 없었다. 평균은 사라지지 않고 부연으로 내려갔다 — 어느 쪽도
    지우지 않는다.
    """
    assert "기본금리 <b>중앙값</b>" in SOURCE
    assert "평균 ${Number(st.mean).toFixed(2)}%" in SOURCE


# ── 0.00%로 공시된 행 (2026-08-09) ──────────────────────────────────────


def test_zero_rate_rows_can_be_filtered_out() -> None:
    """발행 데이터 실측 10,544건(3.22%)이고 거의 전부 농·축협과 새마을금고다.

    **읽기 실패가 아니다.** 못 읽은 값은 빈칸으로 남고 0이 되지 않는다
    (`domain/normalization.py`의 `parse_rate`). 원천이 실제로 0.00으로 공시한
    것이고 대개 그 지점에서 취급하지 않는 상품인데, 화면에서는 «0% 금리
    상품»으로 읽힌다. 그래서 끌 수 있게 둔다.
    """
    assert 'id="hide-zero"' in SOURCE
    assert "state.hideZero && rateOf(r) === 0" in SOURCE


def test_the_zero_filter_starts_off() -> None:
    """빈 체크는 전체를 뜻한다. 기본으로 빼면 그 약속이 깨진다."""
    assert "hideZero: false," in SOURCE
    # 켜져 있는 상태로 시작하는 표시가 없어야 한다.
    assert 'id="hide-zero" checked' not in SOURCE


def test_the_zero_filter_is_measured_against_the_chosen_basis() -> None:
    """우대금리 기준일 때 기본금리가 0인 것은 이 조건과 상관이 없다."""
    assert "state.hideZero && rateOf(r) === 0" in SOURCE
    assert "state.hideZero && r.base === 0" not in SOURCE


def test_the_zero_filter_travels_in_the_link() -> None:
    """안 실으면 링크를 받은 사람이 다른 건수를 보면서 같은 화면이라 믿는다."""
    assert 'p.set("nozero", "1")' in SOURCE
    assert 'p.get("nozero") === "1"' in SOURCE


def test_the_zero_filter_says_how_many_rows_it_would_remove() -> None:
    """숫자가 없으면 켜 볼 이유도 알 수 없고, 껐다 켜며 세어 보게 된다."""
    assert 'id="zero-count"' in SOURCE
    assert "r.base === 0 ? 1 : 0" in SOURCE


def test_resetting_the_conditions_clears_the_zero_filter() -> None:
    """«조건 초기화»가 안 지우는 조건이 하나 있으면 그것부터 의심하게 된다."""
    reset = SOURCE[SOURCE.index('$("reset").addEventListener'):]
    reset = reset[:reset.index("renderGroups();")]
    assert "hideZero: false" in reset
    assert '$("hide-zero").checked = false' in reset
