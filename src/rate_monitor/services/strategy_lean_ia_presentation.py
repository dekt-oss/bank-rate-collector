# ruff: noqa: E501
"""Final Strategy Lean IA presentation reconciler.

All calculation and payload contracts stay intact. This presentation runs after the
late Strategy injectors and only reconciles visible information architecture, DOM
placement, navigation, and readability.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-lean-ia-style"'
SCRIPT_MARKER = 'id="strategy-lean-ia-script"'

_STYLE = r"""
<style id="strategy-lean-ia-style">
/* Lean IA v3: preserve owner DOM/payloads but suppress redundant visible surfaces. */
#market-flow details.changes,.strategy-market-direction,.ux-decision-readiness,.ux-decision-menu,.decision-integrated-insight,.workspace-insights .insightcard,#workspace-label-detail,#workspace-detail-disclosure,#relative-pricing-r1,#rate-funding-matrix,details.strategy-secondary-insights{display:none!important}
#market-funding-competition .funding-sector-tabs,#market-funding-competition .funding-analysis-grid,#market-funding-competition .funding-caveat{display:none!important}
[data-lean-event-direction="1"]{display:none!important}
#market-flow{grid-template-columns:minmax(0,1fr)!important}
.workspace-decision .planning-strip{grid-template-columns:repeat(4,minmax(0,1fr))!important}
.workspace-lean-label{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:24px 2px 10px;padding:0 2px;scroll-margin-top:88px}.workspace-lean-label div{display:flex;align-items:baseline;gap:10px}.workspace-lean-label em{font:800 10px var(--mono);font-style:normal;letter-spacing:.10em;color:var(--accent)}.workspace-lean-label strong{color:var(--ink);font-size:14px;font-weight:780;letter-spacing:-.025em}.workspace-lean-label span{color:var(--soft);font-size:10.5px;line-height:1.45;text-align:right}
#external-market-context,#market-funding-competition,#market-intelligence,#workspace-market-trend,#planning-zone,#workspace-competitor-position,#preference-intelligence,#special-offer-radar{scroll-margin-top:88px}
.workspace-market-trend-anchor{display:block;height:1px;pointer-events:none}
#market-funding-competition{margin-bottom:12px}#market-funding-competition .market-funding-head{margin-bottom:10px}#market-funding-competition .funding-market-strip{margin-bottom:0}
.workspace-competitor-position{display:grid;gap:12px;margin:0 0 12px;scroll-margin-top:88px}.workspace-competitor-position-head{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin:0 2px 1px}.workspace-competitor-position-head div{display:flex;align-items:baseline;gap:10px}.workspace-competitor-position-head em{font:800 10px var(--mono);font-style:normal;letter-spacing:.10em;color:var(--accent)}.workspace-competitor-position-head strong{color:var(--ink);font-size:14px;font-weight:780;letter-spacing:-.025em}.workspace-competitor-position-head span{color:var(--soft);font-size:10.5px;text-align:right}
#workspace-competitor-position>.top5-card,#workspace-competitor-position>#institution-funding-position{margin:0!important}
.top5-card[data-top5-compact="1"]{padding:17px 18px!important}.top5-card[data-top5-compact="1"] .head{margin-bottom:11px!important}.top5-card[data-top5-compact="1"] .head h2{font-size:19px!important}.top5-card[data-top5-compact="1"] th{padding:8px 9px 9px!important;font-size:11px!important}.top5-card[data-top5-compact="1"] td{padding:11px 9px!important;font-size:12px!important;line-height:1.45!important}.top5-card[data-top5-compact="1"] th:nth-child(4),.top5-card[data-top5-compact="1"] th:nth-child(5),.top5-card[data-top5-compact="1"] td:nth-child(4),.top5-card[data-top5-compact="1"] td:nth-child(5){display:none!important}.top5-card[data-top5-compact="1"] .bank{font-size:14px!important;font-weight:820!important}.top5-card[data-top5-compact="1"] .product{font-size:12px!important;line-height:1.45!important;white-space:normal!important}.top5-card[data-top5-compact="1"] .sourcehint{display:none!important}.top5-card[data-top5-compact="1"] .strongrate{font-size:16px!important;font-weight:860!important;white-space:nowrap}.top5-card[data-top5-compact="1"] .strategy-sector-badge{font-size:10.5px!important;min-height:25px!important}.top5-card[data-top5-compact="1"] .rank{width:27px!important;height:27px!important;font-size:11px!important}
.lean-secondary-disclosure{margin:10px 0 0;border:1px solid rgba(91,47,100,.13);border-radius:11px;background:#fcfafc;overflow:hidden}.lean-secondary-disclosure>summary{cursor:pointer;list-style:none;padding:11px 13px;color:#59465e;font-size:11px;font-weight:780}.lean-secondary-disclosure>summary::-webkit-details-marker{display:none}.lean-secondary-disclosure>summary:after{content:"펼치기";float:right;color:#8a7a8d;font-size:10px;font-weight:650}.lean-secondary-disclosure[open]>summary:after{content:"접기"}.lean-secondary-disclosure-body{display:grid;gap:10px;padding:0 10px 10px}
.lean-planning-headline{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:0 0 10px}.lean-planning-headline>div{min-width:0;padding:10px 11px;border:1px solid rgba(91,47,100,.12);border-radius:10px;background:#fff}.lean-planning-headline span{display:block;color:#756579;font-size:10px;font-weight:680}.lean-planning-headline b{display:block;margin-top:4px;color:#39283e;font-size:16px;font-weight:820;line-height:1.2}.lean-planning-headline small{display:block;margin-top:3px;color:#847486;font-size:9.5px;line-height:1.4}
#lean-planning-detail{margin-top:4px}#lean-planning-detail>.lean-secondary-disclosure-body{padding-top:2px}#lean-planning-detail .simform{margin:0}
#institution-funding-position>.lean-secondary-disclosure{margin-top:10px}
#preference-intelligence>.lean-secondary-disclosure,#special-offer-radar>.lean-secondary-disclosure{margin-top:10px}
.strategy-workspace-nav[data-lean-ia-nav="1"]{position:fixed;z-index:25;left:18px;top:50%;transform:translateY(-45%);width:184px;padding:10px;border:1px solid rgba(91,47,100,.13);border-radius:16px;background:rgba(255,255,255,.94);box-shadow:0 18px 48px rgba(52,31,58,.14);backdrop-filter:blur(18px)}.strategy-workspace-nav[data-lean-ia-nav="1"] .workspace-nav-title{display:block;padding:5px 8px 7px;color:#5b2f64;font-size:10px;font-weight:840}.strategy-workspace-nav[data-lean-ia-nav="1"] .workspace-nav-group{display:block;margin:7px 8px 3px;color:#9a8a9c;font-size:9px;font-weight:800;letter-spacing:.08em}.strategy-workspace-nav[data-lean-ia-nav="1"] a{position:relative;display:block;margin:2px 0;padding:7px 8px 7px 19px;border-radius:9px;color:#706472;font-size:10.5px;font-weight:720;line-height:1.3;text-decoration:none}.strategy-workspace-nav[data-lean-ia-nav="1"] a:before{content:"";position:absolute;left:8px;top:50%;width:4px;height:4px;border-radius:50%;background:#cfc5d1;transform:translateY(-50%)}.strategy-workspace-nav[data-lean-ia-nav="1"] a:hover,.strategy-workspace-nav[data-lean-ia-nav="1"] a:focus-visible{color:#4c2854;background:#faf5fa;outline:none}.strategy-workspace-nav[data-lean-ia-nav="1"] a[aria-current="location"]{color:#4f2858;background:#f6edf7;transform:translateX(2px)}.strategy-workspace-nav[data-lean-ia-nav="1"] a[aria-current="location"]:before{width:6px;height:6px;background:#8a4f94;box-shadow:0 0 0 3px rgba(138,79,148,.10)}
@media(min-width:1281px){body.strategy-workspace-has-nav .shell{width:min(1380px,calc(100% - 246px));margin-left:226px;margin-right:auto}}
@media(max-width:1280px){.strategy-workspace-nav{display:none!important}}
@media(max-width:760px){.workspace-decision .planning-strip{grid-template-columns:repeat(2,minmax(0,1fr))!important}.workspace-lean-label,.workspace-competitor-position-head{align-items:flex-start;flex-direction:column;gap:3px}.workspace-lean-label span,.workspace-competitor-position-head span{text-align:left}.top5-card[data-top5-compact="1"]{padding:14px!important}.top5-card[data-top5-compact="1"] tbody tr{grid-template-columns:30px auto minmax(0,1fr) auto!important;grid-template-areas:"r s n m"!important;gap:5px 8px!important;padding:10px!important}.top5-card[data-top5-compact="1"] td:nth-child(1){grid-area:r!important}.top5-card[data-top5-compact="1"] td:nth-child(2){grid-area:s!important}.top5-card[data-top5-compact="1"] td:nth-child(3){grid-area:n!important}.top5-card[data-top5-compact="1"] td:nth-child(6){grid-area:m!important;text-align:right!important}.top5-card[data-top5-compact="1"] .bank{font-size:13px!important}.top5-card[data-top5-compact="1"] .product{font-size:11.5px!important}.top5-card[data-top5-compact="1"] .strongrate{font-size:15px!important}}
@media(max-width:760px){.lean-planning-headline{grid-template-columns:1fr 1fr}}
@media(max-width:480px){.workspace-decision .planning-strip{grid-template-columns:1fr!important}.lean-planning-headline{grid-template-columns:1fr!important}}
</style>
""".strip()

_SCRIPT = r'''
<script id="strategy-lean-ia-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const first=(selector,root=document)=>root.querySelector(selector);
  const isConnected=node=>Boolean(node&&node.isConnected);
  let navObserver=null;

  function hide(node){if(node&&!node.hidden)node.hidden=true;return node}
  function moveAfter(node,anchor){if(isConnected(node)&&isConnected(anchor)&&node!==anchor){if(anchor.nextElementSibling!==node)anchor.insertAdjacentElement("afterend",node);return node}return anchor}
  function setLabel(node,no,title,copy){
    if(!node)return null;
    node.classList.add("workspace-section-label","workspace-lean-label");
    const markup="<div><em>"+no+"</em><strong>"+title+"</strong></div><span>"+copy+"</span>";
    if(node.innerHTML!==markup)node.innerHTML=markup;
    return node;
  }
  function ensureLabel(id,no,title,copy,before){
    let node=$(id);
    if(!node){node=document.createElement("div");node.id=id;before?.parentNode?.insertBefore(node,before)}
    return setLabel(node,no,title,copy);
  }
  function suppressRedundantSurfaces(){
    hide(document.querySelector("#market-flow details.changes"));
    hide(document.querySelector(".strategy-market-direction"));
    hide(document.querySelector(".ux-decision-readiness"));
    hide(document.querySelector(".ux-decision-menu"));
    hide(document.querySelector(".decision-integrated-insight"));
    document.querySelectorAll(".workspace-insights .insightcard").forEach(hide);
    hide($("workspace-label-detail"));
    hide($("workspace-detail-disclosure"));
    hide($("relative-pricing-r1"));
    hide($("rate-funding-matrix"));
    document.querySelectorAll("details.strategy-secondary-insights").forEach(hide);
    const eventFlow=$("plan-flow")?.parentElement;
    if(eventFlow){eventFlow.dataset.leanEventDirection="1";eventFlow.hidden=true}
  }
  function simplifyFundingMarket(){
    const funding=$("market-funding-competition");if(!funding)return null;
    funding.querySelectorAll(".funding-sector-tabs,.funding-analysis-grid,.funding-caveat").forEach(hide);
    const title=funding.querySelector(".market-funding-head h2");if(title&&title.textContent!=="업권 수신 흐름")title.textContent="업권 수신 흐름";
    const fundingCopy="업권 전체 수신잔액의 최신값과 전년 동월 흐름을 확인합니다.";
    const copy=funding.querySelector(".market-funding-head p");if(copy&&copy.textContent!==fundingCopy)copy.textContent=fundingCopy;
    return funding;
  }
  function ensureDisclosure(host,id,label,nodes){
    if(!host)return null;
    let detail=$(id);
    if(!detail){
      detail=document.createElement("details");detail.id=id;detail.className="lean-secondary-disclosure";
      detail.innerHTML='<summary>'+label+'</summary><div class="lean-secondary-disclosure-body"></div>';
      const firstNode=nodes.find(node=>node&&node.parentElement===host);
      if(firstNode)host.insertBefore(detail,firstNode);else host.appendChild(detail);
    }
    const body=detail.querySelector(".lean-secondary-disclosure-body");
    nodes.filter(node=>node&&node!==detail&&node.parentElement===host).forEach(node=>body.appendChild(node));
    return detail;
  }
  function compactPlanning(planning){
    if(!planning)return null;
    const form=planning.querySelector(".simform"),panel=$("prediction-panel");if(!form||!panel)return null;
    const detail=ensureDisclosure(form,"lean-planning-detail","수신예측·모형 상세",[panel]);
    const toggle=$("prediction-toggle");
    if(toggle&&toggle.dataset.leanDisclosureBound!=="1"){toggle.addEventListener("click",()=>{if(detail)detail.open=true});toggle.dataset.leanDisclosureBound="1"}
    return detail;
  }
  function compactInstitution(institution){
    if(!institution)return null;
    const keep=new Set([
      institution.querySelector(":scope>.funding-position-head"),
      institution.querySelector(":scope>.funding-position-tabs"),
      institution.querySelector(":scope>.funding-position-kpis"),
    ].filter(Boolean));
    const nodes=[...institution.children].filter(node=>!keep.has(node)&&node.id!=="lean-institution-detail");
    return ensureDisclosure(institution,"lean-institution-detail","기관별 수신규모·성장·Direct Peer 상세",nodes);
  }
  function compactProductPanel(panel,id,label){
    if(!panel)return null;
    const firstChild=panel.firstElementChild;
    const nodes=[...panel.children].filter(node=>node!==firstChild&&node.id!==id);
    return ensureDisclosure(panel,id,label,nodes);
  }
  function compactSecondarySurfaces(){
    const planning=$("planning-zone"),institution=$("institution-funding-position"),pref=$("preference-intelligence"),special=$("special-offer-radar");
    const details=[
      compactPlanning(planning),
      compactInstitution(institution),
      compactProductPanel(pref,"lean-preference-detail","우대조건 침투율·당사조건 상세"),
      compactProductPanel(special,"lean-special-detail","특판 목록·시장기회 상세"),
    ].filter(Boolean);
    details.forEach(detail=>{if(detail.dataset.leanStateBound!=="1"){detail.addEventListener("toggle",()=>{detail.dataset.userToggled="1"});detail.dataset.leanStateBound="1"}});
    return details;
  }
  function ensureRegionHandoff(){
    let handoff=first(".ux-region-handoff");if(handoff)return handoff;
    const detail=first(".workspace-detail.primary");
    const anchor=detail||first(".top5-card")||$("institution-funding-position");
    if(!anchor?.parentNode)return null;
    handoff=document.createElement("div");handoff.className="ux-region-handoff";
    handoff.innerHTML='<span><b>지역·지도 상세는 검색 조회로 통합했습니다.</b> Strategy에서는 중복 지도를 제거하고 경쟁상단·금리결정 근거만 남깁니다.</span><a href="./">지역 상세 보기</a>';
    anchor.parentNode.insertBefore(handoff,anchor);
    return handoff;
  }
  function ensureCompetitorWrapper(top5,institution){
    let wrapper=$("workspace-competitor-position");
    if(!wrapper){
      wrapper=document.createElement("section");wrapper.id="workspace-competitor-position";wrapper.className="workspace-competitor-position";
      wrapper.innerHTML='<div class="workspace-competitor-position-head"><div><em>04</em><strong>경쟁사 · 기관 포지션</strong></div><span>금리 경쟁상단과 기관 수신규모·성장을 같은 흐름에서 비교합니다.</span></div>';
      const planning=$("planning-zone"),anchor=planning||$("market-flow")||$("market-intelligence");
      anchor?.insertAdjacentElement("afterend",wrapper);
    }
    if(top5&&top5.parentElement!==wrapper)wrapper.appendChild(top5);
    if(institution&&institution.parentElement!==wrapper)wrapper.appendChild(institution);
    return wrapper;
  }
  function reorder(){
    const kpis=first(".grid.kpis"),marketIntel=$("market-intelligence"),marketFlow=$("market-flow"),planning=$("planning-zone");
    // The decision-evidence/readability layers scope their simulator CSS to .workspace-decision.
    // Restore that intended role on the real planning host before the final IA reordering.
    planning?.classList.add("workspace-decision");
    const planningShell=planning?.closest(".workspace-decision")||planning;
    const external=$("external-market-context"),funding=simplifyFundingMarket(),pref=$("preference-intelligence"),special=$("special-offer-radar"),evidence=$("scope-evidence");
    const top5=first(".top5-card"),institution=$("institution-funding-position"),handoff=ensureRegionHandoff();
    const required=[kpis,marketIntel,marketFlow,planning,external,funding,pref,special,evidence,top5,institution,handoff];
    if(required.some(node=>!node||!node.isConnected))return false;
    const marketLabel=$("workspace-label-market")||ensureLabel("workspace-label-market","02","시장현황","대표 시장방향과 12개월 금리 위치를 확인합니다.",kpis);
    const envBefore=marketLabel||kpis;
    const envLabel=ensureLabel("workspace-label-environment","01","시장 자금환경","기준금리·은행 신규취급금리·업권 수신잔액을 먼저 확인합니다.",envBefore);
    let cursor=envLabel;
    if(external)cursor=moveAfter(external,cursor);
    if(funding)cursor=moveAfter(funding,cursor);
    setLabel(marketLabel,"02","시장현황","Market Intelligence와 12개월 시장 추이·당사 위치를 확인합니다.");
    cursor=moveAfter(marketLabel,cursor);cursor=moveAfter(kpis,cursor);
    if(marketIntel)cursor=moveAfter(marketIntel,cursor);
    const trend=marketFlow.querySelector(".chartcard");let trendAnchor=$("workspace-market-trend");if(trend&&!trendAnchor){trendAnchor=document.createElement("span");trendAnchor.id="workspace-market-trend";trendAnchor.className="workspace-market-trend-anchor";trend.prepend(trendAnchor)}else if(trend&&trendAnchor?.parentElement!==trend)trend.prepend(trendAnchor);
    cursor=moveAfter(marketFlow,cursor);
    const designLabel=ensureLabel("workspace-label-design","03","금리설계","시장 확인 후 제안금리와 수신반응 시나리오를 설계합니다.",planningShell);
    cursor=moveAfter(designLabel,cursor);cursor=moveAfter(planningShell,cursor);
    const competitor=ensureCompetitorWrapper(top5,institution);if(competitor)cursor=moveAfter(competitor,cursor);
    if(handoff){if(handoff.hidden)handoff.hidden=false;cursor=moveAfter(handoff,cursor)}
    const productBefore=pref||special||evidence;
    const productLabel=ensureLabel("workspace-label-product","05","상품 · 시장기회","우대조건 구조와 특판 기회를 실제 기능 단위로 확인합니다.",productBefore);
    if(productLabel)cursor=moveAfter(productLabel,cursor);
    if(pref)cursor=moveAfter(pref,cursor);
    if(special)cursor=moveAfter(special,cursor);
    if(evidence)cursor=moveAfter(evidence,cursor);
    return true;
  }
  const navGroups=()=>[
    ["기본환경",[["시장 자금환경","external-market-context"],["업권 수신 흐름","market-funding-competition"]]],
    ["시장현황",[["시장 금리 방향","market-intelligence"],["12개월 시장 추이","workspace-market-trend"]]],
    ["금리설계",[["신상품 금리 시뮬레이션","planning-zone"]]],
    ["경쟁분석",[["경쟁사 · 기관 포지션","workspace-competitor-position"]]],
    ["상품분석",[["우대조건 · 상품구조","preference-intelligence"],["특판 · 시장기회","special-offer-radar"]]],
  ];
  function navLinks(){return [...document.querySelectorAll('#strategy-workspace-nav[data-lean-ia-nav="1"] a[data-workspace-target]')]}
  function setActive(id){navLinks().forEach(link=>{if(link.dataset.workspaceTarget===id)link.setAttribute("aria-current","location");else link.removeAttribute("aria-current")})}
  let hashActivationTarget="";
  let hashActivationTimer=null;
  function activateHash(){const id=location.hash.slice(1),target=$(id);if(!target)return;const link=navLinks().find(item=>item.dataset.workspaceTarget===id);if(!link)return;if(hashActivationTimer)clearTimeout(hashActivationTimer);hashActivationTarget=id;setActive(id);requestAnimationFrame(()=>{target.scrollIntoView({block:"start"});setActive(id)});hashActivationTimer=setTimeout(()=>{if(hashActivationTarget===id)hashActivationTarget="";hashActivationTimer=null},1200)}
  function buildNavigation(){
    let nav=$("strategy-workspace-nav");
    if(nav?.dataset.leanIaNav==="1")return nav;
    nav?.remove();
    nav=document.createElement("nav");nav.id="strategy-workspace-nav";nav.className="strategy-workspace-nav";nav.dataset.leanIaNav="1";nav.setAttribute("aria-label","전략화면 바로가기");
    nav.innerHTML='<span class="workspace-nav-title">전략 메뉴</span>'+navGroups().map(([group,items])=>'<span class="workspace-nav-group">'+group+'</span>'+items.filter(([,id])=>$(id)).map(([label,id])=>'<a href="#'+id+'" data-workspace-target="'+id+'">'+label+'</a>').join('')).join('');
    document.body.appendChild(nav);document.body.classList.add("strategy-workspace-has-nav");
    nav.addEventListener("click",event=>{const link=event.target.closest("a[data-workspace-target]");if(!link)return;setActive(link.dataset.workspaceTarget);const target=$(link.dataset.workspaceTarget);if(target)requestAnimationFrame(()=>target.scrollIntoView({block:"start"}))});
    const links=navLinks();if(!links.length)return nav;
    if(navObserver)navObserver.disconnect();
    if("IntersectionObserver" in window){navObserver=new IntersectionObserver(entries=>{if(hashActivationTarget){setActive(hashActivationTarget);return}const hashId=location.hash.slice(1),hashNode=$(hashId),hashLink=links.find(link=>link.dataset.workspaceTarget===hashId);if(hashNode&&hashLink&&Math.abs(hashNode.getBoundingClientRect().top)<=180){setActive(hashId);return}const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>Math.abs(a.boundingClientRect.top)-Math.abs(b.boundingClientRect.top))[0];if(visible)setActive(visible.target.id)},{rootMargin:"-18% 0px -68% 0px",threshold:[0,.1,.4]});links.map(link=>$(link.dataset.workspaceTarget)).filter(Boolean).forEach(node=>navObserver.observe(node))}
    const hash=location.hash.slice(1);if(hash&&links.some(link=>link.dataset.workspaceTarget===hash))activateHash();else setActive(links[0].dataset.workspaceTarget);
    return nav;
  }
  let lateDomObserver=null;
  let lateDomTimer=null;
  function requiredDomState(){
    const nodes={
      kpis:first(".grid.kpis"),marketIntel:$("market-intelligence"),marketFlow:$("market-flow"),
      planning:$("planning-zone"),external:$("external-market-context"),funding:$("market-funding-competition"),
      pref:$("preference-intelligence"),special:$("special-offer-radar"),evidence:$("scope-evidence"),
      top5:first(".top5-card"),institution:$("institution-funding-position"),handoff:ensureRegionHandoff(),
    };
    const missing=Object.entries(nodes).filter(([,node])=>!node||!node.isConnected).map(([key])=>key);
    if(document.documentElement.dataset.strategyWorkspace!=="market-first-v2")missing.unshift("workspace");
    document.documentElement.dataset.strategyLeanIaMissing=missing.join(",");
    return missing;
  }
  function reconcile(){
    suppressRedundantSurfaces();
    const missing=requiredDomState();
    if(missing.length)return false;
    const ready=reorder();
    if(ready){
      compactSecondarySurfaces();
      buildNavigation();
      const hashId=location.hash.slice(1);if(hashId&&navLinks().some(link=>link.dataset.workspaceTarget===hashId))activateHash();
      document.documentElement.dataset.strategyLeanIa="v3";
      document.documentElement.dataset.strategyLeanIaMissing="";
    }
    return ready;
  }
  function observeLateDom(){
    if(lateDomObserver||!("MutationObserver" in window)||!document.body)return;
    lateDomObserver=new MutationObserver(()=>{reconcile()});
    lateDomObserver.observe(document.body,{childList:true,subtree:true});
    lateDomTimer=setTimeout(()=>{lateDomObserver?.disconnect();lateDomObserver=null;lateDomTimer=null;reconcile()},10000);
  }
  function install(){
    if(document.documentElement.dataset.strategyLeanIaBound!=="1"){window.addEventListener("hashchange",activateHash);document.documentElement.dataset.strategyLeanIaBound="1"}
    [0,40,160,500,1200,3000,6000].forEach(delay=>setTimeout(reconcile,delay));
    observeLateDom();
    reconcile();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
'''.strip("\n")


def inject_strategy_lean_ia(html: str) -> str:
    """Reconcile the final Strategy DOM without changing calculation/data contracts."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Strategy Lean IA 주입 상태가 불완전하다")
    # Common/Search/minimal fixtures can pass through this shared compositor.
    if 'id="market-scope"' not in html or 'id="strategy-workspace-script"' not in html:
        return html
    if 'id="strategy-top5-compact-script"' not in html:
        raise DashboardBuildError("Strategy Lean IA는 TOP5 compact 이후에만 적용할 수 있다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy Lean IA 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _STYLE + "\n</head>", 1)
    return rendered.replace("</body>", _SCRIPT + "\n</body>", 1)
