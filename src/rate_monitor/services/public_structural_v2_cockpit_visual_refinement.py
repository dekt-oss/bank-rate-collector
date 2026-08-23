# ruff: noqa: E501
"""Public Structural v2 Cockpit의 최종 post-processing.

Stage F 계산/시장위치 계약은 건드리지 않는다. production-derived Chrome screenshot에서
확인된 presentation 결함을 후처리하고 Stage H provider adapter를 Cockpit
실행 직전에 연결한 뒤 Stage G factual-only rate finder를 마지막 확장으로 유지한다.

1. 같은 금리의 Ladder marker가 같은 좌표에서 겹치면 하나의 marker로 병합한다.
2. 520px 이하 후보금리표는 8열 표를 2열 label/value 카드 grid로 바꿔 겹침을 막는다.
3. stress range 설명은 통계적 신뢰수준처럼 읽힐 수 있는 금지 용어를 제거한다.
4. 최종 Public Structural 분석 microcopy는 Brand v3의 10.5px 가독성 floor를 지킨다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.public_structural_v2_factual_rate_finder_presentation import (
    inject_public_structural_v2_factual_rate_finder,
)
from rate_monitor.services.public_structural_v2_forecast_provider_presentation import (
    inject_public_structural_v2_forecast_provider,
)

STYLE_MARKER = 'id="public-structural-v2-cockpit-visual-refinement-style"'
SCRIPT_MARKER = 'id="public-structural-v2-cockpit-visual-refinement-script"'

_CSS = r"""
<style id="public-structural-v2-cockpit-visual-refinement-style">
.psv2-rung[data-merged-rate-markers] label:after{content:" · 동일금리"!important;color:#8a6f36}
.psv2>div{min-width:0}
/* Brand v3 contract: analytical microcopy must not render below 10.5px. */
.psv2-head p,.psv2-badge,.psv2-kicker,.psv2-card small,.psv2-card .minor,.psv2-separator,.psv2-panel-head span,.psv2-rung label,.psv2-rung strong,.psv2-mini span,.psv2-mini b,.psv2-chart .axis,.psv2-chart .label,.psv2-chart-legend,.psv2-empty,.psv2-disclosure,.psv2-table th,.psv2-table td,.psv2-table .rate-label,.psv2-table .rate-note,.psv2-table-foot,.psv2-error,.psv2-table td:before{font-size:10.5px!important}
@media(max-width:520px){
  .psv2-table-wrap{overflow:visible;border:0;background:transparent}
  .psv2-table{display:block!important;width:100%!important;min-width:0!important;border-collapse:separate}
  .psv2-table thead{display:none!important}
  .psv2-table tbody{display:grid!important;gap:8px}
  .psv2-table tr{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 10px;padding:10px;border:1px solid rgba(91,47,100,.09);border-radius:10px;background:#fff}
  .psv2-table tr.current{background:#f3faf6}
  .psv2-table tr.proposal{background:#fff9eb}
  .psv2-table td{display:block!important;min-width:0!important;padding:0!important;border:0!important;text-align:left!important;white-space:normal!important;font-size:10.5px;line-height:1.45}
  .psv2-table td:before{display:block;margin-bottom:2px;color:#806f83;font:700 10.5px/1.25 var(--sans);letter-spacing:.02em}
  .psv2-table td:nth-child(1):before{content:"금리"}
  .psv2-table td:nth-child(2):before{content:"공동순위 범위"}
  .psv2-table td:nth-child(3):before{content:"동률"}
  .psv2-table td:nth-child(4):before{content:"시장 threshold"}
  .psv2-table td:nth-child(5):before{content:"기준 총수신"}
  .psv2-table td:nth-child(6){grid-column:1/-1}
  .psv2-table td:nth-child(6):before{content:"stress range"}
  .psv2-table td:nth-child(7):before{content:"현재 대비"}
  .psv2-table td:nth-child(8):before{content:"직전 5bp 표면비용"}
  .psv2-table .rate-label{font-size:10.5px}
}
</style>
""".strip()

_SCRIPT = r"""
<script id="public-structural-v2-cockpit-visual-refinement-script">
(()=>{
  "use strict";
  const HOST_ID="public-structural-v2-cockpit";
  const FORBIDDEN_RANGE_DISCLOSURE="음영은 confidence/prediction interval이 아니라 저·기준·고 민감도 결과의 실제 최소~최대 범위입니다.";
  const SAFE_RANGE_DISCLOSURE="음영은 저·기준·고 민감도 결과를 단순히 묶은 실제 최소~최대 범위이며 통계적 신뢰수준을 뜻하지 않습니다.";

  function mergeSameRateRungs(){
    const ladder=document.querySelector(`#${HOST_ID} .psv2-ladder`);
    if(!ladder)return;
    const groups=new Map();
    for(const rung of [...ladder.querySelectorAll(":scope > .psv2-rung")]){
      const rate=rung.querySelector("strong")?.textContent?.trim();
      if(!rate)continue;
      const group=groups.get(rate)||[];
      group.push(rung);
      groups.set(rate,group);
    }
    for(const group of groups.values()){
      if(group.length<2)continue;
      const primary=group.find(rung=>rung.classList.contains("proposal"))
        ||group.find(rung=>rung.classList.contains("current"))
        ||group[0];
      const labels=[];
      let hasCurrent=false,hasProposal=false;
      for(const rung of group){
        const label=rung.querySelector("label")?.textContent?.trim();
        if(label&&!labels.includes(label))labels.push(label);
        hasCurrent=hasCurrent||rung.classList.contains("current");
        hasProposal=hasProposal||rung.classList.contains("proposal");
      }
      let mergedLabels=labels;
      if(hasCurrent&&hasProposal){
        mergedLabels=labels.filter(label=>label!=="고려저축은행 현재"&&label!=="제안금리");
        mergedLabels.push("현재 · 제안금리");
      }
      const labelNode=primary.querySelector("label");
      if(labelNode)labelNode.textContent=mergedLabels.join(" · ");
      primary.dataset.mergedRateMarkers=String(group.length);
      primary.classList.add("same");
      for(const rung of group){
        if(rung!==primary)rung.remove();
      }
    }
  }

  function normalizeStressDisclosure(){
    const disclosure=document.querySelector(`#${HOST_ID} .psv2-disclosure`);
    if(!disclosure||!disclosure.textContent.includes(FORBIDDEN_RANGE_DISCLOSURE))return;
    disclosure.innerHTML=disclosure.innerHTML.replace(
      FORBIDDEN_RANGE_DISCLOSURE,
      SAFE_RANGE_DISCLOSURE,
    );
  }

  function install(){
    const host=document.getElementById(HOST_ID);
    if(!host||host.dataset.visualRefinementInstalled==="1")return;
    host.dataset.visualRefinementInstalled="1";
    let queued=false;
    const refine=()=>{
      if(queued)return;
      queued=true;
      queueMicrotask(()=>{
        queued=false;
        mergeSameRateRungs();
        normalizeStressDisclosure();
      });
    };
    new MutationObserver(refine).observe(host,{childList:true,subtree:true});
    refine();
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});
  else install();
})();
</script>
""".strip()


def inject_public_structural_v2_cockpit_visual_refinement(html: str) -> str:
    """Stage F visual refinement 후 Stage H adapter와 Stage G finder를 연결한다."""
    states = (STYLE_MARKER in html, SCRIPT_MARKER in html)
    if all(states):
        rendered = html
    else:
        if any(states):
            raise DashboardBuildError(
                "Public Structural v2 Cockpit visual refinement 주입 상태가 불완전"
            )
        if 'id="public-structural-v2-cockpit-script"' not in html:
            raise DashboardBuildError("Public Structural v2 Cockpit 선행 script가 없다")
        if "</head>" not in html or "</body>" not in html:
            raise DashboardBuildError(
                "Public Structural v2 Cockpit visual refinement 주입 위치를 찾지 못했다"
            )
        rendered = html.replace("</head>", _CSS + "\n</head>", 1)
        rendered = rendered.replace("</body>", _SCRIPT + "\n</body>", 1)
    rendered = inject_public_structural_v2_forecast_provider(rendered)
    return inject_public_structural_v2_factual_rate_finder(rendered)
