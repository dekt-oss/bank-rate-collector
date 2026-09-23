# ruff: noqa: E501
"""Strategy presentation for the fail-closed market special-offer radar."""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="special-offer-radar-style"'
SCRIPT_MARKER = 'id="special-offer-radar-script"'

_CSS = r"""
<style id="special-offer-radar-style">
.special-radar{margin:0 0 12px;padding:18px;overflow:hidden}.special-radar-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.special-radar-head h2{margin:0;color:var(--ink);font-size:16px;letter-spacing:-.03em}.special-radar-head p{margin:4px 0 0;color:var(--muted);font-size:10.5px;line-height:1.55}.special-radar-badge{flex:0 0 auto;padding:5px 8px;border:1px solid rgba(169,116,26,.22);border-radius:999px;background:rgba(169,116,26,.07);color:#806538;font-size:9.5px;font-weight:780}.special-radar-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}.special-radar-metric{min-width:0;padding:12px;border:1px solid var(--line);border-radius:11px;background:var(--panel2,#FCFAFC)}.special-radar-metric span{display:block;color:var(--muted);font-size:9.5px}.special-radar-metric b{display:block;margin-top:6px;color:var(--ink);font:780 22px/1 var(--mono)}.special-radar-metric small{display:block;margin-top:6px;color:var(--soft);font-size:9px;line-height:1.4}.special-radar-table-wrap{overflow:auto;border:1px solid var(--line);border-radius:11px;background:var(--panel,#fff)}.special-radar-table{width:100%;min-width:720px;border-collapse:collapse}.special-radar-table th{padding:8px 9px;border-bottom:1px solid var(--line);color:var(--soft);background:var(--panel2,#FCFAFC);font-size:9px;text-align:right}.special-radar-table th:first-child,.special-radar-table th:nth-child(2),.special-radar-table td:first-child,.special-radar-table td:nth-child(2){text-align:left}.special-radar-table td{padding:9px;border-bottom:1px solid var(--line);color:var(--ink);font-size:9.5px;text-align:right}.special-radar-table tr:last-child td{border-bottom:0}.special-radar-table td:first-child,.special-radar-table td:nth-child(2){font-weight:700}.special-radar-table .rate{font:780 11px var(--mono);color:var(--accent-ink,var(--green))}.special-radar-table a{color:var(--accent-ink,var(--green));font-weight:720;text-decoration:none}.special-radar-empty{display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:start;padding:14px;border:1px solid rgba(169,116,26,.16);border-radius:11px;background:rgba(169,116,26,.045);color:#6F6250}.special-radar-empty strong{display:grid;place-items:center;width:28px;height:28px;border-radius:9px;background:rgba(169,116,26,.10);color:#8A682B;font:800 12px var(--mono)}.special-radar-empty b{display:block;color:#5E4B2A;font-size:10.5px}.special-radar-empty p{margin:4px 0 0;font-size:9.5px;line-height:1.55}.special-radar-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 9px}.special-radar-tab{border:1px solid var(--line);border-radius:999px;background:var(--panel,#fff);color:var(--muted);padding:6px 10px;font:750 9.5px var(--sans);cursor:pointer}.special-radar-tab[aria-selected="true"]{border-color:rgba(107,47,116,.28);background:rgba(107,47,116,.08);color:var(--accent-ink,#6b2f74)}.special-radar-tab-panel[hidden]{display:none}.special-radar-table{min-width:1040px}.special-radar-table td:nth-child(n+3),.special-radar-table th:nth-child(n+3){text-align:left}.special-radar-table .rate{text-align:right}.special-radar-evidence small{display:block;margin-top:3px;color:var(--soft);font-size:9px}.special-radar-foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:9px;color:var(--soft);font-size:9px;line-height:1.5}.special-radar-foot b{color:var(--ink)}
@media(max-width:760px){.special-radar{padding:14px}.special-radar-head{flex-direction:column;gap:10px}.special-radar-metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.special-radar-metric{padding:11px}.special-radar-metric span{font-size:10px}.special-radar-metric small{font-size:9.5px}.special-radar-foot{flex-direction:column;gap:3px}}@media(max-width:340px){.special-radar-metrics{grid-template-columns:1fr}}@media(max-width:420px){.special-radar-empty{grid-template-columns:1fr}.special-radar-empty p{font-size:10px}}
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
const offers=Array.isArray(payload.offers)?payload.offers:[];
const currentOffers=Array.isArray(payload.current_offers)?payload.current_offers:[];
const pastOffers=Array.isArray(payload.past_offers)?payload.past_offers:[];
const rate=v=>Number.isFinite(Number(v))?`${Number(v).toFixed(2)}%`:"—";
const metric=(label,value,note)=>`<div class="special-radar-metric"><span>${label}</span><b>${Number(value||0).toLocaleString("ko-KR")}</b><small>${note}</small></div>`;
const terms=x=>x?.special_offer_terms||{};
const period=x=>{const t=terms(x),a=t.sale_start,b=t.sale_end;if(a&&b)return `${esc(a)} ~ ${esc(b)}`;if(a)return `${esc(a)} ~`;if(b)return `~ ${esc(b)}`;return "—"};
const quota=x=>esc(terms(x).quota_text||"—");
const eligibility=x=>esc(terms(x).eligibility_text||"—");
const early=x=>esc(terms(x).early_termination_text||"—");
const specialRate=x=>rate(terms(x).special_rate);
const evidenceLink=x=>{const href=safeHref(x.availability_source_locator||x.evidence_ref||x.evidence_source_locator);const when=x.availability_observed_at||x.evidence_observed_at||"";return `<span class="special-radar-evidence">${href?`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">근거 보기</a>`:"기록됨"}${when?`<small>${esc(String(when).slice(0,16).replace("T"," "))}</small>`:""}</span>`};
function offerTable(items,emptyText){if(!items.length)return `<div class="special-radar-empty"><strong>0</strong><div><b>${esc(emptyText)}</b><p>판매상태를 공식 근거로 확인한 특판만 이 탭에 표시합니다.</p></div></div>`;return `<div class="special-radar-table-wrap"><table class="special-radar-table"><thead><tr><th>금융사</th><th>상품</th><th>특판금리</th><th>판매기간</th><th>한도</th><th>가입대상</th><th>조기종료 조건</th><th>공식 근거</th></tr></thead><tbody>${items.map(x=>`<tr><td>${esc(x.institution_name)}</td><td>${esc(x.product_name)}</td><td class="rate">${specialRate(x)}</td><td>${period(x)}</td><td>${quota(x)}</td><td>${eligibility(x)}</td><td>${early(x)}</td><td>${evidenceLink(x)}</td></tr>`).join("")}</tbody></table></div>`}
function tabbedOffers(){const pending=Number(availability.unknown||0);return `<div class="special-radar-tabs" role="tablist" aria-label="특판 판매상태"><button type="button" class="special-radar-tab" role="tab" data-radar-tab="current" aria-selected="true">현재 판매 중 ${currentOffers.length.toLocaleString("ko-KR")}</button><button type="button" class="special-radar-tab" role="tab" data-radar-tab="past" aria-selected="false">과거 특판 이력 ${pastOffers.length.toLocaleString("ko-KR")}</button></div>${pending?`<div class="special-radar-empty"><strong>?</strong><div><b>판매상태 확인 중 ${pending.toLocaleString("ko-KR")}건</b><p>특판 분류는 확인됐지만 현재 판매 여부를 확정할 공식 근거가 없어 어느 탭에도 넣지 않습니다.</p></div></div>`:""}<div class="special-radar-tab-panel" data-radar-panel="current">${offerTable(currentOffers,"현재 판매 중으로 확인된 특판이 없습니다.")}</div><div class="special-radar-tab-panel" data-radar-panel="past" hidden>${offerTable(pastOffers,"종료가 확인된 과거 특판 이력이 없습니다.")}</div>`}
function emptyState(){return `<div class="special-radar-empty"><strong>대기</strong><div><b>현재 확정된 특판은 0건입니다.</b><p>FSB 일반 공시는 금리정보는 주지만 특판 여부를 명시하지 않아 현재 ${Number(counts.unknown||0).toLocaleString("ko-KR")}건을 미판정으로 보존합니다. 공식 상품페이지 등 상품 단위 명시 근거가 확보되면 Radar에 축적합니다.</p></div></div>`}
function bindTabs(section){section.querySelectorAll("[data-radar-tab]").forEach(button=>button.addEventListener("click",()=>{const key=button.dataset.radarTab;section.querySelectorAll("[data-radar-tab]").forEach(x=>x.setAttribute("aria-selected",String(x===button)));section.querySelectorAll("[data-radar-panel]").forEach(panel=>{panel.hidden=panel.dataset.radarPanel!==key})}))}
function install(){if($("special-offer-radar"))return;const anchor=$("market-flow");if(!anchor)return;const section=document.createElement("section");section.id="special-offer-radar";section.className="card special-radar";const classified=currentOffers.length+pastOffers.length+Number(availability.unknown||0);section.dataset.radarState=classified?"evidence":"pending";const badge=classified?`현재 ${currentOffers.length} · 과거 ${pastOffers.length} · 확인중 ${Number(availability.unknown||0)}`:"공식근거 0건 · 수집 중";const title=classified?"시장 특판 Radar":"특판 Radar · 근거 수집 중";const copy=classified?"확정 특판을 현재 판매 중과 과거 이력으로 분리합니다. 판매상태 미확정은 어느 탭에도 넣지 않습니다.":"현재 FSB 일반 공시만으로는 특판 여부를 확정할 수 없습니다. 추정하지 않고 공식 상품단위 근거를 축적 중입니다.";section.innerHTML=`<div class="special-radar-head"><div><h2>${title}</h2><p>${copy}</p></div><span class="special-radar-badge">${badge}</span></div><div class="special-radar-metrics">${metric("현재 판매 중",availability.confirmed_active,"공식 판매상태 확인")}${metric("과거 특판 이력",availability.confirmed_ended,"종료·마감 확인")}${metric("판매상태 확인중",availability.unknown,"current/past 미배치")}${metric("특판 미판정",counts.unknown,"일반 공시만 있는 상품")}</div>${classified?tabbedOffers():emptyState()}<div class="special-radar-foot"><span>기준일 <b>${esc(payload.as_of||"—")}</b> · 원천 <b>${esc(payload.source_id||"—")}</b></span><span>정책: <b>특판 분류와 판매상태 분리</b> · 일반 금리/Relative Pricing 모집단 변경 없음</span></div>`;anchor.parentNode.insertBefore(section,anchor);bindTabs(section)}
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
