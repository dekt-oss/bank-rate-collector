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
        latest_by_source = _rows(
            conn,
            "SELECT r.id, r.source_id FROM collection_runs r"
            "  JOIN (SELECT source_id, MAX(started_at) AS started_at"
            "          FROM collection_runs GROUP BY source_id) latest"
            "    ON latest.source_id = r.source_id"
            "   AND latest.started_at = r.started_at",
        )
        run_ids = [r["id"] for r in latest_by_source]
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
        # 구는 institutions.address에서 두 번째 토막을 떼어 만든다
        # ("부산 중구 대청로 101-1" → "중구"). 행정구역 공식 코드가
        # 확보되기 전까지의 파생값이므로 화면에도 그렇게 표기한다.
        #
        # 저축은행은 여기 잡히지 않는다. finlife가 주소를 주지 않아
        # institutions.address가 NULL이기 때문이다. 의도한 결과다 —
        # 저축은행 금리는 본점 기준이라 구 단위로 말할 수 없다.
        # 직장금고는 해당 직장 임직원만 가입할 수 있다. 그 금리를 "이 구의
        # 최고금리"로 내세우면 일반 이용자가 가입할 수 없는 값을 보게 된다.
        # 실측에서 강서구 10.00%와 부산진구 5.00%가 모두 직장금고였다.
        # 대표값은 일반 가입 가능분으로 내고, 직장금고는 따로 센다.
        by_district = _rows(
            conn,
            "SELECT TRIM(SUBSTR(i.address, INSTR(i.address, ' ') + 1,"
            "            INSTR(SUBSTR(i.address, INSTR(i.address, ' ') + 1), ' ')))"
            "         AS sigungu,"
            "       i.sector                  AS sector,"
            "       COUNT(DISTINCT i.id)      AS institutions,"
            "       COUNT(*)                  AS observations,"
            "       MAX(CASE WHEN i.availability_scope != 'workplace_members'"
            "                THEN o.base_rate END)            AS base_max,"
            "       MAX(o.base_rate)                          AS base_max_including_workplace,"
            "       COUNT(DISTINCT CASE WHEN i.availability_scope = 'workplace_members'"
            "                           THEN i.id END)        AS workplace_institutions"
            "  FROM rate_observations o"
            "  JOIN product_variants v ON v.id = o.variant_id"
            "  JOIN products p         ON p.id = v.product_id"
            "  JOIN institutions i     ON i.id = p.institution_id"
            f" WHERE o.run_id IN ({placeholders})"
            "   AND i.address IS NOT NULL AND i.address != ''"
            "   AND o.validation_status != 'error'"
            " GROUP BY sigungu, i.sector"
            " ORDER BY base_max DESC",
            tuple(run_ids),
        ) if run_ids else []

        # 구·군별 최고금리 상품. 12개월 기준으로 좁힌다.
        district_top = _rows(
            conn,
            "SELECT sigungu, institution, product, term_months, base_rate,"
            "       source_effective_at FROM ("
            "  SELECT TRIM(SUBSTR(i.address, INSTR(i.address, ' ') + 1,"
            "              INSTR(SUBSTR(i.address, INSTR(i.address, ' ') + 1), ' ')))"
            "           AS sigungu,"
            "         i.canonical_name AS institution,"
            "         p.name           AS product,"
            "         v.term_months    AS term_months,"
            "         o.base_rate      AS base_rate,"
            "         o.source_effective_at AS source_effective_at,"
            "         ROW_NUMBER() OVER ("
            "           PARTITION BY TRIM(SUBSTR(i.address, INSTR(i.address, ' ') + 1,"
            "                     INSTR(SUBSTR(i.address, INSTR(i.address, ' ') + 1), ' ')))"
            "           ORDER BY o.base_rate DESC) AS rn"
            "    FROM rate_observations o"
            "    JOIN product_variants v ON v.id = o.variant_id"
            "    JOIN products p         ON p.id = v.product_id"
            "    JOIN institutions i     ON i.id = p.institution_id"
            f"   WHERE o.run_id IN ({placeholders})"
            "     AND i.address IS NOT NULL AND i.address != ''"
            "     AND o.validation_status != 'error'"
            "     AND v.term_months = 12"
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
    }


def render(template_text: str, summary: dict[str, Any]) -> str:
    """템플릿의 단일 주입 지점에 데이터를 인라인한다."""
    start = template_text.find(DATA_MARKER)
    if start == -1:
        raise DashboardBuildError(f"주입 지점을 찾지 못했다: {DATA_MARKER}")
    end = template_text.find(DATA_END, start)
    if end == -1:
        raise DashboardBuildError("주입 지점이 닫히지 않았다")

    payload = json.dumps(summary, ensure_ascii=False, indent=2)
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
