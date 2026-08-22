"""Public Structural v2 금리결정 Cockpit presentation.

실제 시장위치와 미보정 구조 시나리오를 같은 금리축에 보여주되 인과처럼
합치지 않는다. UI는 Stage D Decision Surface와 Stage E Marginal output만
소비하며 structural 내부 coefficient/formula를 직접 재구현하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="public-structural-v2-cockpit-style"'
ENGINE_MARKER = 'id="public-structural-v2-engine-bundle"'
SCRIPT_MARKER = 'id="public-structural-v2-cockpit-script"'

_ENGINE_FILES = (
    "inflow_engine.js",
    "market_position.js",
    "decision_contract.js",
    "surface.js",
    "marginal.js",
)

_CSS = r"""
<style id="public-structural-v2-cockpit-style">
.psv2{display:grid;gap:14px;margin-top:14px;padding:14px;border:1px solid rgba(118,177,151,.22);border-radius:15px;background:linear-gradient(145deg,rgba(7,24,19,.82),rgba(12,31,25,.58));box-shadow:inset 0 1px 0 rgba(255,255,255,.025)}
.psv2 *{box-sizing:border-box}.psv2-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.psv2-head h3{margin:0;color:#e4eee9;font-size:13px;letter-spacing:-.02em}.psv2-head p{margin:4px 0 0;color:#71867b;font-size:9.5px;line-height:1.55}.psv2-badge{flex:none;padding:5px 8px;border:1px solid rgba(212,179,111,.28);border-radius:999px;background:rgba(212,179,111,.08);color:#d5bc82;font-size:8.5px;font-weight:800;letter-spacing:.04em}
.psv2-decision{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.psv2-card{min-width:0;padding:12px;border:1px solid rgba(215,230,222,.09);border-radius:12px;background:rgba(2,12,9,.34)}.psv2-card.market{border-color:rgba(105,183,148,.22);background:rgba(55,112,87,.08)}.psv2-card.scenario{border-color:rgba(212,179,111,.22);background:rgba(112,83,36,.08)}.psv2-kicker{display:block;margin-bottom:7px;color:#6f8278;font-size:8.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}.psv2-card strong{display:block;color:#e7f0eb;font:800 17px/1.15 var(--mono)}.psv2-card strong.gold{color:#d8bd80}.psv2-card strong.green{color:#8bd2b0}.psv2-card small{display:block;margin-top:5px;color:#708379;font-size:8.8px;line-height:1.5}.psv2-card .minor{margin-top:7px;padding-top:7px;border-top:1px solid rgba(215,230,222,.07);color:#8da097;font:700 9px var(--mono)}
.psv2-separator{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:9px;color:#657a70;font-size:8.5px;font-weight:800;letter-spacing:.04em}.psv2-separator:before,.psv2-separator:after{content:"";height:1px;background:linear-gradient(90deg,transparent,rgba(140,171,156,.2))}.psv2-separator:after{transform:scaleX(-1)}
.psv2-grid{display:grid;grid-template-columns:minmax(0,.88fr) minmax(0,1.12fr);gap:10px}.psv2-panel{min-width:0;padding:12px;border:1px solid rgba(215,230,222,.08);border-radius:12px;background:rgba(2,12,9,.25)}.psv2-panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:10px}.psv2-panel-head b{color:#dfeae4;font-size:10.5px}.psv2-panel-head span{color:#697d73;font-size:8.5px;line-height:1.45;text-align:right}
.psv2-ladder{position:relative;height:198px;margin:4px 8px 0}.psv2-ladder-line{position:absolute;left:26px;top:10px;bottom:10px;width:2px;border-radius:2px;background:linear-gradient(180deg,rgba(212,179,111,.62),rgba(116,196,158,.48),rgba(77,100,89,.22))}.psv2-rung{position:absolute;left:0;right:0;transform:translateY(-50%);display:grid;grid-template-columns:18px 1fr auto;align-items:center;gap:8px}.psv2-rung i{justify-self:end;width:8px;height:8px;border:2px solid #789087;border-radius:50%;background:#0d2019;box-shadow:0 0 0 3px rgba(120,144,135,.08)}.psv2-rung.current i{border-color:#7d9b8d}.psv2-rung.proposal i{width:10px;height:10px;border-color:#d5b66f;background:#2a2416;box-shadow:0 0 0 4px rgba(212,179,111,.12)}.psv2-rung.cutoff i{border-color:#77c29d}.psv2-rung.max i{border-color:#d8bd80}.psv2-rung label{min-width:0;color:#82958c;font-size:8.7px;font-weight:720;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.psv2-rung strong{color:#d7e2dc;font:760 9px var(--mono)}.psv2-rung.proposal label,.psv2-rung.proposal strong{color:#dec17f}.psv2-rung.same label:after{content:" · 동률";color:#9f8b5c}
.psv2-crowding{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px}.psv2-mini{padding:8px;border:1px solid rgba(215,230,222,.07);border-radius:9px;background:rgba(255,255,255,.015)}.psv2-mini span{display:block;color:#64786e;font-size:8px}.psv2-mini b{display:block;margin-top:4px;color:#d6e1db;font:760 10px var(--mono)}
.psv2-chart-wrap{position:relative;min-height:220px}.psv2-chart{display:block;width:100%;height:220px;overflow:visible}.psv2-chart .grid{stroke:rgba(214,229,221,.08);stroke-width:1}.psv2-chart .axis{fill:#64786e;font:8px var(--mono)}.psv2-chart .band{fill:rgba(126,190,160,.09);stroke:none}.psv2-chart .base-line{fill:none;stroke:#8acbab;stroke-width:2.2}.psv2-chart .ref{stroke:rgba(212,179,111,.24);stroke-width:1;stroke-dasharray:3 3}.psv2-chart .ref.market{stroke:rgba(113,183,151,.22)}.psv2-chart .point{fill:#0d2119;stroke:#8acbab;stroke-width:2}.psv2-chart .point.proposal{stroke:#d5b66f;stroke-width:2.5}.psv2-chart .label{fill:#81958b;font:8px var(--sans)}.psv2-chart-legend{display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:5px;color:#64776e;font-size:8.3px}.psv2-chart-legend b{color:#8fc9ad}.psv2-chart-legend em{font-style:normal;color:#d6b974}
.psv2-empty{padding:18px 12px;border:1px dashed rgba(215,230,222,.12);border-radius:10px;color:#758980;font-size:9px;line-height:1.6;text-align:center}.psv2-disclosure{padding:9px 11px;border-left:2px solid rgba(212,179,111,.42);border-radius:0 8px 8px 0;background:rgba(112,83,36,.08);color:#9f9270;font-size:8.8px;line-height:1.55}.psv2-disclosure b{color:#ccb576}
.psv2-table-wrap{overflow:auto;border:1px solid rgba(215,230,222,.07);border-radius:11px}.psv2-table{width:100%;min-width:850px;border-collapse:collapse}.psv2-table th{padding:8px 9px;border-bottom:1px solid rgba(215,230,222,.08);color:#687c72;font-size:8.3px;text-align:right;white-space:nowrap}.psv2-table th:first-child,.psv2-table td:first-child{text-align:left}.psv2-table td{padding:9px;border-bottom:1px solid rgba(215,230,222,.055);color:#cbd8d1;font:700 8.8px var(--mono);text-align:right;white-space:nowrap}.psv2-table tbody tr:last-child td{border-bottom:0}.psv2-table tr.current{background:rgba(114,184,151,.05)}.psv2-table tr.proposal{background:rgba(212,179,111,.055)}.psv2-table .rate-label{display:block;color:#dde8e2;font:780 9.2px var(--sans)}.psv2-table .rate-note{display:block;margin-top:2px;color:#65786f;font:8px var(--sans)}.psv2-table .gold{color:#d6b974}.psv2-table .green{color:#8bceb0}.psv2-table .muted{color:#65776f}.psv2-table-foot{display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:7px;color:#60736a;font-size:8.2px}.psv2-error{padding:10px;border:1px solid rgba(193,108,108,.18);border-radius:10px;background:rgba(97,42,42,.08);color:#b98f8f;font-size:9px;line-height:1.55}
.prediction-panel.psv2-active>.prediction-results,.prediction-panel.psv2-active>.model-detail,.prediction-panel.psv2-active>.model-evidence,.prediction-panel.psv2-active>.warning,.prediction-panel.psv2-active .rate-response-wrap{display:none!important}
@media(max-width:900px){.psv2-decision{grid-template-columns:1fr 1fr}.psv2-decision .scenario{grid-column:1/-1}.psv2-grid{grid-template-columns:1fr}.psv2-ladder{height:175px}}
@media(max-width:520px){.psv2{padding:10px;gap:11px}.psv2-head{display:block}.psv2-badge{display:inline-block;margin-top:8px}.psv2-decision{grid-template-columns:1fr}.psv2-decision .scenario{grid-column:auto}.psv2-card{padding:11px}.psv2-card strong{font-size:15px}.psv2-crowding{grid-template-columns:1fr 1fr}.psv2-panel{padding:10px}.psv2-chart{height:205px}.psv2-chart-wrap{min-height:205px}}
</style>
"""

_JS = r"""
<script id="public-structural-v2-cockpit-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const OUR_INSTITUTION="고려저축은행";
  const ECONOMICS_RADIUS_PP=.15;
  const MARKET_CONFIG={
    version:"public-structural-v2-market-position-v1",
    rate_normalization_decimals:4,
    counterfactual:"replace_anchor_product",
    top10_share:.10,
    top25_share:.25,
    crowding_windows_pp:[.05,.10]
  };
  let tablePromise=null;
  let renderToken=0;

  function inlineData(){
    const el=$("rate-monitor-data");
    if(!el)throw new Error("rate-monitor-data:missing");
    return JSON.parse(String(el.textContent||"").replace(/<\\\//g,"</"));
  }
  function finite(value){
    if(value===null||value===undefined||String(value).trim()==="")return null;
    const number=Number(value);
    return Number.isFinite(number)?number:null;
  }
  function pct(value,digits=2){return Number.isFinite(value)?`${Number(value).toFixed(digits)}%`:"—";}
  function amount(value){return Number.isFinite(value)?`${Number(value).toLocaleString("ko-KR",{maximumFractionDigits:1})}억원`:"—";}
  function signedAmount(value){return Number.isFinite(value)?`${value>=0?"+":""}${Number(value).toLocaleString("ko-KR",{maximumFractionDigits:1})}억원`:"—";}
  function rankText(position){
    if(!position)return"—";
    return position.rank_best===position.rank_worst
      ?`${position.rank_best}위 / ${position.universe_count}개`
      :`${position.rank_best}~${position.rank_worst}위 / ${position.universe_count}개`;
  }
  function decode(table,column,value){
    const lookup=table.lookups?.[column];
    return lookup&&value!==null&&value!==undefined?lookup[value]:value;
  }
  function decodedRows(table){
    const columns=table.columns||[],index=Object.fromEntries(columns.map((name,i)=>[name,i]));
    const get=(row,name)=>name in index?decode(table,name,row[index[name]]):null;
    return (table.rows||[]).map(row=>({
      sector:get(row,"sector"),product_type:get(row,"product_type"),term_months:Number(get(row,"term_months")),
      max_rate:finite(get(row,"max_rate")),product_id:String(get(row,"product_id")??""),
      institution:String(get(row,"institution")??""),product:String(get(row,"product")??""),
      source_effective_at:String(get(row,"source_effective_at")??"")
    }));
  }
  async function loadTable(){
    if(tablePromise)return tablePromise;
    const data=inlineData(),url=data.table_url;
    if(!url)throw new Error("strategy-table:url_missing");
    tablePromise=fetch(url,{cache:"no-store"}).then(response=>{
      if(!response.ok)throw new Error(`strategy-table:http_${response.status}`);
      return response.json();
    }).then(decodedRows);
    return tablePromise;
  }
  function marketMode(){return document.querySelector("[data-market-mode].active")?.dataset.marketMode||"savings_bank";}
  function activeSectors(){
    const mutual=[...document.querySelectorAll("[data-sector]:checked")].map(el=>el.dataset.sector).filter(Boolean);
    const mode=marketMode();
    if(mode==="savings_bank")return["savings_bank"];
    if(mode==="mutual_finance")return mutual;
    return["savings_bank",...mutual];
  }
  function selectedTerm(){return Number(document.querySelector("#term-segment button.active")?.dataset.term||12);}
  function proposalRate(){
    const base=finite($("base-n")?.value),bonus=finite($("bonus-n")?.value);
    return base===null||bonus===null?null:Number((base+bonus).toFixed(4));
  }
  function scenarioInputs(){
    return {
      baseline_new_money:finite($("baseline-new")?.value),
      maturity_amount:finite($("maturity-amount")?.value),
      current_rollover_rate_pct:finite($("rollover-rate")?.value)
    };
  }
  function aggregate(rows,term,sectors){
    const allowed=new Set(sectors),map=new Map();
    for(const row of rows){
      if(!allowed.has(row.sector)||row.product_type!=="term_deposit"||row.term_months!==term||row.max_rate===null||!row.product_id)continue;
      const key=`${row.sector}\0${row.product_id}\0${term}`,old=map.get(key);
      if(!old||row.max_rate>old.max_rate||(row.max_rate===old.max_rate&&row.source_effective_at>old.source_effective_at))map.set(key,row);
    }
    return [...map.values()].sort((a,b)=>b.max_rate-a.max_rate||a.institution.localeCompare(b.institution,"ko")||a.product.localeCompare(b.product,"ko"));
  }
  function marketContext(rows){
    const term=selectedTerm(),sectors=activeSectors(),products=aggregate(rows,term,sectors);
    const anchor=products.filter(row=>row.sector==="savings_bank"&&row.institution===OUR_INSTITUTION)
      .sort((a,b)=>b.max_rate-a.max_rate||a.product_id.localeCompare(b.product_id))[0];
    if(!anchor)throw new Error("현재 선택 범위에서 고려저축은행 anchor 상품을 찾지 못했습니다.");
    const marketRows=products.map(row=>({product_id:`${row.sector}:${row.product_id}`,rate:row.max_rate}));
    return {term,sectors,products,anchor,anchorId:`${anchor.sector}:${anchor.product_id}`,marketRows};
  }
  function ensureHost(){
    const panel=$("prediction-panel");if(!panel)return null;
    let host=$("public-structural-v2-cockpit");
    if(host)return host;
    host=document.createElement("section");host.id="public-structural-v2-cockpit";host.className="psv2";
    host.setAttribute("aria-label","Public Structural v2 금리결정 Cockpit");
    const inputs=panel.querySelector(".predict-inputs");
    (inputs||panel.firstElementChild)?.insertAdjacentElement("afterend",host);
    return host;
  }
  function errorHtml(message){return `<div class="psv2-error"><b>Public Structural v2를 표시하지 못했습니다.</b><br>${String(message||"알 수 없는 오류")}</div>`;}
  function markerRows(position,current,proposal){
    const values=[
      {key:"max",label:"시장 최고",rate:position.market_max_rate,klass:"max"},
      {key:"top10",label:"상위 10% 진입선",rate:position.top10_cutoff,klass:"cutoff"},
      {key:"top25",label:"상위 25% 진입선",rate:position.top25_cutoff,klass:"cutoff"},
      {key:"median",label:"시장 중앙값",rate:position.median_rate,klass:""},
      {key:"current",label:"고려저축은행 현재",rate:current,klass:"current"},
      {key:"proposal",label:"제안금리",rate:proposal,klass:"proposal"}
    ];
    const min=Math.min(...values.map(x=>x.rate)),max=Math.max(...values.map(x=>x.rate)),span=Math.max(.01,max-min);
    return values.map(row=>({...row,top:8+84*(max-row.rate)/span,same:values.some(other=>other!==row&&Math.abs(other.rate-row.rate)<.00005)}));
  }
  function ladderHtml(position,current,proposal){
    return markerRows(position,current,proposal).map(row=>`<div class="psv2-rung ${row.klass}${row.same?" same":""}" style="top:${row.top.toFixed(2)}%"><i></i><label>${row.label}</label><strong>${pct(row.rate)}</strong></div>`).join("");
  }
  function chartHtml(surface,proposal){
    const rows=surface.forecast?.scenarios||[];
    if(rows.length<2)return '<div class="psv2-empty">구조 시나리오 금리점이 부족합니다.</div>';
    const width=620,height=220,pad={l:46,r:16,t:20,b:30};
    const rates=rows.map(row=>Number(row.rate_pct)),lows=rows.map(row=>Number(row.predicted_total_lower)),highs=rows.map(row=>Number(row.predicted_total_upper)),bases=rows.map(row=>Number(row.predicted_total));
    const xMin=Math.min(...rates),xMax=Math.max(...rates),yMin=Math.min(...lows),yMax=Math.max(...highs),xSpan=Math.max(.01,xMax-xMin),ySpan=Math.max(1,yMax-yMin);
    const x=v=>pad.l+(v-xMin)/xSpan*(width-pad.l-pad.r),y=v=>height-pad.b-(v-yMin)/ySpan*(height-pad.t-pad.b);
    const upper=rows.map((row,i)=>`${x(rates[i]).toFixed(1)},${y(highs[i]).toFixed(1)}`).join(" ");
    const lower=[...rows].reverse().map((row,reverseIndex)=>{const i=rows.length-1-reverseIndex;return`${x(rates[i]).toFixed(1)},${y(lows[i]).toFixed(1)}`;}).join(" ");
    const basePath=rows.map((row,i)=>`${i?"L":"M"}${x(rates[i]).toFixed(1)} ${y(bases[i]).toFixed(1)}`).join(" ");
    const yTicks=[0,.5,1].map(f=>{const value=yMin+ySpan*f;return`<line class="grid" x1="${pad.l}" x2="${width-pad.r}" y1="${y(value)}" y2="${y(value)}"/><text class="axis" x="${pad.l-6}" y="${y(value)+3}" text-anchor="end">${Math.round(value)}</text>`;}).join("");
    const xTicks=rows.map((row,i)=>`<text class="axis" x="${x(rates[i])}" y="${height-10}" text-anchor="middle">${rates[i].toFixed(2)}</text>`).join("");
    const refs=(surface.candidate_set?.factual_markers||[]).filter(marker=>marker.labels.some(label=>["top25","top10","market_max"].includes(label))).map(marker=>`<line class="ref market" x1="${x(marker.rate_pct)}" x2="${x(marker.rate_pct)}" y1="${pad.t}" y2="${height-pad.b}"/>`).join("");
    const points=rows.map((row,i)=>`<circle class="point ${Math.abs(rates[i]-proposal)<.00005?"proposal":""}" cx="${x(rates[i])}" cy="${y(bases[i])}" r="${Math.abs(rates[i]-proposal)<.00005?4.5:3.2}"/>`).join("");
    return `<div class="psv2-chart-wrap"><svg class="psv2-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="금리별 미보정 구조 시나리오 총수신 stress range"><polygon class="band" points="${upper} ${lower}"/>${yTicks}${refs}<path class="base-line" d="${basePath}"/>${points}${xTicks}<text class="label" x="${pad.l}" y="11">총수신(억원)</text></svg><div class="psv2-chart-legend"><span><b>● 기준 민감도</b></span><span>음영 = 실제 min/max stress range</span><span><em>● 제안금리</em></span><span>점선 = 시장 threshold 참고선</span></div></div>`;
  }
  function marginalMap(marginal){
    return new Map((marginal?.marginals||[]).map(row=>[Number(row.to_rate_pct).toFixed(4),row]));
  }
  function candidateTable(surface,marginal,current,proposal){
    const forecastByRate=new Map((surface.forecast?.scenarios||[]).map(row=>[Number(row.rate_pct).toFixed(4),row]));
    const posByRate=new Map((surface.market_positions||[]).map(row=>[Number(row.proposal_rate).toFixed(4),row]));
    const marginalByTo=marginalMap(marginal),grid=new Set((surface.candidate_set?.economics_grid||[]).map(rate=>Number(rate).toFixed(4)));
    return [...forecastByRate.keys()].sort((a,b)=>Number(a)-Number(b)).map(key=>{
      const row=forecastByRate.get(key),position=posByRate.get(key),rate=Number(key),isCurrent=Math.abs(rate-current)<.00005,isProposal=Math.abs(rate-proposal)<.00005,m=marginalByTo.get(key),onGrid=grid.has(key);
      const threshold=position.top10_reached?"TOP10 도달":position.top25_reached?"TOP25 도달":"TOP25 미만";
      return `<tr class="${isCurrent?"current":""} ${isProposal?"proposal":""}"><td><span class="rate-label">${pct(rate)}</span><span class="rate-note">${isCurrent?"현재":isProposal?"현재 제안":onGrid?"5bp grid":"제안 별도점"}</span></td><td>${rankText(position)}</td><td>${position?.tie_competitor_count??"—"}개</td><td>${threshold}</td><td class="green">${amount(row.predicted_total)}</td><td>${amount(row.predicted_total_lower)} ~ ${amount(row.predicted_total_upper)}</td><td>${signedAmount(row.incremental_total)}</td><td class="${m?"gold":"muted"}">${m?signedAmount(m.surface_interest_delta):"—"}</td></tr>`;
    }).join("");
  }
  function marketOnlyHtml(position,current,proposal){
    return `<div class="psv2-head"><div><h3>금리결정 Cockpit</h3><p>실제 시장위치와 미보정 구조 시나리오를 분리해 비교합니다.</p></div><span class="psv2-badge">PUBLIC STRUCTURAL v2</span></div><div class="psv2-decision"><div class="psv2-card"><span class="psv2-kicker">제안금리</span><strong>${pct(proposal)}</strong><small>현재 ${pct(current)} · ${proposal>=current?"+":""}${((proposal-current)*100).toFixed(0)}bp</small></div><div class="psv2-card market"><span class="psv2-kicker">실제 시장 위치</span><strong class="green">${rankText(position)}</strong><small>동률 비교상품 ${position.tie_competitor_count}개 · TOP10 ${pct(position.top10_cutoff)}</small><div class="minor">TOP25 ${pct(position.top25_cutoff)} · 중앙값 ${pct(position.median_rate)}</div></div><div class="psv2-card scenario"><span class="psv2-kicker">미보정 구조 시나리오</span><strong class="gold">입력 3개 필요</strong><small>최근 월 신규수신 · 다음 만기도래액 · 현재 재예치율을 입력하면 stress range를 표시합니다.</small></div></div><div class="psv2-separator">시장 사실과 구조 시나리오는 별도 정보입니다</div><div class="psv2-grid"><div class="psv2-panel"><div class="psv2-panel-head"><b>Market Position Ladder</b><span>동일금리는 동률로 겹쳐 표시</span></div><div class="psv2-ladder"><div class="psv2-ladder-line"></div>${ladderHtml(position,current,proposal)}</div><div class="psv2-crowding"><div class="psv2-mini"><span>정확 동률</span><b>${position.exact_tie_count}개</b></div><div class="psv2-mini"><span>±5bp 내</span><b>${position.within_5bp_count}개</b></div><div class="psv2-mini"><span>새로 엄격 우위</span><b>${position.newly_outpriced}개</b></div><div class="psv2-mini"><span>새로 동률</span><b>${position.newly_tied}개</b></div></div></div><div class="psv2-panel"><div class="psv2-panel-head"><b>수신반응 Response Surface</b><span>수신 입력 전에는 계산하지 않음</span></div><div class="psv2-empty">세 입력값을 넣으면 기준 민감도 선과 min/max stress band를 표시합니다.<br>시장 순위·밀집도는 금액식에 직접 반영되지 않습니다.</div></div></div>`;
  }
  function fullHtml(surface,marginal,current,proposal){
    const proposalKey=Number(proposal).toFixed(4),forecast=(surface.forecast?.scenarios||[]).find(row=>Number(row.rate_pct).toFixed(4)===proposalKey),position=(surface.market_positions||[]).find(row=>Number(row.proposal_rate).toFixed(4)===proposalKey);
    const nextMarginal=(marginal?.marginals||[]).find(row=>Math.abs(row.from_rate_pct-proposal)<.00005)||null;
    const costCopy=nextMarginal?`${pct(nextMarginal.from_rate_pct)} → ${pct(nextMarginal.to_rate_pct)} · ${signedAmount(nextMarginal.surface_interest_delta)}`:"제안금리가 5bp grid 밖이면 비교 없음";
    return `<div class="psv2-head"><div><h3>금리결정 Cockpit</h3><p>실제 시장위치 → 별도 구조 시나리오 → 고정 5bp 표면비용 순서로 읽습니다.</p></div><span class="psv2-badge">PUBLIC STRUCTURAL v2</span></div><div class="psv2-decision"><div class="psv2-card"><span class="psv2-kicker">제안금리</span><strong>${pct(proposal)}</strong><small>현재 ${pct(current)} · ${proposal>=current?"+":""}${((proposal-current)*100).toFixed(0)}bp</small></div><div class="psv2-card market"><span class="psv2-kicker">실제 시장 위치</span><strong class="green">${rankText(position)}</strong><small>동률 ${position.tie_competitor_count}개 · TOP10 ${pct(position.top10_cutoff)} · TOP25 ${pct(position.top25_cutoff)}</small><div class="minor">±5bp 경쟁상품 ${position.within_5bp_count}개 · 새로 엄격 우위 ${position.newly_outpriced}개</div></div><div class="psv2-card scenario"><span class="psv2-kicker">미보정 구조 시나리오</span><strong class="gold">${amount(forecast.predicted_total)}</strong><small>stress range ${amount(forecast.predicted_total_lower)} ~ ${amount(forecast.predicted_total_upper)}</small><div class="minor">현재 대비 ${signedAmount(forecast.incremental_total)} · 다음 5bp 표면비용 ${costCopy}</div></div></div><div class="psv2-separator">시장 사실 ≠ 수신금액의 직접 원인</div><div class="psv2-grid"><div class="psv2-panel"><div class="psv2-panel-head"><b>Market Position Ladder</b><span>시장 최고 · TOP10 · TOP25 · 중앙값 · 현재 · 제안</span></div><div class="psv2-ladder"><div class="psv2-ladder-line"></div>${ladderHtml(position,current,proposal)}</div><div class="psv2-crowding"><div class="psv2-mini"><span>정확 동률</span><b>${position.exact_tie_count}개</b></div><div class="psv2-mini"><span>±5bp 내</span><b>${position.within_5bp_count}개</b></div><div class="psv2-mini"><span>새로 엄격 우위</span><b>${position.newly_outpriced}개</b></div><div class="psv2-mini"><span>새로 동률</span><b>${position.newly_tied}개</b></div></div></div><div class="psv2-panel"><div class="psv2-panel-head"><b>Response Surface</b><span>기준 민감도 + 실제 min/max stress band</span></div>${chartHtml(surface,proposal)}</div></div><div class="psv2-disclosure"><b>해석 주의:</b> ${surface.disclosure} 음영은 confidence/prediction interval이 아니라 저·기준·고 민감도 결과의 실제 최소~최대 범위입니다.</div><div><div class="psv2-panel-head"><b>후보금리 비교</b><span>고정 5bp grid + 현재 제안 · off-grid 제안의 marginal은 —</span></div><div class="psv2-table-wrap"><table class="psv2-table"><thead><tr><th>금리</th><th>공동순위 범위</th><th>동률</th><th>시장 threshold</th><th>기준 총수신</th><th>stress range</th><th>현재 대비</th><th>직전 5bp 표면비용</th></tr></thead><tbody>${candidateTable(surface,marginal,current,proposal)}</tbody></table></div><div class="psv2-table-foot"><span>표면비용은 단순 표면이자 변화액이며 FTP/ALM 경제원가가 아닙니다.</span><span>수신 1억원당 비용·연환산 한계조달금리는 현재 버전에서 노출하지 않습니다.</span></div></div>`;
  }
  async function render(){
    const token=++renderToken,host=ensureHost();if(!host)return;
    try{
      const rows=await loadTable();if(token!==renderToken)return;
      const context=marketContext(rows),proposal=proposalRate();
      if(proposal===null)throw new Error("제안금리를 확인할 수 없습니다.");
      const position=PublicStructuralV2MarketPosition.marketPosition({rows:context.marketRows,anchor_product_id:context.anchorId,current_own_rate:context.anchor.max_rate,proposal_rate:proposal},MARKET_CONFIG);
      const inputs=scenarioInputs(),hasInputs=Object.values(inputs).every(value=>value!==null);
      if(!hasInputs){host.innerHTML=marketOnlyHtml(position,context.anchor.max_rate,proposal);return;}
      const data=inlineData(),inflowConfig=data.strategy?.inflow_prediction;
      if(!inflowConfig?.scenarios?.length)throw new Error("Public Structural inflow config가 없습니다.");
      const minRate=Math.max(0,Number((context.anchor.max_rate-ECONOMICS_RADIUS_PP).toFixed(4))),maxRate=Number((context.anchor.max_rate+ECONOMICS_RADIUS_PP).toFixed(4));
      const surface=PublicStructuralV2Surface.buildSurface({generated_at:data.generated_at||new Date().toISOString(),market_rows:context.marketRows,anchor_product_id:context.anchorId,current_own_rate:context.anchor.max_rate,proposal_rate:proposal,economics_min_rate:minRate,economics_max_rate:maxRate,baseline_new_money:inputs.baseline_new_money,maturity_amount:inputs.maturity_amount,current_rollover_rate_pct:inputs.current_rollover_rate_pct,term_months:context.term},PublicStructuralV2MarketPosition,MARKET_CONFIG,PublicStructuralV2DecisionContract,PublicStructuralV2Inflow,inflowConfig);
      const marginal=PublicStructuralV2Marginal.buildFixed5bpMarginals(surface);
      if(token!==renderToken)return;
      host.innerHTML=fullHtml(surface,marginal,context.anchor.max_rate,proposal);
      $("prediction-panel")?.classList.add("psv2-active");
    }catch(error){
      if(token!==renderToken)return;
      host.innerHTML=errorHtml(error?.message||error);
    }
  }
  function install(){
    const panel=$("prediction-panel");if(!panel||$("public-structural-v2-cockpit")?.dataset.installed)return;
    const host=ensureHost();if(!host)return;host.dataset.installed="1";
    ["baseline-new","maturity-amount","rollover-rate","base-n","bonus-n","base-r","bonus-r"].forEach(id=>{const el=$(id);if(el){el.addEventListener("input",()=>setTimeout(render,0));el.addEventListener("change",()=>setTimeout(render,0));}});
    document.querySelectorAll("[data-market-mode],[data-sector],#term-segment button").forEach(el=>el.addEventListener("click",()=>setTimeout(render,40)));
    render();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def _engine_bundle() -> str:
    root = Path(__file__).resolve().parents[3] / "web" / "public-structural-v2"
    sources: list[str] = []
    for name in _ENGINE_FILES:
        path = root / name
        if not path.exists():
            raise DashboardBuildError(f"Public Structural v2 browser engine이 없다: {path}")
        source = path.read_text(encoding="utf-8")
        if "</script" in source.lower():
            raise DashboardBuildError(f"browser engine에 script 종료 marker가 있다: {name}")
        sources.append(source)
    return '<script id="public-structural-v2-engine-bundle">\n' + "\n".join(sources) + "\n</script>"


def inject_public_structural_v2_cockpit(html: str) -> str:
    """실제 Strategy 템플릿에 Public Structural v2 Cockpit을 주입한다."""
    states = (STYLE_MARKER in html, ENGINE_MARKER in html, SCRIPT_MARKER in html)
    if all(states):
        return html
    if any(states):
        raise DashboardBuildError("Public Structural v2 Cockpit 주입 상태가 불완전하다")
    required = (
        'id="planning-zone"',
        'id="prediction-panel"',
        'id="rate-monitor-data"',
        'id="term-segment"',
    )
    missing = [marker for marker in required if marker not in html]
    if missing:
        raise DashboardBuildError(
            "Public Structural v2 Cockpit 선행 DOM 계약이 없다: " + ", ".join(missing)
        )
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Public Structural v2 Cockpit 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    rendered = rendered.replace("</body>", _engine_bundle() + "\n" + _JS + "\n</body>", 1)
    return rendered
