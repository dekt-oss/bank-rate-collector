"""정적 대시보드 생성 (명세서 v3.1 §6).

SQLite를 집계해 summary.json을 만들고, 템플릿의 단일 주입 지점에 인라인해
site/index.html을 생성한다. 게시된 페이지는 외부 fetch가 차단될 수 있으므로
런타임에 JSON을 불러오지 않는다.

빌드 후 자체 검증에 실패하면 산출물을 쓰지 않는다.
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from rate_monitor.domain.timeutil import kst_iso, now_kst
from rate_monitor.services.institution_matching import normalize_institution

PRESENTATION_PATH = Path("config/presentation.yaml")


def reference_sectors(path: Path | None = None) -> tuple[str, ...]:
    """메인 비교표에서 빼는 업권 (v4 §6.4, §9.1).

    시중은행은 참고카드에만 나온다. 전국 공시라 부산 구·군에 연결할 수 없고,
    2금융권 넷과 같은 표에 섞이면 무엇을 비교하는 화면인지가 흐려진다.

    `db_only_sources`는 여기가 아니라 `dedupe_sources`가 맡는다. 그쪽은
    통째로 빼는 것이 아니라 **겹치는 상품만** 뺀다 (v4 §9.1).

    설정 파일이 없으면 아무것도 빼지 않는다. 화면이 조용히 비는 것보다
    참고지표가 섞여 보이는 편이 알아채기 쉽다.
    """
    return tuple(_presentation(path).get("reference_sectors") or ())


def _presentation(path: Path | None = None) -> dict[str, Any]:
    config_path = path or PRESENTATION_PATH
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def dedupe_sources(path: Path | None = None) -> tuple[str, ...]:
    """중복이면 화면에서 물러나는 원천 (v4 §9.1).

    저축은행을 finlife와 저축은행중앙회 양쪽에서 받는다. 같은 상품이 두
    줄로 보이면 안 되므로 한쪽이 물러나야 하고, 명세서는 FSB를 1차로 둔다
    (§11.1 "메인 표시값은 FSB를 우선한다").

    **통째로 빼는 것이 아니다.** §9.1이 말하는 것은 "동일 상품을 메인에
    중복 노출하지 않는다"이고, 실측하면 그 차이가 크다.

        FSB 조합      362개 — 전부 finlife에도 있다
        finlife 조합  756개 — 394개는 FSB에 없다

    통째로 빼면 그 394개(관측 2,688건)가 화면에서 사라진다. 그래서 겹치는
    것만 뺀다.
    """
    return tuple(_presentation(path).get("db_only_sources") or ())

DEFAULT_TEMPLATE = Path("web/templates/dashboard.html")
DEFAULT_SITE = Path("site/index.html")
DEFAULT_SUMMARY = Path("publish/summary.json")

# 공개용 전체 조회 화면. 운영 보드와 같은 summary를 쓰고 표현만 다르다.
# 두 화면이 서로 다른 집계를 하면 어느 쪽이 맞는지 알 수 없게 된다.
DEFAULT_PUBLIC_TEMPLATE = Path("web/templates/public.html")
DEFAULT_PUBLIC_SITE = Path("site/public.html")

DATA_MARKER = '<script id="rate-monitor-data" type="application/json">'
DATA_END = "</script>"

# 저축은행 finlife 데이터의 성격. 화면에 반드시 표기한다 (v3.1 §6.4).
HEAD_OFFICE_NOTICE = "저축은행 공시금리 — 전국 본점 기준 참고값"


class DashboardBuildError(RuntimeError):
    """대시보드 생성 검증 실패."""


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


# 화면이 쓸 금리표의 열 순서. 내려받기 CSV 머리글도 이걸 따른다.
TABLE_COLUMNS = (
    "sector",
    "institution",
    "region",
    "district",
    "product",
    "product_type",
    "term_months",
    "payment_method",
    "interest_method",
    "join_channel",
    "base_rate",
    "max_rate",
    "availability_scope",
    "source_id",
    "source_effective_at",
    # v4 §10.4. `amount_min`은 일부러 뺐다 — 135,384행 중 채워진 값이
    # 0건이다. 빈 칸을 화면에 만들면 "정보 없음"이 아니라 "0원부터"로 읽힌다.
    "outlet",
    "geo_basis",
    "rate_scope",
    "amount_max",
    "preference",
)


# 지역은 이제 칸에서 읽는다 (v4 §4.2, 마이그레이션 8c1a4f2b9d07).
#
# 예전에는 여기 SQL이 주소 문자열을 INSTR/SUBSTR로 잘랐고, 수집 쪽에서는
# `kfcc/parser.split_region`이 같은 일을 파이썬으로 했다. 규칙이 두 벌이라
# 한쪽만 고치면 수집한 값과 보이는 값이 갈라진다. 이제 둘 다
# `services/region_service.split_address`를 쓰고, 그 결과가
# `institutions.region_sido` / `outlets.region_sigungu` 같은 칸에 들어 있다.
#
# 시도를 함께 보는 이유는 그대로다: 구 이름은 전국에서 겹친다. 중구만 해도
# 서울·부산·대구·인천·대전·울산에 있다. 시도 축이 없으면 여섯 도시의 중구가
# 한 줄로 합쳐지고 최고금리가 뒤섞인다.

# 구·군 **집계**는 점포를 먼저 본다. 한 금고가 두 구에 점포를 두면 두 구
# 모두에 그 금고의 금리가 잡혀야 한다 (부산 실측 3건).
SIDO_EXPR = "COALESCE(ot.region_sido, i.region_sido)"
DISTRICT_EXPR = "COALESCE(ot.region_sigungu, i.region_sigungu)"

# 금리표는 다르다. **기관 주소만** 본다.
#
# 예전에는 여기서도 점포를 조인했는데, 그러면 관측 하나가 점포 수만큼
# 복제된다. 실측에서 관측 15,357건이 표에서 32,592행이 됐다 — 저축은행
# 하나가 지점 8곳을 두면 같은 금리가 8줄로 나오고, 그 금리는 지점에
# 적용되지도 않는 본점 기준 값이다. 내려받기 CSV도 그만큼 부풀었다.
#
# 집계(위)와 목록(아래)의 규칙이 다른 것은 의도한 것이다. 집계는 "이 구에서
# 볼 수 있는 금리"를 묻고, 목록은 "이 공시 한 건"을 한 줄로 보여준다.
# 둘은 반드시 같은 주소에서 나와야 한다. 예전에는 구만 인자로 받을 수 있게
# 열어뒀는데, 시도는 하드코딩이라 호출자가 점포 기준 식을 넘기면 "부산 강남구"
# 같은 행이 조용히 생긴다. 인자를 없애고 여기서만 정한다.
TABLE_SIDO_EXPR = "i.region_sido"
TABLE_DISTRICT_EXPR = "i.region_sigungu"

# 지역근거는 점포 것이 우선이다 (v4 §4.1).
#
# 시도·구는 위처럼 기관 칸을 쓰는데, **근거만은 점포를 먼저 본다.** 농·축협은
# 같은 조합의 지점들이 서로 다른 주소를 갖는다(대저농협 3지점 실측). 그 행의
# 지역이 어디서 왔는지를 기관 근거로 덮으면 "점포 기준"이 "기관 기준"으로
# 보이고, 화면 배지가 거짓말을 한다.
TABLE_GEO_BASIS_EXPR = "COALESCE(ot.geo_basis, i.geo_basis)"

RUN_TIME_KEYS = ("started_at", "finished_at")


def _to_kst_times(records: list[dict[str, Any]]) -> None:
    """실행 시각 칸을 한국시간 ISO로 바꾼다. 제자리에서 고친다.

    >>> rows = [{"id": "r", "started_at": "2026-08-06 05:20:52", "finished_at": None}]
    >>> _to_kst_times(rows); rows[0]["started_at"]
    '2026-08-06T14:20:52+09:00'
    """
    for record in records:
        for key in RUN_TIME_KEYS:
            if key in record:
                record[key] = kst_iso(record[key])


# 관측은 값이 바뀔 때만 새 행이 된다 (선행 수정안 §3.2). 그래서 "이번 실행이
# 확인한 금리"를 물으려면 `run_id`(처음 본 실행)가 아니라 `last_run_id`
# (마지막으로 확인한 실행)로 걸어야 한다. run_id로 걸면 안 바뀐 금리가 화면에서
# 통째로 사라진다 — 실측으로 132,502행 중 대부분이 그렇다.


def latest_run_ids(conn: sqlite3.Connection) -> list[str]:
    """수집원마다 마지막 실행의 id.

    전체에서 가장 최근 실행 하나만 보면, 저축은행 다음에 새마을금고를
    돌렸을 때 저축은행 수치가 통째로 사라진다.
    """
    return [
        r["id"]
        for r in _rows(
            conn,
            "SELECT r.id, r.source_id FROM collection_runs r"
            "  JOIN (SELECT source_id, MAX(started_at) AS started_at"
            "          FROM collection_runs GROUP BY source_id) latest"
            "    ON latest.source_id = r.source_id"
            "   AND latest.started_at = r.started_at",
        )
    ]


def _comparison_key(record: dict[str, Any]) -> tuple[str, Any, Any]:
    """"같은 상품"의 기준 (v4 §11.1의 매핑 축).

    기관명·상품유형·가입기간 셋이다. **상품명은 넣지 않는다.** 두 원천이
    같은 상품을 다른 이름으로 부르고("정기예금" vs "정기예금(인터넷)"),
    이름까지 맞추라고 하면 아무것도 안 붙는다.
    """
    return (
        normalize_institution(record.get("institution")),
        record.get("product_type"),
        record.get("term_months"),
    )


def _drop_duplicate_source_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """두 원천이 같은 상품을 주면 한쪽만 남긴다 (v4 §9.1).

    `config/presentation.yaml`의 `db_only_sources`에 적힌 원천이 물러난다.
    지금은 `finlife_savings_bank`이고, 남는 쪽은 저축은행중앙회다 —
    가입방법·우대조건·만기후이율이 더 오기 때문이다 (§11.1).

    **겹치는 것만 뺀다.** 실측(2026-08-06 발행 DB):

        FSB 조합      362개 — 전부 finlife에도 있다
        finlife 조합  756개 — 394개는 FSB에 없다

    통째로 빼면 그 394개가 화면에서 사라진다. 그래서 "다른 원천이 같은
    상품을 이미 보여주는가"를 행마다 묻는다.
    """
    retreating = set(dedupe_sources())
    if not retreating:
        return records

    # 물러나지 않는 원천이 이미 보여주는 상품.
    covered = {
        _comparison_key(r) for r in records if r.get("source_id") not in retreating
    }
    if not covered:
        return records
    return [
        r
        for r in records
        if r.get("source_id") not in retreating or _comparison_key(r) not in covered
    ]


def build_rate_table(
    conn: sqlite3.Connection, run_ids: list[str]
) -> dict[str, Any]:
    """비교 화면이 쓸 전체 금리표.

    관측이 1만 8천 건이라 객체 배열로 만들면 화면에 싣기 무겁다. 값을 배열로
    쓰고 되풀이되는 문자열(기관명·상품명·구)은 조회표로 빼서 크기를 줄인다.

    반환 형태:
        {"columns": [...], "lookups": {"institution": [...], ...},
         "rows": [[0, 3, 12, ...], ...]}

    `rows`의 각 항목은 `columns` 순서를 따르고, 조회표가 있는 열은 그 표의
    색인이 들어간다.
    """
    if not run_ids:
        return {"columns": list(TABLE_COLUMNS), "lookups": {}, "rows": []}

    placeholders = ",".join("?" for _ in run_ids)
    excluded = reference_sectors()
    sector_filter = (
        f"   AND i.sector NOT IN ({','.join('?' for _ in excluded)})" if excluded else ""
    )
    raw = _rows(
        conn,
        "SELECT i.sector                AS sector,"
        "       i.canonical_name        AS institution,"
        f"      {TABLE_SIDO_EXPR} AS region,"
        f"      {TABLE_DISTRICT_EXPR}   AS district,"
        "       p.name                  AS product,"
        "       p.product_type          AS product_type,"
        "       v.term_months           AS term_months,"
        "       v.payment_method        AS payment_method,"
        "       v.interest_method       AS interest_method,"
        "       v.join_channel          AS join_channel,"
        "       o.base_rate             AS base_rate,"
        "       o.max_rate              AS max_rate,"
        "       i.availability_scope    AS availability_scope,"
        "       r.source_id             AS source_id,"
        "       o.source_effective_at   AS source_effective_at,"
        # ── v4 §10.4가 표 행에 요구하는 칸들 ────────────────────────────
        "       ot.name                 AS outlet,"
        # 지역근거. 점포 것이 있으면 그쪽이 맞다 — 농·축협은 같은 조합의
        # 지점들이 서로 다른 주소를 갖는다. 기관 것으로 덮으면 점포 기준이
        # 기관 기준으로 보인다 (v4 §4.1).
        f"      {TABLE_GEO_BASIS_EXPR}  AS geo_basis,"
        "       v.rate_scope            AS rate_scope,"
        "       v.amount_max            AS amount_max,"
        # 우대조건 원문. 조회표로 나가므로 크기가 안 는다 — 실측 38,305행에
        # 서로 다른 문장이 387가지뿐이라 7.5 MB가 0.08 MB가 된다.
        "       o.raw_preference_text   AS preference"
        "  FROM rate_observations o"
        "  JOIN collection_runs r  ON r.id = o.run_id"
        "  JOIN product_variants v ON v.id = o.variant_id"
        "  JOIN products p         ON p.id = v.product_id"
        "  JOIN institutions i     ON i.id = p.institution_id"
        # 점포는 `product_variants.outlet_id`로만 잇는다. 기관으로 이으면
        # 관측 하나가 그 기관의 점포 수만큼 복제된다.
        "  LEFT JOIN outlets ot    ON ot.id = v.outlet_id"
        f" WHERE o.last_run_id IN ({placeholders})"
        "   AND o.validation_status != 'error'"
        # 참고지표는 메인 비교표에 넣지 않는다 (v4 §6.4).
        + sector_filter
        + " ORDER BY o.base_rate DESC",
        (*run_ids, *excluded),
    )

    raw = _drop_duplicate_source_rows(raw)

    # 같은 값이 수천 번 되풀이되는 열만 조회표로 뺀다.
    raw = _drop_duplicate_source_rows(raw)

    # 같은 값이 수천 번 되풀이되는 열만 조회표로 뺀다.
    #
    # `preference`가 여기 있는 것이 이번 확장의 핵심이다. 우대조건 원문을
    # 행마다 그대로 실으면 7.5 MB인데, 서로 다른 문장이 387가지뿐이라
    # 조회표로 빼면 0.08 MB다 (2026-08-06 발행 DB 실측, 90배).
    indexed = ("sector", "institution", "outlet", "region", "district",
               "product", "product_type", "payment_method", "interest_method",
               "join_channel", "availability_scope", "source_id",
               "source_effective_at", "geo_basis", "rate_scope", "preference")
    lookups: dict[str, list[Any]] = {name: [] for name in indexed}
    positions: dict[str, dict[Any, int]] = {name: {} for name in indexed}

    rows: list[list[Any]] = []
    for record in raw:
        row: list[Any] = []
        for column in TABLE_COLUMNS:
            value = record[column]
            if column not in indexed:
                # 금리는 0 패딩 문자열로 저장돼 있다. 화면에서 숫자로 쓰도록
                # 여기서 풀어 준다. 없으면 None을 유지한다 (0으로 만들지 않는다).
                if column in ("base_rate", "max_rate"):
                    row.append(float(value) if value is not None else None)
                else:
                    row.append(value)
                continue
            table = positions[column]
            if value not in table:
                table[value] = len(lookups[column])
                lookups[column].append(value)
            row.append(table[value])
        rows.append(row)

    return {"columns": list(TABLE_COLUMNS), "lookups": lookups, "rows": rows}


# 참고카드가 쓰는 상품. 12개월 정기예금 하나다 (v4 §6.4).
BENCHMARK_TERM_MONTHS = 12
BENCHMARK_PRODUCT_TYPE = "term_deposit"


def _percentile(values: list[float], q: float) -> float | None:
    """정렬된 값에서 백분위. 보간하지 않고 가장 가까운 실측값을 고른다.

    보간하면 화면에 **아무 은행도 주지 않는 금리**가 뜬다. 참고카드는
    "이런 값이 실제로 있다"를 말해야 하므로 있는 값 중에서 고른다.

    >>> _percentile([1.0, 2.0, 3.0, 4.0], 0.5)
    3.0
    >>> _percentile([], 0.5) is None
    True
    """
    if not values:
        return None
    index = min(int(q * len(values)), len(values) - 1)
    return values[index]


def build_benchmarks(
    conn: sqlite3.Connection, run_ids: list[str]
) -> dict[str, Any]:
    """상단 참고카드 (v4 §6.4, §10.6).

    시중은행은 메인 비교표에서 빠지지만 DB에는 있다. 그 값을 12개월
    정기예금 한 상품으로 좁혀 분포로 보여준다.

    §6.4가 여섯 값을 요구한다 — `record_count`·`institution_count`·`p10`·
    `median`·`p90`·`max`. 화면에는 셋만 띄우지만 전부 계산해 둔다. 이상치가
    카드를 왜곡했는지 나중에 확인할 수 있어야 한다.

    **기준금리와의 차이를 계산하지 않는다** (v4 §7.4). 예금금리에서
    기준금리를 뺀 값을 "수익"이나 "마진"이라 부르는 순간 그건 참고지표가
    아니라 투자 권유가 된다.
    """
    empty: dict[str, Any] = {
        # 한국은행 기준금리. v4 PR 6에서 채운다. `None`이면 화면이 카드를
        # 통째로 숨긴다 — 빈 카드를 띄우면 "0%"로 읽힌다.
        "bok_base_rate": None,
        "commercial_bank_12m": None,
    }
    if not run_ids:
        return empty

    placeholders = ",".join("?" for _ in run_ids)
    rows = _rows(
        conn,
        "SELECT o.base_rate AS base_rate, o.max_rate AS max_rate,"
        "       i.id AS institution_id, o.source_effective_at AS source_effective_at"
        "  FROM rate_observations o"
        "  JOIN collection_runs r  ON r.id = o.run_id"
        "  JOIN product_variants v ON v.id = o.variant_id"
        "  JOIN products p         ON p.id = v.product_id"
        "  JOIN institutions i     ON i.id = p.institution_id"
        f" WHERE o.last_run_id IN ({placeholders})"
        "   AND o.validation_status != 'error'"
        "   AND i.sector = 'bank'"
        "   AND v.term_months = ?"
        "   AND p.product_type = ?",
        (*run_ids, BENCHMARK_TERM_MONTHS, BENCHMARK_PRODUCT_TYPE),
    )
    if not rows:
        return empty

    base = sorted(float(r["base_rate"]) for r in rows if r["base_rate"] is not None)
    tops = [float(r["max_rate"]) for r in rows if r["max_rate"] is not None]
    dates = [r["source_effective_at"] for r in rows if r["source_effective_at"]]

    empty["commercial_bank_12m"] = {
        "record_count": len(rows),
        "institution_count": len({r["institution_id"] for r in rows}),
        "p10": _percentile(base, 0.10),
        "median": _percentile(base, 0.50),
        "p90": _percentile(base, 0.90),
        # 최고금리는 우대 포함값이라 기본금리와 섞지 않는다.
        "max": max(tops) if tops else None,
        "max_is_from_max_rate": bool(tops),
        "source_effective_at": max(dates) if dates else None,
    }
    return empty


def build_summary(db_path: Path) -> dict[str, Any]:
    """대시보드가 쓸 집계값. 전부 SQL에서 나온 실측이다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = None
    try:
        latest_run = _rows(
            conn,
            "SELECT id, source_id, status, started_at, finished_at, raw_count, parsed_count,"
            "       valid_count, warning_count, error_count, message"
            "  FROM collection_runs ORDER BY started_at DESC LIMIT 1",
        )
        runs = _rows(
            conn,
            "SELECT id, source_id, status, started_at, finished_at, parsed_count,"
            "       valid_count, error_count"
            "  FROM collection_runs ORDER BY started_at DESC LIMIT 10",
        )
        # DB의 실행 시각은 naive UTC다. 화면에 그대로 내보내면 07:00에 도는
        # 정기 수집이 22:00으로 보인다 — 읽는 사람은 전부 한국에 있다.
        # 저장은 그대로 두고 나가는 자리에서만 바꾼다 (domain/timeutil.py).
        _to_kst_times(latest_run)
        _to_kst_times(runs)

        totals = _rows(
            conn,
            "SELECT (SELECT COUNT(*) FROM institutions)     AS institutions,"
            "       (SELECT COUNT(*) FROM products)         AS products,"
            "       (SELECT COUNT(*) FROM product_variants) AS variants,"
            "       (SELECT COUNT(*) FROM rate_observations) AS observations,"
            "       (SELECT COUNT(*) FROM collection_runs)  AS runs",
        )[0]

        # 수집원마다 마지막 실행을 쓴다.
        #
        # 예전에는 전체에서 가장 최근 실행 하나만 봤다. 수집원이 하나일 때는
        # 맞았지만 저축은행 다음에 새마을금고를 돌리면 저축은행 수치가
        # 화면에서 통째로 사라진다.
        run_ids = latest_run_ids(conn)
        placeholders = ",".join("?" for _ in run_ids)

        # 기간별 금리 분포. base_rate는 0 패딩 문자열이라 사전순 == 수치순이다.
        by_term = _rows(
            conn,
            "SELECT v.term_months AS term_months,"
            "       COUNT(*)                AS count,"
            "       MIN(o.base_rate)        AS base_min,"
            "       MAX(o.base_rate)        AS base_max,"
            "       MAX(o.max_rate)         AS max_rate_top"
            "  FROM rate_observations o"
            "  JOIN product_variants v ON v.id = o.variant_id"
            f" WHERE o.last_run_id IN ({placeholders})"
            " GROUP BY v.term_months"
            " ORDER BY v.term_months",
            tuple(run_ids),
        ) if run_ids else []

        top_rates = _rows(
            conn,
            "SELECT i.canonical_name AS institution,"
            "       p.name           AS product,"
            "       v.term_months    AS term_months,"
            "       v.interest_method AS interest_method,"
            "       o.base_rate      AS base_rate,"
            "       o.max_rate       AS max_rate,"
            "       o.source_effective_at AS source_effective_at"
            "  FROM rate_observations o"
            "  JOIN product_variants v ON v.id = o.variant_id"
            "  JOIN products p         ON p.id = v.product_id"
            "  JOIN institutions i     ON i.id = p.institution_id"
            f" WHERE o.last_run_id IN ({placeholders}) AND o.validation_status != 'error'"
            " ORDER BY o.base_rate DESC LIMIT 15",
            tuple(run_ids),
        ) if run_ids else []

        # 구·군별 집계 — 이 프로젝트의 목적이다.
        #
        # 구는 **점포 주소**에서 뽑는다. 기관 주소가 아니다. 금리는 금고 단위로
        # 공시되지만 한 금고가 두 구에 점포를 두기도 해서, 기관 주소만 쓰면
        # 그 금고가 다른 구에서 통째로 사라진다 (부산 실측 3건).
        # 점포가 있는 구 전부에 그 금고의 금리를 보여준다.
        #
        # 점포 명부가 없는 원천은 기관 주소로 되돌아간다.
        # 저축은행은 둘 다 없어 여기 잡히지 않는다. 의도한 결과다 —
        # 본점 기준 공시라 구 단위로 말할 수 없다.
        #
        # 직장금고는 해당 직장 임직원만 가입할 수 있다. 그 금리를 "이 구의
        # 최고금리"로 내세우면 일반 이용자가 가입할 수 없는 값을 보게 된다.
        # 실측에서 강서구 10.00%와 부산진구 5.00%가 모두 직장금고였다.
        # 대표값은 일반 가입 가능분으로 내고, 직장금고는 따로 센다.
        district_sql = (
            "  FROM rate_observations o"
            "  JOIN product_variants v ON v.id = o.variant_id"
            "  JOIN products p         ON p.id = v.product_id"
            "  JOIN institutions i     ON i.id = p.institution_id"
            "  LEFT JOIN outlets ot    ON ot.institution_id = i.id"
            f" WHERE o.last_run_id IN ({placeholders})"
            "   AND o.validation_status != 'error'"
            # 지역을 못 읽은 행은 뺀다. 예전에는 주소가 비었는지로 걸렀는데,
            # 이제 걸러야 하는 것은 "주소가 있는가"가 아니라 "그 주소에서
            # 지역이 나왔는가"다. 둘은 다르다 — 주소가 있어도 못 읽을 수 있다.
            f"   AND {SIDO_EXPR} IS NOT NULL"
        )
        district_expr = DISTRICT_EXPR
        by_district = _rows(
            conn,
            f"SELECT {SIDO_EXPR} AS sido,"
            f"       {district_expr} AS sigungu,"
            "       i.sector             AS sector,"
            "       COUNT(DISTINCT i.id) AS institutions,"
            "       COUNT(DISTINCT o.id) AS observations,"
            "       MAX(CASE WHEN i.availability_scope != 'workplace_members'"
            "                THEN o.base_rate END)  AS base_max,"
            "       MAX(o.base_rate)                AS base_max_including_workplace,"
            "       COUNT(DISTINCT CASE WHEN i.availability_scope = 'workplace_members'"
            "                           THEN i.id END) AS workplace_institutions"
            + district_sql
            # 시도까지 묶어야 서울 중구와 부산 중구가 한 줄로 합쳐지지 않는다.
            + " GROUP BY sido, sigungu, i.sector"
            " ORDER BY base_max DESC",
            tuple(run_ids),
        ) if run_ids else []

        # 구·군별 최고금리 상품. 12개월 기준으로 좁힌다.
        district_top = _rows(
            conn,
            "SELECT sido, sigungu, institution, product, term_months, base_rate,"
            "       source_effective_at FROM ("
            f"  SELECT {SIDO_EXPR} AS sido,"
            f"         {district_expr} AS sigungu,"
            "         i.canonical_name AS institution,"
            "         p.name           AS product,"
            "         v.term_months    AS term_months,"
            "         o.base_rate      AS base_rate,"
            "         o.source_effective_at AS source_effective_at,"
            f"        ROW_NUMBER() OVER (PARTITION BY {SIDO_EXPR},"
            f"                                        {district_expr}"
            "           ORDER BY o.base_rate DESC) AS rn"
            + district_sql
            + "     AND v.term_months = 12"
            # 직장금고는 제외한다. 일반 이용자가 가입할 수 없다.
            "     AND i.availability_scope != 'workplace_members'"
            ") WHERE rn = 1 ORDER BY base_rate DESC",
            tuple(run_ids),
        ) if run_ids else []

        # 직장금고는 숨기지 않고 따로 보여준다. 가입 제한을 함께 적는다.
        workplace = _rows(
            conn,
            "SELECT i.canonical_name AS institution,"
            "       i.address        AS address,"
            "       p.name           AS product,"
            "       v.term_months    AS term_months,"
            "       o.base_rate      AS base_rate"
            "  FROM rate_observations o"
            "  JOIN product_variants v ON v.id = o.variant_id"
            "  JOIN products p         ON p.id = v.product_id"
            "  JOIN institutions i     ON i.id = p.institution_id"
            f" WHERE o.last_run_id IN ({placeholders})"
            "   AND i.availability_scope = 'workplace_members'"
            "   AND o.validation_status != 'error'"
            " ORDER BY o.base_rate DESC LIMIT 10",
            tuple(run_ids),
        ) if run_ids else []

        reviews = _rows(
            conn,
            "SELECT issue_type, severity, COUNT(*) AS count"
            "  FROM review_items WHERE status = 'open'"
            " GROUP BY issue_type, severity ORDER BY count DESC",
        )
        review_samples = _rows(
            conn,
            "SELECT issue_type, severity, message FROM review_items"
            " WHERE status = 'open' ORDER BY created_at DESC LIMIT 10",
        )

        sources = _rows(
            conn,
            "SELECT s.id, s.name, s.source_role, s.trust_level, s.coverage_status,"
            "       COUNT(o.id) AS observation_count"
            "  FROM sources s"
            "  LEFT JOIN collection_runs r ON r.source_id = s.id"
            "  LEFT JOIN rate_observations o ON o.run_id = r.id"
            " GROUP BY s.id ORDER BY s.priority",
        )

        rate_scopes = _rows(
            conn,
            "SELECT v.rate_scope, COUNT(*) AS count"
            "  FROM rate_observations o JOIN product_variants v ON v.id = o.variant_id"
            " GROUP BY v.rate_scope",
        )

        table = build_rate_table(conn, run_ids)
        benchmarks = build_benchmarks(conn, run_ids)
    finally:
        conn.close()

    return {
        "generated_at": now_kst().isoformat(),
        "notice": HEAD_OFFICE_NOTICE,
        "latest_run": latest_run[0] if latest_run else None,
        "runs": runs,
        "totals": totals,
        "by_term": by_term,
        "by_district": by_district,
        "district_top": district_top,
        "workplace_only": workplace,
        "top_rates": top_rates,
        "reviews": reviews,
        "review_samples": review_samples,
        "sources": sources,
        "rate_scopes": rate_scopes,
        "benchmarks": benchmarks,
        "table": table,
    }


def render(template_text: str, summary: dict[str, Any]) -> str:
    """템플릿의 단일 주입 지점에 데이터를 인라인한다."""
    start = template_text.find(DATA_MARKER)
    if start == -1:
        raise DashboardBuildError(f"주입 지점을 찾지 못했다: {DATA_MARKER}")
    end = template_text.find(DATA_END, start)
    if end == -1:
        raise DashboardBuildError("주입 지점이 닫히지 않았다")

    # 들여쓰기 없이 싣는다. 금리표가 1만 4천 행이라 들여쓰기만으로 파일이
    # 3배 넘게 커진다. 읽기 좋은 형태는 publish/summary.json이 맡는다.
    payload = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    # </script>가 JSON 안에 들어가면 블록이 조기 종료된다.
    payload = payload.replace("</", "<\\/")
    return template_text[: start + len(DATA_MARKER)] + "\n" + payload + "\n" + template_text[end:]


def _verify(html: str, summary: dict[str, Any]) -> None:
    """빌드 후 자체 검증 (v3.1 §6.3). 실패하면 산출물을 쓰지 않는다."""
    leftovers = re.findall(r"\{\{[^}]+\}\}|<!--\s*RATE_MONITOR_[A-Z_]+\s*-->", html)
    if leftovers:
        raise DashboardBuildError(f"치환 마커 잔존: {leftovers[:5]}")

    start = html.find(DATA_MARKER)
    end = html.find(DATA_END, start)
    raw = html[start + len(DATA_MARKER) : end].replace("<\\/", "</")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DashboardBuildError(f"인라인 JSON 파싱 실패: {exc}") from exc

    if parsed["totals"] != summary["totals"]:
        raise DashboardBuildError("화면 집계값이 summary와 다르다")
    if HEAD_OFFICE_NOTICE not in html:
        raise DashboardBuildError("본점 기준 참고값 표기가 없다 (v3.1 §6.4)")


def build_dashboard(
    db_path: Path,
    template_path: Path = DEFAULT_TEMPLATE,
    site_path: Path = DEFAULT_SITE,
    summary_path: Path = DEFAULT_SUMMARY,
    public_template_path: Path | None = DEFAULT_PUBLIC_TEMPLATE,
    public_site_path: Path | None = DEFAULT_PUBLIC_SITE,
) -> dict[str, Any]:
    """SQLite → summary.json + 운영 보드 + 공개용 전체 조회 화면.

    두 화면은 **같은 summary**를 쓴다. 표현만 다르고 집계는 하나다.
    따로 만들면 어느 쪽 숫자가 맞는지 알 수 없게 된다.
    """
    summary = build_summary(db_path)
    html = render(template_path.read_text(encoding="utf-8"), summary)
    _verify(html, summary)

    public_html: str | None = None
    if public_template_path is not None and public_site_path is not None:
        public_html = render(
            public_template_path.read_text(encoding="utf-8"), summary
        )
        _verify(public_html, summary)

    # 금리표는 빼고 쓴다.
    #
    # 이 파일은 사람이 열어 보는 요약이고, 들여쓰기까지 넣어 저장한다.
    # 금리표를 함께 담으면 전국 기준 24 MiB가 된다 — 같은 표가 이미
    # `site-public/data/table.json`에 5.4 MiB로 들어 있으므로 두 벌이다.
    # 게이트는 `totals`만 보므로 빼도 검증이 성립한다.
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    readable = {k: v for k, v in summary.items() if k != "table"}
    readable["table_rows"] = len(summary.get("table", {}).get("rows") or [])
    summary_path.write_text(
        json.dumps(readable, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    site_path.parent.mkdir(parents=True, exist_ok=True)
    site_path.write_text(html, encoding="utf-8")
    if public_html is not None and public_site_path is not None:
        public_site_path.parent.mkdir(parents=True, exist_ok=True)
        public_site_path.write_text(public_html, encoding="utf-8")
    return summary
