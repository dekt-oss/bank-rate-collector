# ruff: noqa: E501
"""Strategy 화면의 금리→수신반응 의사결정 UI를 주입한다.

Stage B는 새로운 예측모형을 만드는 단계가 아니다. 기존 Strategy 템플릿과
``inflow_prediction_service``의 JS parity 계약을 그대로 두고, 이미 계산 가능한
수신반응을 실무 의사결정 순서로 재배치한다.

이 모듈은 Strategy 발행 경로에서만 호출된다. 따라서 Production Strategy Release
Gate가 OFF이면 실행되지 않고 공개 메인 화면에도 영향을 주지 않는다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.external_market_context_presentation import (
    inject_external_market_context_presentation,
)
from rate_monitor.services.market_intelligence_presentation import (
    inject_market_intelligence_presentation,
)
from rate_monitor.services.preference_intelligence_presentation import (
    inject_preference_intelligence_presentation,
)
from rate_monitor.services.public_structural_v2_cockpit_presentation import (
    inject_public_structural_v2_cockpit,
)
from rate_monitor.services.strategy_decision_evidence_refinement_presentation import (
    inject_strategy_decision_evidence_refinement,
)
from rate_monitor.services.strategy_readability_preference_v2_presentation import (
    inject_strategy_readability_preference_v2,
)
from rate_monitor.services.strategy_ux_refinement_presentation import (
    inject_strategy_ux_refinement,
)
from rate_monitor.services.strategy_workspace_presentation import (
    inject_strategy_workspace_presentation,
)

STYLE_MARKER = 'id="rate-response-cockpit-style"'
SCRIPT_MARKER = 'id="rate-response-cockpit-script"'

_CSS = r"""
<style id="rate-response-cockpit-style">
.rate-response-caveat{margin:-2px 0 12px;padding:10px 12px;border:1px solid rgba(212,179,111,.26);border-radius:10px;background:rgba(112,83,36,.13);color:#c7b17e;font-size:9.5px;line-height:1.55}.rate-response-caveat b{color:#e1c98f}.rate-response-wrap{display:grid;gap:9px;padding:11px;border:1px solid rgba(128,200,166,.18);border-radius:11px;background:rgba(8,25,20,.35)}.rate-response-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.rate-response-head b{font-size:10.5px;color:#dbe8e1}.rate-response-head span{font-size:9px;color:#6f8479}.rate-response-table{width:100%;min-width:720px;border-collapse:collapse}.rate-response-table th{padding:7px 8px;border-bottom:1px solid var(--line);color:#71837a;font-size:9px;text-align:right}.rate-response-table th:first-child,.rate-response-table td:first-child{text-align:left}.rate-response-table td{padding:9px 8px;border-bottom:1px solid rgba(213,225,219,.06);font:740 9.5px var(--mono);text-align:right}.rate-response-table tbody tr:last-child td{border-bottom:0}.rate-response-table tr.current{background:rgba(128,200,166,.055)}.rate-response-table tr.proposal{background:rgba(212,179,111,.055)}.rate-response-table .scenario-name{display:block;color:#dbe5df;font:760 9.5px var(--sans)}.rate-response-table .scenario-note{display:block;margin-top:2px;color:#607269;font:9px var(--sans)}.rate-response-table .positive{color:var(--green)}.rate-response-table .negative{color:var(--red)}.rate-response-table .cost{color:var(--gold)}.rate-response-empty{padding:13px;border:1px dashed var(--line);border-radius:9px;color:#71837a;font-size:9px;line-height:1.55;text-align:center}.rate-response-scroll{overflow:auto}.rate-response-foot{display:flex;flex-wrap:wrap;gap:6px 12px;color:#63766c;font-size:9px}.market-position-reference{margin:0}.market-position-reference summary{cursor:pointer;list-style:none;padding:8px 10px;border:1px solid var(--line);border-radius:9px;background:rgba(4,14,11,.18);color:#81938a;font-size:9px;font-weight:760}.market-position-reference summary::-webkit-details-marker{display:none}.market-position-reference summary:after{content:" 펼치기";float:right;color:#607269;font-weight:500}.market-position-reference[open] summary:after{content:" 접기"}.market-position-reference-body{display:grid;gap:10px;padding-top:10px}.market-position-reference-body .simresults,.market-position-reference-body .position{grid-column:auto!important;grid-row:auto!important}@media(min-width:980px){.planning-zone .market-position-reference{grid-column:2;grid-row:1/4}}@media(max-width:760px){.rate-response-table{min-width:650px}.rate-response-head{flex-direction:column}}
</style>
"""

_JS = r"""
<script id="rate-response-cockpit-script">
(()=>{
  const $=id=>document.getElementById(id);
  const pct=v=>Number.isFinite(v)?`${v.toFixed(2)}%`:"—";
  const amount=v=>Number.isFinite(v)?`${v.toLocaleString("ko-KR",{maximumFractionDigits:1})}억원`:"—";
  const signedAmount=v=>Number.isFinite(v)?`${v>=0?"+":""}${v.toLocaleString("ko-KR",{maximumFractionDigits:1})}억원`:"—";
  const numFromText=id=>{const el=$(id);if(!el)return null;const m=String(el.textContent||"").replace(/,/g,"").match(/-?\d+(?:\.\d+)?/);return m?Number(m[0]):null};
  const inputNum=id=>{const el=$(id),v=el?Number(el.value):NaN;return Number.isFinite(v)?v:null};
  const termMonths=()=>{const el=document.querySelector("#planning-basis b");const m=String(el?.textContent||"").match(/\d+/);return m?Number(m[0]):12};
  const proposedRate=()=>{const base=inputNum("base-n"),bonus=inputNum("bonus-n");return Number.isFinite(base)&&Number.isFinite(bonus)?base+bonus:null};

  function scenarioDefinitions(own,proposal){
    const rows=[
      {key:"current",label:"현재금리",note:"당사 현재 최고금리",rate:own,current:true},
      {key:"plus5",label:"+5bp",note:"현재 대비 +0.05%p",rate:own+.05},
      {key:"plus10",label:"+10bp",note:"현재 대비 +0.10%p",rate:own+.10},
      {key:"plus15",label:"+15bp",note:"현재 대비 +0.15%p",rate:own+.15},
    ];
    if(Number.isFinite(proposal)&&!rows.some(x=>Math.abs(x.rate-proposal)<.0001))rows.push({key:"proposal",label:"현재 제안",note:"기본금리 + 우대금리",rate:proposal,proposal:true});
    return rows;
  }

  function renderScenarioTable(){
    const host=$("rate-response-body");
    if(!host)return;
    const baseline=inputNum("baseline-new"),maturity=inputNum("maturity-amount"),rollover=inputNum("rollover-rate"),own=numFromText("own-max"),top10=numFromText("sim-top10"),term=termMonths(),proposal=proposedRate();
    const missing=[];
    if(!Number.isFinite(baseline))missing.push("최근 월 신규수신 기준액");
    if(!Number.isFinite(maturity))missing.push("다음 만기도래액");
    if(!Number.isFinite(rollover))missing.push("현재 재예치율");
    if(!Number.isFinite(own))missing.push("고려저축은행 현재금리");
    if(!Number.isFinite(top10))missing.push("시장 상위 10% 진입선");
    if(typeof window.predictInflow!=="function")missing.push("예측엔진");
    if(missing.length){host.innerHTML=`<div class="rate-response-empty">${missing.join(" · ")} 확인 후 금리별 수신반응을 계산합니다.<br>내부 실적 보정 전에는 결과를 실제 forecast로 해석하지 않습니다.</div>`;return;}
    const rows=scenarioDefinitions(own,proposal).map(s=>{
      const result=window.predictInflow({baseline,maturity,rollover,ownRate:own,proposed:s.rate,top10,term}),base=result.base;
      const deltaClass=base.delta>0?"positive":base.delta<0?"negative":"";
      return `<tr class="${s.current?"current":""} ${s.proposal?"proposal":""}"><td><span class="scenario-name">${s.label}</span><span class="scenario-note">${s.note}</span></td><td>${pct(s.rate)}</td><td>${amount(base.newMoney)}</td><td>${amount(base.renewal)}</td><td>${amount(base.total)}</td><td class="${deltaClass}">${signedAmount(base.delta)}</td><td class="cost">${signedAmount(base.cost)}</td></tr>`;
    }).join("");
    host.innerHTML=`<div class="rate-response-scroll"><table class="rate-response-table"><thead><tr><th>시나리오</th><th>금리</th><th>예상 신규자금</th><th>예상 재예치</th><th>예상 총수신</th><th>현재 대비</th><th>추가 표면이자비용</th></tr></thead><tbody>${rows}</tbody></table></div><div class="rate-response-foot"><span>총수신 = 신규자금 + 재예치이며 순수신이 아닙니다.</span><span>비용은 단순 표면이자 기준 · FTP 미반영</span><span>저·기준·고 민감도 중 표에는 기준 시나리오 표시</span></div>`;
  }

  function install(){
    const planning=$("planning-zone"),panel=$("prediction-panel"),toggle=$("prediction-toggle");
    if(!planning||!panel||!toggle||$("rate-response-wrap"))return;
    const title=planning.querySelector(".head h2"),desc=planning.querySelector(".head p"),summary=$("prediction-summary");
    if(title)title.textContent="금리 결정 · 수신반응 시나리오";
    if(desc)desc.textContent="현재 금리와 제안 금리를 바꿨을 때 신규자금·재예치·총수신·추가비용이 어떻게 달라지는지 비교합니다.";
    if(summary)summary.textContent="내부 실적 미보정 · 현재/+5/+10/+15bp와 제안금리의 수신반응을 스트레스 시나리오로 비교";

    const caveat=document.createElement("div");
    caveat.className="rate-response-caveat";
    caveat.innerHTML="<b>내부 실적 미보정 스트레스 시나리오</b> — 현재 계수는 고려저축은행 실적 추정치가 아니며 실제 forecast가 아닙니다. 내부 실적 확보 후 Stage E에서 보정합니다.";
    panel.insertBefore(caveat,panel.firstChild);

    const inputs=panel.querySelector(".predict-inputs");
    const wrap=document.createElement("div");
    wrap.id="rate-response-wrap";
    wrap.className="rate-response-wrap";
    wrap.innerHTML='<div class="rate-response-head"><div><b>금리별 수신반응 비교</b><span>현재 금리를 기준으로 +5bp · +10bp · +15bp 및 현재 제안금리를 한 번에 비교</span></div><span>기준 민감도 시나리오</span></div><div id="rate-response-body"><div class="rate-response-empty">입력값을 확인하는 중입니다.</div></div>';
    if(inputs)inputs.insertAdjacentElement("afterend",wrap);else panel.appendChild(wrap);

    const simresults=planning.querySelector(".simresults"),position=planning.querySelector(".position");
    if(simresults&&position&&!planning.querySelector(".market-position-reference")){
      const details=document.createElement("details");
      details.className="market-position-reference";
      details.innerHTML='<summary>시장 위치 참고 · 순위/상위 10%/포지션</summary><div class="market-position-reference-body"></div>';
      const body=details.querySelector(".market-position-reference-body");
      simresults.parentNode.insertBefore(details,simresults);
      body.appendChild(simresults);
      body.appendChild(position);
    }

    if(panel.hidden){panel.hidden=false;toggle.setAttribute("aria-expanded","true");toggle.textContent="예측엔진 닫기";}
    ["baseline-new","maturity-amount","rollover-rate","base-n","bonus-n","base-r","bonus-r"].forEach(id=>{const el=$(id);if(el){el.addEventListener("input",renderScenarioTable);el.addEventListener("change",renderScenarioTable);}});
    planning.querySelectorAll(".segment button").forEach(b=>b.addEventListener("click",()=>setTimeout(renderScenarioTable,0)));
    const observer=new MutationObserver(()=>renderScenarioTable());
    [$("own-max"),$("sim-top10"),$("planning-basis")].filter(Boolean).forEach(el=>observer.observe(el,{childList:true,subtree:true,characterData:true}));
    renderScenarioTable();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_strategy_decision_cockpit(html: str) -> str:
    """Strategy HTML에 Stage B/C/D/E0 의사결정 presentation을 합성한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        rendered = html
    else:
        if has_style != has_script:
            raise DashboardBuildError("Rate Response Cockpit 주입 상태가 불완전하다")
        if "</head>" not in html or "</body>" not in html:
            raise DashboardBuildError("Rate Response Cockpit 주입 위치를 찾지 못했다")
        if 'id="prediction-panel"' not in html or "function predictInflow" not in html:
            raise DashboardBuildError("기존 Strategy 수신예측 계약을 찾지 못했다")
        rendered = html.replace("</head>", _CSS + "\n</head>", 1)
        rendered = rendered.replace("</body>", _JS + "\n</body>", 1)
    # 실제 Strategy 템플릿에만 후속 C/D/E0 presentation을 합성한다. 최소 fixture는 B만 유지한다.
    if 'id="market-flow"' in rendered:
        rendered = inject_market_intelligence_presentation(rendered)
        rendered = inject_external_market_context_presentation(rendered)
    if 'class="grid interpretation"' in rendered:
        rendered = inject_preference_intelligence_presentation(rendered)
    if (
        'id="market-flow"' in rendered
        and 'class="grid interpretation"' in rendered
        and 'class="grid primary"' in rendered
    ):
        rendered = inject_strategy_workspace_presentation(rendered)
        if (
            'id="market-scope"' in rendered
            and 'id="scope-evidence"' in rendered
            and 'id="map-card"' in rendered
        ):
            rendered = inject_strategy_ux_refinement(rendered)
            rendered = inject_strategy_readability_preference_v2(rendered)
            rendered = inject_strategy_decision_evidence_refinement(rendered)
            rendered = inject_public_structural_v2_cockpit(rendered)
    return rendered
