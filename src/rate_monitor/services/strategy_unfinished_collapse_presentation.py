# ruff: noqa: E501
"""Strategy의 실질 데이터가 없는 카드만 기본 접힘으로 표시한다.

계산/데이터 계약은 건드리지 않는다. 기존 renderer가 만든 explicit empty-state를
읽어, 유효 데이터 신호가 전혀 없는 카드에만 progressive disclosure를 붙인다.
사용자가 펼친 카드는 같은 세션에서 다시 자동으로 접지 않는다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-unfinished-collapse-style"'
SCRIPT_MARKER = 'id="strategy-unfinished-collapse-script"'

_STYLE = r"""
<style id="strategy-unfinished-collapse-style">
.strategy-unfinished-section{position:relative}
.strategy-unfinished-toggle{display:flex;width:100%;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;border:0;border-bottom:1px solid rgba(91,47,100,.08);background:rgba(255,255,255,.38);color:var(--ink);text-align:left;cursor:pointer}
.strategy-unfinished-toggle strong{font-size:11.5px}.strategy-unfinished-toggle span{flex:0 0 auto;color:var(--muted);font-size:10px;font-weight:780}
.strategy-unfinished-section[data-collapsed="true"]>.strategy-unfinished-toggle{border-bottom:0}
.strategy-unfinished-section[data-collapsed="true"]>:not(.strategy-unfinished-toggle){display:none!important}
</style>
"""

_SCRIPT = r'''
<script id="strategy-unfinished-collapse-script">
(()=>{
  "use strict";
  const EMPTY_SELECTOR=".empty,.funding-empty,.funding-position-empty,.rate-funding-matrix-blocked,.axistext";
  const EMPTY_SIGNAL=/(기간별 이력 데이터가 없습니다|데이터가 아직 없습니다|동일 기준월 verified 기관 데이터가 없습니다|아직 없습니다|준비 중|미구현|현재 비교 데이터 없음|관측 부족|분류 가능한 우대조건이 없습니다|Matrix를 열지 않습니다|연결하지 않았습니다)/;
  const POPULATED_SELECTOR="tbody tr,.change,.pref,.busan-rate-item,.funding-market-card,.funding-point,.trenddot,[data-own-position=\"row\"]";
  let scheduled=false;
  const titleOf=card=>String(card.querySelector("h2,h3,.head strong")?.textContent||"미구현 섹션").trim();
  const isIncomplete=card=>{
    const empty=[...card.querySelectorAll(EMPTY_SELECTOR)].some(node=>EMPTY_SIGNAL.test(String(node.textContent||"")));
    if(!empty)return false;
    return !card.querySelector(POPULATED_SELECTOR);
  };
  const setToggle=(button,expanded)=>{
    const value=String(expanded),label=expanded?"접기":"펼치기",span=button.querySelector("span");
    if(button.getAttribute("aria-expanded")!==value)button.setAttribute("aria-expanded",value);
    if(span&&span.textContent!==label)span.textContent=label;
  };
  const clear=card=>{
    card.classList.remove("strategy-unfinished-section");
    card.removeAttribute("data-collapsed");
    card.querySelector(":scope > .strategy-unfinished-toggle")?.remove();
  };
  const decorate=card=>{
    if(!isIncomplete(card)){clear(card);return}
    card.classList.add("strategy-unfinished-section");
    let button=card.querySelector(":scope > .strategy-unfinished-toggle");
    if(!button){
      button=document.createElement("button");
      button.type="button";button.className="strategy-unfinished-toggle";
      const strong=document.createElement("strong"),span=document.createElement("span");
      strong.textContent=titleOf(card);span.textContent="펼치기";
      button.append(strong,span);button.setAttribute("aria-expanded","false");
      button.addEventListener("click",()=>{
        const collapsed=card.dataset.collapsed==="true";
        card.dataset.collapsed=collapsed?"false":"true";
        setToggle(button,collapsed);
        if(collapsed)card.dataset.userExpanded="true";else delete card.dataset.userExpanded;
      });
      card.prepend(button);
    }
    if(card.dataset.userExpanded!=="true"){
      if(card.dataset.collapsed!=="true")card.dataset.collapsed="true";
      setToggle(button,false);
    }
  };
  const scan=()=>{
    scheduled=false;
    document.querySelectorAll(".card:not(.kpi)").forEach(decorate);
  };
  const schedule=()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(scan)};
  const install=()=>{
    scan();
    const root=document.querySelector("main,.shell")||document.body;
    new MutationObserver(schedule).observe(root,{subtree:true,childList:true,characterData:true});
  };
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
'''.strip("\n")


def inject_strategy_unfinished_collapse(html: str) -> str:
    """Strategy HTML에 unfinished-card progressive disclosure를 주입한다."""
    if STYLE_MARKER in html and SCRIPT_MARKER in html:
        return html
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        raise DashboardBuildError("Strategy unfinished-collapse 주입 상태가 불완전하다")
    if 'id="market-scope"' not in html:
        return html
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy unfinished-collapse 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _STYLE + "\n</head>", 1)
    return rendered.replace("</body>", _SCRIPT + "\n</body>", 1)
