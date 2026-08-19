# ruff: noqa: E501
"""Strategy 화면을 금리결정 작업순서로 재배치하는 presentation.

계산·source precedence·stable identity·예측계수는 바꾸지 않는다. 이미 존재하는
Strategy DOM을 `결정 → 시장근거 → 상품설계 → 지역·경쟁사 상세` 순으로 재배치하고,
모바일 밀도와 참고영역의 progressive disclosure만 조정한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-workspace-style"'
SCRIPT_MARKER = 'id="strategy-workspace-script"'

_CSS = r"""
<style id="strategy-workspace-style">
.workspace-section-label{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:20px 3px 8px;padding:0 2px}.workspace-section-label div{display:flex;align-items:baseline;gap:8px}.workspace-section-label em{font:800 9px var(--mono);font-style:normal;letter-spacing:.08em;color:#7ca993}.workspace-section-label strong{font-size:12px;letter-spacing:-.02em;color:#dbe7e1}.workspace-section-label span{color:#667a70;font-size:9px;text-align:right}
.workspace-decision .sim{border-color:rgba(128,200,166,.28);background:radial-gradient(circle at 82% 4%,rgba(212,179,111,.09),transparent 28%),linear-gradient(148deg,rgba(17,38,31,.99),rgba(8,22,18,.99));box-shadow:0 22px 56px rgba(0,0,0,.24)}.workspace-decision .head h2{font-size:18px}.workspace-decision .planning-strip>div{background:rgba(7,24,19,.44)}
.workspace-legacy-pref{margin:0;border:1px solid rgba(213,225,219,.07);border-radius:12px;background:rgba(4,14,11,.18);overflow:hidden}.workspace-legacy-pref>summary{cursor:pointer;list-style:none;padding:10px 12px;color:#7e9087;font-size:9px;font-weight:760}.workspace-legacy-pref>summary::-webkit-details-marker{display:none}.workspace-legacy-pref>summary:after{content:" 펼치기";float:right;color:#5f7369;font-weight:500}.workspace-legacy-pref[open]>summary:after{content:" 접기"}.workspace-legacy-pref .preference-card{border:0;border-radius:0;box-shadow:none;background:transparent;min-height:0!important}.workspace-insights{grid-template-columns:1fr!important}.workspace-insights .insightcard{min-height:0!important}
.workspace-detail.primary:not(.busan-focus){grid-template-columns:minmax(300px,.68fr) minmax(0,1.32fr)}.workspace-detail.primary:not(.busan-focus) .mapcard{min-height:350px}.workspace-detail.primary:not(.busan-focus) .mapstage{height:270px}.workspace-detail.primary:not(.busan-focus)>article:last-child{min-height:350px}.workspace-detail.primary:not(.busan-focus) .pad{padding:14px}.workspace-detail.primary:not(.busan-focus) td{padding:7px 8px}
.market-flow .changes:not([open]){min-height:0}.market-flow .changes:not([open]) summary{padding:12px 14px}.market-flow .changes:not([open]) summary:after{content:"필요할 때 펼치기"}
@media(max-width:1120px){.workspace-detail.primary:not(.busan-focus){grid-template-columns:1fr 1fr}.workspace-detail.primary:not(.busan-focus) .mapcard,.workspace-detail.primary:not(.busan-focus)>article:last-child{min-height:340px}.workspace-detail.primary:not(.busan-focus) .mapstage{height:260px}}
@media(max-width:760px){
  .hero{padding:18px 3px 12px}.hero h1{font-size:28px}.hero p{font-size:10px}
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.kpi{min-height:104px;padding:12px}.kvalue{font-size:30px}.klabel{font-size:9.5px}.kfoot{font-size:9px}
  .evidence-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.evidence-card{padding:9px 10px}.evidence-grid{font-size:9px}
  .workspace-section-label{margin-top:16px;align-items:flex-start;flex-direction:column;gap:2px}.workspace-section-label span{text-align:left}
  .workspace-decision .sim{padding:15px}.workspace-decision .head h2{font-size:16px}
  .market-intel-controls,.pref-intel-controls{display:grid;gap:7px}.market-intel-control,.pref-intel-control{flex-wrap:nowrap;overflow-x:auto;overscroll-behavior-inline:contain;padding-bottom:2px}.market-intel-control button,.pref-intel-control button{flex:0 0 auto}
  .external-context-rates,.external-context-flows{display:flex;overflow-x:auto;gap:7px;overscroll-behavior-inline:contain;scroll-snap-type:x proximity;padding-bottom:3px}.external-context-card,.external-flow{flex:0 0 min(76vw,260px);scroll-snap-align:start}
  .workspace-detail.primary:not(.busan-focus){grid-template-columns:1fr}.workspace-detail.primary:not(.busan-focus) .mapcard{min-height:350px}.workspace-detail.primary:not(.busan-focus) .mapstage{height:285px}.workspace-detail.primary:not(.busan-focus)>article:last-child{min-height:0}
}
@media(max-width:360px){.kpis,.evidence-strip{grid-template-columns:1fr}.external-context-card,.external-flow{flex-basis:86vw}}
</style>
"""

_JS = r"""
<script id="strategy-workspace-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const insertLabel=(target,id,no,title,copy)=>{
    if(!target||$(id))return;
    const el=document.createElement("div");
    el.id=id;el.className="workspace-section-label";
    el.innerHTML=`<div><em>${no}</em><strong>${title}</strong></div><span>${copy}</span>`;
    target.parentNode.insertBefore(el,target);
  };
  function install(){
    if(document.documentElement.dataset.strategyWorkspace==="decision-first-v1")return;
    const planning=$("planning-zone");
    const marketFlow=$("market-flow");
    const marketIntel=$("market-intelligence");
    const external=$("external-market-context");
    const pref=$("preference-intelligence");
    const interpretation=document.querySelector(".grid.interpretation");
    const primary=document.querySelector(".grid.primary");
    if(!planning||!marketFlow||!interpretation||!primary)return;

    const evidenceAnchor=external||marketIntel||marketFlow;
    evidenceAnchor.parentNode.insertBefore(planning,evidenceAnchor);
    planning.classList.add("workspace-decision");
    marketFlow.classList.add("workspace-evidence");

    if(pref){
      pref.parentNode.insertBefore(interpretation,pref);
      pref.classList.add("workspace-preferences");
    }
    interpretation.classList.add("workspace-insights");

    const legacyPref=interpretation.querySelector(".preference-card");
    if(legacyPref&&!interpretation.querySelector(".workspace-legacy-pref")){
      const details=document.createElement("details");
      details.className="workspace-legacy-pref";
      details.innerHTML="<summary>기존 우대조건 트렌드 요약</summary>";
      legacyPref.parentNode.insertBefore(details,legacyPref);
      details.appendChild(legacyPref);
    }

    const detailAfter=pref||interpretation;
    detailAfter.insertAdjacentElement("afterend",primary);
    primary.classList.add("workspace-detail");

    const changes=marketFlow.querySelector("details.changes");
    if(changes)changes.removeAttribute("open");

    insertLabel(planning,"workspace-label-decision","01","금리 결정","먼저 금리를 바꾸고 수신반응·비용을 비교합니다.");
    insertLabel(evidenceAnchor,"workspace-label-evidence","02","시장 근거","외부 자금환경과 최근 경쟁방향을 결정 근거로 확인합니다.");
    insertLabel(interpretation,"workspace-label-product","03","상품 설계","시장 해석과 우대조건 구조를 상품조건에 연결합니다.");
    insertLabel(primary,"workspace-label-detail","04","지역 · 경쟁사 상세","지도와 TOP5는 필요할 때 확인하는 상세 근거입니다.");

    document.documentElement.dataset.strategyWorkspace="decision-first-v1";
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_strategy_workspace_presentation(html: str) -> str:
    """Strategy HTML에 decision-first workspace presentation을 한 번만 주입한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Strategy Workspace 주입 상태가 불완전하다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy Workspace 주입 위치를 찾지 못했다")
    required = ('id="planning-zone"', 'id="market-flow"', 'class="grid interpretation"', 'class="grid primary"')
    if any(marker not in html for marker in required):
        raise DashboardBuildError("Strategy Workspace 기존 레이아웃 계약을 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
