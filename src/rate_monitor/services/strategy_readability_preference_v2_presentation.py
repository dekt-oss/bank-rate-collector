# ruff: noqa: E501
"""Strategy 100% zoom readability + Preference Intelligence v2 presentation.

기존 Strategy UX 계층 뒤에서 실제 CSS 글자/간격을 확대하고, D1 v2 payload를
상단 market scope에 맞춰 다시 표시한다. 브라우저 zoom/transform은 사용하지 않는다.
상호금융은 공통 taxonomy를 쓰되 선택된 세부업권을 pooled market으로 렌더링한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-readability-preference-v2-style"'
SCRIPT_MARKER = 'id="strategy-readability-preference-v2-script"'

_CSS = r"""
<style id="strategy-readability-preference-v2-style">
@media screen {
  body{font-size:17px!important;line-height:1.62!important}
  .identity b{font-size:15px!important}.nav a{font-size:13px!important}.meta{font-size:12px!important}
  .hero p{font-size:14px!important}.pill{font-size:12px!important}.mode-tab{font-size:12.5px!important;padding:10px 13px!important}
  .sector-toggle{font-size:12px!important;min-height:39px!important;padding:8px 11px!important}.sector-toggle small{font-size:11px!important}
  .scope-status{font-size:12px!important}.ranking-basis,.ranking-basis:before{font-size:11.5px!important}
  .head h2{font-size:19px!important}.head p{font-size:13px!important}.chip{font-size:11.5px!important}
  .klabel{font-size:13px!important}.basis-label,.badge{font-size:11px!important}.kfoot{font-size:11.5px!important}
  .workspace-section-label em{font-size:11px!important}.workspace-section-label strong{font-size:15.5px!important}.workspace-section-label span{font-size:12px!important}
  .planning-strip span,.planning-strip small,.trend-summary span,.trend-summary small,.cstat span{font-size:11.5px!important}
  .planning-basis,.engine-summary,.scope-warning{font-size:11.5px!important}.simrow label,.choice-box>span{font-size:12.5px!important}.simresult span,.simresult small{font-size:11.5px!important}
  .note,.warning{font-size:11.5px!important}.tablewrap th{font-size:11.5px!important}.tablewrap td{font-size:12.5px!important}.product{font-size:11.5px!important}.sourcehint{font-size:11px!important}.strongrate{font-size:13.5px!important}
  .map-layer-tab,.map-switch button,.map-mode-label,.foot{font-size:11.5px!important}.empty{font-size:12px!important}
  .ux-evidence-panel>summary{font-size:12px!important;padding:11px 14px!important}.ux-evidence-panel>summary:after{font-size:11px!important}.ux-evidence-panel .evidence-head strong{font-size:12px!important}.ux-evidence-panel .evidence-head em,.ux-evidence-panel .evidence-grid,.ux-evidence-panel .evidence-reason{font-size:11px!important}
  .workspace-detail.primary .pad{padding:19px!important}.workspace-detail.primary td{padding:11px 10px!important}.ux-region-handoff{font-size:12px!important;padding:11px 13px!important}
  .ux-decision-readiness{padding:18px!important;gap:16px!important}.ux-readiness-title span{font-size:11px!important}.ux-readiness-title strong{font-size:20px!important}.ux-readiness-title p{font-size:12px!important}.ux-readiness-item{padding:11px 12px!important}.ux-readiness-item b{font-size:12px!important}.ux-readiness-item span,.ux-readiness-foot{font-size:11.5px!important}
  .pref-intel{padding:20px!important}.pref-intel-head h2{font-size:19px!important}.pref-intel-head p{font-size:12.5px!important}.pref-intel-badge{font-size:11px!important}.pref-intel-control>span,.pref-intel-control button,.ux-pref-scope{font-size:11.5px!important}.ux-pref-scope-tag{font-size:11px!important;padding:5px 8px!important}
  .pref-intel-caveat,.pref-intel-warning{font-size:11.5px!important}.ux-pref-sector-head{padding:13px 14px!important}.ux-pref-sector-head b{font-size:13.5px!important}.ux-pref-sector-head span{font-size:11px!important}
  .ux-pref-sector .pref-intel-summary div{padding:12px 13px!important}.ux-pref-sector .pref-intel-summary span{font-size:11px!important}.ux-pref-sector .pref-intel-summary b{font-size:18px!important}
  .ux-pref-sector .pref-intel-table th,.ux-pref-sector .pref-intel-table td{font-size:11.5px!important;padding:9px 10px!important}.ux-pref-more>summary{font-size:11.5px!important}.pref-intel-own h3{font-size:13px!important}.pref-intel-own p,.pref-intel-tag,.pref-intel-raw summary,.pref-intel-raw div{font-size:11px!important}
  .rate-response-caveat{font-size:10.5px!important}.rate-response-head b{font-size:11.5px!important}.rate-response-head span,.rate-response-table th,.rate-response-foot{font-size:10.5px!important}.rate-response-table td,.rate-response-table .scenario-name{font-size:11px!important}.rate-response-table .scenario-note{font-size:10.5px!important}
}
.pref-v2-source{display:flex;gap:6px;flex-wrap:wrap;padding:9px 12px;border-top:1px solid rgba(42,61,78,.07);background:#fbfcfd;color:#647783;font-size:10.5px}.pref-v2-source b{color:#344b59}.pref-v2-source span{display:inline-flex;gap:4px;align-items:center;padding:4px 7px;border:1px solid rgba(79,111,159,.13);border-radius:999px;background:#fff}.pref-v2-denom-note{padding:9px 12px;border-top:1px solid rgba(42,61,78,.07);color:#687984;font-size:10.5px;line-height:1.5}.pref-v2-denom-note b{color:#394f5d}.pref-v2-count{color:#6b7e89;font-size:10.5px}.pref-v2-source .low{border-color:rgba(190,109,109,.20);background:#fff8f8;color:#a35b5b}
@media(max-width:760px){@media screen{body{font-size:16px!important}.head h2,.pref-intel-head h2{font-size:18px!important}.tablewrap td{font-size:12px!important}.pref-intel{padding:16px!important}}}
</style>
""".strip()

_JS = r"""
<script id="strategy-readability-preference-v2-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const labels={savings_bank:"저축은행",cu:"신협",kfcc:"새마을금고",nh_local:"농·축협"};
  const mutualOrder=["cu","kfcc","nh_local"];
  const pct=v=>v===null||v===undefined||!Number.isFinite(Number(v))?"—":`${(Number(v)*100).toFixed(0)}%`;
  const lift=v=>v===null||v===undefined||!Number.isFinite(Number(v))?"—":`${Number(v)>0?"+":""}${Number(v).toFixed(1)}%p`;
  const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  let term=12;
  function data(){try{return JSON.parse($("rate-monitor-data")?.textContent||"{}")}catch{return{}}}
  function mode(){return document.querySelector('[data-market-mode].active')?.dataset.marketMode||"combined"}
  function mutualSelected(){return mutualOrder.filter(k=>document.querySelector(`[data-sector="${k}"]`)?.checked&&!document.querySelector(`[data-sector="${k}"]`)?.disabled)}
  function scope(industry,intelligence){return intelligence?.scopes?.find(x=>x.sector===industry&&Number(x.term_months)===term)}
  function mutualScope(sectors,intelligence){const key=mutualOrder.filter(k=>sectors.includes(k)).join("+");return intelligence?.mutual_finance_scopes?.find(x=>x.scope_key===key&&Number(x.term_months)===term)}
  function rows(categories){return categories.map(c=>`<tr><td class="${c.is_other?"other":""}">${esc(c.label)}</td><td class="mono">${pct(c.market_share)}</td><td class="mono">${pct(c.top_tier_share)}</td><td class="mono ${Number(c.top_tier_lift_pp)>0?"positive":Number(c.top_tier_lift_pp)<0?"negative":""}">${lift(c.top_tier_lift_pp)}</td></tr>`).join("")}
  function own(ownCompany){if(!ownCompany)return"";const tags=(ownCompany.preference_labels||[]).length?(ownCompany.preference_labels||[]).map(x=>`<span class="pref-intel-tag">${esc(x)}</span>`).join(""):'<span class="pref-intel-tag">표준분류 조건 없음</span>';const raw=(ownCompany.raw_samples||[]).length?`<details class="pref-intel-raw"><summary>당사 우대조건 원문 근거</summary>${ownCompany.raw_samples.map(x=>`<div>${esc(x)}</div>`).join("")}</details>`:"";return`<div class="pref-intel-own ux-pref-own"><h3>고려저축은행 현재 조건</h3><p>${Number(ownCompany.offering_count||0).toLocaleString("ko-KR")}개 대표상품 · 최고 ${Number(ownCompany.max_rate).toFixed(2)}%</p><div class="pref-intel-tags">${tags}</div>${raw}</div>`}
  function sourceStrip(item){const sources=item?.source_coverage||[];if(!sources.length)return"";return`<div class="pref-v2-source"><b>원천별 판별 가능</b>${sources.map(s=>`<span class="${s.coverage_status==="low"?"low":""}">${labels[s.sector]||s.sector} ${pct(s.known_preference_share)} · 조건보유 ${pct(s.preference_bearing_share_among_known)}</span>`).join("")}</div>`}
  function card(title,item,{showOwn=false,sub=""}={}){
    if(!item||item.status==="no_data")return`<section class="ux-pref-sector pref-intel-main"><div class="ux-pref-sector-head"><b>${esc(title)}</b><span>${term}개월</span></div><div class="ux-pref-empty">현재 선택 범위의 우대조건 비교 데이터가 없습니다.</div></section>`;
    const coverage=item.coverage||{},top=item.top_tier||{},topCoverage=top.coverage||{},categories=item.categories||[],visible=categories.slice(0,5),rest=categories.slice(5);
    const warning=coverage.coverage_status==="low"?`<div class="pref-intel-warning"><b>원천 우대정보 제공률이 낮습니다.</b> 판별 가능 ${pct(coverage.known_preference_share)} · 미제공 ${Number(coverage.missing_count||0).toLocaleString("ko-KR")}건. 원천 미제공을 조건 없음으로 해석하지 않습니다.</div>`:"";
    const head='<thead><tr><th>조건</th><th>전체 우대조건 상품</th><th>상위금리 우대조건 상품</th><th>차이</th></tr></thead>';
    const more=rest.length?`<details class="ux-pref-more"><summary>나머지 조건 ${rest.length}개 보기</summary><table class="pref-intel-table">${head}<tbody>${rows(rest)}</tbody></table></details>`:"";
    const present=Number(coverage.present_count||0),known=Number(coverage.known_preference_count||0);
    return`<section class="ux-pref-sector pref-intel-main"><div class="ux-pref-sector-head"><div><b>${esc(title)}</b><div class="pref-v2-count">우대조건 상품 ${present.toLocaleString("ko-KR")}개 / 판별 가능 ${known.toLocaleString("ko-KR")}개</div></div><span>${term}개월${sub?` · ${esc(sub)}`:""}</span></div>${warning}<div class="pref-intel-summary"><div><span>우대조건 보유율</span><b>${pct(coverage.preference_bearing_share_among_known)}</b></div><div><span>상위군 보유율</span><b>${pct(topCoverage.preference_bearing_share_among_known)}</b></div><div><span>상위금리 기준</span><b>${Number.isFinite(Number(top.cutoff_rate))?Number(top.cutoff_rate).toFixed(2)+"%":"—"}</b></div></div><table class="pref-intel-table">${head}<tbody>${visible.length?rows(visible):'<tr><td colspan="4">우대조건 보유 상품에서 분류 가능한 조건이 없습니다.</td></tr>'}</tbody></table>${more}<div class="pref-v2-denom-note"><b>비중 분모:</b> 실제 우대조건 보유 상품. 한 상품이 여러 조건에 포함될 수 있어 합계는 100%를 넘을 수 있습니다.</div>${sourceStrip(item)}${showOwn?own(item.our_company):""}</section>`;
  }
  function render(){
    const panel=$("preference-intelligence"),body=$("preference-intelligence-body");if(!panel||!body)return;
    const intelligence=data().strategy?.preference_intelligence;if(!intelligence)return;
    panel.dataset.preferenceV2="1";
    panel.querySelectorAll("[data-pi-term]").forEach(b=>b.classList.toggle("active",Number(b.dataset.piTerm)===term));
    let scopeHost=panel.querySelector(".ux-pref-scope");if(!scopeHost){scopeHost=document.createElement("div");scopeHost.className="ux-pref-scope";panel.querySelector(".pref-intel-controls")?.prepend(scopeHost)}
    const selected=mutualSelected(),current=mode(),parts=[];
    if(current!=="mutual_finance")parts.push(card("저축은행",scope("savings_bank",intelligence),{showOwn:true,sub:"저축은행 시장"}));
    if(current!=="savings_bank"&&selected.length){parts.push(card("상호금융 통합",mutualScope(selected,intelligence),{sub:selected.map(k=>labels[k]).join("+")}))}
    body.innerHTML=parts.length?`<div class="ux-pref-grid">${parts.join("")}</div>`:'<div class="pref-intel-empty">상호금융 세부업권을 하나 이상 선택하세요.</div>';
    const tags=[];if(current!=="mutual_finance")tags.push("저축은행");if(current!=="savings_bank"&&selected.length)tags.push(`상호금융 통합 · ${selected.map(k=>labels[k]).join("+")}`);scopeHost.innerHTML=`<b>상단 선택 연동</b>${tags.map(x=>`<span class="ux-pref-scope-tag">${esc(x)}</span>`).join("")}`;
    const copy=panel.querySelector(".pref-intel-head p");if(copy)copy.textContent=`${term}개월 · 우대조건 보유 상품 내부의 조건 비중과 상위금리군 차이를 비교합니다.`;
    const caveat=panel.querySelector(".pref-intel-caveat");if(caveat)caveat.innerHTML='<b>분모는 우대조건 보유 상품입니다.</b> 원천 제공률은 별도 품질 근거이며, 미제공(MISSING)은 조건 없음(NONE)으로 해석하지 않습니다. 구조 비교이지 수신효과 추정이 아닙니다.';
  }
  function install(){
    if(document.documentElement.dataset.preferenceIntelligenceV2==="1")return;
    const panel=$("preference-intelligence");if(!panel)return;
    panel.querySelectorAll("[data-pi-term]").forEach(button=>button.addEventListener("click",()=>{term=Number(button.dataset.piTerm)||12;setTimeout(render,0)}));
    $("market-scope")?.addEventListener("click",()=>setTimeout(render,0));
    $("market-scope")?.addEventListener("change",()=>setTimeout(render,0));
    render();document.documentElement.dataset.preferenceIntelligenceV2="1";
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
""".strip()


def inject_strategy_readability_preference_v2(html: str) -> str:
    """Strategy 최종 계층에 readable scale과 Preference v2 UX를 주입한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Strategy readability/preference v2 주입 상태가 불완전하다")
    required = (
        'id="strategy-ux-refinement-style"',
        'id="preference-intelligence"',
        'id="market-scope"',
    )
    if any(marker not in html for marker in required):
        raise DashboardBuildError("Strategy readability/preference v2 선행 계약을 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
