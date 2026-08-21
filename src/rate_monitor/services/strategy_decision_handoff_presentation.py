"""Strategy 최종 IA에서 Search 지역 상세 handoff를 유지한다.

Strategy의 중복 지도/지역 상세 shell은 숨기되, 사용자가 Search의 지역 상세로
이동할 수 있는 compact handoff는 계속 노출한다. 계산·데이터 계약은 변경하지 않는다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-decision-handoff-style"'
SCRIPT_MARKER = 'id="strategy-decision-handoff-script"'

_CSS = r"""
<style id="strategy-decision-handoff-style">
.ux-region-handoff[data-decision-handoff="1"]{display:flex!important}
</style>
""".strip()

_JS = r"""
<script id="strategy-decision-handoff-script">
(()=>{
  "use strict";
  function install(){
    const handoff=document.querySelector(".ux-region-handoff");
    if(!handoff)return;
    handoff.hidden=false;
    handoff.dataset.decisionHandoff="1";
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
""".strip()


def inject_strategy_decision_handoff(html: str) -> str:
    """Search 지역 상세 handoff를 final Strategy IA에서도 보이게 유지한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Strategy Decision Handoff 주입 상태가 불완전하다")
    if 'class="ux-region-handoff"' not in html:
        raise DashboardBuildError("Strategy Search handoff 선행 계약을 찾지 못했다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy Decision Handoff 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
