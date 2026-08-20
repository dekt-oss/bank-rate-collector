# ruff: noqa: E501
"""Strategy 화면을 검색·조회 화면과 역할 분리한다.

계산/데이터 계약은 유지하고 presentation만 바꾼다.
- 전국 지도/부산 drill-down의 visible owner는 Main으로 단일화
- Strategy의 중복 대형 KPI는 숨기고 planning context를 visible anchor로 사용
- Strategy는 금리결정 가능범위와 내부 calibration boundary를 명시
- TOP5는 원시 탐색표가 아니라 가격결정 benchmark로 재라벨링
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-role-separation-style"'
SCRIPT_MARKER = 'id="strategy-role-separation-script"'

_CSS = r"""
<style id="strategy-role-separation-style">
/* Main owns the full geographic explorer. Keep Strategy geography in the data contract,
   but do not repeat the full Korea map as a second explorer. */
#map-card{display:none!important}
#map-card[aria-hidden="true"] *{pointer-events:none!important}
.workspace-detail.primary.strategy-competition-only,
.grid.primary.strategy-competition-only{display:block!important;grid-template-columns:1fr!important}
.strategy-competition-only .top5-card{min-height:0!important;width:100%;margin:0}
.strategy-competition-only .top5-card .pad{padding:16px}

/* The four large overview KPIs repeat the anchors already shown inside the decision zone. */
.kpis[data-strategy-overview-duplicate="true"]{display:none!important}

.strategy-decision-boundary{display:grid;grid-template-columns:auto minmax(0,1fr) minmax(0,1fr);gap:12px;align-items:stretch;margin:0 0 14px;padding:12px;border:1px solid rgba(91,47,100,.11);border-radius:11px;background:linear-gradient(145deg,#FCFAFC,#F8F3F8)}
.strategy-decision-state{display:flex;flex-direction:column;justify-content:center;gap:4px;min-width:150px;padding:10px;border:1px solid rgba(211,58,124,.18);border-radius:9px;background:#FFF7FA}
.strategy-decision-state span{color:#8A7181;font-size:10px;font-weight:720}
.strategy-decision-state b{color:#693B60;font-size:13px;line-height:1.35}
.strategy-decision-cap{padding:9px 10px;border-left:1px solid rgba(91,47,100,.09)}
.strategy-decision-cap strong{display:block;margin-bottom:5px;color:#423146;font-size:11px}
.strategy-decision-cap p{margin:0;color:#716574;font-size:10.5px;line-height:1.55}
.strategy-decision-cap.blocked strong{color:#8B5B42}

.strategy-region-bridge{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 14px;align-items:center;margin:0 0 10px;padding:11px 13px;border:1px solid rgba(91,47,100,.10);border-radius:11px;background:#FBF9FB}
.strategy-region-bridge b{display:block;color:#443348;font-size:11.5px}
.strategy-region-bridge span{display:block;margin-top:2px;color:#746878;font-size:10.5px;line-height:1.5}
.strategy-region-bridge a{display:inline-flex;align-items:center;justify-content:center;padding:7px 10px;border:1px solid rgba(211,58,124,.20);border-radius:8px;background:#FFF5F9;color:#7C3E64;text-decoration:none;font-size:10.5px;font-weight:760;white-space:nowrap}
.strategy-region-bridge small{grid-column:1/-1;color:#8A7E8C;font-size:10px;line-height:1.45}

.strategy-competition-only #top5-title{font-size:16px}
.strategy-competition-only #top5-copy{max-width:72ch}

@media(max-width:760px){
  .strategy-decision-boundary{grid-template-columns:1fr}
  .strategy-decision-cap{border-left:0;border-top:1px solid rgba(91,47,100,.09)}
  .strategy-region-bridge{grid-template-columns:1fr}
  .strategy-region-bridge a{justify-self:start}
}
</style>
"""

_JS = r"""
<script id="strategy-role-separation-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const TOP5_TITLE="가격결정 경쟁 기준 TOP 5";
  const TOP5_COPY="현재 선택 시장의 상단 금리 anchor · 상세 상품 탐색과 지역 비교는 검색 조회에서 확인";

  function installDecisionBoundary(){
    const planning=$("planning-zone");
    const card=planning?.querySelector(".sim");
    if(!card||$("strategy-decision-boundary"))return;
    const boundary=document.createElement("section");
    boundary.id="strategy-decision-boundary";
    boundary.className="strategy-decision-boundary";
    boundary.setAttribute("aria-label","금리결정 가능범위");
    boundary.innerHTML=`
      <div class="strategy-decision-state"><span>현재 엔진 상태</span><b>시장기준 금리 의사결정 지원</b></div>
      <div class="strategy-decision-cap"><strong>현재 판단 가능</strong><p>시장 위치 · 최근 금리방향 · 경쟁사 상단 · 외부 자금환경 · 우대조건 구조 · 미보정 금리변경 stress scenario</p></div>
      <div class="strategy-decision-cap blocked"><strong>내부자료 후 확정 가능</strong><p>실제 신규수신·재예치 탄력성 · 순수신 forecast · 1bp 증분효율 · FTP 반영 비용 · 목표 순수신 최소비용 최적금리</p></div>`;
    const head=card.querySelector(".head");
    if(head)head.insertAdjacentElement("afterend",boundary);else card.prepend(boundary);
  }

  function removeVisibleDuplicateOverview(){
    const kpis=document.querySelector(".kpis");
    if(kpis)kpis.dataset.strategyOverviewDuplicate="true";
  }

  function lockCompetitionRoleCopy(){
    const title=$("top5-title"),copy=$("top5-copy");
    if(title&&title.textContent!==TOP5_TITLE)title.textContent=TOP5_TITLE;
    if(!copy)return;
    if(copy.textContent!==TOP5_COPY)copy.textContent=TOP5_COPY;
    if(copy.dataset.roleCopyLocked==="true")return;
    copy.dataset.roleCopyLocked="true";
    const observer=new MutationObserver(()=>{
      if(copy.textContent!==TOP5_COPY)copy.textContent=TOP5_COPY;
      if(title&&title.textContent!==TOP5_TITLE)title.textContent=TOP5_TITLE;
    });
    observer.observe(copy,{childList:true,subtree:true,characterData:true});
  }

  function consolidateRegionAndCompetition(){
    const map=$("map-card");
    const section=map?.closest("section");
    const top5=section?.querySelector(".top5-card");
    if(!map||!section||!top5)return;
    map.setAttribute("aria-hidden","true");
    section.classList.add("strategy-competition-only");
    if(!$("strategy-region-bridge")){
      const bridge=document.createElement("aside");
      bridge.id="strategy-region-bridge";
      bridge.className="strategy-region-bridge";
      bridge.innerHTML=`<div><b>지역 상세는 검색 조회에서 확인</b><span>전국 지도와 부산 구·군 drill-down은 원시 지역 탐색 기능으로 검색 조회에 통합했습니다.</span></div><a href="./#reg">검색 조회 · 지역 상세 열기</a><small>Strategy에서는 기존 지역 feature를 삭제하지 않고 시장 인사이트의 보조 근거로만 유지합니다. 저축은행 지역은 본점 소재지 참고값이며 판매 가능 지역을 뜻하지 않습니다.</small>`;
      section.insertBefore(bridge,top5);
    }
    lockCompetitionRoleCopy();
  }

  function relabelSection(){
    const bridge=$("strategy-region-bridge");
    const section=bridge?.closest("section");
    const label=section?.previousElementSibling;
    if(!label?.classList?.contains("workspace-section-label"))return;
    const strong=label.querySelector("strong"),span=label.querySelector("span");
    if(strong)strong.textContent="경쟁 기준 · 지역 상세 연결";
    if(span)span.textContent="금리결정에 필요한 상단 경쟁 기준만 남기고 지역 탐색은 검색 조회로 연결합니다.";
  }

  function install(){
    installDecisionBoundary();
    removeVisibleDuplicateOverview();
    consolidateRegionAndCompetition();
    relabelSection();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_strategy_role_separation(html: str) -> str:
    """Strategy 최종 presentation에 역할분리 layer를 마지막으로 합성한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Strategy 역할분리 presentation 주입 상태가 불완전하다")
    required = ('id="planning-zone"', 'id="map-card"', 'id="top5-title"')
    if not all(marker in html for marker in required):
        raise DashboardBuildError("Strategy 역할분리 대상 DOM 계약을 찾지 못했다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy 역할분리 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
