# ruff: noqa: E501
"""Strategy readiness를 4단계 의사결정 바로가기 메뉴로 압축한다.

기존 readiness owner DOM과 안전 경계는 보존한다. 새 메뉴는 현재 화면의
시장방향·경쟁사 TOP5·세부 비교·자동추천 범위로만 이동하며 계산/예측/데이터
계약을 변경하지 않는다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-decision-scope-compact-style"'
SCRIPT_MARKER = 'id="strategy-decision-scope-compact-script"'

_STYLE = r"""
<style id="strategy-decision-scope-compact-style">
.ux-decision-readiness[data-decision-scope-compact="1"]{display:grid!important;grid-template-columns:minmax(150px,.30fr) minmax(0,1.70fr)!important;gap:10px 14px!important;align-items:center!important;margin:0 0 12px!important;padding:10px 13px!important;border-radius:12px!important;box-shadow:0 4px 14px rgba(77,45,88,.035)!important}
.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title{gap:1px!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>span{display:none!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>strong{font-size:13.5px!important;line-height:1.25!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>p{margin:2px 0 0!important;font-size:9.8px!important;line-height:1.35!important;color:#7b6d7d!important}
.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-grid{display:block!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-item{display:none!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-foot{grid-column:1/-1!important;margin:0!important;padding:5px 2px 0!important;border-top:1px solid rgba(91,47,100,.07)!important;font-size:9.5px!important;line-height:1.35!important;color:#756778!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-foot b{color:#5b2f64!important}
.ux-decision-menu{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}.ux-decision-step{appearance:none;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:8px;align-items:center;min-width:0;padding:8px 9px;border:1px solid rgba(91,47,100,.10);border-radius:9px;background:#fff;color:#453649;text-align:left;cursor:pointer;box-shadow:none;transition:border-color .15s ease,background .15s ease,transform .15s ease}.ux-decision-step:hover,.ux-decision-step:focus-visible{border-color:rgba(91,47,100,.28);background:#fbf7fb;outline:none;transform:translateY(-1px)}.ux-decision-step-no{display:grid;place-items:center;width:25px;height:25px;border-radius:7px;background:#f3edf4;color:#7b4d7f;font-size:9.5px;font-weight:900;font-variant-numeric:tabular-nums}.ux-decision-step-copy{min-width:0}.ux-decision-step-copy b{display:block;color:#392b3d;font-size:10.5px;line-height:1.25}.ux-decision-step-copy small{display:block;margin-top:2px;color:#7c6e7f;font-size:8.9px;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ux-decision-step-arrow{color:#9a859d;font-size:13px;font-weight:800}.ux-decision-step[data-decision-step="boundary"]{background:#fffaf2;border-color:rgba(169,116,26,.14)}.ux-decision-step[data-decision-step="boundary"] .ux-decision-step-no{background:#fff2d9;color:#8a631d}
@media(max-width:1000px){.ux-decision-readiness[data-decision-scope-compact="1"]{grid-template-columns:1fr!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title{display:flex!important;flex-direction:row!important;align-items:baseline!important;gap:8px!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>p{margin:0!important}.ux-decision-menu{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.ux-decision-readiness[data-decision-scope-compact="1"]{padding:9px 10px!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title{display:block!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>p{margin-top:2px!important}.ux-decision-menu{grid-template-columns:1fr}.ux-decision-step-copy small{white-space:normal}}
</style>
""".strip()

_SCRIPT = r'''
<script id="strategy-decision-scope-compact-script">
(()=>{
  "use strict";
  let scheduled=false;
  const STEP_TARGETS={
    market:[".strategy-market-direction"],
    competitors:[".top5-card"],
    detail:[".market-flow",".workspace-decision","#planning-zone"],
    boundary:["#planning-zone",".prediction-panel"]
  };
  function resolveTarget(step){
    for(const selector of STEP_TARGETS[step]||[]){const node=document.querySelector(selector);if(node)return node}
    return null;
  }
  function gotoStep(step){
    const node=resolveTarget(step);if(!node)return;
    node.scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"start"});
    if(!node.hasAttribute("tabindex"))node.setAttribute("tabindex","-1");
    try{node.focus({preventScroll:true})}catch{}
  }
  function compact(){
    scheduled=false;
    const card=document.querySelector(".ux-decision-readiness");
    if(!card||card.dataset.decisionScopeCompact==="1")return;
    const title=card.querySelector(".ux-readiness-title"),grid=card.querySelector(".ux-readiness-grid"),foot=card.querySelector(".ux-readiness-foot");
    if(!title||!grid||!foot||card.querySelectorAll(".ux-readiness-item").length<3)return;
    const kicker=title.querySelector("span"),strong=title.querySelector("strong"),copy=title.querySelector("p");
    if(kicker)kicker.textContent="";
    if(strong)strong.textContent="의사결정 메뉴";
    if(copy)copy.textContent="필요한 판단 화면으로 바로 이동";
    const nav=document.createElement("nav");
    nav.className="ux-decision-menu";
    nav.setAttribute("aria-label","금리 의사결정 4단계 바로가기");
    nav.innerHTML=`
      <button type="button" class="ux-decision-step" data-decision-step="market"><span class="ux-decision-step-no">01</span><span class="ux-decision-step-copy"><b>시장 방향</b><small>최근 30일 인상·인하 흐름</small></span><span class="ux-decision-step-arrow" aria-hidden="true">→</span></button>
      <button type="button" class="ux-decision-step" data-decision-step="competitors"><span class="ux-decision-step-no">02</span><span class="ux-decision-step-copy"><b>경쟁사 TOP5</b><small>상단 금리와 당사 위치 비교</small></span><span class="ux-decision-step-arrow" aria-hidden="true">→</span></button>
      <button type="button" class="ux-decision-step" data-decision-step="detail"><span class="ux-decision-step-no">03</span><span class="ux-decision-step-copy"><b>세부 비교</b><small>추이·변경·근거 상세 확인</small></span><span class="ux-decision-step-arrow" aria-hidden="true">→</span></button>
      <button type="button" class="ux-decision-step" data-decision-step="boundary"><span class="ux-decision-step-no">04</span><span class="ux-decision-step-copy"><b>자동추천 범위</b><small>내부 실적 보정 전 참고용</small></span><span class="ux-decision-step-arrow" aria-hidden="true">→</span></button>`;
    nav.addEventListener("click",event=>{const button=event.target.closest("[data-decision-step]");if(button)gotoStep(button.dataset.decisionStep)});
    grid.appendChild(nav);
    foot.innerHTML='<b>해석 경계:</b> 내부 실적 보정 전에는 최적금리 자동추천으로 해석하지 않습니다.';
    card.dataset.decisionScopeCompact="1";
  }
  function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(compact)}
  function install(){
    compact();
    if(document.querySelector('.ux-decision-readiness[data-decision-scope-compact="1"]'))return;
    const root=document.querySelector("main,.shell")||document.body;
    const observer=new MutationObserver(()=>{
      schedule();
      if(document.querySelector('.ux-decision-readiness[data-decision-scope-compact="1"]'))observer.disconnect();
    });
    observer.observe(root,{subtree:true,childList:true});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
'''.strip("\n")


def inject_strategy_decision_scope_compact(html: str) -> str:
    """Strategy readiness를 4단계 의사결정 바로가기 메뉴로 표시한다."""
    if STYLE_MARKER in html and SCRIPT_MARKER in html:
        return html
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        raise DashboardBuildError("Strategy decision-scope compact 주입 상태가 불완전하다")
    if 'id="market-scope"' not in html:
        return html
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy decision-scope compact 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _STYLE + "\n</head>", 1)
    return rendered.replace("</body>", _SCRIPT + "\n</body>", 1)
