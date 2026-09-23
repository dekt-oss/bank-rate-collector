# ruff: noqa: E501
"""Strategy presentation for the fail-closed market special-offer radar."""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="special-offer-radar-style"'
SCRIPT_MARKER = 'id="special-offer-radar-script"'

_CSS = r"""
<style id="special-offer-radar-style">
.special-radar{margin:0 0 12px;padding:18px;overflow:hidden}.special-radar-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.special-radar-head h2{margin:0;color:var(--ink);font-size:16px;letter-spacing:-.03em}.special-radar-head p{margin:4px 0 0;color:var(--muted);font-size:10.5px;line-height:1.55}.special-radar-badge{flex:0 0 auto;padding:5px 8px;border:1px solid rgba(169,116,26,.22);border-radius:999px;background:rgba(169,116,26,.07);color:#806538;font-size:9.5px;font-weight:780}.special-radar-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}.special-radar-metric{min-width:0;padding:12px;border:1px solid var(--line);border-radius:11px;background:var(--panel2,#FCFAFC)}.special-radar-metric span{display:block;color:var(--muted);font-size:9.5px}.special-radar-metric b{display:block;margin-top:6px;color:var(--ink);font:780 22px/1 var(--mono)}.special-radar-metric small{display:block;margin-top:6px;color:var(--soft);font-size:9px;line-height:1.4}.special-radar-table-wrap{overflow:auto;border:1px solid var(--line);border-radius:11px;background:var(--panel,#fff)}.special-radar-table{width:100%;min-width:720px;border-collapse:collapse}.special-radar-table th{padding:8px 9px;border-bottom:1px solid var(--line);color:var(--soft);background:var(--panel2,#FCFAFC);font-size:9px;text-align:right}.special-radar-table th:first-child,.special-radar-table th:nth-child(2),.special-radar-table td:first-child,.special-radar-table td:nth-child(2){text-align:left}.special-radar-table td{padding:9px;border-bottom:1px solid var(--line);color:var(--ink);font-size:9.5px;text-align:right}.special-radar-table tr:last-child td{border-bottom:0}.special-radar-table td:first-child,.special-radar-table td:nth-child(2){font-weight:700}.special-radar-table .rate{font:780 11px var(--mono);color:var(--accent-ink,var(--green))}.special-radar-table a{color:var(--accent-ink,var(--green));font-weight:720;text-decoration:none}.special-radar-empty{display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:start;padding:14px;border:1px solid rgba(169,116,26,.16);border-radius:11px;background:rgba(169,116,26,.045);color:#6F6250}.special-radar-empty strong{display:grid;place-items:center;width:28px;height:28px;border-radius:9px;background:rgba(169,116,26,.10);color:#8A682B;font:800 12px var(--mono)}.special-radar-empty b{display:block;color:#5E4B2A;font-size:10.5px}.special-radar-empty p{margin:4px 0 0;font-size:9.5px;line-height:1.55}.special-radar-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 10px}.special-radar-tab{appearance:none;border:1px solid var(--line);border-radius:9px;background:var(--panel2,#FCFAFC);color:var(--muted);padding:7px 10px;font:760 10px var(--sans);cursor:pointer}.special-radar-tab[aria-selected="true"]{border-color:rgba(91,47,100,.24);background:rgba(91,47,100,.08);color:var(--ink)}.special-radar-tab b{margin-left:4px;font:800 10px var(--mono)}.special-radar-offer-list{display:grid;gap:8px}.special-radar-offer-card{padding:12px;border:1px solid var(--line);border-radius:11px;background:var(--panel,#fff)}.special-radar-offer-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:9px}.special-radar-offer-head b{display:block;color:var(--ink);font-size:11px}.special-radar-offer-head span{display:block;margin-top:2px;color:var(--muted);font-size:9.5px}.special-radar-offer-rate{flex:0 0 auto;color:var(--accent-ink,var(--green));font:820 16px/1 var(--mono)}.special-radar-offer-meta{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px}.special-radar-offer-meta div{min-width:0;padding:8px;border-radius:8px;background:var(--panel2,#FCFAFC)}.special-radar-offer-meta span{display:block;color:var(--soft);font-size:8.8px}.special-radar-offer-meta b{display:block;margin-top:4px;color:var(--ink);font-size:9.5px;line-height:1.4;overflow-wrap:anywhere}.special-radar-offer-evidence{margin-top:8px;font-size:9px}.special-radar-foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:9px;color:var(--soft);font-size:9px;line-height:1.5}.special-radar-foot b{color:var(--ink)}
@media(max-width:760px){.special-radar{padding:14px}.special-radar-head{flex-direction:column;gap:10px}.special-radar-metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.special-radar-metric{padding:11px}.special-radar-metric span{font-size:10px}.special-radar-metric small{font-size:9.5px}.special-radar-offer-meta{grid-template-columns:repeat(2,minmax(0,1fr))}.special-radar-offer-meta span{font-size:9px}.special-radar-offer-meta b{font-size:10px}.special-radar-foot{flex-direction:column;gap:3px}}@media(max-width:340px){.special-radar-metrics{grid-template-columns:1fr}}@media(max-width:420px){.special-radar-empty{grid-template-columns:1fr}.special-radar-empty p{font-size:10px}}
</style>
"""

_JS = r"""
<script id="special-offer-radar-script">
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const safeHref=v=>{const raw=String(v||"").trim();return /^https?:\/\//i.test(raw)?raw:null};
const payload=(()=>{try{return JSON.parse($("rate-monitor-data")?.textContent||"{}")?.strategy?.special_offer_radar||null}catch{return null}})();
if(!payload)return;
const counts=payload.counts||{};
const availability=payload.availability_counts||{};
const currentOffers=Array.isArray(payload.current_offers)?payload.current_offers:[];
const historicalOffers=Array.isArray(payload.historical_offers)?payload.historical_offers:[];
const allOffers=Array.isArray(payload.offers)?payload.offers:[];
const metric=(label,value,note)=>`<div class="special-radar-metric"><span>${label}</span><b>${Number(value||0).toLocaleString("ko-KR")}</b><small>${note}</small></div>`;
const evidenceLink=v=>{const href=safeHref(v);return href?`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">공식 근거 보기</a>`:"근거 기록됨"};
const field=v=>{const text=String(v??"").trim();return text?esc(text):"—"};
const period=x=>{const a=x.source_effective_from,b=x.source_effective_to;if(a&&b)return `${esc(a)} ~ ${esc(b)}`;if(a)return `${esc(a)}부터`;if(b)return `~ ${esc(b)}`;return "—"};
const offerRate=x=>field(x.offer_terms?.special_rate);
function offerCard(x){
  const terms=x.offer_terms||{};
  return `<article class="special-radar-offer-card"><div class="special-radar-offer-head"><div><b>${esc(x.product_name||"상품명 미확인")}</b><span>${esc(x.institution_name||"금융사 미확인")}</span></div><div class="special-radar-offer-rate">${offerRate(x)}</div></div><div class="special-radar-offer-meta"><div><span>판매기간</span><b>${period(x)}</b></div><div><span>판매한도</span><b>${field(terms.sale_limit)}</b></div><div><span>가입대상</span><b>${field(terms.eligibility)}</b></div><div><span>조기종료 조건</span><b>${field(terms.early_termination_condition)}</b></div><div><span>공시 대표금리</span><b>${Number.isFinite(Number(x.representative_rate))?`${Number(x.representative_rate).toFixed(2)}%`:"—"}</b></div></div><div class="special-radar-offer-evidence">${evidenceLink(x.evidence_ref)}</div></article>`;
}
function emptyState(kind){
  if(kind==="current")return `<div class="special-radar-empty"><strong>0</strong><div><b>현재 판매 중으로 확인된 특판이 없습니다.</b><p>특판 근거만으로 현재 판매를 추정하지 않습니다. 공식 판매상태가 확인된 상품만 이 탭에 표시합니다.</p></div></div>`;
  return `<div class="special-radar-empty"><strong>0</strong><div><b>과거 특판 이력이 아직 없습니다.</b><p>공식 종료일이 지났거나 판매종료가 확인된 특판만 이 탭에 기록합니다.</p></div></div>`;
}
function renderOffers(kind){
  const rows=kind==="history"?historicalOffers:currentOffers;
  const host=$("special-radar-offers");
  if(!host)return;
  host.innerHTML=rows.length?`<div class="special-radar-offer-list">${rows.map(offerCard).join("")}</div>`:emptyState(kind);
  document.querySelectorAll(".special-radar-tab").forEach(btn=>btn.setAttribute("aria-selected",btn.dataset.tab===kind?"true":"false"));
}
function install(){
  if($("special-offer-radar"))return;
  const anchor=$("market-flow");if(!anchor)return;
  const section=document.createElement("section");section.id="special-offer-radar";section.className="card special-radar";
  section.dataset.radarState=allOffers.length?"confirmed":"pending";
  const badge=allOffers.length?`특판 근거 ${allOffers.length.toLocaleString("ko-KR")}건`:"공식근거 0건 · 수집 중";
  const title=allOffers.length?"시장 특판 Radar":"특판 Radar · 근거 수집 중";
  const copy=allOffers.length?"현재 판매 여부와 과거 이력을 분리하고, 공식 근거가 있는 조건만 구조화해 보여줍니다.":"현재 FSB 일반 공시만으로는 특판 여부를 확정할 수 없습니다. 공식 상품단위 근거와 판매상태 근거를 별도로 축적 중입니다.";
  section.innerHTML=`<div class="special-radar-head"><div><h2>${title}</h2><p>${copy}</p></div><span class="special-radar-badge">${badge}</span></div><div class="special-radar-metrics">${metric("현재 판매 중",availability.confirmed_active,"판매상태까지 공식 확인")}${metric("과거 특판 이력",availability.confirmed_ended,"종료일 경과 또는 종료 확인")}${metric("판매상태 확인 필요",availability.unknown,"특판은 확인됐지만 현재 여부 미확정")}${metric("특판 여부 미판정",counts.unknown,"일반 공시만으로는 판정하지 않음")}</div><div class="special-radar-tabs" role="tablist" aria-label="특판 Radar 보기"><button type="button" class="special-radar-tab" data-tab="current" role="tab" aria-selected="true">현재 판매 중 <b>${Number(availability.confirmed_active||0).toLocaleString("ko-KR")}</b></button><button type="button" class="special-radar-tab" data-tab="history" role="tab" aria-selected="false">과거 특판 이력 <b>${Number(availability.confirmed_ended||0).toLocaleString("ko-KR")}</b></button></div><div id="special-radar-offers"></div><div class="special-radar-foot"><span>기준일 <b>${esc(payload.as_of||"—")}</b> · 원천 <b>${esc(payload.source_id||"—")}</b></span><span>정책: <b>현재 판매 탭은 confirmed_active 근거 필수</b> · 경쟁순위/Relative Pricing 모집단 변경 없음</span></div>`;
  anchor.parentNode.insertBefore(section,anchor);
  section.querySelectorAll(".special-radar-tab").forEach(btn=>btn.addEventListener("click",()=>renderOffers(btn.dataset.tab)));
  renderOffers("current");
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_special_offer_radar_presentation(html: str) -> str:
    """Inject a read-only Radar card without creating a mutation surface."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Special-offer Radar 주입 상태가 불완전하다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Special-offer Radar 주입 위치를 찾지 못했다")
    if 'id="rate-monitor-data"' not in html or 'id="market-flow"' not in html:
        raise DashboardBuildError("Special-offer Radar Strategy 계약을 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
