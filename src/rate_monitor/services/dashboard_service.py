"""정적 대시보드 생성 (명세서 v3.1 §6).

SQLite를 집계해 summary.json을 만들고, 템플릿의 단일 주입 지점에 인라인해
site/index.html을 생성한다. 게시된 페이지는 외부 fetch가 차단될 수 있으므로
런타임에 JSON을 불러오지 않는다.

빌드 후 자체 검증에 실패하면 산출물을 쓰지 않는다.
"""

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_TEMPLATE = Path("web/templates/dashboard.html")
DEFAULT_SITE = Path("site/index.html")
DEFAULT_SUMMARY = Path("publish/summary.json")

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
)


# 구는 주소에서 두 번째 토막을 떼어 만든다 ("부산 중구 대청로 101-1" → "중구").
# 점포 주소를 먼저 보고, 점포 명부가 없는 원천은 기관 주소로 되돌아간다.
# 행정구역 공식 코드가 아니라 파생값이다.
DISTRICT_EXPR = (
    "TRIM(SUBSTR(COALESCE(ot.address, i.address),"
    "     INSTR(COALESCE(ot.address, i.address), ' ') + 1,"
    "     INSTR(SUBSTR(COALESCE(ot.address, i.address),"
    "           INSTR(COALESCE(ot.address, i.address), ' ') + 1), ' ')))"
)


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


def build_rate_table(
    conn: sqlite3.Connection, run_ids: list[str], district_expr: str = DISTRICT_EXPR
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
    raw = _rows(
        conn,
        "SELECT i.sector                AS sector,"
        "       i.canonical_name        AS institution,"
        f"      {district_expr}         AS district,"
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
        "       o.source_effective_at   AS source_effective_at"
        "  FROM rate_observations o"
        "  JOIN collection_runs r  ON r.id = o.run_id"
        "  JOIN product_variants v ON v.id = o.variant_id"
        "  JOIN products p         ON p.id = v.product_id"
        "  JOIN institutions i     ON i.id = p.institution_id"
        "  LEFT JOIN outlets ot    ON ot.institution_id = i.id"
        f" WHERE o.run_id IN ({placeholders})"
        "   AND o.validation_status != 'error'"
        " ORDER BY o.base_rate DESC",
        tuple(run_ids),
    )

    # 같은 값이 수천 번 되풀이되는 열만 조회표로 뺀다.
    indexed = ("sector", "institution", "district", "product", "product_type",
               "payment_method", "interest_method", "join_channel",
               "availability_scope", "source_id", "source_effective_at")
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
            f" WHERE o.run_id IN ({placeholders})"
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
            f" WHERE o.run_id IN ({placeholders}) AND o.validation_status != 'error'"
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
            f" WHERE o.run_id IN ({placeholders})"
            "   AND o.validation_status != 'error'"
            "   AND COALESCE(ot.address, i.address) IS NOT NULL"
            "   AND COALESCE(ot.address, i.address) != ''"
        )
        district_expr = DISTRICT_EXPR
        by_district = _rows(
            conn,
            f"SELECT {district_expr} AS sigungu,"
            "       i.sector             AS sector,"
            "       COUNT(DISTINCT i.id) AS institutions,"
            "       COUNT(DISTINCT o.id) AS observations,"
            "       MAX(CASE WHEN i.availability_scope != 'workplace_members'"
            "                THEN o.base_rate END)  AS base_max,"
            "       MAX(o.base_rate)                AS base_max_including_workplace,"
            "       COUNT(DISTINCT CASE WHEN i.availability_scope = 'workplace_members'"
            "                           THEN i.id END) AS workplace_institutions"
            + district_sql
            + " GROUP BY sigungu, i.sector"
            " ORDER BY base_max DESC",
            tuple(run_ids),
        ) if run_ids else []

        # 구·군별 최고금리 상품. 12개월 기준으로 좁힌다.
        district_top = _rows(
            conn,
            "SELECT sigungu, institution, product, term_months, base_rate,"
            "       source_effective_at FROM ("
            f"  SELECT {district_expr} AS sigungu,"
            "         i.canonical_name AS institution,"
            "         p.name           AS product,"
            "         v.term_months    AS term_months,"
            "         o.base_rate      AS base_rate,"
            "         o.source_effective_at AS source_effective_at,"
            f"        ROW_NUMBER() OVER (PARTITION BY {district_expr}"
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
            f" WHERE o.run_id IN ({placeholders})"
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

        table = build_rate_table(conn, run_ids, district_expr)
    finally:
        conn.close()

    return {
        "generated_at": datetime.now(UTC).isoformat(),
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
) -> dict[str, Any]:
    """SQLite → summary.json + site/index.html."""
    summary = build_summary(db_path)
    html = render(template_path.read_text(encoding="utf-8"), summary)
    _verify(html, summary)

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    site_path.parent.mkdir(parents=True, exist_ok=True)
    site_path.write_text(html, encoding="utf-8")
    return summary
