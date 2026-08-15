"""전략 화면 전용 table/template 계약 보강.

공식 검색 화면의 발행 계약은 그대로 두고, 전략 Release Gate가 켜진 빌드에서만
canonical ``product_id``를 table.json에 덧붙인다. 전략 화면은 이 stable id로
상품 대표값을 묶는다.

전략 템플릿은 큰 단일 HTML이라 데이터 계약과 전략 화면 전용 표현 변경을 작은
어댑터로 명시적으로 적용한다. 기대한 원문이 사라지면 조용히 건너뛰지 않고 빌드를
실패시킨다.
"""

import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.services.dashboard_service import DashboardBuildError

PRODUCT_ID_COLUMN = "product_id"
_STRATEGY_TERMS = frozenset({6, 12, 24, 36})
_IDENTITY_KEY_COLUMNS = (
    "source_id",
    "institution",
    "product",
    "product_type",
    "term_months",
    "payment_method",
    "interest_method",
    "join_channel",
)


def _decode(table: dict[str, Any], column: str, value: Any) -> Any:
    lookup = (table.get("lookups") or {}).get(column)
    if lookup is None or value is None:
        return value
    return lookup[value]


def _row_key(table: dict[str, Any], row: list[Any]) -> tuple[Any, ...]:
    columns = {name: index for index, name in enumerate(table.get("columns") or [])}
    return tuple(
        _decode(table, name, row[columns[name]]) for name in _IDENTITY_KEY_COLUMNS
    )


def _product_id_index(db_path: Path) -> dict[tuple[Any, ...], str | None]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT
                r.source_id,
                i.canonical_name,
                p.name,
                p.product_type,
                v.term_months,
                v.payment_method,
                v.interest_method,
                v.join_channel,
                p.id
            FROM rate_observations o
            JOIN collection_runs r ON r.id = o.run_id
            JOIN product_variants v ON v.id = o.variant_id
            JOIN products p ON p.id = v.product_id
            JOIN institutions i ON i.id = p.institution_id
            WHERE o.valid_to IS NULL
              AND o.validation_status != 'error'
            """
        ).fetchall()
    finally:
        conn.close()

    candidates: dict[tuple[Any, ...], set[str]] = {}
    for row in rows:
        key = tuple(row[:-1])
        candidates.setdefault(key, set()).add(str(row[-1]))
    return {
        key: next(iter(ids)) if len(ids) == 1 else None
        for key, ids in candidates.items()
    }


def augment_strategy_table(
    db_path: Path, table: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    """전략 빌드의 table에 압축 ``product_id`` 열을 추가한다.

    검색 화면의 기본 빌드에서는 호출하지 않는다. 전략 비교 universe에 해당하는
    저축은행 정기예금 6/12/24/36개월 행이 stable id와 매칭되지 않으면 build를
    실패시킨다. 이름 기반 fallback으로 조용히 순위를 만드는 것보다 안전하다.
    """
    columns = list(table.get("columns") or [])
    if PRODUCT_ID_COLUMN in columns:
        return table, {"matched": len(table.get("rows") or []), "unmatched": 0}

    source_columns = {name: index for index, name in enumerate(columns)}
    required = set(_IDENTITY_KEY_COLUMNS) | {"sector"}
    missing = sorted(required.difference(source_columns))
    if missing:
        raise DashboardBuildError(
            "전략 stable identity에 필요한 table 열이 없다: " + ", ".join(missing)
        )

    product_ids = _product_id_index(db_path)
    id_lookup: list[str] = []
    id_positions: dict[str, int] = {}
    rows: list[list[Any]] = []
    target_unmatched = 0
    matched = 0

    for source_row in table.get("rows") or []:
        row = list(source_row)
        product_id = product_ids.get(_row_key(table, row))
        if product_id is not None:
            matched += 1
            if product_id not in id_positions:
                id_positions[product_id] = len(id_lookup)
                id_lookup.append(product_id)
            row.append(id_positions[product_id])
        else:
            row.append(None)
            sector = _decode(table, "sector", row[source_columns["sector"]])
            product_type = _decode(
                table, "product_type", row[source_columns["product_type"]]
            )
            term = row[source_columns["term_months"]]
            if (
                sector == "savings_bank"
                and product_type == "term_deposit"
                and term in _STRATEGY_TERMS
            ):
                target_unmatched += 1
        rows.append(row)

    if target_unmatched:
        raise DashboardBuildError(
            "전략 비교상품 stable product_id 매칭 실패: "
            f"{target_unmatched}행"
        )

    lookups = dict(table.get("lookups") or {})
    lookups[PRODUCT_ID_COLUMN] = id_lookup
    return (
        {**table, "columns": [*columns, PRODUCT_ID_COLUMN], "lookups": lookups, "rows": rows},
        {"matched": matched, "unmatched": len(rows) - matched},
    )


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise DashboardBuildError(
            f"전략 템플릿 계약 지점을 찾지 못했다: {label} ({text.count(old)}건)"
        )
    return text.replace(old, new, 1)


def adapt_strategy_template(template_text: str) -> str:
    """stable product id, 우대조건 기준일, 부산 포커스 UI 계약을 적용한다."""
    text = _replace_once(
        template_text,
        'product:look("product",r[c.product]),type:look("product_type",r[c.product_type])',
        'product:look("product",r[c.product]),productId:look("product_id",r[c.product_id]),type:look("product_type",r[c.product_type])',
        "expand.product_id",
    )
    text = _replace_once(
        text,
        'const key=`${r.institution}\\0${r.product}\\0${term}`;',
        'const key=`${r.productId}\\0${term}`;',
        "aggregateProducts.product_id",
    )
    text = _replace_once(
        text,
        'prefKnown:false,tags:new Set}',
        'prefKnown:false,tags:new Set,tagLatest:new Map}',
        "aggregateProducts.preference_date_state",
    )
    text = _replace_once(
        text,
        'if(r.prefStatus==="present"){p.prefKnown=true;String(r.prefTags).split(/\\s+/).filter(Boolean).forEach(x=>p.tags.add(x))}',
        'if(r.prefStatus==="present"){p.prefKnown=true;const prefDate=String(r.sourceEffectiveAt||"");String(r.prefTags).split(/\\s+/).filter(Boolean).forEach(x=>{p.tags.add(x);if(prefDate>String(p.tagLatest.get(x)||""))p.tagLatest.set(x,prefDate)})}',
        "aggregateProducts.preference_date",
    )
    text = _replace_once(
        text,
        'function prefData(term=12){const ps=aggregateProducts(term).filter(p=>p.prefKnown),counts=new Map;for(const p of ps)p.tags.forEach(t=>counts.set(t,(counts.get(t)||0)+1));const labels=data.strategy?.preference_labels||{};return{denom:ps.length,items:[...counts].map(([code,count])=>({code,label:labels[code]||code,count,ratio:ps.length?count/ps.length*100:0})).sort((a,b)=>b.count-a.count).slice(0,6)}}',
        'function prefData(term=12){const ps=aggregateProducts(term).filter(p=>p.prefKnown),counts=new Map,latest=new Map;for(const p of ps)p.tags.forEach(t=>{counts.set(t,(counts.get(t)||0)+1);const d=String(p.tagLatest?.get(t)||"");if(d>String(latest.get(t)||""))latest.set(t,d)});const labels=data.strategy?.preference_labels||{};return{denom:ps.length,items:[...counts].map(([code,count])=>({code,label:labels[code]||code,count,ratio:ps.length?count/ps.length*100:0,latestAt:latest.get(code)||null})).sort((a,b)=>b.count-a.count).slice(0,6)}}',
        "prefData.latest",
    )
    text = _replace_once(
        text,
        'topPref=p.items[0],fresh=products12.map(x=>x.sourceEffectiveAt).filter(Boolean).sort().at(-1);',
        'topPref=p.items[0];',
        "insight.global_freshness",
    )
    text = _replace_once(
        text,
        '조건 기재 상품 중 ${topPref.ratio.toFixed(0)}%에서 확인 · 최신 공시기준일 ${formatDate(fresh)}',
        '조건 기재 상품 중 ${topPref.ratio.toFixed(0)}%에서 확인 · 원천 기준일 ${formatDate(topPref.latestAt)}',
        "insight.preference_reference_date",
    )
    text = _replace_once(
        text,
        '.district-rate.top{fill:var(--gold)}',
        '.district-rate.top{fill:var(--gold)}'
        '@media(min-width:1021px){'
        '.primary.busan-focus{grid-template-columns:minmax(720px,1.45fr) '
        'minmax(420px,.55fr)}'
        '.primary.busan-focus .mapcard{min-height:650px}'
        '.primary.busan-focus .mapstage{height:560px}'
        '}'
        '.primary.busan-focus .district-name{font-size:15px;stroke-width:4px}'
        '.primary.busan-focus .district-rate{font-size:14px;stroke-width:4px}',
        "busan_focus.css",
    )
    text = _replace_once(
        text,
        'function renderKoreaMap(){\n  mapMode="korea";',
        'function renderKoreaMap(){\n  mapMode="korea";'
        'document.querySelector(".primary")?.classList.remove("busan-focus");',
        "busan_focus.reset",
    )
    text = _replace_once(
        text,
        'function showBusanMap(){\n  mapMode="busan";',
        'function showBusanMap(){\n  mapMode="busan";'
        'document.querySelector(".primary")?.classList.add("busan-focus");',
        "busan_focus.open",
    )
    text = _replace_once(
        text,
        'nameText.setAttribute("y",(y-(has?5:0)).toFixed(1));',
        'nameText.setAttribute("y",(y-(has?7:0)).toFixed(1));',
        "busan_focus.name_spacing",
    )
    text = _replace_once(
        text,
        'rateText.setAttribute("y",(y+10).toFixed(1));',
        'rateText.setAttribute("y",(y+12).toFixed(1));',
        "busan_focus.rate_spacing",
    )
    return text
