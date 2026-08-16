"""전략 화면 전용 table/template 계약 보강.

공식 검색 화면의 발행 계약은 그대로 두고, 전략 Release Gate가 켜진 빌드에서만
canonical ``product_id``를 table.json에 덧붙인다. 전략 화면은 이 stable id로
상품 대표값을 묶는다.

전략 템플릿은 큰 단일 HTML이라 데이터 계약과 전략 화면 전용 표현 변경을 작은
어댑터로 명시적으로 적용한다. 기대한 원문이 사라지면 조용히 건너뛰지 않고 빌드를
실패시킨다.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.inflow_prediction_service import public_model_config

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


def _adapt_inflow_prediction(text: str) -> str:
    """수동 단일 민감도 계산기를 구조 예측엔진 v1 UI로 교체한다."""
    model_json = json.dumps(
        public_model_config(), ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")
    text = _replace_once(
        text,
        'const OUR_INSTITUTION="고려저축은행";',
        f'const OUR_INSTITUTION="고려저축은행";const INFLOW_MODEL={model_json};',
        "inflow_model.config",
    )
    text = _replace_once(
        text,
        "기본금리·우대금리·가입기간만 입력하고 실제 시장 비교군과 즉시 비교합니다.",
        "금리를 정하면 실제 시장 포지션과 수신금액 구조모형을 함께 계산합니다.",
        "inflow_model.copy",
    )
    text = _replace_once(
        text,
        '<span class="chip">WHAT-IF</span>',
        '<span class="chip">PREDICT v1</span>',
        "inflow_model.badge",
    )
    old_css = (
        ".assumptions{display:grid;grid-template-columns:1fr 1fr;gap:8px}"
        ".assumptions label{color:#72837a;font-size:9px}"
        ".assumptions input{width:100%;margin-top:4px;padding:9px 10px;"
        "border:1px solid var(--line);border-radius:8px;background:#091814;"
        "color:#e2e9e5;outline:0}"
        ".warning{margin:0;color:#677970;font-size:8.8px;line-height:1.55}"
    )
    new_css = (
        ".prediction-head{display:flex;align-items:center;justify-content:space-between;"
        "gap:10px;padding-top:2px}.prediction-head b{font-size:10.5px}"
        ".model-status{padding:4px 7px;border:1px solid rgba(212,179,111,.25);"
        "border-radius:7px;color:var(--gold);font-size:8px;background:rgba(212,179,111,.06)}"
        ".predict-inputs{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}"
        ".predict-inputs label{color:#72837a;font-size:9px}"
        ".predict-inputs input{width:100%;margin-top:4px;padding:9px 10px;"
        "border:1px solid var(--line);border-radius:8px;background:#091814;"
        "color:#e2e9e5;outline:0}"
        ".prediction-results{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}"
        ".prediction-results .simresult b{font-size:17px}"
        ".model-detail{margin:0;padding:9px 10px;border:1px solid var(--line);"
        "border-radius:9px;background:rgba(4,14,11,.18);color:#74877d;"
        "font-size:8.6px;line-height:1.5}"
        ".warning{margin:0;color:#677970;font-size:8.8px;line-height:1.55}"
    )
    text = _replace_once(text, old_css, new_css, "inflow_model.css")
    text = _replace_once(
        text,
        ".simresults,.assumptions{grid-template-columns:1fr}",
        ".simresults,.predict-inputs,.prediction-results{grid-template-columns:1fr}",
        "inflow_model.mobile_css",
    )
    old_html = (
        '<div class="assumptions"><label>기준 월 수신액 (억원)'
        '<input id="baseline" type="number" min="0" step="1" placeholder="예: 100">'
        '</label><label>+0.10%p당 변화율 (%)'
        '<input id="sensitivity" type="number" step="0.1" placeholder="예: 4">'
        '</label></div>\n      '
        '<div class="simresult"><span>가정 기반 예상 월 수신액</span>'
        '<b id="inflow">가정 입력 필요</b><small id="inflow-note">'
        '기준 수신액과 민감도를 입력하면 계산합니다.</small></div>\n      '
        '<p class="warning">내부 실적 기반 예측모형이 아닙니다. 입력 가정에 따른 '
        '시나리오이며 실제 유입을 보장하지 않습니다.</p>'
    )
    new_html = (
        '<div class="prediction-head"><b>수신금액 예측 엔진</b>'
        '<span class="model-status" id="model-status">내부 실적 미보정</span></div>\n      '
        '<div class="predict-inputs">'
        '<label>최근 월 신규수신 기준액 (억원)'
        '<input id="baseline-new" type="number" min="0" step="1" placeholder="예: 100">'
        '</label><label>다음 만기도래액 (억원)'
        '<input id="maturity-amount" type="number" min="0" step="1" placeholder="예: 200">'
        '</label><label>현재 재예치율 (%)'
        '<input id="rollover-rate" type="number" min="0" max="100" step="0.1" '
        'placeholder="예: 60"></label></div>\n      '
        '<div class="prediction-results">'
        '<div class="simresult"><span>예상 신규자금 · 기준</span>'
        '<b class="green" id="inflow-new">입력 필요</b>'
        '<small id="inflow-new-note">현재 당사금리 기준</small></div>'
        '<div class="simresult"><span>예상 재예치 · 기준</span>'
        '<b id="inflow-rollover">입력 필요</b>'
        '<small id="inflow-rollover-note">만기도래액 × 예상 재예치율</small></div>'
        '<div class="simresult"><span>예상 총수신 · 기준</span>'
        '<b class="gold" id="inflow-total">입력 필요</b>'
        '<small id="inflow-total-note">신규자금 + 재예치</small></div>'
        '<div class="simresult"><span>총수신 시나리오 범위</span>'
        '<b id="inflow-range">입력 필요</b>'
        '<small>저민감 · 기준 · 고민감 스트레스</small></div>'
        '<div class="simresult"><span>현재 대비 총수신 증감</span>'
        '<b id="inflow-delta">입력 필요</b>'
        '<small>현재 금리 baseline 대비</small></div>'
        '<div class="simresult"><span>추가 표면이자비용</span>'
        '<b id="inflow-cost">입력 필요</b>'
        '<small>FTP 미반영 · 선택기간 단순계산</small></div></div>\n      '
        '<p class="model-detail" id="inflow-model-detail">당사 현재금리와 시장 상위10%선을 '
        '확인한 뒤 계산합니다.</p>\n      '
        '<p class="warning">예측엔진 v1은 내부 수신실적 계수가 아직 미보정된 구조모형입니다. '
        '표시 범위는 민감도 스트레스 결과이며 실제 유입을 보장하지 않습니다.</p>'
    )
    text = _replace_once(text, old_html, new_html, "inflow_model.html")
    helper_js = (
        'function predictionNumber(id,{min=0,max=Infinity}={}){const raw=$(id).value.trim(),'
        'value=Number(raw);return raw!==""&&Number.isFinite(value)&&value>=min&&value<=max?value:null}\n'
        'function logistic(x){if(x>=0){const z=Math.exp(-x);return 1/(1+z)}const z=Math.exp(x);return z/(1+z)}\n'
        'function runInflowScenario({baseline,maturity,rollover,ownRate,proposed,top10,term,scenario}){'
        'const step=INFLOW_MODEL.rate_step_percentage_point,currentGap=ownRate-top10,'
        'proposedGap=proposed-top10,relativeChange=proposedGap-currentGap,rateSteps=relativeChange/step,'
        'maxLog=INFLOW_MODEL.max_abs_new_money_log_effect,rawLog=scenario.new_money_log_change_per_10bp*rateSteps,'
        'logEffect=Math.max(-maxLog,Math.min(maxLog,rawLog)),newMoney=baseline*Math.exp(logEffect),'
        'guard=INFLOW_MODEL.rollover_probability_guardrail,p0=Math.max(guard.min,Math.min(guard.max,rollover/100)),'
        'rollLogit=Math.log(p0/(1-p0))+scenario.rollover_log_odds_change_per_10bp*rateSteps,'
        'p1=logistic(rollLogit),renewal=maturity*p1,baselineTotal=baseline+maturity*p0,total=newMoney+renewal,'
        'delta=total-baselineTotal,cost=total*(proposed-ownRate)/100*(term/12);'
        'return{currentGap,proposedGap,relativeChange,rateSteps,newMoney,p1,renewal,baselineTotal,total,delta,cost}}\n'
        'function predictInflow(args){const results=INFLOW_MODEL.scenarios.map(s=>runInflowScenario({...args,scenario:s})),'
        'baseIndex=INFLOW_MODEL.scenarios.findIndex(s=>s.key==="base"),base=results[baseIndex>=0?baseIndex:0],'
        'totals=results.map(x=>x.total);return{base,minTotal:Math.min(...totals),maxTotal:Math.max(...totals)}}\n'
        'function amountText(value){return `${value.toLocaleString("ko-KR",{maximumFractionDigits:1})}억원`}\n'
        'function signedAmountText(value){return `${value>=0?"+":""}${value.toLocaleString("ko-KR",{maximumFractionDigits:1})}억원`}\n'
        'function clearInflowPrediction(message){["inflow-new","inflow-rollover","inflow-total","inflow-range","inflow-delta","inflow-cost"]'
        '.forEach(id=>$(id).textContent="입력 필요");$("inflow-model-detail").textContent=message}\n'
    )
    text = _replace_once(
        text,
        "function updateSim(){\n",
        helper_js + "function updateSim(){\n",
        "inflow_model.helpers",
    )
    old_calc = (
        'const baselineRaw=$("baseline").value.trim(),sensitivityRaw=$("sensitivity").value.trim(),'
        'baseline=Number(baselineRaw),sensitivity=Number(sensitivityRaw);'
        'if(baselineRaw!==""&&sensitivityRaw!==""&&baseline>=0&&Number.isFinite(baseline)&&'
        'Number.isFinite(sensitivity)&&Number.isFinite(stats.mean)){const factor=Math.max(0,1+'
        '((proposed-stats.mean)/.10)*sensitivity/100),estimate=baseline*factor;'
        '$("inflow").textContent=`${estimate.toLocaleString("ko-KR",{maximumFractionDigits:1})}억원`;'
        '$("inflow-note").textContent=`${simTerm}개월 시장 평균 대비 ${proposed-stats.mean>=0?"+":""}'
        '${(proposed-stats.mean).toFixed(2)}%p · 가정 계수 ×${factor.toFixed(2)}`}else{'
        '$("inflow").textContent="가정 입력 필요";$("inflow-note").textContent='
        '"기준 수신액과 민감도를 모두 입력하면 계산합니다."}'
    )
    new_calc = (
        'const baseline=predictionNumber("baseline-new"),maturity=predictionNumber("maturity-amount"),'
        'rollover=predictionNumber("rollover-rate",{min:0,max:100});'
        'if(!own){clearInflowPrediction(`${simTerm}개월 고려저축은행 비교상품이 없어 현재 금리 anchor를 잡을 수 없습니다.`)}'
        'else if(!comp.length||!Number.isFinite(stats.top10)){clearInflowPrediction(`${simTerm}개월 시장 상위10%선을 계산할 비교상품이 필요합니다.`)}'
        'else if(baseline==null||maturity==null||rollover==null){clearInflowPrediction('
        '"최근 월 신규수신 기준액·다음 만기도래액·현재 재예치율을 입력하면 계산합니다.")}'
        'else{const prediction=predictInflow({baseline,maturity,rollover,ownRate:own.max,proposed,top10:stats.top10,term:simTerm}),'
        'b=prediction.base;$("inflow-new").textContent=amountText(b.newMoney);'
        '$("inflow-new-note").textContent=`현재 당사 ${own.max.toFixed(2)}% → 제안 ${proposed.toFixed(2)}%`;'
        '$("inflow-rollover").textContent=amountText(b.renewal);'
        '$("inflow-rollover-note").textContent=`예상 재예치율 ${(b.p1*100).toFixed(1)}%`;'
        '$("inflow-total").textContent=amountText(b.total);'
        '$("inflow-total-note").textContent=`현재금리 baseline ${amountText(b.baselineTotal)}`;'
        '$("inflow-range").textContent=`${amountText(prediction.minTotal)} ~ ${amountText(prediction.maxTotal)}`;'
        '$("inflow-delta").textContent=signedAmountText(b.delta);'
        '$("inflow-cost").textContent=signedAmountText(b.cost);'
        '$("inflow-model-detail").textContent=`${INFLOW_MODEL.version} · ${simTerm}개월 · 상대금리 이동 '
        '${b.relativeChange>=0?"+":""}${(b.relativeChange*100).toFixed(0)}bp · 제안금리 TOP10선 대비 '
        '${b.proposedGap>=0?"+":""}${(b.proposedGap*100).toFixed(0)}bp · 계수 상태 내부 실적 미보정`}'
    )
    text = _replace_once(text, old_calc, new_calc, "inflow_model.calculation")
    text = _replace_once(
        text,
        '$("baseline").addEventListener("input",updateSim);'
        '$("sensitivity").addEventListener("input",updateSim);',
        '["baseline-new","maturity-amount","rollover-rate"].forEach('
        'id=>$(id).addEventListener("input",updateSim));',
        "inflow_model.listeners",
    )
    return text


def adapt_strategy_template(template_text: str) -> str:
    """stable product id, 우대조건 기준일, 부산 focus, 수신 예측 계약을 적용한다."""
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
    return _adapt_inflow_prediction(text)
