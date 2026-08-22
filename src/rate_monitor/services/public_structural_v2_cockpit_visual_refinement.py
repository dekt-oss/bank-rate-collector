"""Public Structural v2 Cockpit의 최종 visual QA 보정.

Stage F 계산/시장위치 계약은 건드리지 않는다. production-derived Chrome screenshot에서
확인된 presentation 결함 두 가지만 후처리한다.

1. 같은 금리의 Ladder marker가 같은 좌표에서 겹치면 하나의 marker로 병합한다.
2. 520px 이하 후보금리표는 충분한 최소폭을 확보해 숫자 열끼리 겹치지 않게 한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="public-structural-v2-cockpit-visual-refinement-style"'
SCRIPT_MARKER = 'id="public-structural-v2-cockpit-visual-refinement-script"'

_CSS = r"""
<style id="public-structural-v2-cockpit-visual-refinement-style">
.psv2-rung[data-merged-rate-markers] label:after{content:" · 동일금리"!important;color:#8a6f36}
@media(max-width:520px){
  .psv2-table{min-width:1240px!important}
  .psv2-table th,.psv2-table td{padding-left:12px!important;padding-right:12px!important}
  .psv2-table th:nth-child(1),.psv2-table td:nth-child(1){min-width:115px}
  .psv2-table th:nth-child(2),.psv2-table td:nth-child(2){min-width:145px}
  .psv2-table th:nth-child(3),.psv2-table td:nth-child(3){min-width:70px}
  .psv2-table th:nth-child(4),.psv2-table td:nth-child(4){min-width:105px}
  .psv2-table th:nth-child(5),.psv2-table td:nth-child(5){min-width:115px}
  .psv2-table th:nth-child(6),.psv2-table td:nth-child(6){min-width:220px}
  .psv2-table th:nth-child(7),.psv2-table td:nth-child(7){min-width:105px}
  .psv2-table th:nth-child(8),.psv2-table td:nth-child(8){min-width:165px}
}
</style>
""".strip()

_SCRIPT = r"""
<script id="public-structural-v2-cockpit-visual-refinement-script">
(()=>{
  "use strict";
  const HOST_ID="public-structural-v2-cockpit";

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
    """Stage F Cockpit 뒤에 visual-only refinement를 주입한다."""
    states = (STYLE_MARKER in html, SCRIPT_MARKER in html)
    if all(states):
        return html
    if any(states):
        raise DashboardBuildError(
            "Public Structural v2 Cockpit visual refinement 주입 상태가 불완전하다"
        )
    if 'id="public-structural-v2-cockpit-script"' not in html:
        raise DashboardBuildError("Public Structural v2 Cockpit 선행 script가 없다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError(
            "Public Structural v2 Cockpit visual refinement 주입 위치를 찾지 못했다"
        )
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _SCRIPT + "\n</body>", 1)
