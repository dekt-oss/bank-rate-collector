from pathlib import Path

path = Path("web/templates/strategy.html")
text = path.read_text(encoding="utf-8")


def once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    text = text.replace(old, new, 1)


# CSS — mode selector / capability states.
css_anchor = ".hero{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding:26px 3px 18px}.hero h1{margin:0;font-size:clamp(31px,2.8vw,42px);line-height:1.02;letter-spacing:-.05em;font-weight:820}.hero p{margin:8px 0 0;color:#82908a;font-size:11px}.scope{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px;max-width:560px}.pill{padding:6px 9px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.025);color:#819089;font-size:9.5px}.pill.active{color:#cee9da;border-color:rgba(128,200,166,.28);background:rgba(65,121,93,.15)}"
css_extra = """
.market-scope{margin-bottom:12px;padding:12px 14px;display:grid;grid-template-columns:auto 1fr;gap:10px 16px;align-items:center;background:linear-gradient(145deg,rgba(17,35,29,.96),rgba(9,23,19,.96))}.mode-tabs{display:flex;gap:5px;flex-wrap:wrap}.mode-tab{border:1px solid var(--line);border-radius:9px;background:#0a1915;color:#7d8d85;padding:8px 11px;font-size:9.5px;font-weight:760;cursor:pointer}.mode-tab.active{color:#d8eee2;border-color:rgba(128,200,166,.42);background:rgba(73,125,97,.22)}.sector-toggles{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}.sector-toggle{display:flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid var(--line);border-radius:9px;background:rgba(4,14,11,.24);color:#9cadA4;font-size:9px}.sector-toggle input{accent-color:var(--green)}.sector-toggle.disabled{opacity:.5}.sector-toggle small{color:#687a71}.scope-status{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:6px;align-items:center;color:#71847a;font-size:9px}.scope-status b{color:#b9d7c8}.scope-warning{margin:0 0 12px;padding:10px 11px;border:1px solid rgba(212,179,111,.22);border-radius:9px;background:rgba(92,72,35,.12);color:#bfae83;font-size:9.5px}.market-flow[hidden],.mapcard[hidden],.simform[hidden]{display:none!important}
""".strip()
once(css_anchor, css_anchor + css_extra, "scope css")

# Hero current-mode pill and selector panel.
once(
    '<div class="scope"><span class="pill active">저축은행</span><span class="pill">정기예금</span>',
    '<div class="scope"><span class="pill active" id="scope-pill">저축은행</span><span class="pill">정기예금</span>',
    "scope pill",
)
once(
    '</section>\n<div class="error" id="error" hidden role="alert"></div>',
    '''</section>\n<section class="card market-scope" id="market-scope" aria-label="전략 비교 업권">\n  <div class="mode-tabs" role="group" aria-label="비교 모드">\n    <button class="mode-tab active" type="button" data-market-mode="savings_bank">저축은행</button>\n    <button class="mode-tab" type="button" data-market-mode="mutual_finance">상호금융</button>\n    <button class="mode-tab" type="button" data-market-mode="combined">저축은행 + 상호금융</button>\n  </div>\n  <div class="sector-toggles" id="sector-toggles" aria-label="상호금융 세부 업권">\n    <label class="sector-toggle"><input type="checkbox" data-sector="cu" checked>신협 <small>확인 중</small></label>\n    <label class="sector-toggle disabled"><input type="checkbox" data-sector="kfcc" disabled>새마을금고 <small>최고금리 미지원</small></label>\n    <label class="sector-toggle disabled"><input type="checkbox" data-sector="nh_local" disabled>농·축협 <small>최고금리 미지원</small></label>\n  </div>\n  <div class="scope-status" id="scope-status"><b>최고금리 기준</b><span>업권 capability를 확인하는 중입니다.</span></div>\n</section>\n<div class="error" id="error" hidden role="alert"></div>''',
    "scope markup",
)

# Make legacy-only sections explicit/safely controllable.
once('<section class="grid market-flow" aria-label="시장 금리와 최근 변화 흐름">', '<section class="grid market-flow" id="market-flow" aria-label="저축은행 시장 금리와 최근 변화 흐름">', "market flow id")
once('<h2>기간별 현재금리 · 12개월 시장 추이</h2><!-- preview-compat: 기간별 금리 추이 --><p>6·12·24·36개월 현재 평균 + 최근 정상 수집일 12개월 시장 최고 / 평균 / 고려저축은행 최고금리</p>', '<h2>기간별 현재금리 · 12개월 시장 추이</h2><!-- preview-compat: 기간별 금리 추이 --><p>현재 평균은 선택 업권 기준 · 이력 추이는 저축은행 정상 수집일 기준</p>', "trend scope copy")
once('<article class="card pad mapcard">', '<article class="card pad mapcard" id="map-card">', "map card id")
once('<section class="planning-zone" aria-label="신상품 기획">', '<section class="planning-zone" id="planning-zone" aria-label="신상품 기획">', "planning id")
once('<div class="simform">', '<div class="scope-warning" id="sim-scope-warning" hidden>상호금융 단독 모드에서는 고려저축은행 기준 신상품·수신 시뮬레이터를 잠급니다. 통합 또는 저축은행 모드에서 사용하세요.</div><div class="simform" id="sim-form">', "sim scope warning")

# JS state / sector-aware helpers.
once(
    'let allRows=[],products12=[],simTerm=12,mapMode="korea";\nconst aggregateCache=new Map;',
    'let allRows=[],products12=[],simTerm=12,mapMode="korea",marketMode="savings_bank",strategyUniverse=null;\nconst aggregateCache=new Map;',
    "js state",
)

aggregate_start = text.index("function aggregateProducts(term){")
aggregate_end = text.index("\nfunction median(", aggregate_start)
aggregate_new = r'''function universeSector(key){return strategyUniverse?.sectors?.[key]||null}
function sectorLabel(key){return universeSector(key)?.label||({savings_bank:"저축은행",cu:"신협",kfcc:"새마을금고",nh_local:"농·축협"}[key]||key)}
function selectedMutualSectors(){return [...document.querySelectorAll('[data-sector]:checked')].map(x=>x.dataset.sector).filter(x=>universeSector(x)?.selectable)}
function activeSectors(){const mutual=selectedMutualSectors();if(marketMode==="savings_bank")return["savings_bank"];if(marketMode==="mutual_finance")return mutual;return["savings_bank",...mutual]}
function modeLabel(){return marketMode==="savings_bank"?"저축은행":marketMode==="mutual_finance"?"상호금융":"저축은행 + 상호금융"}
function capabilityText(meta){if(!meta)return"계약 없음";if(!meta.max_rate_capability)return"최고금리 미지원";if(!meta.selectable)return"현재 비교 데이터 없음";const pct=Number.isFinite(Number(meta.coverage_ratio))?`${(Number(meta.coverage_ratio)*100).toFixed(0)}% 확보`:"coverage 확인 중";return pct}
function renderScopeControls(){
  document.querySelectorAll("[data-market-mode]").forEach(btn=>btn.classList.toggle("active",btn.dataset.marketMode===marketMode));
  document.querySelectorAll("[data-sector]").forEach(input=>{const meta=universeSector(input.dataset.sector),label=input.closest(".sector-toggle"),small=label?.querySelector("small"),enabled=!!meta?.selectable;input.disabled=!enabled;label?.classList.toggle("disabled",!enabled);if(small)small.textContent=capabilityText(meta);if(!enabled)input.checked=false});
  const cu=universeSector("cu"),cu6=cu?.terms?.["6"],parts=[`선택 ${activeSectors().map(sectorLabel).join(" + ")||"없음"}`];
  if(cu&&Number(cu.rows||0)>0)parts.push(`신협 최고금리 ${capabilityText(cu)}`);if(cu6&&Number(cu6.rows||0)===0)parts.push("신협 6개월 공시 데이터 없음");
  for(const key of ["kfcc","nh_local"]){const meta=universeSector(key);if(meta&&!meta.selectable)parts.push(`${sectorLabel(key)}: ${meta.blocked_reason||capabilityText(meta)}`)}
  $("scope-pill").textContent=modeLabel();$("scope-status").innerHTML=`<b>최고금리 기준 · base fallback 없음</b><span>${esc(parts.join(" · "))}</span>`;
}
function applyModeVisibility(){const mutualOnly=marketMode==="mutual_finance";$("market-flow").hidden=mutualOnly;$("map-card").hidden=mutualOnly;$("sim-scope-warning").hidden=!mutualOnly;$("sim-form").hidden=mutualOnly;if(!mutualOnly&&mapMode==="korea")renderKoreaMap()}
function rerenderForScope(){aggregateCache.clear();products12=[];[6,12,24,36].forEach(aggregateProducts);renderMarket();renderPrefs();renderTermStrip();renderInsightsEnhanced();applyModeVisibility();if(marketMode!=="mutual_finance")updateSim()}
function setMarketMode(mode){if(!["savings_bank","mutual_finance","combined"].includes(mode))return;marketMode=mode;renderScopeControls();rerenderForScope()}
function setupMarketScope(){document.querySelectorAll("[data-market-mode]").forEach(btn=>btn.addEventListener("click",()=>setMarketMode(btn.dataset.marketMode)));document.querySelectorAll("[data-sector]").forEach(input=>input.addEventListener("change",()=>{renderScopeControls();rerenderForScope()}));renderScopeControls()}
function aggregateProducts(term){
  const sectors=activeSectors(),cacheKey=`${marketMode}:${sectors.join(",")}:${term}`;
  if(aggregateCache.has(cacheKey))return aggregateCache.get(cacheKey);
  const allowed=new Set(sectors),m=new Map;
  for(const r of allRows){
    if(!allowed.has(r.sector)||r.type!=="term_deposit"||r.term!==term||!Number.isFinite(r.max))continue;
    const key=`${r.sector}\0${r.productId}\0${term}`;
    let p=m.get(key);
    if(!p){p={sector:r.sector,institution:r.institution,product:r.product,term,region:region(r.region),district:r.district||null,max:-Infinity,base:null,sourceId:null,sourceEffectiveAt:null,prefKnown:false,tags:new Set,tagLatest:new Map,otherSamples:new Map};m.set(key,p)}
    if(r.prefStatus==="present"){p.prefKnown=true;const prefDate=String(r.sourceEffectiveAt||""),codes=String(r.prefTags).split(/\s+/).filter(Boolean);codes.forEach(x=>{p.tags.add(x);if(prefDate>String(p.tagLatest.get(x)||""))p.tagLatest.set(x,prefDate)});if(codes.includes("OTHER")&&r.prefRaw){const sampleKey=`${r.institution}\0${r.product}\0${r.prefRaw}`;p.otherSamples.set(sampleKey,{institution:r.institution,product:r.product,raw:r.prefRaw,sourceId:r.sourceId,sourceEffectiveAt:r.sourceEffectiveAt})}}
    const freshness=String(r.sourceEffectiveAt||""),oldFreshness=String(p.sourceEffectiveAt||"");
    if(r.max>p.max||(r.max===p.max&&freshness>oldFreshness)){p.max=r.max;p.base=r.base;p.sourceId=r.sourceId;p.sourceEffectiveAt=r.sourceEffectiveAt;p.region=region(r.region)||p.region;p.district=r.district||p.district}
  }
  const products=[...m.values()].sort((a,b)=>b.max-a.max||String(a.institution).localeCompare(String(b.institution),"ko")||String(a.product).localeCompare(String(b.product),"ko"));
  aggregateCache.set(cacheKey,products);
  return products;
}'''
text = text[:aggregate_start] + aggregate_new + text[aggregate_end:]

# Map and regional insight stay savings-bank-only until H3 geo layers exist.
text = text.replace('const a=regionAverages(products12),top=a[0]?.region;', 'const a=regionAverages(products12.filter(x=>x.sector==="savings_bank")),top=a[0]?.region;')
text = text.replace('const rows=products12.filter(x=>region(x.region)==="부산"&&x.district),g=new Map;', 'const rows=products12.filter(x=>x.sector==="savings_bank"&&region(x.region)==="부산"&&x.district),g=new Map;')
text = text.replace('const regional=regionAverages(products12),strongest=regional[0],', 'const regional=regionAverages(products12.filter(x=>x.sector==="savings_bank")),strongest=regional[0],')

# Current mode should be visible in top5 source hints.
text = text.replace('<span class="sourcehint">${esc(r.sourceId||"원천 미확인")} · ${esc(formatDate(r.sourceEffectiveAt))}</span>', '<span class="sourcehint">${esc(sectorLabel(r.sector))} · ${esc(r.sourceId||"원천 미확인")} · ${esc(formatDate(r.sourceEffectiveAt))}</span>')

# Explicit no-data wording per selected term/mode.
text = text.replace('return`<div class="termcard${t===12?" active":""}"><span>${t}개월 평균 · ${fmt.format(p.length)}상품</span><b>${Number.isFinite(avg)?avg.toFixed(2)+"%":"—"}</b></div>`', 'return`<div class="termcard${t===12?" active":""}"><span>${t}개월 ${p.length?`평균 · ${fmt.format(p.length)}상품`:"데이터 없음"}</span><b>${Number.isFinite(avg)?avg.toFixed(2)+"%":"—"}</b></div>`')

# Boot reads strategy_universe from the same packed payload before expansion.
boot_start = text.index("async function boot(){")
boot_end = text.index('\npair("base-r","base-n")', boot_start)
boot_new = r'''async function boot(){
  renderHealth();renderChangesEnhanced();renderTrendEnhanced();const d=data.generated_at?new Date(data.generated_at):null;$("time").textContent=d&&!Number.isNaN(d.getTime())?`기준 ${d.toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})}`:"데이터 시각 미확인";
  try{const res=await fetch(data.table_url,{cache:"no-store"});if(!res.ok)throw new Error(`금리표 HTTP ${res.status}`);const packed=await res.json();strategyUniverse=packed.strategy_universe||null;allRows=expand(packed);setupMarketScope();aggregateCache.clear();[6,12,24,36].forEach(aggregateProducts);renderMarket();renderKoreaMap();renderPrefs();renderTermStrip();renderInsightsEnhanced();applyModeVisibility();updateSim()}catch(err){$("error").hidden=false;$("error").textContent=`금리표를 불러오지 못했습니다. ${err instanceof Error?err.message:String(err)}`}
}'''
text = text[:boot_start] + boot_new + text[boot_end:]

# Guardrails proving H2 did not silently mix geography/history.
required = [
    'data-market-mode="mutual_finance"',
    'data-sector="kfcc" disabled',
    'function activeSectors()',
    'strategyUniverse=packed.strategy_universe||null',
    'products12.filter(x=>x.sector==="savings_bank")',
    '상호금융 단독 모드에서는 고려저축은행 기준',
    '신협 6개월 공시 데이터 없음',
]
for marker in required:
    if marker not in text:
        raise SystemExit(f"missing H2 marker: {marker}")

path.write_text(text, encoding="utf-8")
print("patched", path, "bytes", path.stat().st_size)
