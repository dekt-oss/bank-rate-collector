# ruff: noqa: E501
"""Strategy 화면을 시장현황→금리설계→상세판단 순서로 재배치하는 presentation.

계산·source precedence·stable identity·예측계수는 바꾸지 않는다. 이미 존재하는
Strategy DOM을 실무 의사결정 흐름으로 재배치하고, 데스크톱에는 실제 기능명을
사용한 왼쪽 floating navigation을 제공한다. 모바일/태블릿은 기존 세로 스크롤을
유지한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.market_funding_strategy_presentation import (
    inject_market_funding_strategy_presentation,
)
from rate_monitor.services.strategy_brand_theme_presentation import inject_strategy_brand_theme

STYLE_MARKER = 'id="strategy-workspace-style"'
SCRIPT_MARKER = 'id="strategy-workspace-script"'

_CSS = r"""
<style id="strategy-workspace-style">
.workspace-section-label{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:22px 3px 9px;padding:0 2px;scroll-margin-top:88px}.workspace-section-label div{display:flex;align-items:baseline;gap:8px}.workspace-section-label em{font:800 9px var(--mono);font-style:normal;letter-spacing:.08em;color:#7ca993}.workspace-section-label strong{font-size:13px;letter-spacing:-.02em;color:#dbe7e1}.workspace-section-label span{color:#667a70;font-size:9px;text-align:right}
.workspace-market-first{scroll-margin-top:88px}.workspace-market-first .kpi{border-color:rgba(128,200,166,.18)}
.workspace-design .sim{border-color:rgba(128,200,166,.28);background:radial-gradient(circle at 82% 4%,rgba(212,179,111,.09),transparent 28%),linear-gradient(148deg,rgba(17,38,31,.99),rgba(8,22,18,.99));box-shadow:0 22px 56px rgba(0,0,0,.24)}.workspace-design .head h2{font-size:18px}.workspace-design .planning-strip>div{background:rgba(7,24,19,.44)}
.workspace-model-detail{margin-top:1px;border:1px solid rgba(128,200,166,.12);border-radius:10px;background:rgba(4,14,11,.18);overflow:hidden}.workspace-model-detail>summary{cursor:pointer;list-style:none;padding:10px 11px;color:#83968c;font-size:9px;font-weight:760}.workspace-model-detail>summary::-webkit-details-marker{display:none}.workspace-model-detail>summary:after{content:" 펼치기";float:right;color:#60736a;font-weight:500}.workspace-model-detail[open]>summary:after{content:" 접기"}.workspace-model-detail-body{display:grid;gap:10px;padding:0 10px 10px}.workspace-model-detail .prediction-results,.workspace-model-detail .model-detail,.workspace-model-detail .model-evidence{margin:0}
.workspace-legacy-pref{margin:0;border:1px solid rgba(213,225,219,.07);border-radius:12px;background:rgba(4,14,11,.18);overflow:hidden}.workspace-legacy-pref>summary{cursor:pointer;list-style:none;padding:10px 12px;color:#7e9087;font-size:9px;font-weight:760}.workspace-legacy-pref>summary::-webkit-details-marker{display:none}.workspace-legacy-pref>summary:after{content:" 펼치기";float:right;color:#5f7369;font-weight:500}.workspace-legacy-pref[open]>summary:after{content:" 접기"}.workspace-legacy-pref .preference-card{border:0;border-radius:0;box-shadow:none;background:transparent;min-height:0!important}.workspace-insights{grid-template-columns:1fr!important}.workspace-insights .insightcard{min-height:0!important}
.workspace-detail.primary:not(.busan-focus){grid-template-columns:minmax(300px,.68fr) minmax(0,1.32fr)}.workspace-detail.primary:not(.busan-focus) .mapcard{min-height:350px}.workspace-detail.primary:not(.busan-focus) .mapstage{height:270px}.workspace-detail.primary:not(.busan-focus)>article:last-child{min-height:350px}.workspace-detail.primary:not(.busan-focus) .pad{padding:14px}.workspace-detail.primary:not(.busan-focus) td{padding:7px 8px}
.workspace-detail-anchor{scroll-margin-top:88px}.workspace-detail-group{margin-top:0}
.workspace-event-contract{display:block;margin:6px 15px 0;color:#667a70;font-size:9px;line-height:1.45}.workspace-event-contract b{color:#8ea69a}.market-flow .changes:not([open]){min-height:0}.market-flow .changes:not([open]) summary{padding:12px 14px}.market-flow .changes:not([open]) summary:after{content:"필요할 때 펼치기"}
.strategy-workspace-nav{position:fixed;z-index:25;left:18px;top:50%;transform:translateY(-45%);width:176px;padding:10px;border:1px solid rgba(91,47,100,.13);border-radius:16px;background:rgba(255,255,255,.92);box-shadow:0 18px 48px rgba(52,31,58,.14);backdrop-filter:blur(18px)}.strategy-workspace-nav .workspace-nav-title{display:block;padding:5px 8px 7px;color:#5b2f64;font-size:10px;font-weight:840;letter-spacing:-.01em}.strategy-workspace-nav .workspace-nav-group{display:block;margin:7px 8px 3px;color:#9a8a9c;font-size:8.5px;font-weight:800;letter-spacing:.08em}.strategy-workspace-nav a{position:relative;display:block;margin:2px 0;padding:7px 8px 7px 19px;border-radius:9px;color:#706472;font-size:10px;font-weight:720;line-height:1.25;text-decoration:none;transition:background .16s ease,color .16s ease,transform .16s ease}.strategy-workspace-nav a:before{content:"";position:absolute;left:8px;top:50%;width:4px;height:4px;border-radius:50%;background:#cfc5d1;transform:translateY(-50%)}.strategy-workspace-nav a:hover,.strategy-workspace-nav a:focus-visible{color:#4c2854;background:#faf5fa;outline:none}.strategy-workspace-nav a[aria-current="location"]{color:#4f2858;background:#f6edf7;transform:translateX(2px)}.strategy-workspace-nav a[aria-current="location"]:before{width:6px;height:6px;background:#8a4f94;box-shadow:0 0 0 3px rgba(138,79,148,.10)}
/* 전국 지도는 외부 SVG image이므로 내부 path CSS 대신 image 자체를 밝게 감쇠한다. */
.workspace-detail.primary:not(.busan-focus) .korea-map-image{opacity:.18;filter:grayscale(1) contrast(.88);transition:opacity .18s ease}
/* Brand v3 polish: 기존 dark-green control/card 잔여물을 브랜드 neutral/selected/structure 역할로 통일한다. */
.segment button{border-color:rgba(91,47,100,.12)!important;background:#FBF9FB!important;color:#6E6270!important}.segment button.active{color:var(--accent-ink)!important;border-color:var(--accent-line)!important;background:var(--accent-soft)!important}.termcard{border-color:rgba(91,47,100,.10)!important;background:#FCFAFC!important}.termcard span{color:#786C7A!important}.termcard b{color:#49384D!important}.termcard.active{border-color:var(--accent-line)!important;background:#FFF3F8!important}.termcard.active b{color:var(--accent-ink)!important}.rank{background:var(--brand-plum)!important;color:#fff!important}.busan-rate-item{border-color:rgba(91,47,100,.10)!important;background:#FCFAFC!important}.busan-rate-item span{color:#49384D!important}.busan-rate-item small{color:#7A6D7C!important}.busan-rate-item b{color:var(--brand-violet)!important}.busan-rate-item.top{border-color:var(--accent-line)!important;background:#FFF3F8!important}.busan-rate-item.top b{color:var(--accent)!important}
@media(min-width:1281px){body.strategy-workspace-has-nav .shell{width:min(1380px,calc(100% - 238px));margin-left:218px;margin-right:auto}}
@media(max-width:1280px){.strategy-workspace-nav{display:none!important}}
@media(max-width:1120px){.workspace-detail.primary:not(.busan-focus){grid-template-columns:1fr 1fr}.workspace-detail.primary:not(.busan-focus) .mapcard,.workspace-detail.primary:not(.busan-focus)>article:last-child{min-height:340px}.workspace-detail.primary:not(.busan-focus) .mapstage{height:260px}}
@media(max-width:760px){
  .hero{padding:18px 3px 12px}.hero h1{font-size:28px}.hero p{font-size:10px}
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.kpi{min-height:104px;padding:12px}.kvalue{font-size:30px}.klabel{font-size:9.5px}.kfoot{font-size:9px}
  .evidence-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.evidence-card{padding:9px 10px}.evidence-grid{font-size:9px}
  .workspace-section-label{margin-top:16px;align-items:flex-start;flex-direction:column;gap:2px}.workspace-section-label span{text-align:left}
  .workspace-design .sim{padding:15px}.workspace-design .head h2{font-size:16px}.workspace-model-detail>summary{padding:9px 10px}
  .market-intel-controls,.pref-intel-controls{display:grid;gap:7px}.market-intel-control,.pref-intel-control{flex-wrap:nowrap;overflow-x:auto;overscroll-behavior-inline:contain;padding-bottom:2px}.market-intel-control button,.pref-intel-control button{flex:0 0 auto}
  .external-context-rates,.external-context-flows{display:flex;overflow-x:auto;gap:7px;overscroll-behavior-inline:contain;scroll-snap-type:x proximity;padding-bottom:3px}.external-context-card,.external-flow{flex:0 0 min(76vw,260px);scroll-snap-align:start}
  .workspace-detail.primary:not(.busan-focus){grid-template-columns:1fr}.workspace-detail.primary:not(.busan-focus) .mapcard{min-height:350px}.workspace-detail.primary:not(.busan-focus) .mapstage{height:285px}.workspace-detail.primary:not(.busan-focus)>article:last-child{min-height:0}
}
@media(max-width:360px){.kpis,.evidence-strip{grid-template-columns:1fr}.external-context-card,.external-flow{flex-basis:86vw}}
@media(prefers-reduced-motion:reduce){.strategy-workspace-nav a{transition:none!important}}
</style>
"""

_JS = r"""
<script id="strategy-workspace-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const first=(selector,root=document)=>root.querySelector(selector);
  const insertLabel=(target,id,no,title,copy)=>{
    if(!target||$(id))return null;
    const el=document.createElement("div");
    el.id=id;el.className="workspace-section-label";
    el.innerHTML=`<div><em>${no}</em><strong>${title}</strong></div><span>${copy}</span>`;
    target.parentNode.insertBefore(el,target);
    return el;
  };
  const assignAnchor=(el,id)=>{if(!el)return null;if(!el.id)el.id=id;el.classList.add("workspace-detail-anchor");return el.id;};
  const findByHeading=(pattern)=>[...document.querySelectorAll("section,article,details")].find(el=>pattern.test(String(el.querySelector("h2,h3,summary")?.textContent||"")));
  const moveAfter=(node,anchor)=>{if(node&&anchor&&node!==anchor){anchor.insertAdjacentElement("afterend",node);return node}return anchor};

  function installModelDisclosure(planning){
    const prediction=$("prediction-panel"),predictionResults=prediction?.querySelector(".prediction-results");
    if(prediction&&predictionResults&&!prediction.querySelector(".workspace-model-detail")){
      const modelDetail=prediction.querySelector(".model-detail"),modelEvidence=prediction.querySelector(".model-evidence");
      const details=document.createElement("details");
      details.className="workspace-model-detail";
      details.innerHTML='<summary>민감도 범위 · 예측모형 상세</summary><div class="workspace-model-detail-body"></div>';
      const body=details.querySelector(".workspace-model-detail-body");
      predictionResults.parentNode.insertBefore(details,predictionResults);body.appendChild(predictionResults);
      if(modelDetail)body.appendChild(modelDetail);if(modelEvidence)body.appendChild(modelEvidence);
    }
    planning.classList.add("workspace-design");
  }

  function installLegacyPreferenceDisclosure(interpretation){
    const legacyPref=interpretation?.querySelector(".preference-card");
    if(legacyPref&&!interpretation.querySelector(".workspace-legacy-pref")){
      const details=document.createElement("details");details.className="workspace-legacy-pref";
      details.innerHTML="<summary>기존 우대조건 트렌드 요약</summary>";
      legacyPref.parentNode.insertBefore(details,legacyPref);details.appendChild(legacyPref);
    }
  }

  function clarifyMarketEventContract(marketFlow){
    const changes=marketFlow?.querySelector("details.changes");if(!changes)return;
    changes.removeAttribute("open");
    const summary=changes.querySelector("summary");
    if(summary){const chip=summary.querySelector(".chip");summary.childNodes[0].textContent="최근 30일 금리 변경 이벤트 ";if(chip)summary.appendChild(chip)}
    if(!changes.querySelector(".workspace-event-contract")){
      const note=document.createElement("small");note.className="workspace-event-contract";
      note.innerHTML="<b>변경 이벤트 진단</b> · 실제 금리가 바뀐 상품 이벤트만 집계합니다. 전체 비교상품의 인상·유지·인하 비중을 계산하는 대표 시장방향 지표와 분모가 다릅니다.";
      summary?.insertAdjacentElement("afterend",note);
    }
  }

  function buildNavigation(targets){
    if($("strategy-workspace-nav"))return;
    const groups=[
      ["시장현황",[["시장 요약",targets.summary],["금리 움직임",targets.movement],["당사 시장 위치",targets.own]]],
      ["금리설계",[["신상품 금리 시뮬레이션",targets.design]]],
      ["상세 판단요소",[["경쟁사 · Peer 분석",targets.peer],["지역별 금리",targets.region],["우대조건 · 상품구조",targets.preference],["특판 · 시장기회",targets.special],["외부 자금환경",targets.external],["데이터 근거 · 품질",targets.evidence]]]
    ];
    const nav=document.createElement("nav");nav.id="strategy-workspace-nav";nav.className="strategy-workspace-nav";nav.setAttribute("aria-label","전략화면 바로가기");
    nav.innerHTML='<span class="workspace-nav-title">전략 메뉴</span>'+groups.map(([group,items])=>`<span class="workspace-nav-group">${group}</span>${items.filter(([,id])=>id&&$(id)).map(([label,id])=>`<a href="#${id}" data-workspace-target="${id}">${label}</a>`).join("")}`).join("");
    document.body.appendChild(nav);document.body.classList.add("strategy-workspace-has-nav");
    const links=[...nav.querySelectorAll("a[data-workspace-target]")];if(!links.length)return;
    const setActive=id=>links.forEach(link=>{if(link.dataset.workspaceTarget===id)link.setAttribute("aria-current","location");else link.removeAttribute("aria-current")});
    links.forEach(link=>link.addEventListener("click",()=>setActive(link.dataset.workspaceTarget)));
    if("IntersectionObserver" in window){
      const observer=new IntersectionObserver(entries=>{const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>Math.abs(a.boundingClientRect.top)-Math.abs(b.boundingClientRect.top))[0];if(visible)setActive(visible.target.id)},{rootMargin:"-18% 0px -68% 0px",threshold:[0,.1,.4]});
      links.map(link=>$(link.dataset.workspaceTarget)).filter(Boolean).forEach(el=>observer.observe(el));
    }
    const hash=location.hash.slice(1);setActive(links.some(link=>link.dataset.workspaceTarget===hash)?hash:links[0].dataset.workspaceTarget);
  }

  function install(){
    if(document.documentElement.dataset.strategyWorkspace==="market-first-v2")return;
    const planning=$("planning-zone"),marketFlow=$("market-flow"),marketIntel=$("market-intelligence"),external=$("external-market-context"),pref=$("preference-intelligence"),interpretation=first(".grid.interpretation"),primary=first(".grid.primary"),kpis=first(".grid.kpis"),evidence=first(".evidence-strip");
    if(!planning||!marketFlow||!interpretation||!primary||!kpis)return;
    const page=planning.parentElement;

    installModelDisclosure(planning);installLegacyPreferenceDisclosure(interpretation);clarifyMarketEventContract(marketFlow);
    interpretation.classList.add("workspace-insights");primary.classList.add("workspace-detail");kpis.classList.add("workspace-market-first");

    const special=$("special-offer-radar")||findByHeading(/특판/i);
    const funding=$("market-funding-strategy")||findByHeading(/자금환경|수신잔액|조달/i);
    const peer=findByHeading(/Peer|동급|규모/i)||primary.querySelector("article:last-child");
    const region=primary.querySelector(".mapcard")||primary;

    const marketLabel=insertLabel(kpis,"workspace-label-market","01","시장현황","대표 시장방향과 당사 위치를 먼저 확인합니다.");
    let cursor=marketLabel||kpis.previousElementSibling;
    if(cursor){cursor=moveAfter(kpis,cursor);if(marketIntel)cursor=moveAfter(marketIntel,cursor);cursor=moveAfter(marketFlow,cursor)}
    const designLabel=insertLabel(planning,"workspace-label-design","02","금리설계","시장 확인 후 금리·우대·기간과 수신반응을 설계합니다.");
    cursor=marketFlow;if(designLabel)cursor=moveAfter(designLabel,cursor);cursor=moveAfter(planning,cursor);
    const detailLabel=insertLabel(primary,"workspace-label-detail","03","상세 판단요소","Peer·지역·우대·특판·자금환경·데이터 근거는 필요할 때 확인합니다.");
    if(detailLabel)cursor=moveAfter(detailLabel,cursor);cursor=moveAfter(primary,cursor);cursor=moveAfter(interpretation,cursor);if(pref)cursor=moveAfter(pref,cursor);if(special)cursor=moveAfter(special,cursor);if(external)cursor=moveAfter(external,cursor);if(funding&&funding!==external&&funding!==special)cursor=moveAfter(funding,cursor);if(evidence)moveAfter(evidence,cursor);

    const summaryId=assignAnchor(kpis,"workspace-market-summary");
    const movementId=assignAnchor(marketIntel||marketFlow,"workspace-market-movement");
    const ownCard=marketFlow.querySelector(".chartcard")||marketFlow;
    const ownId=assignAnchor(ownCard,"workspace-own-position");
    const designId=assignAnchor(planning,"workspace-rate-design");
    const peerId=assignAnchor(peer,"workspace-peer-analysis");
    const regionId=assignAnchor(region,"workspace-region-rates");
    const preferenceId=assignAnchor(pref||interpretation,"workspace-preference-structure");
    const specialId=assignAnchor(special,"workspace-special-opportunity");
    const externalId=assignAnchor(external||funding,"workspace-external-funding");
    const evidenceId=assignAnchor(evidence,"workspace-data-quality");

    buildNavigation({summary:summaryId,movement:movementId,own:ownId,design:designId,peer:peerId,region:regionId,preference:preferenceId,special:specialId,external:externalId,evidence:evidenceId});
    document.documentElement.dataset.strategyWorkspace="market-first-v2";
  }
  const scheduleInstall=()=>requestAnimationFrame(install);
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",scheduleInstall,{once:true});else scheduleInstall();
})();
</script>
"""


def inject_strategy_workspace_presentation(html: str) -> str:
    """Strategy HTML에 market-first workspace presentation을 한 번만 주입한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        rendered = html
    else:
        if has_style != has_script:
            raise DashboardBuildError("Strategy Workspace 주입 상태가 불완전하다")
        if "</head>" not in html or "</body>" not in html:
            raise DashboardBuildError("Strategy Workspace 주입 위치를 찾지 못했다")
        required = (
            'id="planning-zone"',
            'id="market-flow"',
            'class="grid interpretation"',
            'class="grid primary"',
        )
        if any(marker not in html for marker in required):
            raise DashboardBuildError("Strategy Workspace 기존 레이아웃 계약을 찾지 못했다")
        rendered = html.replace("</head>", _CSS + "\n</head>", 1)
        rendered = rendered.replace("</body>", _JS + "\n</body>", 1)
    if 'id="rate-monitor-data"' in rendered and 'id="market-flow"' in rendered:
        rendered = inject_market_funding_strategy_presentation(rendered)
    return inject_strategy_brand_theme(rendered)
