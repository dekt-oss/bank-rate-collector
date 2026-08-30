# ruff: noqa: E501
"""Inject institution funding relative-position UI into the Strategy page."""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="institution-funding-position-style"'
SCRIPT_MARKER = 'id="institution-funding-position-script"'

_CSS = r"""
<style id="institution-funding-position-style">
.funding-position{margin:0 0 12px;padding:18px}.funding-position-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.funding-position-head h2{margin:0;font-size:16px;letter-spacing:-.03em}.funding-position-head p{margin:4px 0 0;color:var(--muted);font-size:10.5px;line-height:1.55}.funding-position-status{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.funding-position-badge{padding:5px 8px;border:1px solid rgba(128,200,166,.23);border-radius:999px;background:rgba(128,200,166,.075);color:var(--green);font-size:9.5px;font-weight:760;white-space:nowrap}.funding-position-badge.partial{border-color:rgba(212,179,111,.26);background:rgba(212,179,111,.08);color:var(--gold)}
.funding-position-tabs{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px}.funding-position-tabs button{border:1px solid var(--line);border-radius:8px;background:var(--panel2);color:var(--muted);padding:7px 10px;font-size:9.5px;font-weight:720;cursor:pointer}.funding-position-tabs button.active{border-color:rgba(128,200,166,.38);background:rgba(128,200,166,.11);color:var(--green)}
.funding-position-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}.funding-position-kpi{min-width:0;padding:12px;border:1px solid var(--line);border-radius:11px;background:var(--panel2)}.funding-position-kpi span{display:block;color:var(--muted);font-size:9px}.funding-position-kpi b{display:block;margin-top:5px;color:var(--ink);font:760 20px/1.1 var(--mono)}.funding-position-kpi small{display:block;margin-top:5px;color:var(--soft);font-size:8.8px}
.funding-position-table-wrap{overflow:auto;max-height:430px;border:1px solid var(--line);border-radius:11px;background:var(--panel2)}.funding-position-table{width:100%;border-collapse:collapse;min-width:760px}.funding-position-table th{position:sticky;top:0;z-index:1;padding:8px;background:var(--panel2);border-bottom:1px solid var(--line);color:var(--soft);font-size:9px;text-align:right;white-space:nowrap}.funding-position-table th:first-child,.funding-position-table td:first-child{text-align:left}.funding-position-table td{padding:9px 8px;border-bottom:1px solid var(--line);color:var(--ink);font:650 9.5px var(--mono);text-align:right;white-space:nowrap}.funding-position-table td:first-child{font-family:var(--sans);font-weight:720}.funding-position-table tr:last-child td{border-bottom:0}.funding-position-table .up{color:var(--green)}.funding-position-table .down{color:var(--red)}.funding-position-percentile{display:inline-flex;align-items:center;justify-content:center;min-width:40px;padding:2px 5px;border-radius:999px;background:rgba(128,200,166,.07);color:#a9d6c1}.funding-position-note{margin-top:9px;color:var(--soft);font-size:9px;line-height:1.55}.funding-position-note strong{color:#b7c9c0}.funding-position-empty{padding:28px;color:var(--muted);font-size:10px;text-align:center}
@media(max-width:800px){.funding-position-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.funding-position-head{flex-direction:column}.funding-position-status{justify-content:flex-start}}@media(max-width:520px){.funding-position{padding:14px}.funding-position-kpis{grid-template-columns:1fr 1fr}.funding-position-kpi b{font-size:17px}}
</style>
"""

_JS = r"""
<script id="institution-funding-position-script">
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const n=v=>v===null||v===undefined||v===""?null:Number(v);
const pct=(v,d=1)=>{const x=n(v);return Number.isFinite(x)?`${x>=0?"+":""}${(x*100).toFixed(d)}%`:"—"};
const percentile=v=>{const x=n(v);return Number.isFinite(x)?`${x.toFixed(0)}%`:"—"};
const coveragePct=v=>{const x=n(v);return Number.isFinite(x)?`${(x*100).toFixed(1)}%`:"산정 불가"};
const money=v=>{const x=n(v);if(!Number.isFinite(x))return "—";const won=x*1e6;if(won>=1e12)return `${(won/1e12).toLocaleString("ko-KR",{maximumFractionDigits:2})}조`;return `${(won/1e8).toLocaleString("ko-KR",{maximumFractionDigits:0})}억`};
const root=(()=>{try{return JSON.parse($("rate-monitor-data")?.textContent||"{}")?.strategy?.institution_funding_positions||null}catch{return null}})();
if(!root?.available)return;
const sectors=root.sectors||{};
const order=["savings_bank","cu","nh_local"].filter(key=>sectors[key]);
if(!order.length)return;
function statusHtml(data){const c=data.coverage||{},ratio=n(c.coverage_ratio),partial=Number.isFinite(ratio)&&ratio<.95;return `<span class="funding-position-badge">${esc(data.analysis_month)} 기준</span><span class="funding-position-badge ${partial?"partial":""}">${partial?"부분 모집단 · ":""}${c.observed_institutions??0}/${c.eligible_institutions??"?"} · ${coveragePct(c.coverage_ratio)}</span>`}
function kpis(data){const c=data.coverage||{},a=data.availability||{},observed=Number(c.observed_institutions||0),g6=Number(a.growth_6m_institutions||0),g12=Number(a.growth_12m_institutions||0);return `<div class="funding-position-kpi"><span>동일 기준월 관측</span><b>${observed.toLocaleString("ko-KR")}개</b><small>백분위 모집단</small></div><div class="funding-position-kpi"><span>기관 coverage</span><b>${coveragePct(c.coverage_ratio)}</b><small>${c.eligible_institutions?`대상 ${Number(c.eligible_institutions).toLocaleString("ko-KR")}개`:"분모 미확정"}</small></div><div class="funding-position-kpi"><span>6M 비교 가능</span><b>${g6.toLocaleString("ko-KR")}개</b><small>${observed?`${(g6/observed*100).toFixed(1)}% of observed`:"—"}</small></div><div class="funding-position-kpi"><span>12M 비교 가능</span><b>${g12.toLocaleString("ko-KR")}개</b><small>${observed?`${(g12/observed*100).toFixed(1)}% of observed`:"—"}</small></div>`}
function table(data){const rows=data.rows||[];if(!rows.length)return '<div class="funding-position-empty">동일 기준월 verified 기관 데이터가 없습니다.</div>';return `<div class="funding-position-table-wrap"><table class="funding-position-table"><thead><tr><th>기관</th><th>수신잔액</th><th>규모 백분위</th><th>6M</th><th>6M 성장 백분위</th><th>12M</th><th>12M 성장 백분위</th><th>Peer 중앙값 대비</th></tr></thead><tbody>${rows.slice(0,40).map(row=>{const g6=n(row.growth_6m_pct),g12=n(row.growth_12m_pct),rel=n(row.relative_growth_6m_vs_peer_median);return `<tr><td>${esc(row.institution||row.institution_id)}</td><td>${money(row.balance_million_krw)}</td><td><span class="funding-position-percentile">${percentile(row.balance_percentile)}</span></td><td class="${Number.isFinite(g6)?(g6>=0?"up":"down"):""}">${pct(row.growth_6m_pct)}</td><td>${percentile(row.growth_6m_percentile)}</td><td class="${Number.isFinite(g12)?(g12>=0?"up":"down"):""}">${pct(row.growth_12m_pct)}</td><td>${percentile(row.growth_12m_percentile)}</td><td class="${Number.isFinite(rel)?(rel>=0?"up":"down"):""}">${pct(row.relative_growth_6m_vs_peer_median)}</td></tr>`}).join("")}</tbody></table></div>`}
function render(sector){const data=sectors[sector];if(!data)return;document.querySelectorAll("#funding-position-tabs button").forEach(b=>b.classList.toggle("active",b.dataset.sector===sector));$("funding-position-status").innerHTML=statusHtml(data);$("funding-position-kpis").innerHTML=kpis(data);$("funding-position-table-body").innerHTML=table(data);$("funding-position-note").innerHTML=`<strong>${esc(data.label)}</strong> 기관별 공시 예수부채의 동일 기준월 상대비교입니다. ECOS 업권 수신잔액과 합계 일치를 전제하지 않으며, 과거월이 없으면 6M/12M을 0으로 채우지 않습니다.`}
function install(){if($("institution-funding-position"))return;const anchor=$("market-funding-competition")||$("external-market-context")||$("market-intelligence")||$("market-flow");if(!anchor)return;const section=document.createElement("section");section.id="institution-funding-position";section.className="card funding-position";section.innerHTML=`<div class="funding-position-head"><div><h2>기관 수신 포지션</h2><p>수신규모 자체가 아니라 같은 업권·같은 기준월에서 얼마나 크고 빠르게 변했는지 비교합니다.</p></div><div id="funding-position-status" class="funding-position-status"></div></div><div id="funding-position-tabs" class="funding-position-tabs">${order.map(key=>`<button type="button" data-sector="${key}">${esc(sectors[key].label||key)}</button>`).join("")}</div><div id="funding-position-kpis" class="funding-position-kpis"></div><div id="funding-position-table-body"></div><div id="funding-position-note" class="funding-position-note"></div>`;anchor.insertAdjacentElement("afterend",section);$("funding-position-tabs").addEventListener("click",event=>{const button=event.target.closest("button[data-sector]");if(button)render(button.dataset.sector)});render(order.includes("cu")?"cu":order[0])}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_institution_funding_position(html: str) -> str:
    """Add a data-driven panel without changing the Strategy template contract."""
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        return html
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy HTML의 head/body 종료 지점을 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
