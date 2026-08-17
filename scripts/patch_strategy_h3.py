from pathlib import Path
import re

html_path = Path("web/templates/strategy.html")
html = html_path.read_text(encoding="utf-8")


def once(old: str, new: str, label: str) -> None:
    global html
    count = html.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    html = html.replace(old, new, 1)


def regex_once(pattern: str, repl: str, label: str) -> None:
    global html
    html, count = re.subn(pattern, repl, html, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 regex match, got {count}")


# Compact evidence strip + map layer controls. Keep the existing visual language.
once(
    '.scope-status b{color:#b9d7c8}.scope-warning',
    '''.scope-status b{color:#b9d7c8}.evidence-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:0 0 12px}.evidence-card{min-width:0;padding:11px 12px;border:1px solid var(--line);border-radius:12px;background:rgba(9,24,20,.72);box-shadow:0 10px 24px rgba(0,0,0,.12)}.evidence-card.active{border-color:rgba(128,200,166,.32);background:linear-gradient(145deg,rgba(30,62,49,.74),rgba(10,27,22,.82))}.evidence-card.blocked{opacity:.72}.evidence-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:7px}.evidence-head strong{font-size:10px}.evidence-head em{font-style:normal;font-size:8.5px;color:#8fa79b}.evidence-card.blocked .evidence-head em{color:#c0a476}.evidence-grid{display:grid;gap:3px;color:#7f9188;font-size:8.8px}.evidence-grid span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.evidence-grid b{margin-right:5px;color:#a8bbb1;font-weight:720}.evidence-reason{margin:7px 0 0;color:#887c65;font-size:8.6px;line-height:1.45}.ranking-basis{display:flex;align-items:center;gap:8px;margin:-4px 2px 12px;color:#73867c;font-size:9px}.ranking-basis:before{content:"비교 단위";padding:2px 6px;border:1px solid rgba(128,200,166,.16);border-radius:99px;color:#9bb5a8;font-weight:760}.map-layer-tabs{display:flex;gap:4px;flex-wrap:wrap}.map-layer-tab{border:1px solid var(--line);border-radius:8px;background:#081712;color:#7e8f86;padding:6px 8px;font-size:8.7px;font-weight:760;cursor:pointer}.map-layer-tab.active{color:#d8eee2;border-color:rgba(128,200,166,.42);background:rgba(73,125,97,.22)}@media(max-width:900px){.evidence-strip{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){.evidence-strip{grid-template-columns:1fr}.ranking-basis{align-items:flex-start;flex-direction:column}.map-switch{justify-content:flex-start;flex-wrap:wrap}}.scope-warning''',
    "H3 evidence CSS",
)

# Evidence cards live directly under the mode selector.
once(
    '  <div class="scope-status" id="scope-status"><b>최고금리 기준</b><span>업권 capability를 확인하는 중입니다.</span></div>\n</section>\n<div class="error"',
    '  <div class="scope-status" id="scope-status"><b>최고금리 기준</b><span>업권 capability를 확인하는 중입니다.</span></div>\n</section>\n<section class="evidence-strip" id="scope-evidence" aria-label="업권별 최고금리 coverage와 데이터 기준"><article class="evidence-card"><div class="evidence-head"><strong>데이터 신뢰도</strong><em>확인 중</em></div><div class="evidence-grid"><span>업권 capability를 불러옵니다.</span></div></article></section>\n<div class="error"',
    "H3 evidence HTML",
)

once(
    '<section class="grid market-flow" id="market-flow"',
    '<div class="ranking-basis" id="ranking-basis">12개월 · 업권별 stable product 대표 최고금리 기준</div>\n<section class="grid market-flow" id="market-flow"',
    "H3 ranking basis HTML",
)

once(
    '<div class="map-switch"><button type="button" id="map-back" hidden>전국 보기</button><span class="chip" id="map-chip">12개월 평균</span></div>',
    '<div class="map-switch"><div class="map-layer-tabs" id="map-layer-tabs" aria-label="지역 지도 업권 레이어"></div><button type="button" id="map-back" hidden>전국 보기</button><span class="chip" id="map-chip">12개월 평균</span></div>',
    "H3 map layer controls",
)

once(
    '<h2 id="top5-title">경쟁사 TOP 5</h2><p>12개월 정기예금 · 기관+상품 대표 최고금리 기준</p>',
    '<h2 id="top5-title">경쟁사 TOP 5</h2><p id="top5-copy">12개월 정기예금 · 기관+상품 대표 최고금리 기준</p>',
    "H3 top5 dynamic copy",
)

once(
    '<footer class="foot"><span><b>지역 기준</b> · 저축은행 공시금리 — 전국 본점 기준 참고값</span><span><b>계산 기준</b> · 최고금리 NULL은 기본금리로 대체하지 않음 · 동일 금리 공동순위</span></footer>',
    '<footer class="foot"><span id="footer-geo"><b>지역 기준</b> · 저축은행 공시금리 — 전국 본점 기준 참고값</span><span id="footer-calc"><b>계산 기준</b> · 최고금리 NULL은 기본금리로 대체하지 않음 · 동일 금리 공동순위</span></footer>',
    "H3 dynamic footer",
)

once(
    'let allRows=[],products12=[],simTerm=12,mapMode="korea",marketMode="savings_bank",strategyUniverse=null;',
    'let allRows=[],products12=[],simTerm=12,mapMode="korea",mapSector="savings_bank",marketMode="savings_bank",strategyUniverse=null;',
    "H3 map sector state",
)

# Metadata semantics are displayed, never guessed into the rate itself.
once(
    'function modeLabel(){return marketMode==="savings_bank"?"저축은행":marketMode==="mutual_finance"?"상호금융":"저축은행 + 상호금융"}\n',
    '''function modeLabel(){return marketMode==="savings_bank"?"저축은행":marketMode==="mutual_finance"?"상호금융":"저축은행 + 상호금융"}\nconst GEO_BASIS_LABELS={head_office_address:"본점 소재지",head_office:"본점 소재지",source_query_region:"원천 조회지역",outlet_address:"점포 주소"};\nconst RATE_SCOPE_LABELS={institution:"기관",outlet:"점포"};\nconst AVAILABILITY_LABELS={all:"전체",general:"일반",all_customers:"전체 고객",member_only:"회원 전용",members:"회원 전용",region_restricted:"지역 제한",internet_only:"인터넷 전용",unknown:"미확인"};\nfunction metaValueList(meta,key){const v=meta?.[key];return Array.isArray(v)?v.filter(Boolean):v?[v]:[]}\nfunction compactMeta(values,labels,fallback){if(!values.length)return fallback;const head=values.slice(0,2).map(x=>labels[x]||String(x));return head.join(" / ")+(values.length>2?` +${values.length-2}`:"")}\nfunction sectorGeoBasis(key){const values=metaValueList(universeSector(key),"geo_basis");if(values.length)return compactMeta(values,GEO_BASIS_LABELS,"지역 기준 미확인");return key==="savings_bank"?"본점 소재지":key==="cu"?"원천 조회지역":"지역 기준 미확인"}\nfunction sectorRateScope(key){return compactMeta(metaValueList(universeSector(key),"rate_scope"),RATE_SCOPE_LABELS,"비교 단위 미확인")}\nfunction sectorAvailability(key){return compactMeta(metaValueList(universeSector(key),"availability_scope"),AVAILABILITY_LABELS,"가입 범위 미확인")}\nfunction termCoverage(meta,term=12){const t=meta?.terms?.[String(term)];if(!t||!Number(t.rows||0))return`${term}M 데이터 없음`;const ratio=Number(t.coverage_ratio),pct=Number.isFinite(ratio)?`${(ratio*100).toFixed(0)}%`:"미확인";return`${pct} · ${fmt.format(Number(t.max_rate_rows||0))}/${fmt.format(Number(t.rows||0))}`}\nfunction renderScopeEvidence(){const host=$("scope-evidence"),active=new Set(activeSectors()),keys=strategyUniverse?.candidate_sectors||["savings_bank","cu","kfcc","nh_local"];host.innerHTML=keys.map(key=>{const meta=universeSector(key),selected=active.has(key),selectable=!!meta?.selectable,state=selectable?(selected?"선택":"사용 가능"):"랭킹 제외",klass=`evidence-card${selected?" active":""}${!selectable?" blocked":""}`,reason=!selectable?(meta?.blocked_reason||(!meta?.max_rate_capability?"공식 최고금리 계약 미지원":"현재 최고금리 비교 데이터 없음")):"";return`<article class="${klass}" data-evidence-sector="${esc(key)}"><div class="evidence-head"><strong>${esc(sectorLabel(key))}</strong><em>${esc(state)}</em></div><div class="evidence-grid"><span><b>12M 최고금리</b>${esc(termCoverage(meta,12))}</span><span><b>비교단위</b>${esc(sectorRateScope(key))}</span><span><b>지역기준</b>${esc(sectorGeoBasis(key))}</span><span><b>가입범위</b>${esc(sectorAvailability(key))}</span><span><b>최신 기준일</b>${esc(formatDate(meta?.latest_source_effective_at))}</span></div>${reason?`<p class="evidence-reason">${esc(reason)}</p>`:""}</article>`}).join("")}\nfunction activeGeoSectors(){return activeSectors().filter(key=>["savings_bank","cu"].includes(key)&&metaValueList(universeSector(key),"geo_basis").length)}\nfunction ensureMapSector(){const sectors=activeGeoSectors();if(!sectors.includes(mapSector))mapSector=sectors[0]||null;return mapSector}\nfunction mapLayerLabel(key){return key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역":sectorLabel(key)}\nfunction setMapSector(key){if(!activeGeoSectors().includes(key))return;mapSector=key;mapMode="korea";renderMapLayerTabs();renderKoreaMap();renderInsightsEnhanced()}\nfunction renderMapLayerTabs(){const host=$("map-layer-tabs"),sectors=activeGeoSectors();host.innerHTML=sectors.map(key=>`<button type="button" class="map-layer-tab${key===mapSector?" active":""}" data-map-sector="${esc(key)}">${esc(mapLayerLabel(key))}</button>`).join("");host.querySelectorAll("[data-map-sector]").forEach(btn=>btn.addEventListener("click",()=>setMapSector(btn.dataset.mapSector)))}\nfunction rankingEntityLabel(){const scopes=activeSectors().flatMap(key=>metaValueList(universeSector(key),"rate_scope"));if(scopes.length&&scopes.every(x=>x==="institution"))return"기관";if(scopes.length&&scopes.every(x=>x==="outlet"))return"점포";return"비교 주체"}\nfunction rankingBasisText(){const sectors=activeSectors();if(!sectors.length)return"12개월 · 현재 선택된 최고금리 비교 업권 없음";return`12개월 · sector + stable product 대표 · ${sectors.map(key=>`${sectorLabel(key)} ${sectorRateScope(key)}`).join(" · ")}`}\n''',
    "H3 metadata helpers",
)

# Scope rerender now owns evidence + geography layer semantics.
once(
    '  $("scope-pill").textContent=modeLabel();$("scope-status").innerHTML=`<b>최고금리 기준 · base fallback 없음</b><span>${esc(parts.join(" · "))}</span>`;\n}',
    '  $("scope-pill").textContent=modeLabel();$("scope-status").innerHTML=`<b>최고금리 기준 · base fallback 없음</b><span>${esc(parts.join(" · "))}</span>`;renderScopeEvidence();$("ranking-basis").textContent=rankingBasisText();\n}',
    "H3 scope evidence render",
)

once(
    'function applyModeVisibility(){const mutualOnly=marketMode==="mutual_finance",savingsOnly=marketMode==="savings_bank";$("market-flow").hidden=mutualOnly;$("map-card").hidden=mutualOnly;$("trend-delta").hidden=!savingsOnly;$("sim-scope-warning").hidden=!mutualOnly;$("sim-form").hidden=mutualOnly;if(!mutualOnly&&mapMode==="korea")renderKoreaMap()}',
    'function applyModeVisibility(){const mutualOnly=marketMode==="mutual_finance",savingsOnly=marketMode==="savings_bank";$("market-flow").hidden=mutualOnly;$("map-card").hidden=false;$("trend-delta").hidden=!savingsOnly;$("sim-scope-warning").hidden=!mutualOnly;$("sim-form").hidden=mutualOnly;ensureMapSector();renderMapLayerTabs();if(mapMode==="busan"&&mapSector!=="savings_bank")mapMode="korea";renderKoreaMap()}',
    "H3 map visibility",
)

once(
    'function rerenderForScope(){aggregateCache.clear();products12=[];[6,12,24,36].forEach(aggregateProducts);renderMarket();renderPrefs();renderTermStrip();renderInsightsEnhanced();applyModeVisibility();if(marketMode!=="mutual_finance")updateSim()}',
    'function rerenderForScope(){aggregateCache.clear();products12=[];[6,12,24,36].forEach(aggregateProducts);renderMarket();renderPrefs();renderTermStrip();ensureMapSector();renderInsightsEnhanced();applyModeVisibility();if(marketMode!=="mutual_finance")updateSim()}',
    "H3 rerender ordering",
)

# KPI denominator is sector-aware; same display name in another sector never collapses.
once(
    '  products12=aggregateProducts(12);\n  if(!products12.length){',
    '  products12=aggregateProducts(12);$("ranking-basis").textContent=rankingBasisText();$("top5-copy").textContent=`12개월 정기예금 · ${modeLabel()} · sector + stable product 대표 최고금리`;$("footer-calc").innerHTML=`<b>계산 기준</b> · ${esc(modeLabel())} evidence-backed 최고금리 · NULL은 기본금리로 대체하지 않음 · 동일 금리 공동순위`;\n  if(!products12.length){',
    "H3 ranking copy",
)

once(
    '    $("mean").textContent="—";$("count").textContent="0";$("institutions").textContent="기관 0곳";$("median").textContent="중앙값 —";',
    '    $("mean").textContent="—";$("count").textContent="0";$("institutions").textContent=`${rankingEntityLabel()} 0곳`;$("median").textContent="중앙값 —";',
    "H3 empty unit label",
)

once(
    '  const stats=ratesStats(products12),lead=products12[0],inst=new Set(products12.map(x=>x.institution));',
    '  const stats=ratesStats(products12),lead=products12[0],inst=new Set(products12.map(x=>`${x.sector}\\0${x.institution}`));',
    "H3 sector-aware institution count",
)

once(
    '$("institutions").textContent=`기관 ${fmt.format(inst.size)}곳`;',
    '$("institutions").textContent=`${rankingEntityLabel()} ${fmt.format(inst.size)}곳 · ${fmt.format(activeSectors().length)}개 업권`;',
    "H3 institution unit copy",
)

regex_once(
    r'  \$\("top5"\)\.innerHTML=products12\.slice\(0,5\)\.map\(\(r,i\)=>\{.*?\}\)\.join\(""\)\n}',
    '''  $("top5").innerHTML=products12.slice(0,5).map((r,i)=>{\n    const spread=Number.isFinite(r.base)?r.max-r.base:null,provenance=[sectorLabel(r.sector),sectorRateScope(r.sector),r.sourceId||"원천 미확인",formatDate(r.sourceEffectiveAt),sectorAvailability(r.sector)].join(" · ");\n    return`<tr><td><span class="rank">${i+1}</span></td><td><span class="bank">${esc(r.institution)}</span><span class="product" title="${esc(r.product)}">${esc(r.product)}</span><span class="sourcehint" title="${esc(provenance)}">${esc(provenance)}</span></td><td>${Number.isFinite(r.base)?r.base.toFixed(2)+"%":"—"}</td><td>${Number.isFinite(spread)?`${spread>=0?"+":""}${spread.toFixed(2)}%p`:"—"}</td><td class="strongrate">${r.max.toFixed(2)}%</td></tr>`\n  }).join("")\n}''',
    "H3 TOP5 evidence sourcehint",
)

# Geography uses raw canonical geo observations grouped by stable product + explicit geo basis.
once(
    'function regionAverages(rows){',
    '''function geoProducts(sector,term=12){const m=new Map;for(const r of allRows){if(r.sector!==sector||r.type!=="term_deposit"||r.term!==term||!Number.isFinite(r.max)||!r.productId)continue;const geo=region(r.region);if(!geo||!coords[geo])continue;const district=sector==="savings_bank"?(r.district||""):"",key=`${sector}\\0${r.productId}\\0${term}\\0${geo}\\0${district}`,freshness=String(r.sourceEffectiveAt||""),old=m.get(key);if(!old||r.max>old.max||(r.max===old.max&&freshness>String(old.sourceEffectiveAt||"")))m.set(key,{sector,productId:r.productId,institution:r.institution,product:r.product,term,region:geo,district:r.district||null,max:r.max,sourceEffectiveAt:r.sourceEffectiveAt})}return[...m.values()]}\nfunction regionAverages(rows){''',
    "H3 geo stable observations",
)

new_map = r'''function renderKoreaMap(){
  mapMode="korea";document.querySelector(".primary")?.classList.remove("busan-focus");$("busan-rate-list").hidden=true;$("busan-rate-list").innerHTML="";$("top5-name-head").textContent="금융사 / 상품";const sector=ensureMapSector(),svg=$("geo-map");svg.setAttribute("viewBox","130 -5 450 675");svg.innerHTML=koreaSvg();$("map-back").hidden=true;$("map-mode-label").style.left="auto";$("map-mode-label").style.right="16px";
  if(!sector){svg.setAttribute("aria-label","현재 선택 범위에 지역 지도 데이터 없음");$("map-title").textContent="지역 비교 레이어";$("map-copy").textContent="현재 선택 범위에 표시 가능한 최고금리 지역 관측이 없습니다.";$("map-chip").textContent="데이터 없음";$("map-mode-label").textContent="지도 레이어 없음";$("footer-geo").innerHTML="<b>지역 기준</b> · 현재 선택된 지도 레이어 없음";$("nodes").innerHTML="";return}
  const savings=sector==="savings_bank",geoBasis=sectorGeoBasis(sector),geoRows=geoProducts(sector,12),a=regionAverages(geoRows),top=a[0]?.region;
  svg.setAttribute("aria-label",savings?"저축은행 본점 소재지별 금리 분포 지도":"신협 원천 조회지역별 금리 분포 지도");$("map-title").textContent=savings?"전국 본점 소재지별 금리 분포":"신협 조회지역별 금리 분포";$("map-copy").textContent=savings?"본점 소재지별 stable product 대표 최고금리 평균 · 부산을 누르면 구별 지도 확대":"공식 source_query_region별 stable product 최고금리 관측 평균 · 본점/판매 가능 지역으로 해석하지 않음";$("map-chip").textContent=`12개월 · ${fmt.format(a.length)}지역`;$("map-mode-label").textContent=savings?`저축은행 · ${geoBasis} · SGIS 2020 시도 경계 · 제주 inset`:`신협 · ${geoBasis} · SGIS 2020 시도 경계 · district 추정 없음`;$("footer-geo").innerHTML=savings?`<b>지역 기준</b> · 저축은행 ${esc(geoBasis)} — 판매 가능 지역으로 해석하지 않음`:`<b>지역 기준</b> · 신협 ${esc(geoBasis)} — 본점 소재지·판매 가능 지역으로 해석하지 않음`;
  $("nodes").innerHTML=a.map(x=>{const[cx,cy]=coords[x.region],preset=koreaLabelOffsets[x.region]||[22,-16,"start"],dx=preset[0],dy=preset[1],anchor=preset[2],lx=cx+dx,labelY=cy+dy,rateY=labelY+14,lineX=anchor==="end"?lx+7:anchor==="start"?lx-7:lx,lineY=labelY+5,clickable=savings&&x.region==="부산",klass=["node",x.region===top?"top":"",clickable?"busan clickable":""].filter(Boolean).join(" ");return`<g class="${klass}" data-region="${esc(x.region)}" role="${clickable?"button":"img"}" tabindex="${clickable?"0":"-1"}" aria-label="${esc(x.region)} 지역 평균 ${x.rate.toFixed(2)}%${clickable?", 부산 지도 확대":""}"><line class="node-line" x1="${cx}" y1="${cy}" x2="${lineX}" y2="${lineY}"/><circle class="node-ring" cx="${cx}" cy="${cy}" r="${x.region===top?14:11}"/><circle class="node-core" cx="${cx}" cy="${cy}" r="4.3"/><text class="node-label" x="${lx}" y="${labelY}" text-anchor="${anchor}">${esc(x.region)}</text><text class="node-rate" x="${lx}" y="${rateY}" text-anchor="${anchor}">${x.rate.toFixed(2)}%</text></g>`}).join("");
  const busan=clickable=>document.querySelector('[data-region="부산"]');const busanNode=savings?busan(true):null;if(busanNode){const open=()=>showBusanMap();busanNode.addEventListener("click",open);busanNode.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();open()}})}
}
'''
regex_once(
    r'function renderKoreaMap\(\)\{.*?\n\}\nfunction busanDistrictData\(\)\{',
    new_map + 'function busanDistrictData(){',
    "H3 layered Korea map",
)

once(
    '  const rows=products12.filter(x=>x.sector==="savings_bank"&&region(x.region)==="부산"&&x.district),g=new Map;',
    '  const rows=geoProducts("savings_bank",12).filter(x=>region(x.region)==="부산"&&x.district),g=new Map;',
    "H3 savings-only district data",
)

once(
    'function showBusanMap(){\n  mapMode="busan";',
    'function showBusanMap(){\n  if(mapSector!=="savings_bank")return;\n  mapMode="busan";',
    "H3 district guard",
)

# Region insight follows the visible geo layer; combined-mode geographies are never averaged together.
once(
    '  const regional=regionAverages(products12.filter(x=>x.sector==="savings_bank")),strongest=regional[0],weakest=regional.at(-1);',
    '  const geoSector=ensureMapSector(),regional=geoSector?regionAverages(geoProducts(geoSector,12)):[],strongest=regional[0],weakest=regional.at(-1),geoBasis=geoSector?sectorGeoBasis(geoSector):"지역 기준 미확인";',
    "H3 insight geo layer",
)

old_region_item = '''    {icon:"◇",tag:"지역 편차",\n      title:Number.isFinite(regionalSpread)\n        ?`지역 평균 편차 ${formatBp(regionalSpread)}`\n        :"지역 데이터 확인 중",\n      text:strongest&&weakest\n        ?`${strongest.region} ${strongest.rate.toFixed(2)}% ↔ `\n          +`${weakest.region} ${weakest.rate.toFixed(2)}%`\n        :"본점 소재지 정보가 있는 비교상품이 필요합니다.",\n      action:"본점 소재지 참고값이며 판매 가능 지역으로 해석하지 않고 "\n        +"지역 경쟁강도 참고에만 사용합니다."},'''
new_region_item = '''    {icon:"◇",tag:geoSector?`${sectorLabel(geoSector)} 지역 편차`:"지역 편차",\n      title:Number.isFinite(regionalSpread)\n        ?`지역 평균 편차 ${formatBp(regionalSpread)}`\n        :"지역 데이터 확인 중",\n      text:strongest&&weakest\n        ?`${strongest.region} ${strongest.rate.toFixed(2)}% ↔ `\n          +`${weakest.region} ${weakest.rate.toFixed(2)}% · ${geoBasis}`\n        :"현재 선택 지도 레이어의 지역 관측이 필요합니다.",\n      action:geoSector==="savings_bank"\n        ?"본점 소재지 참고값이며 판매 가능 지역으로 해석하지 않고 지역 경쟁강도 참고에만 사용합니다."\n        :geoSector==="cu"\n          ?"신협 source_query_region 관측이며 본점 소재지·판매 가능 지역이나 부산 구 단위로 추정하지 않습니다."\n          :"서로 다른 geography basis는 같은 지역 평균으로 합치지 않습니다."},'''
once(old_region_item, new_region_item, "H3 insight geo semantics")

once(
    'allRows=expand(packed);setupMarketScope();aggregateCache.clear();[6,12,24,36].forEach(aggregateProducts);renderMarket();renderKoreaMap();renderPrefs();renderTermStrip();renderInsightsEnhanced();applyModeVisibility();updateSim()',
    'allRows=expand(packed);setupMarketScope();aggregateCache.clear();[6,12,24,36].forEach(aggregateProducts);renderMarket();renderPrefs();renderTermStrip();ensureMapSector();renderInsightsEnhanced();applyModeVisibility();updateSim()',
    "H3 boot map ownership",
)

html_path.write_text(html, encoding="utf-8")

# H2's temporary "map hidden until H3" assertion expires now that H3 owns geography.
h2_path = Path("tests/test_strategy_mutual_finance_h2.py")
h2 = h2_path.read_text(encoding="utf-8")
h2, count = re.subn(
    r'\n\ndef test_h2_keeps_geography_savings_bank_only_until_h3\(\) -> None:\n.*?(?=\n\ndef test_h2_does_not_relabel_savings_history_as_mutual_history)',
    '',
    h2,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit(f"remove temporary H2 geography test: expected 1, got {count}")
h2_path.write_text(h2, encoding="utf-8")

Path("tests/test_strategy_mutual_finance_h3.py").write_text(
    '''def _html() -> str:\n    with open("web/templates/strategy.html", encoding="utf-8") as handle:\n        return handle.read()\n\n\ndef test_h3_exposes_coverage_freshness_scope_and_availability() -> None:\n    html = _html()\n\n    assert 'id="scope-evidence"' in html\n    assert "meta?.latest_source_effective_at" in html\n    assert '"geo_basis"' in html\n    assert '"rate_scope"' in html\n    assert '"availability_scope"' in html\n    assert "termCoverage(meta,12)" in html\n    assert "meta?.blocked_reason" in html\n\n\ndef test_h3_ranking_denominators_are_sector_namespaced_and_explicit() -> None:\n    html = _html()\n\n    assert '`${x.sector}\\\\0${x.institution}`' in html\n    assert 'id="ranking-basis"' in html\n    assert "sector + stable product 대표" in html\n    assert 'id="top5-copy"' in html\n    assert "sectorRateScope(r.sector)" in html\n    assert "sectorAvailability(r.sector)" in html\n    assert "max_rate ?? base_rate" not in html\n\n\ndef test_h3_geography_uses_separate_savings_and_cu_layers() -> None:\n    html = _html()\n\n    assert 'mapSector="savings_bank"' in html\n    assert 'id="map-layer-tabs"' in html\n    assert 'key==="savings_bank"?"저축은행 본점":key==="cu"?"신협 조회지역"' in html\n    assert "function geoProducts(sector,term=12)" in html\n    assert '`${sector}\\\\0${r.productId}\\\\0${term}\\\\0${geo}\\\\0${district}`' in html\n    assert 'geoSector?regionAverages(geoProducts(geoSector,12)):[]' in html\n    assert "서로 다른 geography basis는 같은 지역 평균으로 합치지 않습니다." in html\n\n\ndef test_h3_cu_region_is_not_relabelled_as_head_office_or_busan_district() -> None:\n    html = _html()\n\n    assert 'source_query_region:"원천 조회지역"' in html\n    assert "본점/판매 가능 지역으로 해석하지 않음" in html\n    assert "본점 소재지·판매 가능 지역이나 부산 구 단위로 추정하지 않습니다." in html\n    assert 'clickable=savings&&x.region==="부산"' in html\n    assert 'if(mapSector!=="savings_bank")return' in html\n    assert 'geoProducts("savings_bank",12).filter' in html\n\n\ndef test_h3_mutual_only_keeps_map_but_still_locks_savings_bank_history_and_simulator() -> None:\n    html = _html()\n\n    assert '$("map-card").hidden=false' in html\n    assert '$("market-flow").hidden=mutualOnly' in html\n    assert '$("sim-form").hidden=mutualOnly' in html\n    assert '$("trend-delta").hidden=!savingsOnly' in html\n''',
    encoding="utf-8",
)
