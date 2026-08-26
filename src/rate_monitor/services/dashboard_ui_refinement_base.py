# ruff: noqa: E501
"""검색 조회/Strategy 공통 헤더와 검색 지도 가독성 보정.

이 모듈은 presentation-only layer다. 수집 데이터, 금리 산식, source precedence,
stable product identity, Strategy release gate를 변경하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.main_map_drilldown_refinement import (
    inject_main_map_drilldown_refinement,
)

STYLE_MARKER = 'id="dashboard-ui-refinement-style"'
SCRIPT_MARKER = 'id="dashboard-ui-refinement-script"'
_STRATEGY_TEMPLATE = Path("web/templates/strategy.html")

DASHBOARD_UI_STYLE = r"""
<style id="dashboard-ui-refinement-style">
/* Shared product header: Search and Strategy keep one visual/navigation contract. */
header.top.shared-dashboard-header,
header.topbar.shared-dashboard-header{
  position:sticky!important;top:10px!important;z-index:40!important;
  display:grid!important;grid-template-columns:auto minmax(0,1fr) auto!important;
  align-items:center!important;gap:16px!important;min-height:64px!important;
  padding:9px 14px!important;border:0!important;border-radius:16px!important;
  background:radial-gradient(circle at 8% 0,rgba(255,255,255,.10),transparent 28%),linear-gradient(130deg,#4D2D58 0%,#734A7E 44%,#B34A77 100%)!important;
  box-shadow:0 12px 30px rgba(65,36,71,.16)!important;overflow:visible!important;
  backdrop-filter:none!important;color:#fff!important;
}
.shared-header-identity,header.topbar.shared-dashboard-header>.identity{display:flex!important;align-items:center!important;gap:10px!important;min-width:max-content!important}
.shared-header-logo,header.topbar.shared-dashboard-header .logo{display:grid!important;place-items:center!important;width:36px!important;height:36px!important;border:1px solid rgba(255,255,255,.20)!important;border-radius:11px!important;background:rgba(255,255,255,.13)!important;color:#fff!important;box-shadow:inset 0 1px rgba(255,255,255,.16)!important;font:850 10px/1 var(--sans)!important}
.shared-header-identity strong,header.topbar.shared-dashboard-header>.identity b{color:#fff!important;font-size:14px!important;font-weight:800!important;letter-spacing:-.02em!important}
header.top.shared-dashboard-header>.page-nav,header.topbar.shared-dashboard-header>.nav{justify-self:center!important;display:flex!important;padding:4px!important;border:1px solid rgba(255,255,255,.10)!important;border-radius:11px!important;background:rgba(255,255,255,.10)!important;box-shadow:none!important}
header.top.shared-dashboard-header>.page-nav a,header.topbar.shared-dashboard-header>.nav a{text-decoration:none!important;padding:7px 15px!important;border-radius:8px!important;color:rgba(255,255,255,.74)!important;background:transparent!important;font-size:12px!important;font-weight:760!important;white-space:nowrap!important}
header.top.shared-dashboard-header>.page-nav a.active,header.topbar.shared-dashboard-header>.nav a.active{color:#5B2F64!important;background:#fff!important;box-shadow:0 2px 8px rgba(48,26,53,.16)!important}
header.top.shared-dashboard-header>.page-nav a:focus-visible,header.topbar.shared-dashboard-header>.nav a:focus-visible{outline:2px solid rgba(255,255,255,.92)!important;outline-offset:2px!important}
header.top.shared-dashboard-header>.head-right,header.topbar.shared-dashboard-header>.meta{justify-self:end!important;width:auto!important;max-width:none!important;margin:0!important;display:flex!important;align-items:center!important;justify-content:flex-end!important;gap:8px!important;min-width:0!important;color:rgba(255,255,255,.78)!important;font-size:10.5px!important;white-space:nowrap!important}
header.top.shared-dashboard-header .main-report-button,header.topbar.shared-dashboard-header .ux-report-button{order:-2!important;appearance:none!important;border:1px solid rgba(255,255,255,.22)!important;border-radius:8px!important;background:rgba(255,255,255,.10)!important;color:#fff!important;padding:6px 9px!important;font:760 10.5px var(--sans)!important;box-shadow:none!important;cursor:pointer!important;white-space:nowrap!important}
header.top.shared-dashboard-header .main-report-button:hover,header.top.shared-dashboard-header .main-report-button:focus-visible,header.topbar.shared-dashboard-header .ux-report-button:hover,header.topbar.shared-dashboard-header .ux-report-button:focus-visible{background:rgba(255,255,255,.18)!important;outline:none!important}
.shared-header-time{color:rgba(255,255,255,.72)!important;font-size:10px!important;white-space:nowrap!important}
header.top.shared-dashboard-header #health-open{min-height:0!important;border:0!important;border-radius:6px!important;background:transparent!important;color:#fff!important;padding:4px 0!important;font-size:10.5px!important;box-shadow:none!important}
header.top.shared-dashboard-header #health-open:hover{background:transparent!important;color:#fff!important}header.top.shared-dashboard-header #health-open:focus-visible{outline:1px solid rgba(255,255,255,.65)!important;outline-offset:3px!important}
header.top.shared-dashboard-header #health-open .health-dot{width:8px!important;height:8px!important;box-shadow:0 0 0 4px rgba(255,255,255,.08)!important}
header.topbar.shared-dashboard-header .statusdot{width:8px!important;height:8px!important;background:#5fc7a0!important;box-shadow:0 0 0 4px rgba(95,199,160,.12)!important}

/* Search-only title/company/freshness controls live below the common header. */
.shared-page-context-main{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:18px;margin:14px 0 0;padding:15px 17px;border:1px solid rgba(91,47,100,.10);border-radius:14px;background:linear-gradient(145deg,#fff,#fbf8fb);box-shadow:0 7px 20px rgba(61,39,65,.05)}
.shared-page-context-main>.brand{min-width:0!important;display:flex!important;align-items:center!important;gap:13px!important}
.shared-page-context-main .brand-mark{width:44px!important;height:44px!important;border:1px solid rgba(91,47,100,.16)!important;border-radius:13px!important;background:linear-gradient(145deg,#f4edf5,#eaddea)!important;color:#5B2F64!important;box-shadow:inset 0 1px #fff!important;font-size:20px!important}
.shared-page-context-main .brand-title{margin:0!important;color:#302433!important;font-size:clamp(23px,2.1vw,31px)!important;line-height:1.08!important;letter-spacing:-.04em!important}
.shared-page-context-main .sub{margin-top:5px!important;color:#756b77!important;font-size:11.5px!important;line-height:1.45!important}
.shared-page-actions{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap;min-width:0}
.shared-page-context-main .mine-pick{min-width:210px;border-color:rgba(91,47,100,.12)!important;background:#fff!important;box-shadow:none!important}
.shared-page-context-main .mine-pick label{color:#776b79!important}
.shared-page-context-main .mine-pick select{color:#4e3a52!important;background:#fff!important}
.shared-page-context-main .stamp{color:#756b77!important;font-size:10px!important;text-align:right!important}
.shared-page-context-main .collect-box{margin-left:0!important}

/* Search map: keep choropleth, but make direct region comparison the primary reading path. */
.main-map-shell{grid-template-columns:minmax(0,1fr) minmax(190px,225px)!important;gap:12px!important}
.main-map-stage{min-height:390px!important;background:radial-gradient(circle at 50% 48%,rgba(91,47,100,.045),transparent 48%),rgba(255,255,255,.46)!important}
.main-map-stage svg{max-height:455px!important;padding:8px 10px!important}
.main-map-side{padding:12px!important;gap:8px!important}
.main-map-side h3{font-size:15px!important}.main-map-rate{font-size:25px!important}.main-map-meta{font-size:10px!important;line-height:1.5!important}.main-map-top{margin-top:5px!important;padding-top:8px!important;gap:5px!important}.main-map-top b{font-size:10.5px!important}.main-map-hint{margin-top:auto!important;padding-top:7px!important;font-size:9.5px!important;line-height:1.45!important}
.main-map-label-layer{pointer-events:none}.main-map-direct-label{text-anchor:middle}.main-map-label-name,.main-map-label-rate{paint-order:stroke;stroke:rgba(255,255,255,.96);stroke-linejoin:round;stroke-linecap:round}.main-map-label-name{fill:#413343;stroke-width:4px;font:820 14px var(--sans);letter-spacing:-.02em}.main-map-label-rate{fill:#5B2F64;stroke-width:4.5px;font:900 16px var(--mono);font-variant-numeric:tabular-nums}.main-map-label-rate.is-thin{fill:#8a7e8c;font-size:12px;font-family:var(--sans);font-weight:760}

@media(max-width:1000px){.shared-page-context-main{grid-template-columns:1fr}.shared-page-actions{justify-content:flex-start}.main-map-shell{grid-template-columns:1fr!important}.main-map-side{display:grid!important;grid-template-columns:minmax(160px,.7fr) minmax(0,1.3fr)!important;align-items:start!important}.main-map-side .main-map-top{margin:0!important;padding:0!important;border:0!important}.main-map-hint{grid-column:1/-1;margin:0!important}}
@media(max-width:760px){header.top.shared-dashboard-header,header.topbar.shared-dashboard-header{grid-template-columns:auto minmax(0,1fr)!important;row-gap:8px!important}.shared-header-identity strong,header.topbar.shared-dashboard-header>.identity b{display:none!important}header.top.shared-dashboard-header>.page-nav,header.topbar.shared-dashboard-header>.nav{justify-self:end!important}header.top.shared-dashboard-header>.head-right,header.topbar.shared-dashboard-header>.meta{grid-column:1/-1!important;justify-self:stretch!important;justify-content:flex-end!important}.shared-page-context-main{padding:13px!important}.shared-page-actions{align-items:stretch!important}.shared-page-context-main .mine-pick{min-width:min(100%,240px)}.main-map-stage{min-height:360px!important}.main-map-label-name{font-size:21px!important;stroke-width:6px!important}.main-map-label-rate{font-size:23px!important;stroke-width:6px!important}.main-map-label-rate.is-thin{font-size:17px!important}.main-map-side{grid-template-columns:1fr!important}}
@media(max-width:480px){header.top.shared-dashboard-header>.page-nav a,header.topbar.shared-dashboard-header>.nav a{padding:6px 9px!important;font-size:10px!important}header.topbar.shared-dashboard-header>.meta{display:flex!important;font-size:9.5px!important}.shared-header-time,header.topbar.shared-dashboard-header>.meta #time{display:none!important}.shared-page-context-main .brand-mark{display:none!important}.shared-page-context-main .brand-title{font-size:22px!important}.main-map-stage{min-height:330px!important}.main-map-stage svg{padding:5px!important}}
@media print{.shared-page-context-main{display:none!important}.main-map-label-name,.main-map-label-rate{stroke:#fff!important}}
</style>
"""

DASHBOARD_UI_SCRIPT = r"""
<script id="dashboard-ui-refinement-script">
(()=>{
  "use strict";
  const NS="http://www.w3.org/2000/svg";
  const REGION_LABEL_POSITIONS={
    "서울":[261,132],"인천·경기":[286,194],"강원":[405,124],"충청":[313,298],
    "전라":[266,454],"경북":[455,330],"경남":[407,452],"부산":[505,482],"제주":[216,635]
  };

  function generatedTimeLabel(){
    try{
      const data=JSON.parse(document.getElementById("rate-monitor-data")?.textContent||"{}");
      const d=data.generated_at?new Date(data.generated_at):null;
      if(d&&!Number.isNaN(d.getTime()))return `기준 ${d.toLocaleString("ko-KR",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})}`;
    }catch{}
    return "기준시각 미확인";
  }

  function installMainHeader(header){
    if(header.dataset.sharedDashboardHeader)return;
    header.dataset.sharedDashboardHeader="main";
    header.classList.add("shared-dashboard-header");
    const brand=header.querySelector(":scope > .brand");
    const actions=header.querySelector(":scope > .head-right");
    if(!brand||!actions)return;

    const identity=document.createElement("div");
    identity.className="shared-header-identity";
    identity.innerHTML='<span class="shared-header-logo" aria-hidden="true">SB</span><strong>SB 인사이트</strong>';
    header.prepend(identity);

    if(!actions.querySelector(".shared-header-time")){
      const time=document.createElement("span");
      time.className="shared-header-time";
      time.textContent=generatedTimeLabel();
      const health=actions.querySelector("#health-open");
      if(health)actions.insertBefore(time,health);else actions.appendChild(time);
    }

    if(!document.querySelector(".shared-page-context-main")){
      const context=document.createElement("section");
      context.className="shared-page-context-main";
      context.setAttribute("aria-label","검색 조회 화면 정보와 전용 제어");
      const pageActions=document.createElement("div");
      pageActions.className="shared-page-actions";
      context.appendChild(brand);
      for(const selector of [".mine-pick",".stamp",".collect-box"]){
        const node=actions.querySelector(selector);
        if(node)pageActions.appendChild(node);
      }
      if(pageActions.childElementCount)context.appendChild(pageActions);
      header.insertAdjacentElement("afterend",context);
    }
  }

  function installStrategyHeader(header){
    if(header.dataset.sharedDashboardHeader)return;
    header.dataset.sharedDashboardHeader="strategy";
    header.classList.add("shared-dashboard-header");
    const identity=header.querySelector(":scope > .identity");
    const logo=identity?.querySelector(".logo");
    const title=identity?.querySelector("b");
    if(logo)logo.textContent="SB";
    if(title)title.textContent="SB 인사이트";
  }

  function installSharedHeader(){
    const main=document.querySelector("header.top");
    const strategy=document.querySelector("header.topbar");
    if(main)installMainHeader(main);
    else if(strategy)installStrategyHeader(strategy);
  }

  function parseRegionRate(path){
    const text=path.getAttribute("aria-label")||"";
    const match=text.match(/중앙값\s+([0-9]+(?:\.[0-9]+)?)%/);
    return match?Number(match[1]):null;
  }

  function addText(group,klass,x,y,text){
    const node=document.createElementNS(NS,"text");
    node.setAttribute("class",klass);
    node.setAttribute("x",String(x));
    node.setAttribute("y",String(y));
    node.textContent=text;
    group.appendChild(node);
  }

  function syncMainMapLabels(){
    const svg=document.querySelector("#reg .main-map-stage svg");
    if(!svg)return;
    svg.querySelector(".main-map-label-layer")?.remove();
    const values=new Map();
    svg.querySelectorAll("path[data-region-key]").forEach(path=>{
      const key=path.dataset.regionKey;
      if(!key||values.has(key))return;
      values.set(key,{rate:parseRegionRate(path),thin:path.dataset.hasRate!=="1"});
    });
    if(!values.size)return;

    const layer=document.createElementNS(NS,"g");
    layer.setAttribute("class","main-map-label-layer");
    layer.setAttribute("aria-hidden","true");
    for(const [region,pos] of Object.entries(REGION_LABEL_POSITIONS)){
      const value=values.get(region);
      if(!value)continue;
      const group=document.createElementNS(NS,"g");
      group.setAttribute("class","main-map-direct-label");
      group.dataset.regionKey=region;
      addText(group,"main-map-label-name",pos[0],pos[1]-5,region);
      addText(
        group,
        `main-map-label-rate${value.thin?" is-thin":""}`,
        pos[0],pos[1]+14,
        Number.isFinite(value.rate)?`${value.rate.toFixed(2)}%`:"표본 부족"
      );
      layer.appendChild(group);
    }
    svg.appendChild(layer);
    svg.dataset.mainMapDirectLabels="1";
  }

  function installMainMapObserver(){
    const host=document.getElementById("reg");
    if(!host||host.dataset.directLabelsObserver)return;
    host.dataset.directLabelsObserver="1";
    const observer=new MutationObserver(()=>queueMicrotask(syncMainMapLabels));
    observer.observe(host,{childList:true});
    queueMicrotask(syncMainMapLabels);
  }

  installSharedHeader();
  installMainMapObserver();
})();
</script>
"""


def inject_dashboard_ui_refinement(html: str) -> str:
    """공통 헤더와 검색 지도 가독성 presentation을 마지막 계층에 추가한다."""
    rendered = html
    if STYLE_MARKER not in rendered:
        if "</head>" not in rendered:
            raise DashboardBuildError("dashboard UI refinement를 넣을 head가 없다")
        rendered = rendered.replace("</head>", DASHBOARD_UI_STYLE + "\n</head>", 1)
    if SCRIPT_MARKER not in rendered:
        if "</body>" not in rendered:
            raise DashboardBuildError("dashboard UI refinement를 넣을 body가 없다")
        rendered = rendered.replace("</body>", DASHBOARD_UI_SCRIPT + "\n</body>", 1)

    # 검색 조회에는 #reg가 있고 Strategy에는 없다. 같은 public injection entry를
    # 유지하되 검색 화면일 때만 compact map + 부산 SVG drill-down을 마지막에
    # 덧씌운다. Strategy Release Gate와는 독립적으로 source template geometry만 읽는다.
    if 'id="reg"' in rendered:
        rendered = inject_main_map_drilldown_refinement(
            rendered,
            _STRATEGY_TEMPLATE.read_text(encoding="utf-8"),
        )
    return rendered
