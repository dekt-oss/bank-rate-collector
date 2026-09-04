# ruff: noqa: E501
"""Strategy의 큰 금리결정 준비도 카드를 compact한 업무 범위 strip으로 바꾼다.

기존 readiness DOM과 안전 경계는 보존하고, 사용자에게 보이는 용어와 밀도만
정리한다. 계산·예측·데이터 계약을 새로 만들지 않는다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-decision-scope-compact-style"'
SCRIPT_MARKER = 'id="strategy-decision-scope-compact-script"'

_STYLE = r"""
<style id="strategy-decision-scope-compact-style">
.ux-decision-readiness[data-decision-scope-compact="1"]{display:grid!important;grid-template-columns:minmax(145px,.35fr) minmax(0,1.65fr)!important;gap:10px 14px!important;align-items:center!important;margin:0 0 12px!important;padding:10px 13px!important;border-radius:12px!important;box-shadow:0 4px 14px rgba(77,45,88,.035)!important}
.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title{gap:1px!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>span{display:none!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>strong{font-size:13.5px!important;line-height:1.25!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>p{margin:2px 0 0!important;font-size:9.8px!important;line-height:1.35!important;color:#7b6d7d!important}
.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-grid{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:6px!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-item{min-height:0!important;padding:7px 9px!important;border-radius:9px!important;box-shadow:none!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-item b{margin:0 0 2px!important;font-size:10.5px!important;line-height:1.35!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-item span{font-size:9.5px!important;line-height:1.35!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-foot{grid-column:1/-1!important;margin:0!important;padding:5px 2px 0!important;border-top:1px solid rgba(91,47,100,.07)!important;font-size:9.5px!important;line-height:1.35!important;color:#756778!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-foot b{color:#5b2f64!important}
@media(max-width:900px){.ux-decision-readiness[data-decision-scope-compact="1"]{grid-template-columns:1fr!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title{display:flex!important;flex-direction:row!important;align-items:baseline!important;gap:8px!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>p{margin:0!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-grid{grid-template-columns:1fr 1fr!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-item.pending{grid-column:1/-1!important}}
@media(max-width:520px){.ux-decision-readiness[data-decision-scope-compact="1"]{padding:9px 10px!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title{display:block!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-title>p{margin-top:2px!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-grid{grid-template-columns:1fr!important}.ux-decision-readiness[data-decision-scope-compact="1"] .ux-readiness-item.pending{grid-column:auto!important}}
</style>
""".strip()

_SCRIPT = r'''
<script id="strategy-decision-scope-compact-script">
(()=>{
  "use strict";
  let scheduled=false;
  function compact(){
    scheduled=false;
    const card=document.querySelector(".ux-decision-readiness");
    if(!card||card.dataset.decisionScopeCompact==="1")return;
    const title=card.querySelector(".ux-readiness-title"),items=[...card.querySelectorAll(".ux-readiness-item")],foot=card.querySelector(".ux-readiness-foot");
    if(!title||items.length<3||!foot)return;
    const kicker=title.querySelector("span"),strong=title.querySelector("strong"),copy=title.querySelector("p");
    if(kicker)kicker.textContent="";
    if(strong)strong.textContent="의사결정 범위";
    if(copy)copy.textContent="지금 가능한 판단과 보류 영역";
    const labels=[
      ["시장 비교 가능","현재금리·상위선·경쟁사 비교"],
      ["수신반응은 시나리오","시장·외부환경과 함께 참고"],
      ["최적금리 자동추천은 아직 불가","내부 실적 보정 전 보류"]
    ];
    items.slice(0,3).forEach((item,index)=>{
      const b=item.querySelector("b"),span=item.querySelector("span"),label=labels[index];
      if(b)b.textContent=label[0];
      if(span)span.textContent=label[1];
    });
    foot.innerHTML='<b>해석 경계:</b> 내부 실적 보정 전에는 최적금리 자동추천으로 해석하지 않습니다.';
    card.dataset.decisionScopeCompact="1";
  }
  function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(compact)}
  function install(){
    compact();
    if(document.querySelector(".ux-decision-readiness"))return;
    const root=document.querySelector("main,.shell")||document.body;
    const observer=new MutationObserver(()=>{
      schedule();
      if(document.querySelector(".ux-decision-readiness"))observer.disconnect();
    });
    observer.observe(root,{subtree:true,childList:true});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
'''.strip("\n")


def inject_strategy_decision_scope_compact(html: str) -> str:
    """Strategy readiness를 compact 업무 범위 strip으로 표시한다."""
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
