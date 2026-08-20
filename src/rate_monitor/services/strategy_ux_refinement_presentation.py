# ruff: noqa: E501
"""Strategy dashboard UX hierarchy refinement.

This presentation changes only display defaults and information hierarchy. It does not
change rate calculations, source precedence, stable identity, collection contracts, or
Strategy release-gate semantics.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-ux-refinement-style"'
SCRIPT_MARKER = 'id="strategy-ux-refinement-script"'

_MODE_TABS_OLD = '''<div class="mode-tabs" role="group" aria-label="비교 모드">
    <button class="mode-tab active" type="button" data-market-mode="savings_bank">저축은행</button>
    <button class="mode-tab" type="button" data-market-mode="mutual_finance">상호금융</button>
    <button class="mode-tab" type="button" data-market-mode="combined">저축은행 + 상호금융</button>
  </div>'''
_MODE_TABS_NEW = '''<div class="mode-tabs" role="group" aria-label="비교 모드">
    <button class="mode-tab active" type="button" data-market-mode="combined">저축은행 + 상호금융</button>
    <button class="mode-tab" type="button" data-market-mode="savings_bank">저축은행</button>
    <button class="mode-tab" type="button" data-market-mode="mutual_finance">상호금융</button>
  </div>'''

_CSS = r"""
<style id="strategy-ux-refinement-style">
/* 1. Readability: keep KPI hierarchy, but remove the 9px micro-type feel. */
body{font-size:16px;line-height:1.6}.identity b{font-size:14px}.nav a{font-size:12px}.meta{font-size:11px}.hero p{font-size:13px}.pill{font-size:11px}.mode-tab{font-size:11.5px;padding:9px 12px}.sector-toggle{font-size:11px}.sector-toggle small{font-size:10px}.scope-status{font-size:11px;line-height:1.55}.ranking-basis{font-size:10.5px}.ranking-basis:before{font-size:10px}.head h2{font-size:17px}.head p{font-size:12px}.chip{font-size:10.5px}.klabel{font-size:12px}.basis-label,.badge{font-size:10px}.kfoot{font-size:10.5px}.workspace-section-label em{font-size:10px}.workspace-section-label strong{font-size:14px}.workspace-section-label span{font-size:11px}.planning-strip span,.planning-strip small,.trend-summary span,.trend-summary small,.cstat span{font-size:10.5px}.planning-basis,.engine-summary,.scope-warning{font-size:10.5px}.simrow label,.choice-box>span{font-size:11.5px}.simresult span,.simresult small{font-size:10.5px}.note,.warning{font-size:10.5px}.tablewrap th{font-size:10.5px}.tablewrap td{font-size:11.5px}.product{font-size:10.5px}.sourcehint{font-size:10px}.strongrate{font-size:12.5px}.map-layer-tab,.map-switch button{font-size:10.5px}.map-mode-label{font-size:10.5px}.foot{font-size:10.5px}.empty{font-size:11px}

/* 2. Mutual-finance checkboxes are secondary exclusions, not a second mode selector. */
.market-scope{grid-template-columns:auto 1fr;row-gap:8px}.sector-toggles{position:relative;align-items:center}.sector-toggles:before{content:"상호금융 세부업권 · 기본 전체";color:#6f7f89;font-size:10.5px;font-weight:720;margin-right:2px}.sector-toggles[data-savings-only="true"]{display:none}.sector-toggle{min-height:36px;padding:7px 10px}

/* 3. Collection/capability evidence is preserved, but visually demoted below KPIs. */
.ux-evidence-panel{margin:0 0 12px;border:1px solid rgba(42,61,78,.08);border-radius:12px;background:#fff;box-shadow:0 5px 16px rgba(35,55,72,.04);overflow:hidden}.ux-evidence-panel>summary{display:flex;align-items:center;justify-content:space-between;gap:12px;cursor:pointer;list-style:none;padding:10px 13px;color:#526573;font-size:11px;font-weight:760}.ux-evidence-panel>summary::-webkit-details-marker{display:none}.ux-evidence-panel>summary:after{content:"상세 보기";color:#7b8a94;font-size:10px;font-weight:600}.ux-evidence-panel[open]>summary:after{content:"접기"}.ux-evidence-panel .ux-evidence-summary-copy{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ux-evidence-panel .evidence-strip{margin:0;padding:0 10px 10px;grid-template-columns:repeat(4,minmax(0,1fr))}.ux-evidence-panel .evidence-card{padding:9px 10px;box-shadow:none}.ux-evidence-panel .evidence-head strong{font-size:11px}.ux-evidence-panel .evidence-head em,.ux-evidence-panel .evidence-grid,.ux-evidence-panel .evidence-reason{font-size:10px}

/* 4. Restore the map as a real analysis surface; TOP5 stays readable beside it. */
.workspace-detail.primary:not(.busan-focus){grid-template-columns:minmax(590px,1.08fr) minmax(520px,.92fr)}.workspace-detail.primary:not(.busan-focus) .mapcard{min-height:530px}.workspace-detail.primary:not(.busan-focus) .mapstage{height:435px}.workspace-detail.primary:not(.busan-focus)>article:last-child{min-height:530px}.workspace-detail.primary:not(.busan-focus) .pad{padding:17px}.workspace-detail.primary:not(.busan-focus) td{padding:9px 8px}.workspace-detail.primary:not(.busan-focus) .korea-map-image{opacity:.27;filter:grayscale(.82) contrast(.96)}.workspace-detail.primary:not(.busan-focus) .node-label{font-size:15px}.workspace-detail.primary:not(.busan-focus) .node-rate{font-size:16px}.maplegend{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;margin-top:11px;font-size:10.5px}.ux-map-legend-title{color:#526573;font-weight:720}.ux-map-legend-scale{display:flex;align-items:center;gap:7px;white-space:nowrap;color:#71818b}.legendbar{width:170px;height:8px}

/* 5. D2 follows the top-level market scope. Only period remains local. */
.pref-intel{padding:18px}.pref-intel-head h2{font-size:17px}.pref-intel-head p{font-size:11.5px}.pref-intel-badge{font-size:10px}.pref-intel-controls{align-items:center;padding:9px 11px}.pref-intel-control>span{font-size:10.5px}.pref-intel-control button{font-size:10.5px;padding:6px 9px}.pref-intel-control[data-ux-sector-control]{display:none!important}.ux-pref-scope{display:flex;align-items:center;gap:6px;flex-wrap:wrap;color:#667884;font-size:10.5px}.ux-pref-scope b{color:#334b5a}.ux-pref-scope-tag{display:inline-flex;padding:4px 7px;border:1px solid rgba(79,111,159,.16);border-radius:999px;background:#f2f6fb;color:#476b8d;font-size:10px;font-weight:720}.pref-intel-caveat,.pref-intel-warning{font-size:10.5px}.ux-pref-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.ux-pref-sector{border:1px solid rgba(42,61,78,.09);border-radius:12px;background:#fff;overflow:hidden}.ux-pref-sector-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:11px 12px;border-bottom:1px solid rgba(42,61,78,.07);background:#fafbfd}.ux-pref-sector-head b{color:#263946;font-size:12px}.ux-pref-sector-head span{color:#6b7c87;font-size:10px}.ux-pref-sector .pref-intel-summary span{font-size:10px}.ux-pref-sector .pref-intel-summary b{font-size:16px}.ux-pref-sector .pref-intel-table th,.ux-pref-sector .pref-intel-table td{font-size:10.5px;padding:8px 9px}.ux-pref-more{border-top:1px solid rgba(42,61,78,.07)}.ux-pref-more>summary{cursor:pointer;list-style:none;padding:9px 11px;color:#5f7380;font-size:10.5px;font-weight:720}.ux-pref-more>summary::-webkit-details-marker{display:none}.ux-pref-more>summary:after{content:"펼치기";float:right;color:#7a8993}.ux-pref-more[open]>summary:after{content:"접기"}.ux-pref-own{margin:10px 11px 11px}.ux-pref-empty{padding:16px;color:#73838d;font-size:11px;text-align:center}.pref-intel-own h3{font-size:12px}.pref-intel-own p,.pref-intel-tag,.pref-intel-raw summary,.pref-intel-raw div{font-size:10px}

@media(max-width:1180px){.workspace-detail.primary:not(.busan-focus){grid-template-columns:1fr}.workspace-detail.primary:not(.busan-focus) .mapcard{min-height:520px}.workspace-detail.primary:not(.busan-focus) .mapstage{height:425px}.workspace-detail.primary:not(.busan-focus)>article:last-child{min-height:0}.ux-pref-grid{grid-template-columns:1fr 1fr}}
@media(max-width:900px){.ux-evidence-panel .evidence-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.ux-pref-grid{grid-template-columns:1fr}.market-scope{grid-template-columns:1fr}.sector-toggles{justify-content:flex-start}}
@media(max-width:760px){body{font-size:15px}.hero p{font-size:12px}.klabel{font-size:11px}.kfoot{font-size:10px}.workspace-detail.primary:not(.busan-focus) .mapcard{min-height:470px}.workspace-detail.primary:not(.busan-focus) .mapstage{height:380px}.maplegend{grid-template-columns:1fr}.ux-map-legend-scale{justify-content:space-between}.legendbar{flex:1;max-width:190px}.pref-intel{padding:14px}}
@media(max-width:480px){.ux-evidence-panel .evidence-strip{grid-template-columns:1fr}.ux-evidence-panel>summary{align-items:flex-start}.ux-evidence-panel .ux-evidence-summary-copy{white-space:normal}.workspace-detail.primary:not(.busan-focus) .mapstage{height:350px}.sector-toggles:before{width:100%}}
</style>
"""

_JS = r"""
<script id="strategy-ux-refinement-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const sectorLabels={savings_bank:"저축은행",cu:"신협",kfcc:"새마을금고",nh_local:"농·축협"};
  const pct=v=>Number.isFinite(Number(v))?`${(Number(v)*100).toFixed(0)}%`:"—";
  const lift=v=>Number.isFinite(Number(v))?`${Number(v)>0?"+":""}${Number(v).toFixed(1)}%p`:"—";
  const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  let prefTerm=12;

  function activeMode(){return document.querySelector('[data-market-mode].active')?.dataset.marketMode||"combined"}
  function activeSectorKeys(){
    const mode=activeMode();
    const mutual=[...document.querySelectorAll('[data-sector]:checked:not(:disabled)')].map(x=>x.dataset.sector);
    if(mode==="savings_bank")return["savings_bank"];
    if(mode==="mutual_finance")return mutual;
    return["savings_bank",...mutual];
  }
  function syncSectorFilterVisibility(){const host=$("sector-toggles");if(host)host.dataset.savingsOnly=String(activeMode()==="savings_bank")}

  function compactEvidence(){
    const evidence=$("scope-evidence");if(!evidence||evidence.closest(".ux-evidence-panel"))return;
    const details=document.createElement("details");details.className="ux-evidence-panel";
    const summary=document.createElement("summary");summary.innerHTML='<span class="ux-evidence-summary-copy">수집 데이터 기준 · 업권별 coverage와 기준일</span>';
    evidence.parentNode.insertBefore(details,evidence);details.appendChild(summary);details.appendChild(evidence);
  }
  function updateEvidenceSummary(){
    const copy=document.querySelector(".ux-evidence-summary-copy");if(!copy)return;
    const sectors=activeSectorKeys().map(k=>sectorLabels[k]||k).join(" + ")||"선택 업권 없음";
    copy.textContent=`데이터 기준 · ${sectors} · 업권별 수집률/기준일은 필요할 때 확인`;
  }

  function updateMapLegend(){
    const legend=document.querySelector(".maplegend");if(!legend)return;
    const title=$("map-title")?.textContent||"";
    const unit=title.includes("부산")?"구·군별":"지역별";
    legend.innerHTML=`<span class="ux-map-legend-title">색 기준 · 12개월 ${unit} 대표 최고금리 평균</span><span class="ux-map-legend-scale"><span>낮은 금리</span><i class="legendbar" aria-hidden="true"></i><span>높은 금리</span></span>`;
  }

  function prefScopeFor(sector,intelligence){return intelligence?.scopes?.find(x=>x.sector===sector&&Number(x.term_months)===prefTerm)}
  function preferenceRows(categories){
    return categories.map(c=>`<tr><td class="${c.is_other?"other":""}">${esc(c.label)}</td><td class="mono">${pct(c.market_share)}</td><td class="mono">${pct(c.top_tier_share)}</td><td class="mono ${Number(c.top_tier_lift_pp)>0?"positive":Number(c.top_tier_lift_pp)<0?"negative":""}">${lift(c.top_tier_lift_pp)}</td></tr>`).join("");
  }
  function ownCompanyHtml(own){
    if(!own)return"";
    const tags=(own.preference_labels||[]).length?(own.preference_labels||[]).map(x=>`<span class="pref-intel-tag">${esc(x)}</span>`).join(""):'<span class="pref-intel-tag">표준분류 조건 없음</span>';
    const raw=(own.raw_samples||[]).length?`<details class="pref-intel-raw"><summary>당사 우대조건 원문 근거</summary>${own.raw_samples.map(x=>`<div>${esc(x)}</div>`).join("")}</details>`:"";
    return`<div class="pref-intel-own ux-pref-own"><h3>고려저축은행 현재 조건</h3><p>${Number(own.offering_count||0).toLocaleString("ko-KR")}개 대표상품 · 최고 ${Number(own.max_rate).toFixed(2)}%</p><div class="pref-intel-tags">${tags}</div>${raw}</div>`;
  }
  function sectorPreferenceCard(sector,item){
    const label=sectorLabels[sector]||sector;
    if(!item||item.status==="no_data")return`<section class="ux-pref-sector"><div class="ux-pref-sector-head"><b>${label}</b><span>${prefTerm}개월</span></div><div class="ux-pref-empty">현재 선택 기간의 우대조건 비교 데이터가 없습니다.</div></section>`;
    const coverage=item.coverage||{},top=item.top_tier||{},topCoverage=top.coverage||{},categories=item.categories||[];
    const visible=categories.slice(0,5),rest=categories.slice(5);
    const warning=coverage.coverage_status==="low"?`<div class="pref-intel-warning"><b>우대정보 제공률이 낮습니다.</b> 알려진 조건 ${pct(coverage.known_preference_share)} · 미제공 ${Number(coverage.missing_count||0).toLocaleString("ko-KR")}건. 미제공을 조건 없음으로 해석하지 않습니다.</div>`:"";
    const tableHead='<thead><tr><th>조건</th><th>시장 전체</th><th>상위금리상품</th><th>차이</th></tr></thead>';
    const more=rest.length?`<details class="ux-pref-more"><summary>나머지 조건 ${rest.length}개 보기</summary><table class="pref-intel-table">${tableHead}<tbody>${preferenceRows(rest)}</tbody></table></details>`:"";
    return`<section class="ux-pref-sector"><div class="ux-pref-sector-head"><b>${label}</b><span>${prefTerm}개월 · 상위 조건 ${Math.min(5,categories.length)}개 우선</span></div>${warning}<div class="pref-intel-summary"><div><span>우대정보 제공률</span><b>${pct(coverage.known_preference_share)}</b></div><div><span>상위금리 기준</span><b>${Number.isFinite(Number(top.cutoff_rate))?Number(top.cutoff_rate).toFixed(2)+"%":"—"}</b></div><div><span>상위군 우대정보 제공</span><b>${pct(topCoverage.known_preference_share)}</b></div></div><table class="pref-intel-table">${tableHead}<tbody>${visible.length?preferenceRows(visible):'<tr><td colspan="4">분류 가능한 우대조건이 없습니다.</td></tr>'}</tbody></table>${more}${sector==="savings_bank"?ownCompanyHtml(item.our_company):""}</section>`;
  }
  function renderPreferenceFromTopScope(){
    const panel=$("preference-intelligence"),body=$("preference-intelligence-body");if(!panel||!body)return;
    let payload={};try{payload=JSON.parse($("rate-monitor-data")?.textContent||"{}")}catch{return}
    const intelligence=payload.strategy?.preference_intelligence;if(!intelligence)return;
    const sectorControl=panel.querySelector(".pref-intel-control:first-child");if(sectorControl)sectorControl.dataset.uxSectorControl="true";
    let scope=panel.querySelector(".ux-pref-scope");if(!scope){scope=document.createElement("div");scope.className="ux-pref-scope";panel.querySelector(".pref-intel-controls")?.prepend(scope)}
    const sectors=activeSectorKeys();scope.innerHTML=`<b>상단 선택 연동</b>${sectors.map(k=>`<span class="ux-pref-scope-tag">${sectorLabels[k]||k}</span>`).join("")}`;
    const termButtons=panel.querySelectorAll("[data-pi-term]");termButtons.forEach(b=>b.classList.toggle("active",Number(b.dataset.piTerm)===prefTerm));
    body.innerHTML=sectors.length?`<div class="ux-pref-grid">${sectors.map(k=>sectorPreferenceCard(k,prefScopeFor(k,intelligence))).join("")}</div>`:'<div class="pref-intel-empty">상호금융 세부업권을 하나 이상 선택하세요.</div>';
    const copy=panel.querySelector(".pref-intel-head p");if(copy)copy.textContent=`상단 업권 선택을 그대로 반영해 ${prefTerm}개월 시장 전체와 상위금리 상품의 우대조건을 비교합니다.`;
  }
  function bindPreference(){
    const panel=$("preference-intelligence");if(!panel)return;
    panel.querySelectorAll("[data-pi-term]").forEach(button=>button.addEventListener("click",()=>{prefTerm=Number(button.dataset.piTerm)||12;setTimeout(renderPreferenceFromTopScope,0)}));
    $("market-scope")?.addEventListener("click",()=>setTimeout(()=>{syncSectorFilterVisibility();updateEvidenceSummary();renderPreferenceFromTopScope();updateMapLegend()},0));
    $("market-scope")?.addEventListener("change",()=>setTimeout(()=>{syncSectorFilterVisibility();updateEvidenceSummary();renderPreferenceFromTopScope();updateMapLegend()},0));
  }

  function install(){
    if(document.documentElement.dataset.strategyUxRefinement==="hierarchy-v2")return;
    compactEvidence();syncSectorFilterVisibility();updateEvidenceSummary();updateMapLegend();bindPreference();renderPreferenceFromTopScope();
    const mapTitle=$("map-title");if(mapTitle)new MutationObserver(updateMapLegend).observe(mapTitle,{childList:true,subtree:true,characterData:true});
    document.documentElement.dataset.strategyUxRefinement="hierarchy-v2";
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def _apply_default_scope(html: str) -> str:
    """Make combined scope the deterministic initial UI state before runtime boot."""
    if _MODE_TABS_OLD not in html and _MODE_TABS_NEW not in html:
        raise DashboardBuildError("Strategy 비교모드 버튼 계약을 찾지 못했다")
    rendered = html.replace(_MODE_TABS_OLD, _MODE_TABS_NEW, 1)
    rendered = rendered.replace(
        '<span class="pill active" id="scope-pill">저축은행</span>',
        '<span class="pill active" id="scope-pill">저축은행 + 상호금융</span>',
        1,
    )
    rendered = rendered.replace(
        '<input type="checkbox" data-sector="kfcc">',
        '<input type="checkbox" data-sector="kfcc" checked>',
        1,
    )
    rendered = rendered.replace(
        '<input type="checkbox" data-sector="nh_local">',
        '<input type="checkbox" data-sector="nh_local" checked>',
        1,
    )
    rendered = rendered.replace(
        'mapSector="savings_bank",marketMode="savings_bank",strategyUniverse=null;',
        'mapSector="savings_bank",marketMode="combined",strategyUniverse=null;',
        1,
    )
    return rendered


def inject_strategy_ux_refinement(html: str) -> str:
    """Apply the approved readability, scope, evidence, map, and D2 UX refinement."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Strategy UX refinement 주입 상태가 불완전하다")
    required = (
        'id="market-scope"',
        'id="scope-evidence"',
        'id="preference-intelligence"',
        'id="map-card"',
        'id="strategy-workspace-style"',
    )
    if any(marker not in html for marker in required):
        raise DashboardBuildError("Strategy UX refinement 선행 presentation 계약을 찾지 못했다")
    rendered = _apply_default_scope(html)
    rendered = rendered.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
