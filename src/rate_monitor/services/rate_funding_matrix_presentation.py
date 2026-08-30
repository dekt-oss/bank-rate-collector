# ruff: noqa: E501
"""Strategy presentation for temporally aligned Rate × Funding matrix."""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="rate-funding-matrix-style"'
SCRIPT_MARKER = 'id="rate-funding-matrix-script"'

_CSS = r"""
<style id="rate-funding-matrix-style">
.rate-funding-matrix{margin:0 0 12px;padding:18px}.rate-funding-matrix-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:12px}.rate-funding-matrix-head h2{margin:0;font-size:16px;letter-spacing:-.03em}.rate-funding-matrix-head p{margin:4px 0 0;color:var(--muted);font-size:10.5px;line-height:1.55}.rate-funding-matrix-tabs{display:flex;gap:5px;flex-wrap:wrap}.rate-funding-matrix-tabs button{border:1px solid var(--line);border-radius:8px;background:var(--panel2);color:var(--muted);padding:7px 10px;font-size:9.5px;font-weight:720;cursor:pointer}.rate-funding-matrix-tabs button.active{border-color:rgba(128,200,166,.38);background:rgba(128,200,166,.11);color:var(--green)}.rate-funding-matrix-meta{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}.rate-funding-matrix-kpi{padding:11px;border:1px solid var(--line);border-radius:11px;background:var(--panel2)}.rate-funding-matrix-kpi span{display:block;color:var(--muted);font-size:9px}.rate-funding-matrix-kpi b{display:block;margin-top:5px;color:var(--ink);font:760 17px/1.1 var(--mono)}.rate-funding-matrix-kpi small{display:block;margin-top:4px;color:var(--soft);font-size:9px}.rate-funding-matrix-blocked{padding:20px;border:1px solid rgba(212,179,111,.24);border-radius:12px;background:rgba(212,179,111,.055)}.rate-funding-matrix-blocked b{display:block;color:var(--gold);font-size:12px}.rate-funding-matrix-blocked p{margin:7px 0 0;color:var(--muted);font-size:10px;line-height:1.65}.rate-funding-matrix-chart{position:relative;height:410px;border:1px solid var(--line);border-radius:12px;background:var(--panel2);overflow:hidden}.rate-funding-matrix-chart svg{width:100%;height:100%;display:block}.rate-funding-matrix-axis{color:var(--soft);font-size:9px}.rate-funding-matrix-note{margin-top:9px;color:var(--soft);font-size:9px;line-height:1.6}.rate-funding-matrix-note strong{color:#b7c9c0}.rate-funding-matrix-legend{display:flex;justify-content:space-between;gap:8px;margin:7px 4px 0;color:var(--soft);font-size:9px}.rate-funding-matrix-badge{display:inline-flex;padding:4px 7px;border:1px solid rgba(128,200,166,.23);border-radius:999px;background:rgba(128,200,166,.07);color:var(--green);font-size:9px;font-weight:720}.rate-funding-matrix-badge.blocked{border-color:rgba(212,179,111,.25);background:rgba(212,179,111,.07);color:var(--gold)}
@media(max-width:800px){.rate-funding-matrix-head{flex-direction:column}.rate-funding-matrix-meta{grid-template-columns:repeat(2,minmax(0,1fr))}.rate-funding-matrix-chart{height:340px}}@media(max-width:520px){.rate-funding-matrix{padding:14px}.rate-funding-matrix-chart{height:300px}}
</style>
"""

_JS = r"""
<script id="rate-funding-matrix-script">
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num=v=>v===null||v===undefined||v===""?null:Number(v);
const pct=(v,d=1)=>{const x=num(v);return Number.isFinite(x)?`${(x*100).toFixed(d)}%`:"—"};
const rate=v=>{const x=num(v);return Number.isFinite(x)?`${x.toFixed(2)}%`:"—"};
const root=(()=>{try{return JSON.parse($("rate-monitor-data")?.textContent||"{}")?.strategy?.rate_funding_matrix||null}catch{return null}})();
if(!root?.sectors||!Object.keys(root.sectors).length)return;
const order=(root.display_order||Object.keys(root.sectors)).filter(k=>root.sectors[k]);
if(!order.length)return;
let active=order[0];
function kpi(label,value,small){return `<div class="rate-funding-matrix-kpi"><span>${esc(label)}</span><b>${esc(value)}</b><small>${esc(small)}</small></div>`}
function meta(d){return [kpi("Funding 6M 비교",`${Number(d.funding_growth_6m_institutions||0).toLocaleString("ko-KR")}개`,`${esc(d.analysis_month)} 기준`),kpi("동일시점 금리",`${Number(d.historical_rate_institutions||0).toLocaleString("ko-KR")}개`,`12M 정기예금 공시 최고금리`),kpi("정확 결합",`${Number(d.paired_institutions||0).toLocaleString("ko-KR")}개`,d.pair_coverage_ratio?`결합률 ${pct(d.pair_coverage_ratio)}`:"결합률 산정 불가"),kpi("소급 차단",`${Number(d.current_rate_institutions_not_carried_back||0).toLocaleString("ko-KR")}개`,`현재 금리를 과거월에 미사용`)].join("")}
function blocked(d){return `<div class="rate-funding-matrix-blocked"><b>시점정합 금리 이력이 부족해 Matrix를 열지 않습니다.</b><p>${esc(d.analysis_month)} 수신잔액과 같은 시점에 유효했던 12개월 정기예금 공시 최고금리를 찾지 못했습니다. 현재 공시금리가 존재하더라도 과거 수신잔액에 소급해 붙이지 않습니다. 동일시점 exact pair가 확보되면 이 영역은 자동으로 사분면 Matrix로 전환됩니다.</p></div>`}
function chart(d){const pts=(d.points||[]).map(p=>({...p,x:num(p.rate_pct),y:num(p.growth_6m_pct),b:num(p.balance_million_krw)})).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&Number.isFinite(p.b));if(pts.length<2)return blocked(d);let minX=Math.min(...pts.map(p=>p.x)),maxX=Math.max(...pts.map(p=>p.x)),minY=Math.min(...pts.map(p=>p.y)),maxY=Math.max(...pts.map(p=>p.y));if(minX===maxX){minX-=.05;maxX+=.05}if(minY===maxY){minY-=.005;maxY+=.005}const mx=num(d.median_rate_pct),my=num(d.median_growth_6m_pct),pad=36,w=900,h=390,sx=x=>pad+(x-minX)/(maxX-minX)*(w-pad*2),sy=y=>h-pad-(y-minY)/(maxY-minY)*(h-pad*2),balances=pts.map(p=>Math.max(1,p.b)),minB=Math.min(...balances),maxB=Math.max(...balances),radius=b=>maxB===minB?6:4+Math.sqrt((Math.max(1,b)-minB)/(maxB-minB))*9;const circles=pts.map(p=>`<circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="${radius(p.b).toFixed(1)}" fill="rgba(128,200,166,.42)" stroke="rgba(169,214,193,.85)" stroke-width="1"><title>${esc(p.institution||"기관명 미확인")} · 금리 ${rate(p.x)} · 6M ${pct(p.y)}</title></circle>`).join("");const vx=Number.isFinite(mx)?sx(mx):w/2,hy=Number.isFinite(my)?sy(my):h/2;return `<div class="rate-funding-matrix-chart"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="12개월 대표 공시 최고금리와 6개월 수신잔액 변화 Matrix"><line x1="${vx}" y1="${pad}" x2="${vx}" y2="${h-pad}" stroke="rgba(212,179,111,.45)" stroke-dasharray="5 5"/><line x1="${pad}" y1="${hy}" x2="${w-pad}" y2="${hy}" stroke="rgba(212,179,111,.45)" stroke-dasharray="5 5"/>${circles}<text x="${w-pad}" y="${h-8}" text-anchor="end" fill="currentColor" class="rate-funding-matrix-axis">12M 대표 공시 최고금리 →</text><text x="12" y="${pad}" fill="currentColor" class="rate-funding-matrix-axis">↑ 6M 수신증가율</text></svg></div><div class="rate-funding-matrix-legend"><span>중앙선: 동월 exact pair 중앙값</span><span>버블: 수신잔액 규모</span></div>`}
function render(sector){const d=root.sectors[sector];if(!d)return;active=sector;document.querySelectorAll("#rate-funding-matrix-tabs button").forEach(b=>b.classList.toggle("active",b.dataset.sector===sector));$("rate-funding-matrix-status").innerHTML=`<span class="rate-funding-matrix-badge ${d.available?"":"blocked"}">${d.available?"시점정합 Matrix":"과거금리 이력 부족"} · ${esc(d.analysis_month)}</span>`;$("rate-funding-matrix-meta").innerHTML=meta(d);$("rate-funding-matrix-body").innerHTML=d.available?chart(d):blocked(d);$("rate-funding-matrix-note").innerHTML=`<strong>${esc(d.label)}</strong>의 12개월 대표 공시 <strong>최고금리</strong>와 exact 6M 수신잔액 증감률의 동월 연관성 비교입니다. 기관 대표금리는 기존 Strategy와 동일하게 presentation.db_only_sources 우선순위를 적용한 뒤 상품별 공시 최고금리 대표값 중 기관 최고값을 사용합니다. 사분면 경계는 고정 임계값이 아니라 결합된 동일 업권 모집단의 중앙값입니다. 이 화면은 인과효과 판정이 아닙니다.`}
function install(){if($("rate-funding-matrix"))return;const anchor=$("institution-funding-position")||$("market-funding-competition")||$("external-market-context");if(!anchor)return;const section=document.createElement("section");section.id="rate-funding-matrix";section.className="card rate-funding-matrix";section.innerHTML=`<div class="rate-funding-matrix-head"><div><h2>Rate × Funding Matrix</h2><p>12개월 대표 공시 최고금리와 6M 수신잔액 변화는 반드시 같은 시점 계약으로만 결합합니다.</p></div><div id="rate-funding-matrix-status"></div></div><div id="rate-funding-matrix-tabs" class="rate-funding-matrix-tabs">${order.map(k=>`<button type="button" data-sector="${k}">${esc(root.sectors[k].label||k)}</button>`).join("")}</div><div id="rate-funding-matrix-meta" class="rate-funding-matrix-meta"></div><div id="rate-funding-matrix-body"></div><div id="rate-funding-matrix-note" class="rate-funding-matrix-note"></div>`;anchor.insertAdjacentElement("afterend",section);$("rate-funding-matrix-tabs").addEventListener("click",e=>{const b=e.target.closest("button[data-sector]");if(b)render(b.dataset.sector)});render(active)}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_rate_funding_matrix(html: str) -> str:
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        return html
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy HTML의 head/body 종료 지점을 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
