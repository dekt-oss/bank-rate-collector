# ruff: noqa: E501
"""Stage D2 우대조건 시장구조 presentation.

D1 ``preference_intelligence`` 결과만 표시한다. 우대조건 침투율의 분모는 실제
우대조건 보유 상품(``preference_status=present``)이며, 원천 제공률은 별도 품질
지표로 분리한다. 상위금리 상품에서 더 자주 관찰되는 조건을 수신증가의 원인으로
해석하지 않으며 내부 실적 보정 전에는 인과효과를 계산하거나 암시하지 않는다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="preference-intelligence-style"'
SCRIPT_MARKER = 'id="preference-intelligence-script"'

_CSS = r"""
<style id="preference-intelligence-style">
.pref-intel{margin:0 0 12px;padding:16px;border:1px solid rgba(212,179,111,.18);border-radius:16px;background:linear-gradient(145deg,rgba(31,28,20,.82),rgba(10,23,19,.97));box-shadow:0 16px 36px rgba(0,0,0,.12)}.pref-intel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:11px}.pref-intel-head h2{margin:0;font-size:15px;letter-spacing:-.02em}.pref-intel-head p{margin:4px 0 0;color:#817d70;font-size:9.5px}.pref-intel-badge{padding:4px 7px;border:1px solid rgba(212,179,111,.24);border-radius:99px;color:#c8ad75;font-size:9px;white-space:nowrap}
.pref-intel-controls{display:flex;gap:8px 12px;flex-wrap:wrap;padding:9px 10px;margin-bottom:10px;border:1px solid rgba(213,225,219,.07);border-radius:11px;background:rgba(4,14,11,.22)}.pref-intel-control{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.pref-intel-control>span{margin-right:2px;color:#756f62;font-size:9px;font-weight:760}.pref-intel-control button{border:1px solid var(--line);border-radius:8px;background:#091813;color:#7d8f86;padding:5px 8px;font-size:9px;font-weight:760;cursor:pointer}.pref-intel-control button.active{color:#eadcba;border-color:rgba(212,179,111,.38);background:rgba(112,83,36,.20)}
.pref-intel-caveat{margin-bottom:10px;padding:9px 11px;border:1px solid rgba(212,179,111,.18);border-radius:10px;background:rgba(112,83,36,.09);color:#a99872;font-size:9px;line-height:1.5}.pref-intel-caveat b{color:#d7bd83}.pref-intel-warning{margin-bottom:10px;padding:9px 11px;border:1px dashed rgba(217,137,137,.22);border-radius:10px;color:#c79999;background:rgba(88,41,41,.09);font-size:9px;line-height:1.5}
.pref-intel-grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(250px,.65fr);gap:10px}.pref-intel-main,.pref-intel-own{border:1px solid rgba(213,225,219,.07);border-radius:12px;background:rgba(5,17,14,.28);overflow:hidden}.pref-intel-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0;border-bottom:1px solid rgba(213,225,219,.07)}.pref-intel-summary div{padding:10px 11px;border-right:1px solid rgba(213,225,219,.06)}.pref-intel-summary div:last-child{border-right:0}.pref-intel-summary span{display:block;color:#6f7d75;font-size:9px}.pref-intel-summary b{display:block;margin-top:3px;color:#d7e2dc;font:780 16px var(--mono)}
.pref-intel-table{width:100%;border-collapse:collapse}.pref-intel-table th{padding:7px 9px;border-bottom:1px solid rgba(213,225,219,.06);color:#6e7b74;font-size:9px;text-align:right}.pref-intel-table th:first-child,.pref-intel-table td:first-child{text-align:left}.pref-intel-table td{padding:8px 9px;border-bottom:1px solid rgba(213,225,219,.05);font-size:9px;text-align:right}.pref-intel-table tbody tr:last-child td{border-bottom:0}.pref-intel-table td:first-child{color:#b9c8c0;font-weight:720}.pref-intel-table .mono{font-family:var(--mono)}.pref-intel-table .positive{color:var(--green)}.pref-intel-table .negative{color:var(--red)}.pref-intel-table .other{color:var(--gold)}
.pref-intel-own{padding:12px}.pref-intel-own h3{margin:0 0 8px;font-size:11px}.pref-intel-own p{margin:0 0 8px;color:#728179;font-size:9px;line-height:1.45}.pref-intel-tags{display:flex;gap:5px;flex-wrap:wrap}.pref-intel-tag{padding:4px 6px;border:1px solid rgba(128,200,166,.18);border-radius:7px;background:rgba(62,109,87,.10);color:#a9c6b7;font-size:9px}.pref-intel-raw{margin-top:10px}.pref-intel-raw summary{cursor:pointer;color:#8f8369;font-size:9px}.pref-intel-raw div{margin-top:6px;padding:7px;border-radius:8px;background:rgba(255,255,255,.025);color:#857f70;font-size:9px;line-height:1.45;white-space:pre-wrap}.pref-intel-empty{padding:18px;border:1px dashed rgba(212,179,111,.20);border-radius:11px;color:#a69369;font-size:9.5px;text-align:center;line-height:1.55}
@media(max-width:900px){.pref-intel-grid{grid-template-columns:1fr}}@media(max-width:560px){.pref-intel{padding:13px}.pref-intel-head{flex-direction:column}.pref-intel-summary{grid-template-columns:1fr 1fr}.pref-intel-summary div:nth-child(2){border-right:0}.pref-intel-summary div:nth-child(3){grid-column:1/-1;border-top:1px solid rgba(213,225,219,.06)}.pref-intel-controls{display:grid;gap:8px}.pref-intel-table{min-width:430px}.pref-intel-main{overflow:auto}}
</style>
"""

_JS = r"""
<script id="preference-intelligence-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const raw=$("rate-monitor-data")?.textContent||"{}";let payload={};
  try{payload=JSON.parse(raw)}catch{return}
  const intelligence=payload.strategy?.preference_intelligence;
  const anchor=document.querySelector(".interpretation");
  if(!intelligence||!anchor||$("preference-intelligence"))return;
  const sectors={savings_bank:"저축은행",cu:"신협",kfcc:"새마을금고",nh_local:"농·축협"};
  const state={sector:"savings_bank",term:12};
  const percent=v=>v===null||v===undefined||!Number.isFinite(Number(v))?"—":`${(Number(v)*100).toFixed(0)}%`;
  const lift=v=>v===null||v===undefined||!Number.isFinite(Number(v))?"—":`${Number(v)>0?"+":""}${Number(v).toFixed(1)}%p`;
  const scope=()=>intelligence.scopes?.find(x=>x.sector===state.sector&&Number(x.term_months)===state.term);

  const panel=document.createElement("section");panel.id="preference-intelligence";panel.className="pref-intel";panel.setAttribute("aria-label","우대조건 시장구조 분석");
  panel.innerHTML=`<div class="pref-intel-head"><div><h2>상품 · 우대조건 전략</h2><p>우대조건 보유 상품 안에서 조건 침투율을 비교합니다.</p></div><span class="pref-intel-badge">D1 Structure Evidence</span></div><div class="pref-intel-controls"><div class="pref-intel-control"><span>업권</span>${Object.entries(sectors).map(([k,v])=>`<button type="button" data-pi-sector="${k}">${v}</button>`).join("")}</div><div class="pref-intel-control"><span>기간</span>${[6,12,24,36].map(v=>`<button type="button" data-pi-term="${v}">${v}개월</button>`).join("")}</div></div><div class="pref-intel-caveat"><b>침투율 분모는 우대조건 보유 상품입니다.</b> 하나의 상품이 여러 조건에 포함될 수 있어 조건별 침투율 합계는 100%를 넘을 수 있습니다. 구조 비교이며 수신효과 추정이 아닙니다.</div><div id="preference-intelligence-body"></div>`;
  anchor.parentNode.insertBefore(panel,anchor);

  function active(){panel.querySelectorAll("[data-pi-sector]").forEach(b=>b.classList.toggle("active",b.dataset.piSector===state.sector));panel.querySelectorAll("[data-pi-term]").forEach(b=>b.classList.toggle("active",Number(b.dataset.piTerm)===state.term));}
  function render(){
    active();const item=scope(),body=$("preference-intelligence-body");if(!body)return;
    if(!item||item.status==="no_data"){body.innerHTML=`<div class="pref-intel-empty">${sectors[state.sector]} · ${state.term}개월 우대조건 비교 데이터가 없습니다.</div>`;return;}
    const coverage=item.coverage||{},top=item.top_tier||{},topCoverage=top.coverage||{};
    const warning=coverage.coverage_status==="low"?`<div class="pref-intel-warning"><b>원천 우대정보 제공률이 낮습니다.</b> 판별 가능 ${percent(coverage.known_preference_share)} · 미제공 ${Number(coverage.missing_count||0).toLocaleString("ko-KR")}건. 미제공을 '조건 없음'으로 해석하지 않습니다.</div>`:"";
    const rows=(item.categories||[]).slice(0,8).map(c=>`<tr><td class="${c.is_other?"other":""}">${c.label}</td><td class="mono">${percent(c.market_product_share)}</td><td class="mono">${percent(c.top_tier_product_share)}</td><td class="mono ${Number(c.top_tier_lift_pp)>0?"positive":Number(c.top_tier_lift_pp)<0?"negative":""}">${lift(c.top_tier_lift_pp)}</td></tr>`).join("")||'<tr><td colspan="4">우대조건 보유 상품에서 분류 가능한 조건이 없습니다.</td></tr>';
    const own=item.our_company;
    const ownHtml=own?`<div class="pref-intel-own"><h3>고려저축은행 현재 조건</h3><p>${own.offering_count}개 대표상품 · 최고 ${Number(own.max_rate).toFixed(2)}%</p><div class="pref-intel-tags">${(own.preference_labels||[]).length?(own.preference_labels||[]).map(x=>`<span class="pref-intel-tag">${x}</span>`).join(""):'<span class="pref-intel-tag">표준분류 조건 없음</span>'}</div>${(own.raw_samples||[]).length?`<details class="pref-intel-raw"><summary>당사 우대조건 원문 근거</summary>${own.raw_samples.map(x=>`<div>${String(x).replaceAll("<","&lt;").replaceAll(">","&gt;")}</div>`).join("")}</details>`:""}</div>`:`<div class="pref-intel-own"><h3>당사 비교</h3><p>${state.sector==="savings_bank"?"현재 선택 기간의 고려저축은행 우대조건 대표데이터가 없습니다.":"고려저축은행은 저축은행 업권에서만 당사 비교를 제공합니다."}</p></div>`;
    body.innerHTML=`${warning}<div class="pref-intel-grid"><div class="pref-intel-main"><div class="pref-intel-summary"><div><span>원천 우대정보 제공률</span><b>${percent(coverage.known_preference_share)}</b></div><div><span>우대조건 보유율</span><b>${percent(coverage.preference_bearing_share_among_known)}</b></div><div><span>상위군 우대조건 보유율</span><b>${percent(topCoverage.preference_bearing_share_among_known)}</b></div></div><table class="pref-intel-table"><thead><tr><th>조건</th><th>전체 우대상품 침투율</th><th>상위금리군 침투율</th><th>침투율 차이</th></tr></thead><tbody>${rows}</tbody></table></div>${ownHtml}</div>`;
  }
  panel.addEventListener("click",event=>{const b=event.target.closest("button");if(!b)return;if(b.dataset.piSector)state.sector=b.dataset.piSector;if(b.dataset.piTerm)state.term=Number(b.dataset.piTerm);render();});
  render();
})();
</script>
"""


def inject_preference_intelligence_presentation(html: str) -> str:
    """Strategy HTML에 D1 기반 D2 우대조건 분석을 한 번만 주입한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Preference Intelligence 주입 상태가 불완전하다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Preference Intelligence 주입 위치를 찾지 못했다")
    if 'id="rate-monitor-data"' not in html or 'class="grid interpretation"' not in html:
        raise DashboardBuildError("기존 Strategy 우대조건 영역 계약을 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
