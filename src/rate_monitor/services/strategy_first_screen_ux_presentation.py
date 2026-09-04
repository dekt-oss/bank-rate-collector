# ruff: noqa: E501
"""Strategy 첫 화면의 정보 위계와 대표 통계 표현을 가볍게 정리한다.

표시 전용 후처리다. 원천 수집, canonical 상품 집계, source precedence,
stable product identity, 역사 시계열의 평균(mean) 계약과 수신예측 계산은 변경하지
않는다. 첫 화면 KPI만 이미 계산되는 ``median`` 값을 대표 중심값으로 사용한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-first-screen-ux-style"'
SCRIPT_MARKER = 'id="strategy-first-screen-ux-script"'

STYLE = r"""
<style id="strategy-first-screen-ux-style">
/* 첫 화면의 업권 선택은 데이터보다 강하게 보이지 않게 compact + soft state로 둔다. */
.strategy-sector-family-controls{gap:7px!important}
.strategy-sector-family-controls .sector-family-parent{
  min-height:32px!important;
  padding:5px 8px!important;
  gap:6px!important;
  border-radius:8px!important;
  border-color:rgba(91,47,100,.13)!important;
  background:#fbf9fb!important;
  color:#554659!important;
  font-size:10.5px!important;
  font-weight:760!important;
  box-shadow:none!important;
}
.strategy-sector-family-controls .sector-family-parent input{
  width:13px!important;
  height:13px!important;
  accent-color:#b44a78!important;
}
.strategy-sector-family-controls .sector-family-parent.selected,
.strategy-sector-family-controls .sector-family-parent:has(input:checked){
  border-color:rgba(180,74,120,.28)!important;
  background:#fff3f8!important;
  color:#6d3655!important;
  box-shadow:none!important;
}
.strategy-sector-family-controls .sector-family-parent small{
  font-size:9.5px!important;
  font-weight:680!important;
  opacity:.68!important;
}
.strategy-mutual-family{gap:5px!important}
.strategy-mutual-children{margin-left:12px!important;padding:5px 6px 5px 9px!important;border-left-width:2px!important;background:rgba(91,47,100,.025)!important}
.strategy-mutual-children .sector-toggle{min-height:31px!important;padding:5px 8px!important;font-size:10.5px!important;border-radius:8px!important}
.strategy-mutual-children .sector-toggle input{width:13px!important;height:13px!important}

/* 현재 비교/이력/예측은 큰 카드가 아니라 필터의 보조 상태 문구로 취급한다. */
.strategy-scope-contract{
  display:flex!important;
  grid-template-columns:none!important;
  align-items:center!important;
  flex-wrap:wrap!important;
  gap:5px 10px!important;
  margin:3px 2px 0!important;
  padding:0!important;
  border:0!important;
  border-radius:0!important;
  background:transparent!important;
}
.strategy-scope-contract span,
.strategy-scope-contract .boundary,
.strategy-scope-contract .available{
  display:inline-flex!important;
  align-items:baseline!important;
  gap:4px!important;
  min-width:0!important;
  padding:0!important;
  border:0!important;
  border-radius:0!important;
  background:transparent!important;
  color:#716574!important;
  font-size:9.5px!important;
  line-height:1.45!important;
}
.strategy-scope-contract span+span:before{content:"·";margin-right:5px;color:#b7aeb9}
.strategy-scope-contract b,
.strategy-scope-contract .boundary b,
.strategy-scope-contract .available b{
  display:inline!important;
  margin:0!important;
  color:#514456!important;
  font-size:9.5px!important;
  font-weight:820!important;
  letter-spacing:0!important;
}

/* 첫 화면 KPI는 비교군 → 중앙값 → 최고금리 → 상위10% 진입선 순서로 읽힌다. */
.kpis .kpi{min-width:0}
.kpis .kpi.strategy-median-kpi #trend-delta{display:none!important}
.kpis #median{display:none!important}

@media(max-width:760px){
  .strategy-sector-family-controls .sector-family-parent{min-height:31px!important;font-size:10.5px!important}
  .strategy-mutual-children{margin-left:9px!important}
  .strategy-scope-contract{align-items:flex-start!important;gap:3px 8px!important}
  .strategy-scope-contract span{font-size:9px!important}
  .strategy-scope-contract b{font-size:9px!important}
}
</style>
""".strip()

SCRIPT = r'''
<script id="strategy-first-screen-ux-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);

  function replaceLeadingLabel(host,text){
    if(!host)return;
    const node=[...host.childNodes].find(item=>item.nodeType===Node.TEXT_NODE);
    if(node)node.nodeValue=`${text} `;
  }

  function installKpiHierarchy(){
    const host=document.querySelector(".kpis"),count=$("count"),medianValue=$("mean"),marketMax=$("market-max"),top10=$("top10");
    if(!host||!count||!medianValue||!marketMax||!top10)return;
    const compareCard=count.closest(".kpi"),medianCard=medianValue.closest(".kpi"),maxCard=marketMax.closest(".kpi"),topCard=top10.closest(".kpi");
    if(!compareCard||!medianCard||!maxCard||!topCard)return;

    [compareCard,medianCard,maxCard,topCard].forEach(card=>host.appendChild(card));
    medianCard.classList.add("strategy-median-kpi");
    replaceLeadingLabel(medianCard.querySelector(".klabel"),"시장 중앙값");
    const foot=medianCard.querySelector(".kfoot span:first-child");
    if(foot)foot.textContent="상품 대표 최고금리 중앙값";

    const medianSource=$("median");
    const syncMedian=()=>{
      const raw=String(medianSource?.textContent||"").replace(/^중앙값\s*/,"").trim();
      if(!raw||raw==="—"){medianValue.textContent="—";return}
      const match=raw.match(/^(-?\d+(?:\.\d+)?)%$/);
      if(!match){medianValue.textContent="—";return}
      medianValue.innerHTML=`${match[1]}<small>%</small>`;
    };
    if(medianSource){
      new MutationObserver(syncMedian).observe(medianSource,{childList:true,subtree:true,characterData:true});
      syncMedian();
    }
  }

  function setScopeLabel(node,text){
    if(node&&String(node.textContent||"")!==text)node.textContent=text;
  }

  function compactScopeContract(){
    const contract=$("strategy-scope-contract");
    if(!contract)return;
    const labels=contract.querySelectorAll("b");
    setScopeLabel(labels[0],"비교 기준");
    setScopeLabel(labels[1],"이력");
    setScopeLabel(labels[2],"예측");
  }

  function install(){
    installKpiHierarchy();
    compactScopeContract();
    const root=$("market-scope")?.parentElement||document.body;
    new MutationObserver(compactScopeContract).observe(root,{childList:true,subtree:true});
    requestAnimationFrame(compactScopeContract);
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});
  else install();
})();
</script>
'''.strip("\n")


def inject_strategy_first_screen_ux(html: str) -> str:
    """Strategy 첫 화면에 compact controls와 median 중심 KPI 위계를 주입한다."""
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        return html
    if 'id="market-scope"' not in html:
        return html
    required = (
        'class="grid kpis"',
        'id="market-max"',
        'id="mean"',
        'id="count"',
        'id="median"',
        'id="top10"',
    )
    missing = [anchor for anchor in required if anchor not in html]
    if missing:
        raise DashboardBuildError(
            "Strategy 첫 화면 UX anchor를 찾지 못했다: " + ", ".join(missing)
        )
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy 첫 화면 UX 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", STYLE + "\n</head>", 1)
    return rendered.replace("</body>", SCRIPT + "\n</body>", 1)
