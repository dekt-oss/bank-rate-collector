# ruff: noqa: E501
"""Search/Strategy 상품군 + 전역 가입기간 presentation 계약."""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

PRODUCT_SCOPE_STYLE_MARKER = 'id="dashboard-product-scope-style"'


def _replace_required(html: str, old: str, new: str, label: str, *, count: int = 1) -> str:
    if old not in html:
        raise DashboardBuildError(f"상품군/기간 UI 보정 anchor를 찾지 못했다: {label}")
    return html.replace(old, new, count)


PRODUCT_SCOPE_STYLE = r"""
<style id="dashboard-product-scope-style">
.product-family-tabs,.global-term-tabs{display:flex;gap:5px;flex-wrap:wrap}
.product-family-tabs button,.global-term-tabs button{appearance:none;border:1px solid var(--line);border-radius:9px;background:var(--surface,#0a1915);color:var(--ink-2,#8fa099);padding:7px 13px;font:760 12px var(--sans);cursor:pointer}
.product-family-tabs button[aria-pressed="true"],.product-family-tabs button.active,.global-term-tabs button[aria-pressed="true"],.global-term-tabs button.active{border-color:var(--accent,#80c8a6);background:var(--accent-bg,rgba(73,125,97,.22));color:var(--accent-ink,#d8eee2)}
.product-family-group .product-family-tabs{margin-bottom:8px}.product-savings-detail{margin-top:8px;padding:8px 10px;border:1px solid var(--line);border-radius:9px;background:var(--surface-2,rgba(4,14,11,.24))}.product-savings-detail .nested-head{margin-bottom:6px}.product-savings-detail .checks{display:flex;gap:10px;flex-wrap:wrap}.product-savings-detail label{display:inline-flex;align-items:center;gap:6px}.product-savings-detail input{accent-color:var(--accent,#80c8a6)}
.product-term-row{margin-top:10px;padding-top:9px;border-top:1px solid var(--line-soft,var(--line))}.product-term-row .lbl{margin-bottom:6px}
.strategy-product-scope{grid-column:1/-1;display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding-bottom:3px}.strategy-product-scope>span{color:#8fa79b;font-size:9px;font-weight:760}.strategy-product-scope .product-family-tabs button,.strategy-product-scope .global-term-tabs button{background:#0a1915;color:#7d8d85;font-size:9.5px;padding:8px 12px}.strategy-product-scope .product-family-tabs button.active,.strategy-product-scope .global-term-tabs button.active{color:#d8eee2;border-color:rgba(128,200,166,.42);background:rgba(73,125,97,.22)}.strategy-savings-types{display:flex;gap:7px;flex-wrap:wrap}.strategy-savings-types[hidden]{display:none!important}.strategy-savings-types label{display:flex;align-items:center;gap:5px;padding:7px 9px;border:1px solid var(--line);border-radius:9px;background:rgba(4,14,11,.24);color:#9cada4;font-size:9px}.strategy-savings-types input{accent-color:var(--green)}.strategy-term-scope{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.strategy-term-scope>span{color:#8fa79b;font-size:9px;font-weight:760}
@media(max-width:760px){.strategy-product-scope{align-items:flex-start;flex-direction:column}.strategy-term-scope{align-items:flex-start;flex-direction:column}}
@media(max-width:480px){.product-family-tabs,.global-term-tabs{width:100%}.product-family-tabs button,.global-term-tabs button{flex:1}}
</style>
"""

SEARCH_PRODUCT_RUNTIME = r'''
  const PRODUCT_DEPOSIT_TYPE = "term_deposit";
  const PRODUCT_SAVINGS_TYPES = ["installment_savings", "flexible_savings"];
  const GLOBAL_TERMS = [6, 12, 24, 36];
  let emptySavingsSelected = false;
  const activeProductFamily = () => state.picked.type.has(PRODUCT_DEPOSIT_TYPE)
    ? "deposit"
    : (PRODUCT_SAVINGS_TYPES.some((type) => state.picked.type.has(type)) || emptySavingsSelected)
      ? "savings" : "deposit";
  const setProductFamily = (family) => {
    state.picked.type.clear();
    emptySavingsSelected = false;
    if (family === "savings") PRODUCT_SAVINGS_TYPES.forEach((type) => state.picked.type.add(type));
    else state.picked.type.add(PRODUCT_DEPOSIT_TYPE);
  };
  const noteSavingsSelection = () => {
    if (state.picked.type.has(PRODUCT_DEPOSIT_TYPE)) { emptySavingsSelected = false; return; }
    emptySavingsSelected = !PRODUCT_SAVINGS_TYPES.some((type) => state.picked.type.has(type));
  };
  const productScopeLabel = () => {
    if (activeProductFamily() === "deposit") return "예금";
    const picked = PRODUCT_SAVINGS_TYPES.filter((type) => state.picked.type.has(type));
    if (picked.length === 2) return "적금 전체";
    if (picked[0] === "installment_savings") return "적금 · 정기적금";
    if (picked[0] === "flexible_savings") return "적금 · 자유적금";
    return "적금 · 선택 없음";
  };
  const activeGlobalTerm = () => {
    const lo = Number(state.tmin), hi = Number(state.tmax);
    return GLOBAL_TERMS.includes(lo) && lo === hi ? lo : 12;
  };
  const setGlobalTerm = (term) => {
    const value = Number(term);
    if (!GLOBAL_TERMS.includes(value)) return;
    state.tmin = value; state.tmax = value;
    state.picked.term.clear();
    groupValues(GROUPS.find((g) => g.key === "term"))
      .forEach((bucket) => state.picked.term.add(bucket));
  };
'''.strip("\n")

SEARCH_PRODUCT_GROUP = r'''
  const productTypeGroupHtml = () => {
    const family = activeProductFamily();
    const savings = PRODUCT_SAVINGS_TYPES.filter((type) => state.picked.type.has(type));
    const detail = family === "savings" ? `<div class="product-savings-detail"><div class="nested-head"><span>적금 세부선택 <span class="selected">${num(savings.length)}/2 선택</span></span></div><div class="checks"><label><input type="checkbox" data-group="type" value="installment_savings" ${state.picked.type.has("installment_savings") ? "checked" : ""}>정기적금</label><label><input type="checkbox" data-group="type" value="flexible_savings" ${state.picked.type.has("flexible_savings") ? "checked" : ""}>자유적금</label></div></div>` : "";
    const term = activeGlobalTerm();
    const terms = GLOBAL_TERMS.map((value) => `<button type="button" data-global-term="${value}" aria-pressed="${term === value}">${value}개월</button>`).join("");
    return `<div class="group product-family-group"><div class="lbl">상품군</div><div class="product-family-tabs" role="group" aria-label="상품군"><button type="button" data-product-family="deposit" aria-pressed="${family === "deposit"}">예금</button><button type="button" data-product-family="savings" aria-pressed="${family === "savings"}">적금</button></div>${detail}<div class="product-term-row"><div class="lbl">가입기간</div><div class="global-term-tabs" role="group" aria-label="가입기간">${terms}</div></div></div>`;
  };
'''.strip("\n")

STRATEGY_PRODUCT_RUNTIME = r'''
const PRODUCT_SAVINGS_TYPES=new Set(["installment_savings","flexible_savings"]);
const GLOBAL_TERMS=[6,12,24,36];
let depositRows=[],savingsRows=[],productMode="deposit",depositUniverse=null,savingsUniverse=null,scopeTerm=12;
let savingsTypes=new Set(["installment_savings","flexible_savings"]);
function activeProductTypes(){return productMode==="savings"?savingsTypes:new Set(["term_deposit"])}
function productScopeKey(){return productMode==="savings"?`savings:${[...savingsTypes].sort().join(",")}`:"deposit"}
function productScopeLabel(){if(productMode!=="savings")return"예금";if(savingsTypes.size===2)return"적금 전체";if(!savingsTypes.size)return"적금 · 선택 없음";return savingsTypes.has("installment_savings")?"적금 · 정기적금":"적금 · 자유적금"}
function historyScopeKey(){if(productMode!=="savings")return"deposit";if(savingsTypes.size===2)return"savings_all";if(!savingsTypes.size)return null;return savingsTypes.has("installment_savings")?"savings_installment":"savings_flexible"}
function emptyMarketChanges(){return{window_days:30,count:0,up_count:0,down_count:0,affected_variant_count:0,latest_changed_at:null,items:[]}}
function emptyRateTrend(){return{window_days:63,points:[],scope:{our_institution:OUR_INSTITUTION}}}
function activeHistory(){const key=historyScopeKey();return key?data.strategy?.product_history?.scopes?.[key]?.[String(scopeTerm)]||{}:{}}
function activeMarketChanges(){return activeHistory().market_changes||emptyMarketChanges()}
function activeRateTrend(){return activeHistory().rate_trend||emptyRateTrend()}
function syntheticSavingsProductId(r){return["current",r.sector,r.institution,r.product,r.type].map(x=>String(x||"")).join("\0")}
function prepareSavingsRows(packed){return expand(packed).filter(r=>PRODUCT_SAVINGS_TYPES.has(r.type)&&GLOBAL_TERMS.includes(r.term)).map(r=>{const sourceMax=Number.isFinite(r.max),base=Number.isFinite(r.base);return{...r,productId:syntheticSavingsProductId(r),max:sourceMax?r.max:(base?r.base:null),rateBasis:sourceMax?"source_max_rate":(base?"collected_base_rate":null)}}).filter(r=>Number.isFinite(r.max))}
function buildSavingsUniverse(rows){const sectors={};for(const key of ["savings_bank","cu","kfcc","nh_local"]){const sectorRows=rows.filter(r=>r.sector===key),terms={};for(const term of GLOBAL_TERMS){const termRows=sectorRows.filter(r=>r.term===term);terms[String(term)]={rows:termRows.length,max_rate_rows:termRows.length,strategy_rate_rows:termRows.length,coverage_ratio:termRows.length?1:null,selectable:termRows.length>0}}const vals=field=>[...new Set(sectorRows.map(r=>r[field]).filter(Boolean))].sort();sectors[key]={label:({savings_bank:"저축은행",cu:"신협",kfcc:"새마을금고",nh_local:"농·축협"})[key],state:sectorRows.length?"supported":"no_rows",max_rate_capability:true,strategy_rate_capability:true,selectable:sectorRows.length>0,rows:sectorRows.length,max_rate_rows:sectorRows.length,strategy_rate_rows:sectorRows.length,coverage_ratio:sectorRows.length?1:null,latest_source_effective_at:sectorRows.map(r=>r.sourceEffectiveAt).filter(Boolean).sort().at(-1)||null,geo_basis:vals("geoBasis"),rate_scope:vals("rateScope"),availability_scope:vals("availabilityScope"),evidence:"canonical_current_max_then_collected_base",rate_basis_counts:{},blocked_reason:null,terms}}return{metric_basis:"collected_best_rate",metric_label:"수집 데이터 기준 최고금리",default_mode:"savings_bank",candidate_sectors:Object.keys(sectors),published_sectors:Object.keys(sectors),base_rate_fallback:true,canonical_max_rate_unchanged:true,strategy_rate_policy:"source_max_then_collected_base_for_current_savings_snapshot",sectors}}
function renderProductScopeControls(){document.querySelectorAll("[data-product-mode]").forEach(btn=>{const on=btn.dataset.productMode===productMode;btn.classList.toggle("active",on);btn.setAttribute("aria-pressed",String(on))});const detail=$("strategy-savings-types");if(detail)detail.hidden=productMode!=="savings";document.querySelectorAll("[data-savings-type]").forEach(input=>{input.checked=savingsTypes.has(input.dataset.savingsType)});document.querySelectorAll("[data-scope-term]").forEach(btn=>{const on=Number(btn.dataset.scopeTerm)===scopeTerm;btn.classList.toggle("active",on);btn.setAttribute("aria-pressed",String(on))});document.querySelectorAll("#term-segment button").forEach(btn=>btn.classList.toggle("active",Number(btn.dataset.term)===scopeTerm));const pill=$("product-scope-pill");if(pill)pill.textContent=`${productScopeLabel()} · ${scopeTerm}개월`}
function setProductMode(mode){if(!["deposit","savings"].includes(mode)||mode===productMode)return;productMode=mode;allRows=mode==="savings"?savingsRows:depositRows;strategyUniverse=mode==="savings"?savingsUniverse:depositUniverse;mapSector="savings_bank";renderProductScopeControls();rerenderForScope()}
function setScopeTerm(term){const value=Number(term);if(!GLOBAL_TERMS.includes(value)||value===scopeTerm)return;scopeTerm=value;simTerm=value;renderProductScopeControls();rerenderForScope()}
function renderProductHistoryScope(){renderChangesEnhanced();renderTrendEnhanced()}
'''.strip("\n")


def _inject_search(html: str) -> str:
    rendered = html
    rendered = _replace_required(rendered, 'const TYPE_KO = { term_deposit: "예금", installment_savings: "적금",\n                    flexible_savings: "자유적립", demand_deposit: "입출금", other: "기타" };', 'const TYPE_KO = { term_deposit: "예금", installment_savings: "정기적금",\n                    flexible_savings: "자유적금", demand_deposit: "입출금", other: "기타" };', "search type labels")
    rendered = _replace_required(rendered, '{ key: "type", label: "상품유형", ko: TYPE_KO },', '{ key: "type", label: "상품군", ko: TYPE_KO },', "search type group label")
    rendered = _replace_required(rendered, '  const busanOn = () => state.picked.region.has(BUSAN_SIDO);', '  const busanOn = () => state.picked.region.has(BUSAN_SIDO);\n\n' + SEARCH_PRODUCT_RUNTIME, "search runtime")
    old_default = '''  const applyDefaultGroup = (g) => {\n    state.picked[g.key].clear();\n    if (g.key === "region") {\n      DEFAULT_REGIONS.filter((v) => groupValues(g).includes(v))\n        .forEach((v) => state.picked.region.add(v));\n      if (busanOn()) selectAllBusanDistricts();\n    } else selectAllGroup(g.key);\n  };'''
    new_default = '''  const applyDefaultGroup = (g) => {\n    state.picked[g.key].clear();\n    if (g.key === "region") {\n      DEFAULT_REGIONS.filter((v) => groupValues(g).includes(v))\n        .forEach((v) => state.picked.region.add(v));\n      if (busanOn()) selectAllBusanDistricts();\n    } else if (g.key === "type") {\n      state.picked.type.add(PRODUCT_DEPOSIT_TYPE);\n    } else selectAllGroup(g.key);\n  };'''
    rendered = _replace_required(rendered, old_default, new_default, "search defaults")
    rendered = _replace_required(rendered, 'Object.assign(state, { q: "", rmin: null, tmin: null, tmax: null,', 'Object.assign(state, { q: "", rmin: null, tmin: 12, tmax: 12,', "search default term")
    rendered = _replace_required(rendered, '  const shortGroupSummary = (key) => {\n    const g = GROUPS.find((x) => x.key === key);', '  const shortGroupSummary = (key) => {\n    if (key === "type") return `상품군 ${productScopeLabel()}`;\n    if (key === "term") return `가입기간 ${activeGlobalTerm()}개월`;\n    const g = GROUPS.find((x) => x.key === key);', "search summaries")
    rendered = _replace_required(rendered, '  const groupHtml = (groups) => groups.map((g) => {\n      let boxes;', SEARCH_PRODUCT_GROUP + '\n\n  const groupHtml = (groups) => groups.map((g) => {\n      if (g.key === "type") return productTypeGroupHtml();\n      if (g.key === "term") return "";\n      let boxes;', "search scope ui")
    rendered = _replace_required(rendered, '  const basisLabel = () => (noTermOrTypePicked() ? "12개월 정기예금" : "");', '  const basisLabel = () => `${activeGlobalTerm()}개월 ${productScopeLabel()}`;', "search basis")
    rendered = rendered.replace('type: ["installment_savings"]', 'type: ["installment_savings", "flexible_savings"]')
    rendered = _replace_required(rendered, '    if (box.checked) set.add(box.value); else set.delete(box.value);\n    // main group은 마지막 하나까지 실제로 끌 수 있다.', '    if (box.checked) set.add(box.value); else set.delete(box.value);\n    if (key === "type") { noteSavingsSelection(); renderGroups(); }\n    // main group은 마지막 하나까지 실제로 끌 수 있다.', "search subtype change")
    rendered = _replace_required(rendered, '  $("conditions").addEventListener("click", (e) => {\n    const detail = e.target.closest("[data-detail]");', '  $("conditions").addEventListener("click", (e) => {\n    const family = e.target.closest("[data-product-family]");\n    if (family) { setProductFamily(family.dataset.productFamily); renderGroups(); renderPresets(); redraw(); return; }\n    const term = e.target.closest("[data-global-term]");\n    if (term) { setGlobalTerm(term.dataset.globalTerm); renderGroups(); redraw(); return; }\n    const detail = e.target.closest("[data-detail]");', "search scope events")
    return rendered


def _inject_strategy(html: str) -> str:
    rendered = html
    rendered = _replace_required(rendered, '<span class="pill">정기예금</span>', '<span class="pill" id="product-scope-pill">예금 · 12개월</span>', "strategy pill")
    controls = '<section class="card market-scope" id="market-scope" aria-label="전략 비교 업권">\n  <div class="strategy-product-scope" aria-label="상품군과 가입기간 선택"><span>상품군</span><div class="product-family-tabs" role="group"><button class="active" type="button" data-product-mode="deposit" aria-pressed="true">예금</button><button type="button" data-product-mode="savings" aria-pressed="false">적금</button></div><div class="strategy-savings-types" id="strategy-savings-types" hidden><label><input type="checkbox" data-savings-type="installment_savings" checked>정기적금</label><label><input type="checkbox" data-savings-type="flexible_savings" checked>자유적금</label></div><div class="strategy-term-scope"><span>가입기간</span><div class="global-term-tabs" role="group" aria-label="가입기간"><button type="button" data-scope-term="6" aria-pressed="false">6개월</button><button class="active" type="button" data-scope-term="12" aria-pressed="true">12개월</button><button type="button" data-scope-term="24" aria-pressed="false">24개월</button><button type="button" data-scope-term="36" aria-pressed="false">36개월</button></div></div></div>'
    rendered = _replace_required(rendered, '<section class="card market-scope" id="market-scope" aria-label="전략 비교 업권">', controls, "strategy controls")
    rendered = _replace_required(rendered, 'const $=id=>document.getElementById(id),fmt=new Intl.NumberFormat("ko-KR");', 'const $=id=>document.getElementById(id),fmt=new Intl.NumberFormat("ko-KR");\n' + STRATEGY_PRODUCT_RUNTIME, "strategy runtime")
    rendered = _replace_required(rendered, 'function rankingBasisText(){const sectors=activeSectors();if(!sectors.length)return"12개월 · 현재 선택된 최고금리 비교 업권 없음";return`12개월 · sector + stable product 대표 · ${sectors.map(key=>`${sectorLabel(key)} ${sectorRateScope(key)}`).join(" · ")}`}', 'function rankingBasisText(){const sectors=activeSectors();if(!sectors.length)return`${scopeTerm}개월 · ${productScopeLabel()} · 현재 선택된 최고금리 비교 업권 없음`;return`${scopeTerm}개월 · ${productScopeLabel()} · ${productMode==="deposit"?"stable product":"현재 canonical 상품"} 대표 · ${sectors.map(key=>`${sectorLabel(key)} ${sectorRateScope(key)}`).join(" · ")}`}', "strategy ranking basis")
    rendered = _replace_required(rendered, 'function renderScopeControls(){\n  document.querySelectorAll("[data-market-mode]").forEach(btn=>btn.classList.toggle("active",btn.dataset.marketMode===marketMode));', 'function renderScopeControls(){\n  renderProductScopeControls();\n  document.querySelectorAll("[data-market-mode]").forEach(btn=>btn.classList.toggle("active",btn.dataset.marketMode===marketMode));', "strategy scope render")
    rendered = _replace_required(rendered, '<span><b>12M 수집기준 최고</b>${esc(termCoverage(meta,12))}</span>', '<span><b>${scopeTerm}M 수집기준 최고</b>${esc(termCoverage(meta,scopeTerm))}</span>', "strategy evidence term")
    rendered = _replace_required(rendered, 'function rerenderForScope(){aggregateCache.clear();products12=[];[6,12,24,36].forEach(aggregateProducts);renderMarket();renderPrefs();renderTermStrip();ensureMapSector();renderInsightsEnhanced();applyModeVisibility();if(marketMode!=="mutual_finance")updateSim()}', 'function rerenderForScope(){aggregateCache.clear();products12=[];GLOBAL_TERMS.forEach(aggregateProducts);renderMarket();renderPrefs();renderTermStrip();ensureMapSector();renderProductHistoryScope();renderInsightsEnhanced();applyModeVisibility();if(marketMode!=="mutual_finance")updateSim()}', "strategy rerender")
    rendered = _replace_required(rendered, 'function setupMarketScope(){document.querySelectorAll("[data-market-mode]").forEach(btn=>btn.addEventListener("click",()=>setMarketMode(btn.dataset.marketMode)));document.querySelectorAll("[data-sector]").forEach(input=>input.addEventListener("change",()=>{renderScopeControls();rerenderForScope()}));renderScopeControls()}', 'function setupMarketScope(){document.querySelectorAll("[data-product-mode]").forEach(btn=>btn.addEventListener("click",()=>setProductMode(btn.dataset.productMode)));document.querySelectorAll("[data-savings-type]").forEach(input=>input.addEventListener("change",()=>{if(input.checked)savingsTypes.add(input.dataset.savingsType);else savingsTypes.delete(input.dataset.savingsType);renderProductScopeControls();rerenderForScope()}));document.querySelectorAll("[data-scope-term]").forEach(btn=>btn.addEventListener("click",()=>setScopeTerm(btn.dataset.scopeTerm)));document.querySelectorAll("[data-market-mode]").forEach(btn=>btn.addEventListener("click",()=>setMarketMode(btn.dataset.marketMode)));document.querySelectorAll("[data-sector]").forEach(input=>input.addEventListener("change",()=>{renderScopeControls();rerenderForScope()}));renderScopeControls()}', "strategy scope events")
    rendered = _replace_required(rendered, '  const sectors=activeSectors(),cacheKey=`${marketMode}:${sectors.join(",")}:${term}`;', '  const sectors=activeSectors(),cacheKey=`${productScopeKey()}:${marketMode}:${sectors.join(",")}:${term}`;', "strategy cache")
    rendered = _replace_required(rendered, '    if(!allowed.has(r.sector)||r.type!=="term_deposit"||r.term!==term||!Number.isFinite(r.max)||!r.productId)continue;', '    if(!allowed.has(r.sector)||!activeProductTypes().has(r.type)||r.term!==term||!Number.isFinite(r.max)||!r.productId)continue;', "strategy product filter")
    rendered = _replace_required(rendered, 'if(r.sector!==sector||r.type!=="term_deposit"||r.term!==term||!Number.isFinite(r.max)||!r.productId||r.geoBasis!==expectedBasis)continue;', 'if(r.sector!==sector||!activeProductTypes().has(r.type)||r.term!==term||!Number.isFinite(r.max)||!r.productId||r.geoBasis!==expectedBasis)continue;', "strategy geo filter")
    rendered = _replace_required(rendered, 'products12=aggregateProducts(12);$("ranking-basis").textContent=rankingBasisText();$("top5-copy").textContent=`12개월 정기예금 · ${modeLabel()} · sector + stable product 대표 수집기준 최고금리`;$("footer-calc").innerHTML=`<b>계산 기준</b> · ${esc(modeLabel())} 수집 데이터 기준 최고금리 · 원천 max 우선 · 미기재 시 수집 기본금리 · 명시 가산만 합산 · 동일 금리 공동순위`;', 'products12=aggregateProducts(scopeTerm);$("ranking-basis").textContent=rankingBasisText();$("top5-copy").textContent=`${scopeTerm}개월 ${productScopeLabel()} · ${modeLabel()} · ${productMode==="deposit"?"stable product":"현재 canonical 상품"} 대표 수집기준 최고금리`;$("footer-calc").innerHTML=`<b>계산 기준</b> · ${scopeTerm}개월 ${esc(productScopeLabel())} · ${esc(modeLabel())} 수집 데이터 기준 최고금리 · 원천 max 우선 · 미기재 시 수집 기본금리 · 동일 금리 공동순위`;', "strategy market scope")
    rendered = _replace_required(rendered, 'function renderPrefs(){const p=prefData(12);', 'function renderPrefs(){const p=prefData(scopeTerm);', "strategy prefs term")
    rendered = _replace_required(rendered, 'return`<div class="termcard${t===12?" active":""}">', 'return`<div class="termcard${t===scopeTerm?" active":""}">', "strategy term strip")
    rendered = rendered.replace('geoProducts(sector,12)', 'geoProducts(sector,scopeTerm)')
    rendered = rendered.replace('geoProducts("savings_bank",12)', 'geoProducts("savings_bank",scopeTerm)')
    rendered = rendered.replace('$("map-chip").textContent=`12개월 · ${fmt.format(a.length)}지역`;', '$("map-chip").textContent=`${scopeTerm}개월 · ${fmt.format(a.length)}지역`;')
    rendered = _replace_required(rendered, '  const tr=data.strategy?.rate_trend||{};\n  const pts=(tr.points||[]).filter', '  const tr=activeRateTrend();\n  const pts=(tr.points||[]).filter', "strategy active trend")
    rendered = _replace_required(rendered, '  const c=data.strategy?.market_changes||{},items=c.items||[],flow=marketDirection(c);', '  const c=activeMarketChanges(),items=c.items||[],flow=marketDirection(c);', "strategy active changes")
    rendered = _replace_required(rendered, '  const c=data.strategy?.market_changes||{},flow=marketDirection(c),p=prefData(12);', '  const c=activeMarketChanges(),flow=marketDirection(c),p=prefData(scopeTerm);', "strategy insight history")
    rendered = _replace_required(rendered, '  const geoSector=ensureMapSector(),regional=geoSector?regionAverages(geoProducts(geoSector,12)):[],strongest=regional[0],weakest=regional.at(-1),geoBasis=geoSector?sectorGeoBasis(geoSector):"지역 기준 미확인";', '  const geoSector=ensureMapSector(),regional=geoSector?regionAverages(geoProducts(geoSector,scopeTerm)):[],strongest=regional[0],weakest=regional.at(-1),geoBasis=geoSector?sectorGeoBasis(geoSector):"지역 기준 미확인";', "strategy insight geo term")
    rendered = _replace_required(rendered, '  const pts=(data.strategy?.rate_trend?.points||[])', '  const pts=(activeRateTrend().points||[])', "strategy insight trend")
    rendered = _replace_required(rendered, '  const flow=marketDirection(data.strategy?.market_changes||{});', '  const flow=marketDirection(activeMarketChanges());', "strategy planning history")
    rendered = _replace_required(rendered, '$("planning-basis").innerHTML=`<span>선택기간</span><b>${simTerm}개월</b><span>· 상단 KPI는 12개월 고정</span>`;', '$("planning-basis").innerHTML=`<span>전역 가입기간</span><b>${scopeTerm}개월</b><span>· KPI·TOP·지도·추이·시뮬레이터 연동</span>`;', "strategy planning term")
    rendered = _replace_required(rendered, 'function applyModeVisibility(){const mutualOnly=marketMode==="mutual_finance",savingsOnly=marketMode==="savings_bank";$("market-flow").hidden=mutualOnly;$("map-card").hidden=false;$("trend-delta").hidden=!savingsOnly;$("sim-scope-warning").hidden=!mutualOnly;$("sim-form").hidden=mutualOnly;ensureMapSector();renderMapLayerTabs();if(mapMode==="busan"&&mapSector!=="savings_bank")mapMode="korea";renderKoreaMap()}', 'function applyModeVisibility(){const mutualOnly=marketMode==="mutual_finance",savingsOnly=marketMode==="savings_bank",installmentMode=productMode==="savings";$("market-flow").hidden=mutualOnly;$("map-card").hidden=false;$("trend-delta").hidden=!savingsOnly;$("sim-form").hidden=mutualOnly;$("prediction-toggle").hidden=installmentMode;$("prediction-panel").hidden=true;$("prediction-summary").textContent=installmentMode?"적금 시장 KPI·TOP·추이는 선택 조건에 연동 · 수신금액 예측은 예금 전용":"내부 실적 미보정 · 신규수신·만기·재예치율 3개 입력으로 총수신 범위 계산";$("sim-scope-warning").hidden=!(mutualOnly||installmentMode);$("sim-scope-warning").textContent=mutualOnly?"상호금융 단독 모드에서는 고려저축은행 기준 신상품·수신 시뮬레이터를 잠급니다. 통합 또는 저축은행 모드에서 사용하세요.":"적금은 실제 관측 이력과 시장 순위까지 비교합니다. 신규수신·만기·재예치율 기반 수신금액 예측은 정기예금 전용이라 실행하지 않습니다.";ensureMapSector();renderMapLayerTabs();if(mapMode==="busan"&&mapSector!=="savings_bank")mapMode="korea";renderKoreaMap()}', "strategy savings prediction guard")
    rendered = _replace_required(rendered, '  const baseline=predictionNumber("baseline-new"),maturity=predictionNumber("maturity-amount"),rollover=predictionNumber("rollover-rate",{min:0,max:100});', '  if(productMode==="savings"){clearInflowPrediction("적금은 시장 KPI·순위·변화추이까지만 계산합니다. 수신금액 예측은 정기예금 전용 모델입니다.");return}\n  const baseline=predictionNumber("baseline-new"),maturity=predictionNumber("maturity-amount"),rollover=predictionNumber("rollover-rate",{min:0,max:100});', "strategy prediction execution")
    rendered = _replace_required(rendered, 'function setupSegments(){document.querySelectorAll("#term-segment button").forEach(btn=>btn.addEventListener("click",()=>{document.querySelectorAll("#term-segment button").forEach(x=>x.classList.remove("active"));btn.classList.add("active");simTerm=Number(btn.dataset.term);updateSim()}));$("map-back").addEventListener("click",resetMap)}', 'function setupSegments(){document.querySelectorAll("#term-segment button").forEach(btn=>btn.addEventListener("click",()=>setScopeTerm(btn.dataset.term)));$("map-back").addEventListener("click",resetMap)}', "strategy simulator term")
    old_boot = '  try{const res=await fetch(data.table_url,{cache:"no-store"});if(!res.ok)throw new Error(`금리표 HTTP ${res.status}`);const packed=await res.json();strategyUniverse=packed.strategy_universe||null;allRows=expand(packed);setupMarketScope();aggregateCache.clear();[6,12,24,36].forEach(aggregateProducts);renderMarket();renderPrefs();renderTermStrip();ensureMapSector();renderInsightsEnhanced();applyModeVisibility();updateSim()}catch(err){$("error").hidden=false;$("error").textContent=`금리표를 불러오지 못했습니다. ${err instanceof Error?err.message:String(err)}`}'
    new_boot = '  try{const [strategyRes,canonicalRes]=await Promise.all([fetch(data.table_url,{cache:"no-store"}),fetch("data/table.json",{cache:"no-store"})]);if(!strategyRes.ok)throw new Error(`전략 금리표 HTTP ${strategyRes.status}`);if(!canonicalRes.ok)throw new Error(`예·적금 금리표 HTTP ${canonicalRes.status}`);const [packed,canonical]=await Promise.all([strategyRes.json(),canonicalRes.json()]);depositUniverse=packed.strategy_universe||null;depositRows=expand(packed);savingsRows=prepareSavingsRows(canonical);savingsUniverse=buildSavingsUniverse(savingsRows);strategyUniverse=depositUniverse;allRows=depositRows;setupMarketScope();aggregateCache.clear();GLOBAL_TERMS.forEach(aggregateProducts);renderMarket();renderPrefs();renderTermStrip();ensureMapSector();renderProductHistoryScope();renderInsightsEnhanced();applyModeVisibility();updateSim()}catch(err){$("error").hidden=false;$("error").textContent=`금리표를 불러오지 못했습니다. ${err instanceof Error?err.message:String(err)}`}'
    rendered = _replace_required(rendered, old_boot, new_boot, "strategy dual boot")
    return rendered


def inject_dashboard_product_scope(html: str) -> str:
    rendered = html
    if 'id="conditions"' in rendered:
        rendered = _inject_search(rendered)
    elif 'id="market-scope"' in rendered and 'id="top5"' in rendered:
        rendered = _inject_strategy(rendered)
    if PRODUCT_SCOPE_STYLE_MARKER not in rendered:
        if "</head>" not in rendered:
            raise DashboardBuildError("상품군/기간 UI style을 넣을 head가 없다")
        rendered = rendered.replace("</head>", PRODUCT_SCOPE_STYLE + "\n</head>", 1)
    return rendered
