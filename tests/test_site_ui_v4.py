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


def test_korean_brand_is_broad_and_the_page_is_light_only() -> None:
    assert "RATE FINDER" not in SOURCE
    assert "DEPOSIT RATE INTELLIGENCE" not in SOURCE
    assert "<title>전국 예·적금 금리 비교</title>" in SOURCE
    assert '<h1 class="brand-title">전국 예·적금 금리 비교</h1>' in SOURCE
    assert 'id="theme"' not in SOURCE
    assert 'id="copylink"' not in SOURCE
    assert "prefers-color-scheme: dark" not in SOURCE
    assert "data-theme" not in SOURCE


def test_source_caveat_is_small_and_below_the_result_table() -> None:
    table = SOURCE.index('<div class="scroll">')
    caveat = SOURCE.index('<p class="source-caveat">')
    footer = SOURCE.index('<footer id="foot">')
    assert table < caveat < footer
    assert ".source-caveat" in SOURCE


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
    assert 'state.gu.clear(); state.detailOpen.delete("gu");' in SOURCE


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


def test_the_rate_basis_is_always_the_max_rate() -> None:
    """비교·정렬·하한·차트가 한 기준을 써야 조건마다 답이 흔들리지 않는다."""
    assert 'const rateOf = (r) => r.max;' in SOURCE
    assert "if (state.rmin != null && !(rateOf(r) >= state.rmin)) return false;" in SOURCE
    assert 'sort: "max", dir: -1' in SOURCE
    assert 'name="basis"' not in SOURCE
    assert "최고금리(우대 포함)" in SOURCE


def test_the_average_never_hides_its_denominator() -> None:
    """최고금리는 전체의 27.6%에만 있다.

    없는 것을 0으로 세면 평균이 통째로 거짓이 된다. 분모를 값 옆에 적는다.
    """
    assert "원천 미제공" in SOURCE
    assert "건 기준" in SOURCE
    assert "const average = (rows, pick) =>" in SOURCE


def test_the_average_is_computed_over_the_filtered_set_not_the_page() -> None:
    """보이는 100건으로 내면 정렬을 바꿀 때마다 평균이 움직인다."""
    assert "const max = average(current, rateOf);" in SOURCE
    assert "최고금리 중앙값" in SOURCE
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


def test_each_footnote_is_a_single_line() -> None:
    """주석이 표보다 길어지면 아무도 안 읽는다.

    수집원 한 줄에는 화면 이름과 꼬리표 하나만 온다. 자세한 주의사항은 위
    `notice-detail`이 이미 말하고, 원천 주소는 줄을 하나 더 만든다.
    """
    match = re.search(r"const SOURCE_NOTE = \{(.*?)\n  \};", SOURCE, re.S)
    assert match, "SOURCE_NOTE를 찾지 못했다"
    body = match.group(1)
    assert "<br>" not in body and "<b>" not in body, "설명이 다시 여러 줄이 됐다"
    for text in re.findall(r'"([^"]+)"', body):
        assert len(text) <= 40, f"한 줄에 담기엔 길다: {text}"
    assert "s.base_reference" not in SOURCE, "원천 주소가 줄을 하나 더 만든다"


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


def test_the_basis_note_carries_no_repository_link() -> None:
    """«근거» 줄은 어떤 파일에서 나온 값인지만 적는다.

    무엇이 검사되고 무엇이 검사되지 않는지는 `docs/data-trust.md`에 있지만,
    화면에는 링크를 걸지 않는다 — 금리를 보러 온 사람에게 저장소 주소는 갈
    곳이 아니고, 포크에서는 가리키는 곳도 달라진다. 문서는 저장소에 그대로
    남아 있어야 하므로 파일 존재는 여기서 계속 지킨다.
    """
    from pathlib import Path

    from rate_monitor.services.site_service import INLINE_KEYS

    assert "data_trust_url" not in SOURCE, "근거 줄에 저장소 링크가 다시 붙었다"
    assert "data_trust_url" not in INLINE_KEYS, "안 쓰는 값이 발행본에 실린다"
    assert "blob/main" not in SOURCE, "화면이 저장소 파일을 직접 가리킨다"

    doc = Path(__file__).resolve().parents[1] / "docs" / "data-trust.md"
    assert doc.exists(), "근거 문서가 사라졌다"


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
    """SVG 색은 밝은 화면의 공통 CSS 토큰을 따라야 한다."""
    assert 'getComputedStyle(document.documentElement)' in SOURCE
    # 차트를 그리는 코드에 16진 색이 있으면 안 된다. 흰 글자(#fff)는
    # 색 배지 위에 얹는 것이라 변수로 둘 수 없다 — 그것만 예외다.
    chart_src = SOURCE[SOURCE.index("── 차트 1"):SOURCE.index("── 조건을 주소에 담는다")]
    literals = [w for w in re.findall(r"#[0-9a-fA-F]{3,6}", chart_src) if w != "#fff"]
    assert not literals, f"차트에 박힌 색: {literals}"
    assert "applyTheme" not in SOURCE


def test_every_chart_says_what_it_counted() -> None:
    """빼면 보는 사람이 차트와 표를 같은 모집단으로 믿는다.

    표 바로 위에 나란히 있으므로 제일 위험한 오해다. 이제 셋 다 조건을
    따르지만 **따르는 범위가 다르다** — 그래서 배지가 더 필요해졌다.

        금리 분포     조건 전부. 기간·유형이 비면 12개월 정기예금으로 좁힌다
        가입기간별   조건 전부. 좁히지 않는다 (가로축이 기간이다)
        권역별       지역만 빼고 전부
    """
    assert '<span class="badge live" id="hist-badge">조회 조건 반영</span>' in SOURCE
    assert '<span class="badge live" id="terms-badge">조회 조건 반영</span>' in SOURCE
    assert "조회 조건 반영 (지역 제외)" in SOURCE
    # 인라인 집계는 기본금리뿐이므로 최고금리 표를 받기 전에는 그리지 않는다.
    assert "const termRowsFromSummary = () => [];" in SOURCE
    assert "const regionRowsFromSummary = () => [];" in SOURCE
    assert "최고금리 표를 받는 중입니다" in SOURCE


def test_the_representative_value_is_never_the_maximum() -> None:
    """우대 상품 한 건이 권역 전체를 대표하면 안 된다.

    최고금리를 쓰되 대표값은 그 최고금리들의 중앙값이어야 한다.
    """
    chart = SOURCE[SOURCE.index("── 차트 3"):SOURCE.index("const drawCharts")]
    assert "const v = rateOf(r);" in chart
    assert "v: median(b.vals)" in chart
    assert "base_p50" not in chart


def test_a_thin_sample_is_named_not_drawn() -> None:
    """96건과 1,284건의 중앙값은 같은 값이 아니다."""
    assert "REG_MIN_N" in SOURCE
    assert "표본 부족" in SOURCE
    assert "개사 · " in SOURCE, "막대마다 표본 크기를 적어야 한다"


def test_the_region_chart_does_not_encode_the_rate_as_a_length() -> None:
    """권역 중앙값은 3.00~3.80% 안에 몰려 있다.

    막대로 그리면 축을 2.90%부터 끊어야 차이가 보이고, 끊으면 «3.80이 3.00의
    두 배»처럼 보인다. 그래서 길이로 말하지 않는 네모로 바꿨다 (2026-08-10).
    """
    reg = SOURCE[SOURCE.index("── 차트 3"):SOURCE.index("const drawCharts")]
    assert 'class="regtiles"' in SOURCE
    assert "const wide = W >= 900;" not in reg, "막대 배치가 되돌아왔다"
    assert "sy(d.v)" not in reg and "sx(d.v)" not in reg, "값을 길이로 그린다"
    # 막대 시절에는 «0부터가 아닙니다»를 적어 압축을 밝혀야 했다. 길이로
    # 말하지 않으면 밝힐 것도 없다 — 경고를 지웠으면 원인도 없어야 한다.
    assert "0부터가 아닙니다" not in reg


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


def test_the_rank_carries_its_percentile() -> None:
    """«498위»만으로는 좋은 쪽인지 알 수 없다 (2026-08-10 사용자 요청).

    분모를 나란히 적어도 30,041을 머릿속에서 나누게 된다. 순위가 나오는
    두 자리(순위 줄·참고카드)가 **같은 말을 써야** 한 쪽만 고쳐지지 않는다.

    1등이 «상위 0.0%»가 되면 분모가 없는 것처럼 읽힌다. 아래는 화면과
    같은 계산을 파이썬으로 다시 한 것이다.
    """
    assert SOURCE.count("topPct(stats.rank, stats.total)") == 2, "한 자리만 고쳤다"

    def top_pct(rank: int, total: int) -> str:
        if not total:
            return ""
        pct = rank / total * 100
        return "상위 0.1% 이내" if pct < 0.1 else f"상위 {pct:.1f}%"

    assert top_pct(498, 30_041) == "상위 1.7%"
    assert top_pct(1, 30_041) == "상위 0.1% 이내"
    assert top_pct(30_041, 30_041) == "상위 100.0%"
    assert top_pct(1, 0) == ""
    # 화면 코드가 같은 규칙을 쓰는지.
    assert 'return pct < 0.1 ? "상위 0.1% 이내" : `상위 ${pct.toFixed(1)}%`;' in SOURCE
    assert "if (!total) return \"\";" in SOURCE


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


def test_the_region_chart_names_what_it_actually_counted() -> None:
    """제목에 업권을 박아 두면 조건을 걸었을 때 거짓말이 된다.

    저축은행만 켰는데 제목이 «2금융권»이면 화면이 거짓을 말한다. 그래서
    고른 업권을 제목이 그대로 적는다.
    """
    assert "const picked = [...state.picked.sector].map((s) => SECTOR_KO[s] || s);" in SOURCE
    assert 'const who = !live ? "최고금리"' in SOURCE
    assert "const regionRowsFromSummary = () => [];" in SOURCE
    assert "저축은행 기본금리 중앙값" not in SOURCE


def test_the_pinned_row_can_expand_its_preference_text() -> None:
    """정작 제일 궁금한 행이 안 펼쳐지고 있었다 (2026-08-07).

    고정 행만 따로 그려서 원문 줄이 아예 안 붙었다. 같은 함수를 거치게 한다.
    """
    assert "rows.unshift(withDetail(pinned, stats))" in SOURCE
    assert "const rows = slice.map((r) => withDetail(r, null));" in SOURCE


def test_the_whole_row_opens_and_closes_the_text() -> None:
    """단추 글자만 눌리게 두면 겨냥하기 어렵다.

    행 아무 데나 누르면 열리고 다시 누르면 닫힌다. 펼친 원문 줄에도 같은
    표식을 붙여야 「접기」를 겨냥해 위로 되돌아가지 않는다.

    원문이 있는 행에만 붙인다 — 없는 행에 손 모양 커서를 띄우면 눌러도
    아무 일이 없어 고장으로 읽힌다.
    """
    assert 'const hit = r.pref ? ` data-row="${esc(r._i)}"` : "";' in SOURCE
    assert '<tr class="detail" data-row="${esc(r._i)}">' in SOURCE
    assert 'e.target.closest("tr[data-row]")' in SOURCE
    assert "tbody tr[data-row] { cursor: pointer; }" in SOURCE
    # 여는 것과 닫는 것이 같은 자리다. 따로 두면 한쪽만 고쳐진다.
    assert "if (state.open.has(key)) state.open.delete(key); else state.open.add(key);" in SOURCE


def test_dragging_the_text_to_copy_does_not_close_it() -> None:
    """원문 위를 눌러도 닫히게 한 뒤로 생긴 자리다.

    조건을 복사하려고 긁으면 손을 떼는 순간 창이 닫혀, 다시 열어 처음부터
    긁어야 한다.
    """
    assert "const picked = window.getSelection();" in SOURCE
    assert "if (picked && !picked.isCollapsed && tr.contains(picked.anchorNode)) return;" in SOURCE


def test_the_preference_cell_is_clipped_by_width_not_by_letter_count() -> None:
    """«24글자»로 자르면 한글에서는 칸을 넘긴다 (2026-08-10).

    한글 한 글자는 `1ch`(숫자 0의 폭)의 두 배 가까이다. 24글자가 22ch를
    그냥 넘어서, `white-space: nowrap`인 칸 밖으로 흘러 옆 칸 위에 겹쳐
    찍혔다 — 표가 깨져 보이던 원인이다. 재는 일은 브라우저에 맡긴다.
    """
    assert "one.slice(0, 24)" not in SOURCE, "글자 수로 다시 자른다"
    assert ".pref { max-width: 22ch; }" not in SOURCE, "칸에 걸면 글자가 넘쳐 흐른다"
    assert "text-overflow: ellipsis" in SOURCE
    assert '<span class="one">${esc(one)}</span>' in SOURCE


# ── 2단계: 움직이는 시각화와 자주 쓰는 조건 (2026-08-10) ──────────────


def test_the_region_chart_shows_how_much_the_median_wobbles() -> None:
    """«부산 3.20%»와 «수영구 3.45%»를 나란히 놓으면 순위를 매기고 싶어진다.

    수영구는 44건이라 표본이 조금만 달랐어도 3.10%나 3.50%가 나온다. 그 폭을
    안 적으면 **흔들림을 차이로 읽는다.** 막대마다 구간을 함께 긋는다.
    """
    assert "const medianBand = (sorted) => {" in SOURCE
    assert "band: medianBand(b.vals)," in SOURCE
    # 칸마다 «±0.15%p»로 적는다. 처음에는 막대 위에 붉은 선으로 그었는데
    # 여덟 중 일곱이 붉어져 색이 경고 구실을 못 했고, 좁은 화면에서는 선이
    # 칸 밖으로 나가 숫자와 겹쳤다 (2026-08-10).
    assert "±${w.toFixed(2)}%p" in SOURCE
    assert 'w > BAND_LOUD ? " loud" : ""' in SOURCE
    assert ".regtile .bd.loud" in SOURCE, "넘는 칸을 구분할 방법이 없다"
    # 몇 곳이 넓은지는 범례가 직접 센다. 눈으로 찾게 두면 안 찾는다.
    assert "bandWidth(d.band) > BAND_LOUD" in SOURCE


def test_the_sample_gate_measures_the_wobble_not_the_row_count() -> None:
    """«30건 미만이면 표본 부족»은 실측에서 부실한 규칙이었다 (2026-08-10).

    구·군 287곳 중 30건 이상인데 중앙값이 0.40%p 폭으로 흔들리는 곳이 6곳
    있었고, 반대로 4건뿐인데 폭이 0인 곳도 있었다 — 그 4건이 같은 금리다.
    건수는 흔들림의 대리 지표일 뿐이라 흔들림을 직접 잰다.
    """
    assert "d.n >= REG_MIN_N" not in SOURCE, "건수로 다시 자른다"
    assert "d.n < REG_MIN_N" not in SOURCE, "건수로 다시 자른다"
    assert "const shown = D.filter((d) => d.n >= MEDIAN_BAND_MIN);" in SOURCE


def test_the_median_band_matches_a_bootstrap() -> None:
    """화면은 다시 뽑아 세지 않는다(부트스트랩). 정렬 한 번으로 낸다.

    몇 번째와 몇 번째 사이에 참값이 있는지는 이항분포가 정한다. 아래는 화면과
    **같은 식**을 파이썬으로 다시 쓴 것이고, 부트스트랩 결과와 맞는지 본다.
    순서통계량 쪽이 더 좁으면 화면이 흔들림을 좁게 말하고 있다는 뜻이다.
    """
    import math
    import random
    import statistics

    def band(values: list[float]) -> tuple[float, float]:
        v = sorted(values)
        n = len(v)
        k = max(0, math.floor((n - 1.96 * math.sqrt(n)) / 2))
        return v[k], v[n - 1 - k]

    rng = random.Random(11)
    sample = [round(rng.gauss(3.2, 0.25), 2) for _ in range(120)]
    lo, hi = band(sample)
    boots = sorted(
        statistics.median(rng.choices(sample, k=len(sample))) for _ in range(400)
    )
    assert (hi - lo) >= (boots[389] - boots[10]) - 0.02, f"{lo}~{hi}"
    assert "1.96 * Math.sqrt(n)" in SOURCE, "화면이 다른 식을 쓴다"
    assert "const MEDIAN_BAND_MIN = 8;" in SOURCE


def test_a_preset_only_ticks_the_boxes_that_are_already_there() -> None:
    """단추가 숨은 조건을 만들면 «조건 3개»라고 적힌 화면에 네 개가 걸린다.

    어느 쪽이 맞는지 알 수 없게 되므로, 단추는 아래 체크박스를 켜기만 한다.
    단추가 켜는 값은 파이썬 쪽 열거형과 같은 코드여야 한다 — 한쪽만 바뀌면
    누르는 순간 0건이 되고, 화면은 «조건에 맞는 행이 없습니다»라고만 말한다.
    """
    from rate_monitor.domain.enums import ProductType, Sector

    match = re.search(r"const COND_PRESETS = \[(.*?)\n  \];", SOURCE, re.S)
    assert match, "COND_PRESETS를 찾지 못했다"
    body = match.group(1)
    for key in re.findall(r"(\w+): \[", body):
        assert key in {"region", "sector", "type", "term"}, f"없는 축: {key}"
    for code in ("term_deposit", "installment_savings"):
        assert code in body and code in {t.value for t in ProductType}
    for code in ("savings_bank", "nh_local", "cu", "kfcc"):
        assert code in body and code in {x.value for x in Sector}
    assert "state.picked[k].clear();" in SOURCE
    assert "if (on && g) applyDefaultGroup(g);" in SOURCE
    assert "else vs.forEach((v) => state.picked[k].add(v));" in SOURCE


def test_default_filters_match_the_basic_mode_contract() -> None:
    assert "const DEFAULT_TERMS" not in SOURCE
    assert 'else selectAllGroup(g.key);' in SOURCE, "가입기간도 전체 선택을 사용한다"
    assert 'const DEFAULT_REGIONS = ["서울", "경기", BUSAN_SIDO];' in SOURCE
    assert 'if (busanOn()) selectAllBusanDistricts();' in SOURCE
    assert "selectAllPreferenceTags();" in SOURCE
    assert 'dfrom: latestAsOf ? shiftDays(latestAsOf, 30) : null' in SOURCE
    assert 'state.dfrom = latestAsOf ? shiftDays(latestAsOf, 30) : null' in SOURCE
    assert 'const date = thirtyDays ? "공시일 최근 30일"' in SOURCE
    assert 'if (!hasUrlFilters) applyDefaultFilters();' in SOURCE
    assert '$("groups-basic").innerHTML' in SOURCE
    assert '$("groups-advanced").innerHTML' in SOURCE
    assert 'id="advanced-filters" hidden' in SOURCE
    assert 'id="filter-toggle"' in SOURCE


def test_all_means_every_checkbox_is_actually_selected() -> None:
    assert 'data-all="${esc(g.key)}"' in SOURCE
    assert "const selectAllGroup = (key) =>" in SOURCE
    assert "groupValues(g).forEach((v) => state.picked[key].add(v));" in SOURCE
    assert 'e.target.closest("[data-all]")' in SOURCE
    assert "if (!set.size) selectAllGroup(box.dataset.group);" not in SOURCE
    assert "const emptyMainGroup = () =>" in SOURCE
    assert 'allSelected ? "전체 해제" : "전체 선택"' in SOURCE
    assert "if (g && groupAllSelected(g)) {" in SOURCE
    assert 'p.set("date", "all")' in SOURCE
    assert 'GROUPS.filter((g) => !urlSetKeys.has(g.key)).forEach(applyDefaultGroup);' in SOURCE


def test_our_company_median_line_is_red_and_dashed() -> None:
    ours = SOURCE[SOURCE.index('x1="${sx(ours)}"'):]
    ours = ours[:ours.index("const text =")]
    assert 'stroke="${css("--crit")}"' in ours
    assert 'stroke-dasharray="6 4"' in ours


def test_the_preset_count_matches_what_clicking_it_gives() -> None:
    """단추에 «62건»이라 적어 놓고 누르니 다른 수가 나오면 둘 다 못 믿는다.

    지역 조건에는 예외가 하나 있다 — 전국 공시 행은 시도에 매이지 않는다.
    세는 쪽에도 **같은 예외**가 있어야 한다.
    """
    assert "const rowMatchesPreset = (r, p) =>" in SOURCE
    # 프리셋 count도 실제 클릭 후 matcher와 같은 nationwide 예외를 사용한다.
    assert 'if (g.key === "region" && NATIONWIDE_GEO.has(r.geo)) continue;' in SOURCE
    assert "ALL.filter((r) => rowMatchesPreset(r, p)).length" in SOURCE
    # exact-12 preset은 bucket뿐 아니라 scalar range까지 count에 반영한다.
    assert 'const tmin = presetOwnValue(p, "tmin");' in SOURCE
    assert 'const tmax = presetOwnValue(p, "tmax");' in SOURCE


def test_turning_a_preset_off_also_drops_what_hung_under_it() -> None:
    """부산을 껐는데 구·군만 남으면 아무것도 안 걸린 것처럼 보인다."""
    assert 'state.gu.clear(); state.detailOpen.delete("gu");' in SOURCE


def test_the_histogram_says_how_many_rows_a_bar_holds() -> None:
    """그림은 «어디가 두꺼운가»까지만 말한다. 몇 건인지는 눈으로 못 센다.

    분모는 **그림과 같은 모집단**이어야 한다. 다른 데서 가져오면 «전체의 3%»가
    무엇의 3%인지 알 수 없다.
    """
    assert 'data-n="${b.n}"' in SOURCE
    assert '$("hist").dataset.total = String(values.length);' in SOURCE
    assert 'id="hist-hover" aria-live="polite"' in SOURCE


def test_the_sideways_scrollbar_is_reachable_without_going_to_the_bottom() -> None:
    """표가 100건이면 스크롤 상자가 4,032px가 된다 (2026-08-10 실측).

    가로 막대는 그 맨 아래에 붙으므로, 옆 칸을 보려고 5,165px를 내려갔다가
    다시 올라와야 했다. 상자 높이를 화면에 맞춰 자르면 막대가 늘 보인다.
    세로로 굴려도 열 이름이 따라오도록 `thead th`의 sticky는 그대로 둔다.
    """
    block = SOURCE[SOURCE.index("  .scroll {"):SOURCE.index("  table { border-collapse")]
    assert "overflow: auto;" in block, "가로만 굴리면 높이를 자를 수 없다"
    assert "max-height: 78vh;" in block
    assert "position: sticky; top: 0;" in SOURCE, "열 이름이 따라오지 않는다"


def test_the_rank_line_folds_instead_of_pushing_the_page_sideways() -> None:
    """휴대폰에서 이 줄 하나가 페이지 전체를 옆으로 밀고 있었다 (2026-08-10 실측).

    `white-space: nowrap`이라 390px 화면에서 477px까지 늘어났다. 백분위를
    붙이기 전에도 410px로 이미 넘쳤다 — 조건 패널을 보려면 화면 전체를
    좌우로 흔들어야 했다.
    """
    block = SOURCE[SOURCE.index("  .rankline {"):SOURCE.index("  .rankline.off {")]
    assert "white-space: nowrap" not in block, "다시 한 줄로 못 박았다"
    assert "flex-wrap: wrap" in block


def test_the_expanded_text_does_not_stretch_to_the_table_width() -> None:
    """원문 줄은 표만큼 넓다(14열이면 1,479px).

    그대로 두면 휴대폰에서 한 줄이 1,389px로 뻗어, 조건 하나 읽으려고 옆으로
    계속 밀어야 했다. `sticky`가 없으면 표를 옆으로 민 상태에서 행을 눌렀을
    때 원문이 화면 밖(왼쪽 −887px)에 그려져 눌러도 아무 일이 없어 보인다.
    """
    block = SOURCE[SOURCE.index("  .pf {"):SOURCE.index("  .pf dt {")]
    assert "max-width: min(1000px, calc(100vw - 44px));" in block
    assert "position: sticky; left: 0;" in block


def test_the_expanded_text_splits_the_labels_the_collector_joined() -> None:
    """원천이 «우대조건: … / 가입대상: …»을 줄로 이어 붙여 준다.

    통짜 글뭉치로 두면 우대조건과 가입 자격이 한 문단으로 읽힌다.
    **라벨 목록이 파이썬 쪽과 어긋나면** 새 라벨이 앞 항목 본문에 붙는다.
    """
    import re as _re

    from rate_monitor.domain import preference_taxonomy as tax

    match = _re.search(r"const PREF_LABELS = \[(.*?)\];", SOURCE)
    assert match, "PREF_LABELS를 찾지 못했다"
    screen = set(_re.findall(r'"([^"]+)"', match.group(1)))
    # 파이썬이 라벨로 인정하는 것과 같은 집합이어야 한다.
    python = set(_re.findall(r"\w+", tax._ANY_LABEL.pattern.split("(?:")[1].split(")")[0]))
    assert screen == python, f"화면 {sorted(screen)} ≠ 파이썬 {sorted(python)}"


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
    basis = SOURCE[SOURCE.index("const screenBasis = () =>"):
                   SOURCE.index("const histogram = () =>")]
    assert "rows.length >= HIST_MIN_ROWS" in basis
    assert "{ rows: current, narrowed: false }" in basis
    # 권역 차트도 같은 규칙을 쓴다.
    region = SOURCE[SOURCE.index("const regionBasis = () =>"):
                    SOURCE.index("const groupOf =")]
    assert "narrowed.length >= HIST_MIN_ROWS" in region


def test_the_region_chart_ignores_only_the_region_condition() -> None:
    """이 그림의 가로축이 지역이다.

    지역까지 걸면 «부산만» 골랐을 때 막대가 하나만 남아 비교가 사라진다.
    나머지 조건은 그대로 따라야 한다 — 저축은행만 켜면 저축은행의 권역
    중앙값이 나와야 한다 (2026-08-09 사용자 지정).
    """
    assert "const matches = (r, skipRegion) => {" in SOURCE
    assert 'if (skipRegion && g.key === "region") continue;' in SOURCE
    assert "ALL.filter((r) => matches(r, true))" in SOURCE
    assert "<b>지역 조건만 빼고</b>" in SOURCE


def test_the_region_grouping_table_is_published_not_copied() -> None:
    """시도 → 권역 표를 화면에 따로 적으면 언젠가 한쪽만 바뀐다.

    그날 발행된 막대와 화면이 다시 낸 막대가 다른 권역에 서는데, 둘 다
    «권역별»이라 적혀 있어 어느 쪽이 틀렸는지 알 수 없다.
    """
    assert "region_groups" in INLINE_KEYS
    assert "(data.region_groups || {})[sido]" in SOURCE
    # 화면에 표를 복사해 두지 않았는지 본다.
    assert "인천·경기" not in SOURCE.split("<script")[0]


def test_our_company_number_is_decided_in_one_place() -> None:
    """세 곳이 «고려저축은행 중앙값»이라 적는데 값이 달랐다 (2026-08-07).

    카드 3.00%(전 상품군) · 분포 3.90%(12개월 정기예금) · 권역선 3.00%.
    **권역 차트가 제일 나빴다** — 막대는 12개월 기준인데 기준선만 전체
    기준이라, 서로 다른 것을 비교해 «우리가 전 권역보다 낮다»고 보였다.
    """
    assert "const screenBasis = () =>" in SOURCE
    assert "const regionBasis = () =>" in SOURCE

    # 카드·순위줄·분포는 화면 기준 하나를 공유한다.
    assert SOURCE.count("mineStats(screenBasis().rows)") == 2   # render + 카드
    assert "const stats = mineStats(source);" in SOURCE          # 분포

    # 권역 차트의 기준선은 **막대와 같은 집합**에서 낸다. 다른 데서 내면
    # «전 권역보다 높다/낮다»가 거짓이 된다.
    assert SOURCE.count("regionBars(mineStats(regionBasis()))") == 3
    assert "mineStats(current)" not in SOURCE, "옛 잣대가 남아 있다"
    assert "wholeBasis" not in SOURCE, "아무도 안 쓰는 잣대가 남아 있다"


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
    # 권역 그림은 2026-08-10에 네모로 바뀌어 SVG가 아니다 — CSS 격자가 접는다.
    for chart in ('chartWidth("hist"', 'chartWidth("terms"'):
        assert chart in SOURCE, chart
    # 폭이 바뀌면 다시 그려야 한다. 안 그리면 창을 돌렸을 때 옛 폭이 남는다.
    assert 'window.addEventListener("resize"' in SOURCE
    # 높이만 바뀔 때는 안 그린다 — 모바일 주소창이 접힐 때마다 다시 그리면
    # 13만 행이 딸려 스크롤이 끊긴다.
    assert "if (window.innerWidth === lastWidth) return;" in SOURCE


def test_the_region_tiles_reflow_on_a_narrow_screen() -> None:
    """세로 막대 아홉을 340px에 세우면 막대당 37px이라 이름도 안 들어갔다.

    배치를 손으로 갈라 두 벌 그리는 대신 격자가 스스로 접게 한다 — 한 벌만
    있으면 «넓은 쪽만 고쳤다»가 생길 수 없다.
    """
    # 열 수는 폭을 재서 정한다. `auto-fit`으로 두면 열 개를 놓을 때
    # «9개 + 1개»가 되어 마지막 한 칸만 덩그러니 남는다 (2026-08-10 지적).
    assert "const maxCols = Math.max(2, Math.floor((boxW + TILE_GAP)" in SOURCE
    assert "Math.ceil(D.length / Math.ceil(D.length / maxCols))" in SOURCE
    tiles_css = SOURCE[SOURCE.index("  .regtiles {"):SOURCE.index("  .regtile {")]
    assert "auto-fit" not in tiles_css, "열 수를 다시 브라우저에 맡겼다"
    # 어느 폭에서든 표본 크기는 적는다. 적는 자리가 한 곳뿐이어야 한다.
    reg = SOURCE[SOURCE.index("── 차트 3"):SOURCE.index("const drawCharts")]
    assert reg.count("개사 · ${num(d.n)}건") == 1


def test_the_tile_rows_come_out_even() -> None:
    """칸을 줄에 고르게 나눈다. 아래는 화면과 같은 규칙을 다시 쓴 것이다.

    열 개를 아홉 열에 놓으면 마지막 줄에 한 칸만 남아 «덜 그려진 것»처럼
    보인다. 줄 수를 먼저 정하고 그 줄로 나눈다.
    """
    import math

    def cols(n: int, max_cols: int) -> int:
        return min(n, math.ceil(n / math.ceil(n / max_cols)))

    assert cols(10, 9) == 5, "권역 열 개는 5×2로 놓인다"
    assert cols(17, 9) == 9, "부산 구·군 열일곱은 9+8"
    assert cols(8, 9) == 8, "여덟 개는 한 줄"
    # 폭에서 구한 최대 열 수를 넘지 않는다 — 넘으면 칸이 최소 폭보다 좁아진다.
    for n in range(2, 40):
        for max_cols in (2, 3, 5, 9):
            assert cols(n, max_cols) <= max_cols, (n, max_cols)


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
    assert 'state.prefTags.clear(); state.detailOpen.delete("pref");' in SOURCE


def test_the_top_conditions_lead_and_all_start_checked_without_filtering() -> None:
    """전체 체크는 보이는 상태와 일치하되 추가 제한으로 해석하지 않는다."""
    assert "const PREF_TOP = [" in SOURCE
    assert 'counts.has("OTHER") ? ["OTHER"] : []' in SOURCE
    assert "prefTags: new Set()," in SOURCE
    assert "const selectAllPreferenceTags = () =>" in SOURCE
    assert "PREF_TAG_CODES.forEach((code) => state.prefTags.add(code));" in SOURCE
    assert "state.prefTags.size < PREF_TAG_CODES.length" in SOURCE


def test_the_detail_filter_is_an_or_not_an_and() -> None:
    """조건은 여러 개가 함께 붙는다. 전부 만족을 요구하면 거의 안 남는다."""
    assert "if (r.prefTags.has(code)) hit = true;" in SOURCE


def test_nested_filters_are_collapsed_until_detail_view_is_requested() -> None:
    assert 'data-detail="gu"' in SOURCE
    assert 'data-detail="pref"' in SOURCE
    assert 'state.detailOpen.has("gu")' in SOURCE
    assert 'state.detailOpen.has("pref")' in SOURCE
    assert '${open ? "세부 접기" : "세부 보기"}' in SOURCE


def test_selecting_all_nested_options_is_not_an_extra_filter() -> None:
    """전체를 눌러 고려저축은행처럼 분류 태그가 없는 행이 사라지면 안 된다."""
    assert 'const prefNarrowed = state.prefTags.size' in SOURCE
    assert "if (prefNarrowed)" in SOURCE
    assert 'const guNarrowed = state.gu.size' in SOURCE
    assert "state.gu.size < BUSAN.length" in SOURCE
    assert 'r.region === BUSAN_SIDO' in SOURCE


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
    assert "state.hideZero && isShownAsZero(rateOf(r))" in SOURCE


def test_the_zero_filter_starts_off() -> None:
    """빈 체크는 전체를 뜻한다. 기본으로 빼면 그 약속이 깨진다."""
    assert "hideZero: false," in SOURCE
    # 켜져 있는 상태로 시작하는 표시가 없어야 한다.
    assert 'id="hide-zero" checked' not in SOURCE


def test_the_zero_filter_is_measured_against_the_chosen_basis() -> None:
    """우대금리 기준일 때 기본금리가 0인 것은 이 조건과 상관이 없다."""
    assert "state.hideZero && isShownAsZero(rateOf(r))" in SOURCE
    assert "state.hideZero && r.base === 0" not in SOURCE


def test_the_zero_filter_removes_what_the_screen_shows_as_zero() -> None:
    """정확히 0인 것만 지우면 0.001~0.004%인 204건이 남는다.

    표는 소수 둘째 자리까지 적으므로 그것도 «0.00%»로 찍힌다. 켰는데 0%가
    그대로 보이면 조건이 고장 난 것으로 읽힌다 — 실제로 그렇게 나갔다.
    실측: 걸리는 행이 10,544건에서 10,748건이 됐고, 켠 뒤 표 첫 화면의
    «0.00%» 칸이 100개에서 0개가 됐다.
    """
    assert "const isShownAsZero = (v) => v != null && Math.round(v * 100) === 0;" in SOURCE
    # 건수 라벨도 같은 규칙이어야 한다. 다르면 «10,544건이라더니 왜 더 빠지지»가 된다.
    assert "if (isShownAsZero(r.base)) zeroCount.base += 1;" in SOURCE
    assert "if (isShownAsZero(r.max)) zeroCount.max += 1;" in SOURCE


def test_the_zero_filter_travels_in_the_link() -> None:
    """안 실으면 링크를 받은 사람이 다른 건수를 보면서 같은 화면이라 믿는다."""
    assert 'p.set("nozero", "1")' in SOURCE
    assert 'p.get("nozero") === "1"' in SOURCE


def test_the_zero_filter_says_how_many_rows_it_would_remove() -> None:
    """숫자가 없으면 켜 볼 이유도 알 수 없고, 껐다 켜며 세어 보게 된다."""
    assert 'id="zero-count"' in SOURCE
    assert "const renderZeroCount = () => {" in SOURCE


def test_resetting_the_conditions_clears_the_zero_filter() -> None:
    """«조건 초기화»가 안 지우는 조건이 하나 있으면 그것부터 의심하게 된다."""
    reset = SOURCE[SOURCE.index('$("reset").addEventListener'):]
    reset = reset[:reset.index("renderGroups();")]
    assert "applyDefaultFilters();" in reset
    assert "hideZero: false" in SOURCE[SOURCE.index("const applyDefaultFilters"):]
    assert '$("hide-zero").checked = false' in reset


# ── 화면 순서 (2026-08-09) ──────────────────────────────────────────────


def test_the_conditions_come_before_the_charts_and_the_table() -> None:
    """조건 → 그림 → 표. 쓰는 순서 그대로다.

    예전에는 그림이 위, 조건이 아래였다. 그러면 처음 들어온 사람이 «전체
    기준» 그림부터 보고, 조건을 걸려고 내려갔다가, 바뀐 그림을 보려고 다시
    올라와야 한다. 스크롤을 두 번 왕복하는 배치다.
    """
    conditions = SOURCE.index('<section class="panel" id="conditions">')
    charts = SOURCE.index('<div class="charts" id="charts" hidden>')
    table = SOURCE.index('<div class="scroll">')
    assert conditions < charts < table


def test_the_zero_toggle_sits_next_to_the_charts_it_changes() -> None:
    """조건 목록 안에 섞으면 체크박스 스무 개 중 하나가 된다.

    이 조건만 자주 껐다 켜는 것이 쓰임이라, 켠 손과 바뀌는 그림이 한 화면에
    있어야 한다.
    """
    zero = SOURCE.index('<div class="zero-bar" id="zero-bar" hidden>')
    conditions_end = SOURCE.index("  </section>", SOURCE.index('id="conditions"'))
    charts = SOURCE.index('<div class="charts" id="charts" hidden>')
    assert conditions_end < zero < charts


def test_the_benchmark_cards_stay_at_the_very_top() -> None:
    """오늘 확인할 값이 첫 화면이다 (v4 §10.6). 조건보다 앞이다."""
    marks = SOURCE.index('<div class="marks" id="marks" hidden></div>')
    conditions = SOURCE.index('<section class="panel" id="conditions">')
    assert marks < conditions


def test_the_filter_callback_is_wrapped_so_the_index_is_not_a_flag() -> None:
    """`ALL.filter(matches)`는 인덱스를 두 번째 인자로 넘긴다.

    `matches(r, skipRegion)`에서 그 인덱스가 곧 «지역 조건을 건너뛰라»가
    되어, 0번 행을 뺀 모든 행이 지역 조건을 무시했다. 화면으로는 «부산을
    켰는데 건수가 그대로»로 보였다 (2026-08-09 브라우저 확인에서 발견).
    """
    assert "ALL.filter((r) => matches(r))" in SOURCE
    # 주석에는 «이렇게 쓰면 안 된다»고 적혀 있다. 그걸 위반으로 세면
    # 규칙을 설명하지 못하게 된다 (`_visible`이 있는 이유와 같다).
    assert "ALL.filter(matches)" not in _visible(SOURCE)


# ── 32만 행에서도 손이 안 밀리게 (2026-08-09) ────────────────────────────


def test_typing_does_not_refilter_on_every_keystroke() -> None:
    """타자마다 32만 행을 다시 훑으면 글자가 밀린다.

    실측: 한 글자에 467ms. 네 글자를 치면 2초 가까이 멈춘다. 손을 멈춘
    뒤에 한 번만 돌게 하니 연타 중 멈춘 시간이 1ms가 됐다.
    """
    assert "const TYPING_PAUSE_MS = 200;" in SOURCE
    assert "const redrawSoon = afterTyping(redraw);" in SOURCE
    # 체크박스는 지연을 걸지 않는다. 한 번 누르는 것이라 바로 반응해야 한다.
    handler = SOURCE[SOURCE.index('$("conditions").addEventListener("change"'):]
    assert "redrawSoon()" not in handler[:2000]


def test_the_screen_bases_are_computed_once_per_draw() -> None:
    """한 번 그릴 때 카드·순위줄·분포·캡션이 같은 잣대를 묻는다.

    물을 때마다 32만 행을 다시 훑으면 조건 하나에 몇 백 ms가 붙는다.
    """
    assert "let basisCache = {}" in SOURCE
    assert "if (basisCache.screen) return basisCache.screen;" in SOURCE
    assert "if (basisCache.region) return basisCache.region;" in SOURCE
    # 조건이 바뀌면 반드시 비운다. 안 비우면 옛 집합으로 그린다.
    render = SOURCE[SOURCE.index("  const render = () => {"):]
    assert render.index("clearBasis();") < render.index("current = ALL.filter")


def test_the_term_buckets_are_filled_in_one_pass() -> None:
    """구간마다 전체를 다시 훑으면 32만 행 × 6구간 = 200만 번을 돈다."""
    fn = SOURCE[SOURCE.index("const termRowsFromScreen = () =>"):
                SOURCE.index("const termRowsFromSummary = () =>")]
    assert "current.forEach((r) => {" in fn
    # 구간 루프 안에서 전체를 다시 훑지 않는다.
    assert "rows.forEach" not in fn
