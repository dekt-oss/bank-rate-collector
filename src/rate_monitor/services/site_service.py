"""공개 웹사이트 산출물 생성.

`dashboard_service`가 만드는 두 화면은 데이터를 HTML 안에 통째로 박아
넣는다. 게시된 아티팩트가 외부 요청을 못 하기 때문이었다. 진짜 웹사이트에
올리면 그 제약이 없어지고, 대신 **크기가 문제가 된다.**

    부산 15,357건   →  723 KB
    전국 168,750건  →  약 8 MB      ← 열 때마다 8MB를 받는다

그래서 여기서는 화면과 데이터를 나눈다.

    index.html      가볍다. 요약과 조회 UI만 들어 있다
    strategy.html   같은 데이터를 읽는 전략 대시보드·시뮬레이션 실험 화면
    data/table.json 금리표. 화면이 열린 뒤 따로 받는다 (압축 배열 형태)
    data/rates.csv  사람이 받아가는 파일. 버튼이 이 파일을 그냥 가리킨다
    data/rates.json 같은 내용의 JSON

화면이 쓰는 `table.json`과 사람이 받는 `rates.json`은 **다른 파일이다.**
앞은 조회표 색인이 든 압축 배열이고 뒤는 한 행이 한 객체인 형태다. 한때 둘
다 `rates.json`이었는데, 내보내기 복사가 금리표를 덮어써서 화면이 빈 표를
받았다.

내려받기 버튼도 달라진다. 예전에는 브라우저가 15,357행을 CSV로 조립했다.
이제는 서버에 이미 있는 파일을 가리키기만 하면 된다 — 16만 행을 브라우저가
만들 이유가 없다.
"""

import gzip
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rate_monitor.domain.timeutil import now_kst
from rate_monitor.services.dashboard_service import (
    DATA_END,
    DATA_MARKER,
    HEAD_OFFICE_NOTICE,
    DashboardBuildError,
    build_summary,
)
from rate_monitor.services.strategy_service import build_strategy_summary

DEFAULT_TEMPLATE = Path("web/templates/site.html")
DEFAULT_STRATEGY_TEMPLATE = Path("web/templates/strategy.html")
DEFAULT_OUT = Path("site-public")
STRATEGY_FILE = "strategy.html"

# 화면이 받아 가는 금리표. 내보내기 파일과 이름이 겹치면 안 된다.
TABLE_FILE = "data/table.json"

# 기존 검색·조회 템플릿은 안정화된 거대한 단일 HTML이다. 실험 화면 하나를
# 붙이려고 그 DOM을 다시 구성하지 않는다. 빌드 산출물의 기존 액션 영역에
# 링크 하나만 삽입하고, 전략 화면을 제거하면 이 삽입도 함께 사라진다.
HEAD_ACTION_MARKER = '<div class="head-right">'
STRATEGY_NAV = (
    '<a class="icon-btn" href="strategy.html" style="text-decoration:none" '
    'aria-label="전략 대시보드 열기">전략 대시보드</a>'
)

# 이 크기를 넘는 내려받기 파일은 압축해서 싣는다.
#
# 2026-08-06 전국 실측: 내보내기 JSON이 53 MB다. 한 행이 한 객체이고 열
# 이름이 한글이라 132,502번 되풀이된다. 압축하면 985 KB — 54분의 1이다.
#
# 큰 파일을 그대로 두면 두 군데가 아프다. rate-data 브랜치가 수집마다
# 그만큼 불어나고, 받는 사람도 53 MB를 기다린다. 그 크기의 JSON은 편집기로
# 열리지도 않아서 어차피 프로그램으로 읽는다 — 압축을 풀 수 있는 쪽이다.
#
# CSV는 이 선(17 MB) 아래라 그대로 둔다. 엑셀이 바로 열 수 있어야 한다.
EXPORT_GZIP_BYTES = 20 * 1024 * 1024

# 화면에 인라인하는 것과 파일로 빼는 것을 가른다.
#
# 요약(집계·수집원·검수)은 몇 KB라 인라인이 낫다 — 첫 화면이 바로 그려진다.
# 금리표는 원천이 늘수록 커지므로 반드시 파일로 뺀다.
INLINE_KEYS = (
    "generated_at", "notice", "latest_run", "runs", "totals",
    "by_term", "by_district", "district_top", "workplace_only",
    "top_rates", "reviews", "review_samples", "sources", "rate_scopes",
    # 참고카드 (v4 §10.6). 표를 받기 전에 그려야 하므로 인라인에 넣는다.
    "benchmarks",
    # 마지막 수집이 실패한 원천. 화면이 그 사실을 알려야 한다.
    "stale_sources",
    # source별 마지막 시도/정상 수집/freshness. 관리자 상태 패널이 쓴다.
    "collection_health",
    # «지금 수집하기» 링크. 없으면 화면이 버튼을 통째로 숨긴다.
    "collect_workflow_url",
    # 권역 9개 단위 중앙값. 표를 받기 전에 그릴 때 쓴다 — 구 단위
    # (`by_district`)를 다시 중앙값 내면 틀리기 때문이다.
    "by_region",
    # 시도 → 권역 묶음. 화면이 조회 조건에 맞춰 권역 중앙값을 다시 낼 때
    # 쓴다. 이 표를 화면에 따로 적으면 언젠가 한쪽만 바뀐다.
    "region_groups",
    "region_other",
)


@dataclass(frozen=True)
class SiteManifest:
    """무엇을 얼마만 한 크기로 썼는지. 배포 전에 눈으로 확인할 값이다."""

    generated_at: str
    page_bytes: int
    data_bytes: int
    rows: int
    files: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "generated_at": self.generated_at,
                "page_bytes": self.page_bytes,
                "data_bytes": self.data_bytes,
                "rows": self.rows,
                "files": list(self.files),
            },
            ensure_ascii=False,
            indent=2,
        )


def split_summary(summary: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """요약을 화면용(가벼움)과 데이터용(무거움)으로 가른다.

    >>> page, data = split_summary({"totals": {"a": 1}, "table": {"rows": [[1]]}})
    >>> sorted(page)
    ['table_rows', 'table_url', 'totals']
    >>> page["table_url"]
    'data/table.json'
    >>> page["table_rows"]
    1
    >>> data["rows"]
    [[1]]
    """
    page = {k: v for k, v in summary.items() if k in INLINE_KEYS}
    table = summary.get("table") or {}
    page["table_url"] = TABLE_FILE
    # 행 수는 요약 숫자로도 쓰인다. 표를 받기 전에 화면이 그려야 하므로
    # 여기서 미리 세어 넣는다.
    page["table_rows"] = len(table.get("rows") or [])
    return page, table


def render(template_text: str, page_data: dict[str, Any]) -> str:
    """템플릿의 단일 주입 지점에 화면용 데이터만 인라인한다."""
    start = template_text.find(DATA_MARKER)
    if start == -1:
        raise DashboardBuildError(f"주입 지점을 찾지 못했다: {DATA_MARKER}")
    end = template_text.find(DATA_END, start)
    if end == -1:
        raise DashboardBuildError("주입 지점이 닫히지 않았다")

    payload = json.dumps(page_data, ensure_ascii=False, separators=(",", ":"))
    # </script>가 JSON 안에 들어가면 블록이 조기 종료된다.
    payload = payload.replace("</", "<\\/")
    return (
        template_text[: start + len(DATA_MARKER)]
        + "\n" + payload + "\n"
        + template_text[end:]
    )


def _add_strategy_nav(html: str) -> str:
    """현행 검색 화면의 헤더 액션에 실험 화면 링크 하나만 붙인다."""
    if HEAD_ACTION_MARKER not in html:
        raise DashboardBuildError("검색 화면 헤더 액션 영역을 찾지 못했다")
    return html.replace(
        HEAD_ACTION_MARKER,
        HEAD_ACTION_MARKER + "\n      " + STRATEGY_NAV,
        1,
    )


def build_site(
    db_path: Path,
    template_path: Path = DEFAULT_TEMPLATE,
    out_dir: Path = DEFAULT_OUT,
    *,
    export_dir: Path | None = None,
    strategy_template_path: Path | None = DEFAULT_STRATEGY_TEMPLATE,
) -> SiteManifest:
    """SQLite → 배포 가능한 정적 사이트 한 벌.

    `export_dir`을 주면 그 안의 CSV·JSON을 `data/`로 복사한다. 내려받기
    버튼이 브라우저에서 조립하지 않고 이 파일을 그냥 가리킨다.

    `strategy_template_path`가 있으면 현행 조회 화면과 같은 `table.json`을 읽는
    전략 실험 화면도 `strategy.html`로 만든다. 두 화면의 데이터 원본을
    갈라놓지 않는 것이 핵심이다.
    """
    summary = build_summary(db_path)
    page_data, table = split_summary(summary)

    out_dir.mkdir(parents=True, exist_ok=True)
    # 이전 실행이 남긴 내려받기 파일을 지운다. 압축 여부가 크기에 따라
    # 바뀌므로, 안 지우면 부산 때의 rates.json과 전국 때의 rates.json.gz가
    # 같이 남아 어느 쪽이 최신인지 알 수 없게 된다.
    for stale in out_dir.glob("data/rates.*"):
        stale.unlink()
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 금리표. 화면이 열린 뒤 받는다.
    table_path = out_dir / TABLE_FILE
    table_path.write_text(
        json.dumps(table, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    # gzip도 함께 둔다. 정적 호스팅이 알아서 골라 주는 경우가 많고,
    # 안 골라줘도 화면이 직접 받을 수 있다.
    gz_path = table_path.with_suffix(".json.gz")
    with table_path.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)

    files = [str(table_path.relative_to(out_dir)), str(gz_path.relative_to(out_dir))]

    # 사람이 받아가는 파일. 이름을 고정해 화면이 가리킬 수 있게 한다.
    downloads: dict[str, dict[str, Any]] = {}
    if export_dir is not None and export_dir.exists():
        for source in sorted(export_dir.iterdir()):
            if source.suffix not in (".csv", ".json"):
                continue
            # rates_20260805.csv → rates.csv. 주소가 날짜마다 바뀌면 링크를
            # 걸어둔 사람이 매번 깨진 주소를 보게 된다.
            target = data_dir / f"rates{source.suffix}"
            if target == table_path:
                raise DashboardBuildError(
                    f"내보내기 파일이 금리표를 덮어쓴다: {target}"
                )
            size = source.stat().st_size
            if size > EXPORT_GZIP_BYTES:
                target = target.with_name(target.name + ".gz")
                with source.open("rb") as src, gzip.open(target, "wb", compresslevel=9) as dst:
                    shutil.copyfileobj(src, dst)
            else:
                shutil.copyfile(source, target)
            relative = str(target.relative_to(out_dir))
            files.append(relative)
            # 화면이 가리킬 주소와 크기. 눌러 보기 전에 얼마짜리인지 알아야
            # 한다 — 53 MB를 모르고 누르면 받는 줄도 모르고 기다린다.
            downloads[source.suffix.lstrip(".")] = {
                "url": relative,
                "bytes": target.stat().st_size,
                "compressed": target.suffix == ".gz",
            }
    page_data["downloads"] = downloads

    html = render(template_path.read_text(encoding="utf-8"), page_data)
    if strategy_template_path is not None:
        html = _add_strategy_nav(html)
    _verify(html, page_data)
    page_path = out_dir / "index.html"
    page_path.write_text(html, encoding="utf-8")
    files.insert(0, "index.html")

    if strategy_template_path is not None:
        strategy_page_data = {
            **page_data,
            "strategy": build_strategy_summary(db_path),
        }
        strategy_html = render(
            strategy_template_path.read_text(encoding="utf-8"), strategy_page_data
        )
        _verify_strategy(strategy_html, strategy_page_data)
        (out_dir / STRATEGY_FILE).write_text(strategy_html, encoding="utf-8")
        files.insert(1, STRATEGY_FILE)

    # 검색엔진에게 이 사이트를 통째로 긁지 말라고 한다.
    #
    # HTML의 `<meta name="robots">`는 크롤러가 파일을 **받은 뒤에** 읽는다.
    # 그래서 index.html이 아닌 파일 — /data/rates.csv 17 MB 같은 것 — 은
    # 색인되기 전에 이미 내려간다. robots.txt는 받기 전에 읽히므로 그걸
    # 막는다. 두 개가 겹치는 게 아니라 서로 다른 시점을 맡는다.
    (out_dir / "robots.txt").write_text(
        "User-agent: *\nDisallow: /\n", encoding="utf-8"
    )
    files.append("robots.txt")

    manifest = SiteManifest(
        generated_at=now_kst().isoformat(),
        # `page_bytes`는 기존 계약대로 index.html만 센다. 전략 화면이 생겼다고
        # 기존 크기 게이트의 의미를 바꾸지 않는다.
        page_bytes=page_path.stat().st_size,
        data_bytes=table_path.stat().st_size,
        rows=len(table.get("rows") or []),
        files=tuple(files),
    )
    (out_dir / "site-manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def _inline_payload(html: str) -> dict[str, Any]:
    start = html.find(DATA_MARKER)
    if start == -1:
        raise DashboardBuildError(f"주입 지점을 찾지 못했다: {DATA_MARKER}")
    end = html.find(DATA_END, start)
    if end == -1:
        raise DashboardBuildError("주입 지점이 닫히지 않았다")
    raw = html[start + len(DATA_MARKER) : end].replace("<\\/", "</")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DashboardBuildError(f"인라인 JSON 파싱 실패: {exc}") from exc
    if not isinstance(parsed, dict):
        raise DashboardBuildError("인라인 JSON이 객체가 아니다")
    return parsed


def _verify(html: str, page_data: dict[str, Any]) -> None:
    """기존 조회 화면 빌드 후 자체 검증 (v3.1 §6.3)."""
    parsed = _inline_payload(html)
    if parsed.get("totals") != page_data.get("totals"):
        raise DashboardBuildError("화면 집계값이 summary와 다르다")
    if HEAD_OFFICE_NOTICE not in html:
        raise DashboardBuildError("본점 기준 참고값 표기가 없다 (v3.1 §6.4)")
    # 금리표가 페이지에 섞여 들어가면 분리한 의미가 없다.
    raw = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    if '"rows":[[' in raw:
        raise DashboardBuildError("금리표가 페이지에 인라인됐다. 분리가 깨졌다")


def _verify_strategy(html: str, page_data: dict[str, Any]) -> None:
    """전략 화면이 기존 데이터 계약을 우회하지 않는지 검증한다."""
    parsed = _inline_payload(html)
    if parsed.get("table_url") != TABLE_FILE:
        raise DashboardBuildError("전략 화면이 canonical table.json을 가리키지 않는다")
    if parsed.get("totals") != page_data.get("totals"):
        raise DashboardBuildError("전략 화면 집계값이 summary와 다르다")
    if "strategy" not in parsed:
        raise DashboardBuildError("전략 화면용 시장 변화 집계가 없다")
    if HEAD_OFFICE_NOTICE not in html:
        raise DashboardBuildError("전략 화면에 저축은행 지역근거 주의문이 없다")
    raw = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    if '"rows":[[' in raw:
        raise DashboardBuildError("전략 화면에 금리표가 인라인됐다")
