# ruff: noqa: E501
"""Strategy 상품군 복수 선택과 핵심 비교영역 가독성 후속 presentation.

PR #211의 예금/적금·가입기간 계약은 유지하면서 다음만 보정한다.
- 예금/적금을 복수 선택 가능한 체크박스로 노출한다.
- 예금+적금 동시 선택 시 현재 비교 모집단을 합치되 금리값/원천 우선순위는 바꾸지 않는다.
- 서로 다른 상품군의 historical intelligence는 합성하지 않고 fail-closed 한다.
- 수신금액 예측은 기존 정기예금 단독 전용 경계를 유지한다.
- TOP5에 예금/적금 상품군 배지를 붙이고 핵심 텍스트 대비를 높인다.
- 금리결정 인사이트의 핵심 수치를 별도 metric으로 강조한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="dashboard-product-scope-readability-style"'
SCRIPT_MARKER = 'id="dashboard-strategy-scope-readability-script"'

READABILITY_STYLE = r"""
<style id="dashboard-product-scope-readability-style">
/* 상품군은 하나 이상 복수선택, 가입기간은 기존 단일 전역 scope를 유지한다. */
.strategy-product-scope>.product-family-tabs{display:none!important}
.strategy-family-checks{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.strategy-family-checks label,.strategy-savings-types label{display:inline-flex!important;align-items:center!important;gap:7px!important;min-height:36px!important;padding:7px 11px!important;border:1px solid rgba(74,54,76,.22)!important;border-radius:9px!important;background:rgba(255,255,255,.88)!important;color:#493a4b!important;font-size:10.5px!important;font-weight:800!important;line-height:1!important;box-shadow:0 1px 0 rgba(255,255,255,.72) inset!important;cursor:pointer!important}
.strategy-family-checks label.active,.strategy-savings-types label.active{border-color:#123f32!important;background:#123f32!important;color:#fff!important;box-shadow:0 0 0 2px rgba(18,63,50,.12)!important}
.strategy-family-checks input,.strategy-savings-types input{width:15px!important;height:15px!important;margin:0!important;accent-color:#16845f!important}
.strategy-family-checks label.active input,.strategy-savings-types label.active input{accent-color:#67c8a2!important}
.strategy-product-scope>span,.strategy-term-scope>span{color:var(--ink)!important;opacity:.72!important;font-size:10.5px!important;font-weight:820!important}
.strategy-product-scope .strategy-savings-types{gap:7px!important}
.strategy-product-scope .global-term-tabs{gap:7px!important}
.strategy-product-scope .global-term-tabs button{min-height:36px!important;padding:8px 13px!important;border:1px solid rgba(74,54,76,.22)!important;border-radius:9px!important;background:rgba(255,255,255,.88)!important;color:#493a4b!important;font-size:10.5px!important;font-weight:820!important;box-shadow:0 1px 0 rgba(255,255,255,.72) inset!important}
.strategy-product-scope .global-term-tabs button.active,.strategy-product-scope .global-term-tabs button[aria-pressed="true"]{border-color:#123f32!important;background:#123f32!important;color:#fff!important;box-shadow:0 0 0 2px rgba(18,63,50,.14)!important}
.strategy-product-scope .global-term-tabs button:focus-visible,.strategy-family-checks input:focus-visible,.strategy-savings-types input:focus-visible{outline:2px solid rgba(91,47,100,.55)!important;outline-offset:2px!important}

/* 경쟁사 TOP5: light surface에서도 hard-coded 연회색이 되지 않도록 theme ink를 기준으로 한다. */
.top5-card th{color:var(--ink)!important;opacity:.68!important;font-size:10px!important;font-weight:820!important}
.top5-card td{color:var(--ink)!important;font-size:11px!important}
.top5-card .bank{color:var(--ink)!important;font-size:12px!important;font-weight:880!important;letter-spacing:-.01em!important}
.top5-card .product{color:var(--ink)!important;opacity:.82!important;font-size:10.5px!important;font-weight:700!important;line-height:1.4!important}
.top5-card .sourcehint{color:var(--ink)!important;opacity:.64!important;font-size:9.5px!important;line-height:1.45!important}
.top5-card .strongrate{color:var(--green2,var(--green))!important;font-size:12px!important;font-weight:900!important}
.top5-card .head h2{color:var(--ink)!important;font-size:17px!important;font-weight:860!important}
.top5-card .head p{color:var(--ink)!important;opacity:.67!important;font-size:10.5px!important}
.top5-card .product-family-badge{display:inline-flex!important;align-items:center!important;justify-content:center!important;min-width:38px!important;margin-top:4px!important;padding:3px 7px!important;border:1px solid rgba(91,47,100,.18)!important;border-radius:999px!important;background:#f6eff7!important;color:#694373!important;font-size:9.5px!important;font-weight:860!important;line-height:1!important;vertical-align:middle!important}
.top5-card .product-family-badge.savings{border-color:rgba(47,125,101,.19)!important;background:#eef7f3!important;color:#2f6f59!important}
.top5-card .product-family-badge+.product{display:inline-block!important;max-width:calc(100% - 52px)!important;margin:4px 0 0 6px!important;vertical-align:middle!important}

/* 금리결정 인사이트: PC에서는 3개 카드를 한 행에, 핵심 숫자를 먼저 읽히게 한다. */
.insightcard .head h2{color:var(--ink)!important;font-size:18px!important;font-weight:880!important;letter-spacing:-.025em!important}
.insightcard .head p{color:var(--ink)!important;opacity:.70!important;font-size:11px!important;line-height:1.5!important}
.insightcard .insights{gap:10px!important}
.insightcard .insight{min-width:0!important;grid-template-columns:30px minmax(0,1fr)!important;gap:10px!important;padding:12px!important}
.insightcard .insight b{display:flex!important;align-items:baseline!important;gap:7px!important;flex-wrap:wrap!important;color:var(--ink)!important;font-size:12px!important;font-weight:880!important;line-height:1.35!important}
.insightcard .insight b .insight-metric{color:#5b2f64!important;font:900 28px/1 var(--mono)!important;letter-spacing:-.055em!important;white-space:nowrap!important}
.insightcard .insight:nth-child(2) b .insight-metric{color:#96661d!important}
.insightcard .insight:nth-child(3) b .insight-metric{color:#2f7d65!important}
.insightcard .insight b .insight-title-copy{color:var(--ink)!important;opacity:.82!important;font-size:11.5px!important;font-weight:850!important;line-height:1.35!important}
.insightcard .insight span{color:var(--ink)!important;opacity:.75!important;font-size:10.5px!important;line-height:1.5!important}
.insightcard .insight em{color:var(--ink)!important;opacity:.72!important;font-size:9.5px!important;font-weight:840!important}
.insightcard .insight small{color:var(--ink)!important;opacity:.72!important;font-size:10px!important;line-height:1.5!important}
@media(min-width:980px){.insightcard .insights{grid-template-columns:repeat(3,minmax(0,1fr))!important}.insightcard .insight:last-child{grid-column:auto!important}}
@media(min-width:761px) and (max-width:979px){.insightcard .insights{grid-template-columns:repeat(2,minmax(0,1fr))!important}.insightcard .insight:last-child{grid-column:auto!important}}
@media(max-width:760px){.strategy-family-checks{width:100%}.strategy-family-checks label{flex:1;justify-content:center}.strategy-product-scope .global-term-tabs{width:100%}.strategy-product-scope .global-term-tabs button{flex:1}.top5-card .product-family-badge+.product{max-width:calc(100% - 56px)!important}.insightcard .insights{grid-template-columns:1fr!important}.insightcard .insight:last-child{grid-column:auto!important}.insightcard .insight b .insight-metric{font-size:26px!important}}
</style>
"""

READABILITY_SCRIPT = r'''
<script id="dashboard-strategy-scope-readability-script">
(()=>{
  const PRODUCT_FAMILY_MODES=new Set(["deposit","savings","combined"]);
  const toList=value=>Array.isArray(value)?value:(value?[value]:[]);
  const uniqueValues=(...values)=>[...new Set(values.flatMap(toList).filter(Boolean))];
  const asCount=value=>Number.isFinite(Number(value))?Number(value):0;
  const latestValue=(a,b)=>[a,b].filter(Boolean).sort().at(-1)||null;
  const mergedRecordCounts=(a,b)=>{
    const result={};
    for(const [key,value] of Object.entries(a||{}))result[key]=asCount(value);
    for(const [key,value] of Object.entries(b||{}))result[key]=(result[key]||0)+asCount(value);
    return result;
  };
  const mergeTermMeta=(a,b)=>{
    const rows=asCount(a?.rows)+asCount(b?.rows),strategyRows=asCount(a?.strategy_rate_rows??a?.max_rate_rows)+asCount(b?.strategy_rate_rows??b?.max_rate_rows),maxRows=asCount(a?.max_rate_rows)+asCount(b?.max_rate_rows);
    return{...(a||{}),...(b||{}),rows,max_rate_rows:maxRows,strategy_rate_rows:strategyRows,coverage_ratio:rows?strategyRows/rows:null,selectable:!!(a?.selectable||b?.selectable)};
  };
  const mergeSectorMeta=(a,b,key)=>{
    const rows=asCount(a?.rows)+asCount(b?.rows),strategyRows=asCount(a?.strategy_rate_rows??a?.max_rate_rows)+asCount(b?.strategy_rate_rows??b?.max_rate_rows),maxRows=asCount(a?.max_rate_rows)+asCount(b?.max_rate_rows),selectable=!!(a?.selectable||b?.selectable),terms={};
    GLOBAL_TERMS.forEach(term=>{terms[String(term)]=mergeTermMeta(a?.terms?.[String(term)],b?.terms?.[String(term)])});
    return{...(a||{}),...(b||{}),label:a?.label||b?.label||key,state:selectable?"supported":"no_rows",max_rate_capability:!!(a?.max_rate_capability||b?.max_rate_capability),strategy_rate_capability:!!(a?.strategy_rate_capability||b?.strategy_rate_capability),selectable,rows,max_rate_rows:maxRows,strategy_rate_rows:strategyRows,coverage_ratio:rows?strategyRows/rows:null,latest_source_effective_at:latestValue(a?.latest_source_effective_at,b?.latest_source_effective_at),geo_basis:uniqueValues(a?.geo_basis,b?.geo_basis),rate_scope:uniqueValues(a?.rate_scope,b?.rate_scope),availability_scope:uniqueValues(a?.availability_scope,b?.availability_scope),rate_basis_counts:mergedRecordCounts(a?.rate_basis_counts,b?.rate_basis_counts),blocked_reason:selectable?null:(a?.blocked_reason||b?.blocked_reason||null),evidence:"deposit_stable_plus_savings_canonical_current",terms};
  };
  const buildCombinedUniverse=()=>{
    const keys=uniqueValues(depositUniverse?.candidate_sectors,savingsUniverse?.candidate_sectors,["savings_bank","cu","kfcc","nh_local"]),sectors={};
    keys.forEach(key=>{sectors[key]=mergeSectorMeta(depositUniverse?.sectors?.[key],savingsUniverse?.sectors?.[key],key)});
    return{...(depositUniverse||{}),metric_basis:"mixed_product_family_collected_best_rate",metric_label:"예금 + 적금 수집 데이터 기준 최고금리",default_mode:"savings_bank",candidate_sectors:keys,published_sectors:keys.filter(key=>sectors[key]?.selectable),base_rate_fallback:true,canonical_max_rate_unchanged:true,strategy_rate_policy:"deposit_stable_plus_current_savings_snapshot",sectors};
  };
  const savingsKey=()=>[...savingsTypes].sort().join(",");
  const hasSavingsFamily=()=>productMode!=="deposit";
  activeProductTypes=function(){if(productMode==="deposit")return new Set(["term_deposit"]);if(productMode==="savings")return new Set(savingsTypes);return new Set(["term_deposit",...savingsTypes])};
  productScopeKey=function(){if(productMode==="deposit")return"deposit";if(productMode==="savings")return`savings:${savingsKey()}`;return`combined:${savingsKey()}`};
  productScopeLabel=function(){
    if(productMode==="deposit")return"예금";
    if(productMode==="savings"){if(savingsTypes.size===2)return"적금 전체";if(!savingsTypes.size)return"적금 · 선택 없음";return savingsTypes.has("installment_savings")?"적금 · 정기적금":"적금 · 자유적금"}
    if(savingsTypes.size===2)return"예금 + 적금";
    if(!savingsTypes.size)return"예금 + 적금(유형 미선택)";
    return savingsTypes.has("installment_savings")?"예금 + 정기적금":"예금 + 자유적금";
  };
  historyScopeKey=function(){
    if(productMode==="combined")return null;
    if(productMode==="deposit")return"deposit";
    if(savingsTypes.size===2)return"savings_all";
    if(!savingsTypes.size)return null;
    return savingsTypes.has("installment_savings")?"savings_installment":"savings_flexible";
  };
  const priorRenderProductScopeControls=renderProductScopeControls;
  renderProductScopeControls=function(){
    priorRenderProductScopeControls();
    document.querySelectorAll("[data-product-family-toggle]").forEach(input=>{
      const on=input.dataset.productFamilyToggle==="deposit"?productMode!=="savings":productMode!=="deposit";
      input.checked=on;input.closest("label")?.classList.toggle("active",on);
    });
    const detail=$("strategy-savings-types");if(detail)detail.hidden=!hasSavingsFamily();
    document.querySelectorAll("[data-savings-type]").forEach(input=>input.closest("label")?.classList.toggle("active",input.checked));
  };
  setProductMode=function(mode){
    if(!PRODUCT_FAMILY_MODES.has(mode))return;
    productMode=mode;
    if(mode==="deposit"){allRows=depositRows;strategyUniverse=depositUniverse}
    else if(mode==="savings"){allRows=savingsRows;strategyUniverse=savingsUniverse}
    else{allRows=[...depositRows,...savingsRows];strategyUniverse=buildCombinedUniverse()}
    mapSector="savings_bank";renderProductScopeControls();rerenderForScope();
  };
  rankingBasisText=function(){const sectors=activeSectors(),representative=productMode==="deposit"?"stable product":productMode==="savings"?"현재 canonical 상품":"예금 stable + 적금 canonical";if(!sectors.length)return`${scopeTerm}개월 · ${productScopeLabel()} · 현재 선택된 최고금리 비교 업권 없음`;return`${scopeTerm}개월 · ${productScopeLabel()} · ${representative} 대표 · ${sectors.map(key=>`${sectorLabel(key)} ${sectorRateScope(key)}`).join(" · ")}`};
  const decorateTop5ProductFamilies=()=>{
    const rows=[...document.querySelectorAll("#top5 tr")];
    products12.slice(0,5).forEach((product,index)=>{
      const host=rows[index]?.querySelector("td:nth-child(2)"),name=host?.querySelector(".product");
      if(!host||!name)return;
      let badge=host.querySelector(".product-family-badge");
      if(!badge){badge=document.createElement("span");name.insertAdjacentElement("beforebegin",badge)}
      const family=product.productFamily==="savings"?"savings":"deposit";
      badge.className=`product-family-badge ${family}`;
      badge.textContent=family==="savings"?"적금":"예금";
      badge.setAttribute("aria-label",`상품군 ${badge.textContent}`);
    });
  };
  const emphasizeInsightMetrics=()=>{
    document.querySelectorAll("#insights .insight b").forEach(title=>{
      if(title.querySelector(".insight-metric"))return;
      const text=String(title.textContent||"").trim(),match=text.match(/([+-]?\d+(?:\.\d+)?(?:bp|%p|%))/);
      if(!match)return;
      const metric=document.createElement("strong"),copy=document.createElement("span"),label=`${text.slice(0,match.index)} ${text.slice((match.index||0)+match[0].length)}`.trim().replace(/\s+/g," ");
      metric.className="insight-metric";metric.textContent=match[1];
      copy.className="insight-title-copy";copy.textContent=label;
      title.textContent="";title.appendChild(metric);if(label)title.appendChild(copy);
    });
  };
  const priorRenderMarket=renderMarket;
  renderMarket=function(){priorRenderMarket();const representative=productMode==="deposit"?"stable product":productMode==="savings"?"현재 canonical 상품":"예금 stable + 적금 canonical";const copy=$("top5-copy");if(copy)copy.textContent=`${scopeTerm}개월 ${productScopeLabel()} · ${modeLabel()} · ${representative} 대표 수집기준 최고금리`;decorateTop5ProductFamilies()};
  const priorRenderInsightsEnhanced=renderInsightsEnhanced;
  renderInsightsEnhanced=function(){priorRenderInsightsEnhanced();emphasizeInsightMetrics()};
  const priorApplyModeVisibility=applyModeVisibility;
  applyModeVisibility=function(){
    priorApplyModeVisibility();
    if(productMode!=="combined")return;
    const toggle=$("prediction-toggle"),panel=$("prediction-panel"),summary=$("prediction-summary"),warning=$("sim-scope-warning");
    if(toggle)toggle.hidden=true;if(panel)panel.hidden=true;
    if(summary)summary.textContent="예금+적금 시장 비교 · 수신금액 예측은 예금 단독 전용";
    if(warning){warning.hidden=false;warning.textContent="예금+적금 통합 비교에서는 현재 KPI·순위·지도·우대조건을 함께 계산합니다. 상품군별 이력 계약이 달라 통합 이력은 재가공하지 않으며, 신규수신·만기·재예치율 기반 수신금액 예측도 예금 단독에서만 실행합니다."}
  };
  const familyModeFromControls=()=>{const deposit=document.querySelector('[data-product-family-toggle="deposit"]')?.checked,savings=document.querySelector('[data-product-family-toggle="savings"]')?.checked;return deposit&&savings?"combined":savings?"savings":"deposit"};
  const syncFamilyUrl=()=>{const p=new URLSearchParams(location.search);p.set("family",productMode);p.set("term",String(scopeTerm));if(productMode!=="deposit")p.set("savings",savingsTypes.size?[...savingsTypes].sort().join(","):"none");else p.delete("savings");const q=p.toString();history.replaceState(null,"",q?`${location.pathname}?${q}${location.hash}`:`${location.pathname}${location.hash}`)};
  document.querySelectorAll("[data-product-family-toggle]").forEach(input=>input.addEventListener("change",()=>{
    const checked=[...document.querySelectorAll("[data-product-family-toggle]:checked")];
    if(!checked.length){input.checked=true;renderProductScopeControls();return}
    setProductMode(familyModeFromControls());syncFamilyUrl();
  }));
  document.addEventListener("change",e=>{if(e.target.closest?.('[data-savings-type]'))queueMicrotask(syncFamilyUrl)});
  document.addEventListener("click",e=>{if(e.target.closest?.('[data-scope-term],#term-segment button'))queueMicrotask(syncFamilyUrl)});
  renderProductScopeControls();
})();
</script>
'''.strip("\n")


def _replace_required(html: str, old: str, new: str, label: str) -> str:
    if old not in html:
        raise DashboardBuildError(f"Strategy 상품군/가독성 보정 anchor를 찾지 못했다: {label}")
    return html.replace(old, new, 1)


def inject_dashboard_product_scope_readability(html: str) -> str:
    """Strategy 산출물에 복수 상품군 선택과 가독성 보정을 추가한다."""
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        return html
    if 'id="market-scope"' not in html or 'data-product-mode="deposit"' not in html:
        return html

    rendered = _replace_required(
        html,
        '<div class="product-family-tabs" role="group">',
        '<div class="strategy-family-checks" role="group" aria-label="상품군 복수 선택"><label class="active"><input type="checkbox" data-product-family-toggle="deposit" checked>예금</label><label><input type="checkbox" data-product-family-toggle="savings">적금</label></div><div class="product-family-tabs" role="group" aria-hidden="true">',
        "product family checkbox controls",
    )
    rendered = _replace_required(
        rendered,
        'family==="deposit"||family==="savings"',
        'family==="deposit"||family==="savings"||family==="combined"',
        "shared URL combined family",
    )
    rendered = _replace_required(
        rendered,
        'if(productMode==="savings")p.set("savings",savingsTypes.size?[...savingsTypes].sort().join(","):"none");',
        'if(productMode!=="deposit")p.set("savings",savingsTypes.size?[...savingsTypes].sort().join(","):"none");',
        "shared URL combined subtype preservation",
    )
    rendered = _replace_required(
        rendered,
        'if(q.hasFamily){productMode=q.family;savingsTypes=new Set(q.family==="savings"?q.savings:["installment_savings","flexible_savings"]);allRows=q.family==="savings"?savingsRows:depositRows;strategyUniverse=q.family==="savings"?savingsUniverse:depositUniverse;mapSector="savings_bank"}',
        'if(q.hasFamily){savingsTypes=new Set(q.family==="deposit"?["installment_savings","flexible_savings"]:q.savings);setProductMode(q.family)}',
        "shared URL restore through product mode contract",
    )
    rendered = _replace_required(
        rendered,
        'installmentMode=productMode==="savings"',
        'installmentMode=productMode!=="deposit"',
        "deposit-only prediction visibility",
    )
    rendered = _replace_required(
        rendered,
        'if(productMode==="savings"){clearInflowPrediction(',
        'if(productMode!=="deposit"){clearInflowPrediction(',
        "deposit-only prediction execution",
    )
    rendered = _replace_required(
        rendered,
        'if(!p){p={sector:r.sector,institution:r.institution',
        'if(!p){p={sector:r.sector,productFamily:r.type==="term_deposit"?"deposit":"savings",institution:r.institution',
        "TOP5 product family provenance",
    )
    rendered = rendered.replace("</head>", READABILITY_STYLE + "\n</head>", 1)
    return rendered.replace("</body>", READABILITY_SCRIPT + "\n</body>", 1)
