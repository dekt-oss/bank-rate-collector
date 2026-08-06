"""공개 웹사이트 산출물 검증.

핵심은 하나다 — **금리표가 페이지 안에 들어가면 안 된다.** 전국 16만 8천
행이면 8MB짜리 HTML이 되고, 화면을 열 때마다 그걸 받는다. 나눴다는 사실을
말로 적어두는 대신 테스트가 지키게 한다.
"""

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from rate_monitor.db import models as m
from rate_monitor.db.session import create_db_engine, make_session_factory
from rate_monitor.services.dashboard_service import DATA_END, DATA_MARKER, DashboardBuildError
from rate_monitor.services.site_service import (
    TABLE_FILE,
    build_site,
    render,
    split_summary,
)
from tests.test_kfcc_collection import run_collect

TEMPLATE = Path(__file__).resolve().parents[1] / "web" / "templates" / "site.html"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """실물 fixture로 한 번 수집한 DB.

    손으로 행을 넣지 않는다. 실제 저장 경로가 만드는 모양이라야 화면이
    받는 것과 같다.
    """
    path = tmp_path / "site.sqlite3"
    engine = create_db_engine(path)
    m.Base.metadata.create_all(engine)
    run_collect(make_session_factory(engine), tmp_path / "raw")
    engine.dispose()
    return path


# fixture 한 벌이 만드는 관측 수. 여기 한 곳에만 적는다.
ROWS = 78


def _inline(html: str) -> dict:
    start = html.find(DATA_MARKER)
    end = html.find(DATA_END, start)
    return json.loads(html[start + len(DATA_MARKER) : end].replace("<\\/", "</"))


# ── 가르기 ──────────────────────────────────────────────────────────────


def test_table_never_reaches_the_page() -> None:
    page, table = split_summary({"totals": {"a": 1}, "table": {"rows": [[1], [2]]}})
    assert "table" not in page
    assert table["rows"] == [[1], [2]]
    assert page["table_url"] == TABLE_FILE
    assert page["table_rows"] == 2


def test_unknown_summary_keys_are_dropped() -> None:
    """인라인 목록에 없는 열쇠는 화면에 싣지 않는다. 모르는 것이 커질 수 있다."""
    page, _ = split_summary({"totals": {}, "raw_dump": ["x"] * 1000})
    assert "raw_dump" not in page


def test_render_refuses_a_template_without_the_marker() -> None:
    with pytest.raises(DashboardBuildError, match="주입 지점"):
        render("<html>표시할 곳이 없다</html>", {"totals": {}})


# ── 빌드 ────────────────────────────────────────────────────────────────


def test_build_writes_page_and_data_separately(db: Path, tmp_path: Path) -> None:
    out = tmp_path / "site-public"
    manifest = build_site(db, TEMPLATE, out)

    assert (out / "index.html").exists()
    assert (out / TABLE_FILE).exists()
    # fixture가 담고 있는 행 수. 바뀌면 시끄럽게 실패해야 한다.
    assert manifest.rows == ROWS

    table = json.loads((out / TABLE_FILE).read_text(encoding="utf-8"))
    assert len(table["rows"]) == ROWS
    assert "base_rate" in table["columns"]


def test_page_stays_small_while_the_table_carries_the_rows(
    db: Path, tmp_path: Path
) -> None:
    """행을 늘려도 페이지는 그대로여야 한다. 이게 분리의 정의다."""
    out = tmp_path / "site-public"
    manifest = build_site(db, TEMPLATE, out)

    html = (out / "index.html").read_text(encoding="utf-8")
    inline = _inline(html)
    assert "table" not in inline
    assert "rows" not in inline
    assert inline["table_url"] == TABLE_FILE
    assert manifest.page_bytes == (out / "index.html").stat().st_size

    # 요약이 담는 표본(최고금리 10건 등)은 페이지에 있어도 된다. 없어야 하는
    # 것은 **전체 행**이다. 표에만 있는 상품이 반드시 남아 있어야 한다.
    table_text = (out / TABLE_FILE).read_text(encoding="utf-8")
    products = set(json.loads(table_text)["lookups"]["product"])
    only_in_table = [p for p in products if p not in html]
    assert only_in_table, "상품 이름이 전부 페이지에 들어가 있다"


def test_page_does_not_grow_with_the_number_of_rows(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """분리의 정의 그 자체 — 행이 500배가 돼도 페이지는 그대로다.

    전국 16만 8천 행을 인라인하면 8MB가 된다. 그 회귀를 크기로 잡는다.
    """
    from rate_monitor.services import site_service

    real = site_service.build_summary

    def inflated(path: Path) -> dict:
        summary = real(path)
        table = summary["table"]
        table["rows"] = table["rows"] * 500
        return summary

    small = build_site(db, TEMPLATE, tmp_path / "small")
    monkeypatch.setattr(site_service, "build_summary", inflated)
    large = build_site(db, TEMPLATE, tmp_path / "large")

    assert large.rows == small.rows * 500
    assert large.data_bytes > small.data_bytes * 100
    # 페이지는 요약만 싣는다. 표가 커져도 바이트가 거의 그대로여야 한다.
    # (행 수를 적는 숫자의 자릿수만큼만 늘어난다 — 78 → 39000이면 3바이트.)
    assert abs(large.page_bytes - small.page_bytes) < 100


def test_gzip_copy_matches_the_table(db: Path, tmp_path: Path) -> None:
    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out)
    gz = out / "data" / "table.json.gz"
    assert gz.exists()
    assert gzip.decompress(gz.read_bytes()) == (out / TABLE_FILE).read_bytes()
    # 압축이 실제로 줄여야 gzip을 둘 이유가 있다.
    assert gz.stat().st_size < (out / TABLE_FILE).stat().st_size


def test_manifest_records_what_was_written(db: Path, tmp_path: Path) -> None:
    out = tmp_path / "site-public"
    manifest = build_site(db, TEMPLATE, out)
    recorded = json.loads((out / "site-manifest.json").read_text(encoding="utf-8"))
    assert recorded["rows"] == manifest.rows == ROWS
    assert recorded["page_bytes"] == manifest.page_bytes
    assert "index.html" in recorded["files"]
    assert TABLE_FILE in recorded["files"]


def test_head_office_notice_survives(db: Path, tmp_path: Path) -> None:
    """v3.1 §6.4 필수 표기. 사라지면 빌드가 실패해야 한다."""
    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "저축은행 공시금리 — 전국 본점 기준 참고값" in html


def test_build_fails_if_the_table_leaks_into_the_page(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검증이 실제로 잡는지. 안 잡으면 있으나 마나다."""
    from rate_monitor.services import site_service

    monkeypatch.setattr(
        site_service, "split_summary",
        lambda summary: ({**summary, "table_url": TABLE_FILE}, summary.get("table") or {}),
    )
    with pytest.raises(DashboardBuildError, match="인라인"):
        build_site(db, TEMPLATE, tmp_path / "leaky")


# ── 내려받기 파일 ───────────────────────────────────────────────────────


def test_export_files_get_fixed_names(db: Path, tmp_path: Path) -> None:
    """`rates_20260805.csv` → `data/rates.csv`.

    주소에 날짜가 박히면 링크를 걸어둔 사람이 다음 수집 뒤에 깨진 주소를
    보게 된다.
    """
    exports = tmp_path / "export"
    exports.mkdir()
    (exports / "rates_20260805.csv").write_text("권역,기관\n새마을금고,대청", encoding="utf-8")

    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out, export_dir=exports)

    assert (out / "data" / "rates.csv").read_text(encoding="utf-8").startswith("권역")


def test_export_json_does_not_overwrite_the_table(db: Path, tmp_path: Path) -> None:
    """한때 둘 다 `rates.json`이라 내보내기가 금리표를 덮어썼다.

    화면은 압축 배열을 기대하는데 객체 배열을 받아 빈 표를 그렸다. 이름이
    다시 겹치면 여기서 잡힌다.
    """
    exports = tmp_path / "export"
    exports.mkdir()
    (exports / "rates_20260805.json").write_text(
        json.dumps({"records": [{"기관": "대청"}]}, ensure_ascii=False), encoding="utf-8"
    )

    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out, export_dir=exports)

    table = json.loads((out / TABLE_FILE).read_text(encoding="utf-8"))
    assert "rows" in table and len(table["rows"]) == ROWS
    assert json.loads((out / "data" / "rates.json").read_text(encoding="utf-8"))["records"]


def test_huge_export_is_compressed(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """전국 내보내기 JSON이 53 MB다. 그대로 실으면 두 군데가 아프다 —
    rate-data 브랜치가 수집마다 그만큼 불고, 받는 사람도 53 MB를 기다린다.

    작은 CSV는 그대로 둔다. 엑셀이 바로 열 수 있어야 한다.
    """
    # 실제 문턱은 20 MB다. 테스트에서 그만한 파일을 쓰면 느리기만 하므로
    # 문턱을 낮춰 갈림길만 확인한다.
    from rate_monitor.services import site_service

    monkeypatch.setattr(site_service, "EXPORT_GZIP_BYTES", 2_000)

    exports = tmp_path / "export"
    exports.mkdir()
    (exports / "rates_20260806.csv").write_text("권역,기관\n새마을금고,대청", encoding="utf-8")
    # 압축이 잘 되는 내용이라야 .gz가 원본보다 작아진다.
    (exports / "rates_20260806.json").write_text(
        '{"records":[' + '{"기관":"대청"},' * 2_000 + '{"기관":"중부산"}]}',
        encoding="utf-8",
    )
    assert (exports / "rates_20260806.json").stat().st_size > 2_000

    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out, export_dir=exports)

    assert (out / "data" / "rates.csv").exists()
    assert not (out / "data" / "rates.json").exists()
    packed = out / "data" / "rates.json.gz"
    assert packed.exists()
    assert packed.stat().st_size < (exports / "rates_20260806.json").stat().st_size
    # 압축을 풀면 원본 그대로여야 한다. 줄이려다 내용을 잃으면 안 된다.
    assert gzip.decompress(packed.read_bytes()) == (
        exports / "rates_20260806.json"
    ).read_bytes()

    inline = _inline((out / "index.html").read_text(encoding="utf-8"))
    assert inline["downloads"]["json"]["url"] == "data/rates.json.gz"
    assert inline["downloads"]["json"]["compressed"] is True
    assert inline["downloads"]["csv"]["compressed"] is False


def test_previous_download_files_do_not_linger(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """압축 여부는 크기에 따라 바뀐다.

    부산(작음)을 빌드한 자리에 전국(큼)을 빌드하면 rates.json과
    rates.json.gz가 같이 남는다. 화면은 .gz를 가리키는데 옆에 오래된
    rates.json이 그대로 있어, 예전 주소를 아는 사람은 지난달 자료를 받는다.
    """
    from rate_monitor.services import site_service

    monkeypatch.setattr(site_service, "EXPORT_GZIP_BYTES", 2_000)

    exports = tmp_path / "export"
    exports.mkdir()
    small = exports / "rates_20260805.json"
    small.write_text('{"records":[]}', encoding="utf-8")

    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out, export_dir=exports)
    assert (out / "data" / "rates.json").exists()

    small.unlink()
    (exports / "rates_20260806.json").write_text(
        '{"records":[' + '{"기관":"대청"},' * 2_000 + '{"기관":"중부산"}]}',
        encoding="utf-8",
    )
    build_site(db, TEMPLATE, out, export_dir=exports)

    assert (out / "data" / "rates.json.gz").exists()
    assert not (out / "data" / "rates.json").exists(), "지난 빌드의 파일이 남았다"


def test_missing_export_dir_is_not_an_error(db: Path, tmp_path: Path) -> None:
    """내보내기를 안 돌렸다고 사이트 빌드가 죽으면 안 된다."""
    manifest = build_site(
        db, TEMPLATE, tmp_path / "site-public", export_dir=tmp_path / "없음"
    )
    assert manifest.rows == ROWS


# ── 화면이 실제로 쓰는 이름 ─────────────────────────────────────────────


def test_template_points_at_the_files_the_build_writes(db: Path, tmp_path: Path) -> None:
    """템플릿의 링크와 빌드가 쓰는 파일 이름이 어긋나면 404가 된다.

    둘이 다른 파일에 적혀 있어 눈으로는 안 맞춰진다.
    """
    out = tmp_path / "site-public"
    exports = tmp_path / "export"
    exports.mkdir()
    (exports / "rates_20260805.csv").write_text("a,b\n1,2", encoding="utf-8")
    (exports / "rates_20260805.json").write_text('{"records":[]}', encoding="utf-8")
    build_site(db, TEMPLATE, out, export_dir=exports)

    inline = _inline((out / "index.html").read_text(encoding="utf-8"))
    assert set(inline["downloads"]) == {"csv", "json"}
    for kind, entry in inline["downloads"].items():
        target = out / entry["url"]
        assert target.exists(), f"{kind} 링크가 가리키는 파일이 없다: {entry['url']}"
        assert entry["bytes"] == target.stat().st_size


def test_data_files_are_not_cached_long(db: Path, tmp_path: Path) -> None:
    """`data/` 아래는 주소가 그대로인 채 내용만 바뀐다.

    오래 캐시하면 새로고침해도 어제 금리가 나온다. 수집을 아무리 자주
    돌려도 보는 사람에게는 안 바뀐 것과 같다.
    """
    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out)
    config = json.loads((out / "vercel.json").read_text(encoding="utf-8"))
    rules = {r["source"]: r["headers"][0]["value"] for r in config["headers"]}
    assert "must-revalidate" in rules["/data/(.*)"]
    assert "max-age=0" in rules["/data/(.*)"]


def test_page_declares_utf8(db: Path, tmp_path: Path) -> None:
    """charset이 없으면 화면의 한글 낱말이 통째로 깨진다.

    2026-08-06 Chromium 실측 — `<meta charset>` 없이 정적 호스팅에 올리면
    "새마을금고"가 "ìƒˆë§ˆì„ê¸ˆê³ "로 나왔다. table.json은 fetch가 UTF-8로
    읽어 멀쩡해서, 화면 글자만 깨진 채 데이터가 잘못된 것처럼 보였다.
    """
    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out)
    head = (out / "index.html").read_text(encoding="utf-8")[:600]
    assert '<meta charset="utf-8">' in head
    assert head.lstrip().startswith("<!doctype html>")


def test_row_count_shown_on_the_page_matches_the_table(db: Path, tmp_path: Path) -> None:
    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out)
    inline = _inline((out / "index.html").read_text(encoding="utf-8"))
    table = json.loads((out / TABLE_FILE).read_text(encoding="utf-8"))
    assert inline["table_rows"] == len(table["rows"])


def test_observations_survive_the_round_trip(db: Path, tmp_path: Path) -> None:
    """DB의 금리가 그대로 표에 도착하는지. 중간에서 바뀌면 안 된다."""
    out = tmp_path / "site-public"
    build_site(db, TEMPLATE, out)
    table = json.loads((out / TABLE_FILE).read_text(encoding="utf-8"))
    base = table["columns"].index("base_rate")
    delivered = sorted(row[base] for row in table["rows"])

    conn = sqlite3.connect(db)
    try:
        stored = sorted(
            float(r[0]) for r in conn.execute(
                "SELECT base_rate FROM rate_observations WHERE validation_status != 'error'"
            )
        )
    finally:
        conn.close()
    # 저장은 `003.2000` 같은 0 패딩 문자열이고 화면은 숫자를 기대한다.
    # 그 변환이 값을 바꾸지 않았는지 본다.
    assert delivered == stored
    assert max(stored) > 0
