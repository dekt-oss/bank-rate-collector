# ruff: noqa: E501
"""Strategy 상단에 최근 30일의 factual 시장 방향을 compact하게 표시한다.

시장 방향은 기존 ``strategy.market_changes`` 의 실제 최고금리 변경 이벤트만
사용한다. 새 예측점수나 추천 규칙을 만들지 않고, 기존 금리결정 인사이트는
삭제하지 않은 채 보조 상세로 내린다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-market-direction-style"'
SCRIPT_MARKER = 'id="strategy-market-direction-script"'

_STYLE = r"""
<style id="strategy-market-direction-style">
.strategy-market-direction{display:grid;grid-template-columns:minmax(180px,.72fr) minmax(0,1.55fr);gap:18px;align-items:center;margin:0 0 14px;padding:14px 18px;border:1px solid rgba(91,47,100,.12);border-radius:15px;background:linear-gradient(145deg,#fff,#fbf8fb);box-shadow:0 5px 18px rgba(77,45,88,.035)}
.strategy-market-direction *{box-sizing:border-box}.strategy-market-direction-copy{min-width:0}.strategy-market-direction-kicker{display:block;color:#b43773;font-size:10.5px;font-weight:850;letter-spacing:.08em}.strategy-market-direction-title{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;margin-top:3px}.strategy-market-direction-title b{color:#322336;font-size:18px;letter-spacing:-.025em}.strategy-market-direction-title strong{color:#4e3a52;font-size:21px;letter-spacing:-.03em}.strategy-market-direction-scope{margin-top:4px;color:#776879;font-size:10.5px;line-height:1.45}
.strategy-market-direction-viz{min-width:0}.strategy-market-direction-scale{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;margin-bottom:6px;color:#78697a;font-size:10px;font-weight:760}.strategy-market-direction-scale span:nth-child(2){text-align:center}.strategy-market-direction-scale span:last-child{text-align:right}.strategy-market-direction-track{position:relative;height:11px;border:1px solid rgba(91,47,100,.13);border-radius:999px;background:linear-gradient(90deg,rgba(117,139,166,.12),rgba(255,255,255,.96) 50%,rgba(91,151,119,.13));box-shadow:inset 0 1px 2px rgba(57,39,62,.04)}.strategy-market-direction-center{position:absolute;left:50%;top:-4px;bottom:-4px;width:1px;background:rgba(91,47,100,.22)}.strategy-market-direction-marker{position:absolute;top:50%;width:17px;height:17px;border:4px solid #fff;border-radius:50%;background:#684b70;box-shadow:0 1px 6px rgba(57,39,62,.24);transform:translate(-50%,-50%);transition:left .18s ease}.strategy-market-direction-meta{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:7px;color:#67586a;font-size:10.5px}.strategy-market-direction-meta b{color:#443048}.strategy-market-direction-note{margin-top:4px;color:#817383;font-size:9.8px;line-height:1.4}
.strategy-secondary-insights{margin:10px 0 14px;border:1px solid rgba(91,47,100,.10);border-radius:12px;background:#fff}.strategy-secondary-insights>summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 13px;color:#554259;font-size:11px;font-weight:800;cursor:pointer;list-style:none}.strategy-secondary-insights>summary::-webkit-details-marker{display:none}.strategy-secondary-insights>summary:after{content:"펼치기";color:#8a798d;font-size:10px;font-weight:700}.strategy-secondary-insights[open]>summary:after{content:"접기"}.strategy-secondary-insights>.decision-integrated-insight{margin:0!important;border:0!important;border-top:1px solid rgba(91,47,100,.08)!important;border-radius:0 0 12px 12px!important;box-shadow:none!important}.strategy-secondary-insights>.decision-integrated-insight .head h2{font-size:15px!important}.strategy-secondary-insights>.decision-integrated-insight .head p{font-size:10.5px!important}
@media(max-width:760px){.strategy-market-direction{grid-template-columns:1fr;gap:10px;padding:12px 13px}.strategy-market-direction-title b{font-size:16px}.strategy-market-direction-title strong{font-size:19px}.strategy-market-direction-meta{justify-content:flex-start}.strategy-secondary-insights>summary{padding:10px 12px}}
</style>
""".strip()

_SCRIPT = r'''
<script id="strategy-market-direction-script">
(()=>{
  "use strict";
  const DATA_ID="rate-monitor-data";
  const BAR_CLASS="strategy-market-direction";
  const DETAILS_CLASS="strategy-secondary-insights";
  let scheduled=false;

  function payload(){
    try{return JSON.parse(document.getElementById(DATA_ID)?.textContent||"{}")}catch{return{}}
  }
  function direction(changes){
    const up=Math.max(0,Number(changes?.up_count||0));
    const down=Math.max(0,Number(changes?.down_count||0));
    const total=up+down;
    const position=total?Math.max(0,Math.min(100,up/total*100)):50;
    const label=!total?"변화 없음":up>down?"상승 우세":down>up?"하락 우세":"혼조";
    return{up,down,total,position,label};
  }
  function bar(){
    const readiness=document.querySelector(".ux-decision-readiness");
    if(!readiness)return;
    const changes=payload()?.strategy?.market_changes||{};
    const state=direction(changes);
    let host=document.querySelector(`.${BAR_CLASS}`);
    if(!host){
      host=document.createElement("section");
      host.className=BAR_CLASS;
      host.setAttribute("aria-label","최근 30일 시장 방향");
      readiness.insertAdjacentElement("beforebegin",host);
    }
    host.innerHTML=`
      <div class="strategy-market-direction-copy">
        <span class="strategy-market-direction-kicker">최근 30일</span>
        <div class="strategy-market-direction-title"><b>시장 방향</b><strong>${state.label}</strong></div>
        <div class="strategy-market-direction-scope">저축은행 · 12개월 정기예금 · 최고금리 변경 이벤트</div>
      </div>
      <div class="strategy-market-direction-viz">
        <div class="strategy-market-direction-scale" aria-hidden="true"><span>인하 우세</span><span>혼조</span><span>인상 우세</span></div>
        <div class="strategy-market-direction-track" role="meter" aria-label="인상 이벤트 비중" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${state.position.toFixed(1)}">
          <i class="strategy-market-direction-center" aria-hidden="true"></i>
          <i class="strategy-market-direction-marker" style="left:${state.position.toFixed(2)}%" aria-hidden="true"></i>
        </div>
        <div class="strategy-market-direction-meta"><span><b>인상 ${state.up.toLocaleString("ko-KR")}건</b> · 인하 ${state.down.toLocaleString("ko-KR")}건</span><span>변경 이벤트 ${state.total.toLocaleString("ko-KR")}건</span></div>
        <div class="strategy-market-direction-note">실제 금리 변경 이벤트의 방향 균형을 표시합니다. 예측·추천 점수가 아닙니다.</div>
      </div>`;
  }
  function secondaryInsights(){
    const insight=document.querySelector(".decision-integrated-insight");
    const readiness=document.querySelector(".ux-decision-readiness");
    if(!insight||!readiness)return;
    let details=document.querySelector(`.${DETAILS_CLASS}`);
    if(!details){
      details=document.createElement("details");
      details.className=DETAILS_CLASS;
      const summary=document.createElement("summary");
      summary.textContent="세부 인사이트";
      details.append(summary);
    }
    const title=insight.querySelector(".head h2"),copy=insight.querySelector(".head p");
    if(title)title.textContent="세부 시장 인사이트";
    if(copy)copy.textContent="경쟁강도·지역 편차·우대조건 구조 등 보조 판단 근거입니다.";
    if(insight.parentElement!==details)details.append(insight);
    const top5=document.querySelector(".decision-integrated-top5");
    const anchor=top5||readiness;
    if(details.previousElementSibling!==anchor)anchor.insertAdjacentElement("afterend",details);
  }
  function render(){scheduled=false;bar();secondaryInsights()}
  function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(render)}
  function install(){
    render();
    const root=document.querySelector("main,.shell")||document.body;
    new MutationObserver(schedule).observe(root,{subtree:true,childList:true});
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
'''.strip("\n")


def inject_strategy_market_direction(html: str) -> str:
    """Strategy 의사결정 시작부에 factual 30일 시장 방향 presentation을 합성한다."""
    if STYLE_MARKER in html and SCRIPT_MARKER in html:
        return html
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        raise DashboardBuildError("Strategy market-direction 주입 상태가 불완전하다")
    if 'id="market-scope"' not in html:
        return html
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy market-direction 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _STYLE + "\n</head>", 1)
    return rendered.replace("</body>", _SCRIPT + "\n</body>", 1)
