# ruff: noqa: E501
"""Strategy 상품군 경계와 의사결정 표면을 명시적으로 보여주는 presentation.

계산·정렬·source precedence·stable product identity·예측식은 변경하지 않는다.
현재 product-scope runtime이 이미 가진 상태를 설명하고, TOP5에 당사 위치를
보조 행/표식으로 노출하며, 기존 인사이트의 근거와 기획 포인트를 더 명시적인
판단 근거/권고 행동으로 표시한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="dashboard-strategy-decision-clarity-style"'
SCRIPT_MARKER = 'id="dashboard-strategy-decision-clarity-script"'

CLARITY_STYLE = r"""
<style id="dashboard-strategy-decision-clarity-style">
/* 선택 컨트롤: 선택상태뿐 아니라 텍스트 자체도 업무 화면에서 빠르게 읽히게 한다. */
.strategy-family-checks{gap:9px!important}
.strategy-family-checks label,.strategy-savings-types label{min-height:38px!important;padding:8px 12px!important;font-size:12.5px!important}
.strategy-product-scope .global-term-tabs{gap:8px!important}
.strategy-product-scope .global-term-tabs button{min-height:38px!important;padding:8px 14px!important;font-size:12px!important}
.strategy-product-scope>span,.strategy-term-scope>span{font-size:11.5px!important}
.strategy-savings-types{margin-left:2px!important}

/* 현재비교/이력/예측 경계를 상시 노출해 통합모드의 의미를 화면에서 설명한다. */
.strategy-scope-contract{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:-1px 0 2px;padding:8px;border:1px solid rgba(91,47,100,.11);border-radius:10px;background:rgba(255,255,255,.62)}
.strategy-scope-contract span{min-width:0;padding:6px 8px;border-radius:8px;background:#f8f4f8;color:#554159;font-size:11.5px;line-height:1.4}
.strategy-scope-contract b{display:block;margin-bottom:2px;color:#2f2333;font-size:10.5px;font-weight:850;letter-spacing:.02em}
.strategy-scope-contract .boundary{background:#fff7e8;color:#654c21}.strategy-scope-contract .boundary b{color:#6f4d12}
.strategy-scope-contract .available{background:#eef7f3;color:#315e4e}.strategy-scope-contract .available b{color:#255844}

/* TOP5는 시장 순위를 유지한 채 당사 현재 위치만 보조한다. */
.top5-card tr.our-position-row td{background:rgba(18,63,50,.045)!important}
.top5-card tr.our-position-row td:first-child{box-shadow:inset 3px 0 0 #2f7d65}
.top5-card .our-position-badge{display:inline-flex;align-items:center;margin-left:6px;padding:2px 6px;border:1px solid rgba(47,125,101,.24);border-radius:999px;background:#eef7f3;color:#285f4c;font-size:9.5px;font-weight:900;line-height:1.2;vertical-align:middle}
.top5-card .our-position-note{display:block;margin-top:5px;color:#365f51;font-size:10.5px;font-weight:780;line-height:1.45}
.top5-card .our-position-empty td{padding:9px 10px!important;background:#faf7fa!important;color:#66566a!important;font-size:10.5px!important;text-align:left!important}
.top5-card .our-rank{display:inline-flex;align-items:center;justify-content:center;min-width:34px;padding:3px 5px;border-radius:7px;background:#eef7f3;color:#285f4c;font-size:9.5px;font-weight:900}

/* 기존 계산된 문장을 그대로 쓰되 근거와 행동을 역할별로 분리한다. */
.insightcard .insight .insight-evidence{display:block!important;margin-top:7px!important;padding-top:7px!important;border-top:1px solid rgba(91,47,100,.09)!important;color:#55475a!important;opacity:1!important;font-size:11.5px!important;line-height:1.5!important}
.insightcard .insight .insight-action{display:block!important;margin-top:8px!important;padding:8px 9px!important;border:1px solid rgba(47,125,101,.14)!important;border-radius:8px!important;background:#eef7f3!important;color:#315e4e!important;opacity:1!important;font-size:11.5px!important;font-weight:720!important;line-height:1.5!important}
@media(max-width:760px){.strategy-scope-contract{grid-template-columns:1fr}.strategy-family-checks label,.strategy-savings-types label{font-size:12px!important}.strategy-product-scope .global-term-tabs button{font-size:12px!important}.top5-card .our-position-note{font-size:10.5px!important}}
</style>
"""

CLARITY_SCRIPT = r'''
<script id="dashboard-strategy-decision-clarity-script">
(()=>{
  const ensureScopeContract=()=>{
    const host=document.getElementById("market-scope"),controls=host?.querySelector(".strategy-product-scope");
    if(!host||!controls)return null;
    let contract=document.getElementById("strategy-scope-contract");
    if(!contract){
      contract=document.createElement("div");
      contract.id="strategy-scope-contract";
      contract.className="strategy-scope-contract";
      contract.setAttribute("aria-label","현재 비교 범위와 기능 경계");
      controls.insertAdjacentElement("afterend",contract);
    }
    return contract;
  };
  const scopeHistoryCopy=()=>{
    if(productMode==="combined")return"통합 이력 미생성 · 상품군별 이력 유지";
    if(productMode==="deposit")return"예금 이력 사용";
    if(!savingsTypes.size)return"선택된 적금 유형 없음";
    if(savingsTypes.size===2)return"적금 이력 · 유형별 분리정책 적용";
    return savingsTypes.has("installment_savings")?"정기적금 이력 사용":"자유적금 이력 사용";
  };
  const renderScopeContract=()=>{
    const contract=ensureScopeContract();if(!contract)return;
    const predictionAvailable=productMode==="deposit";
    contract.innerHTML=`<span><b>현재 비교</b>${esc(productScopeLabel())} · ${scopeTerm}개월</span><span class="boundary"><b>이력</b>${esc(scopeHistoryCopy())}</span><span class="${predictionAvailable?"available":"boundary"}"><b>수신예측</b>${predictionAvailable?"예금 단독 · 사용 가능":"예금 단독에서만 사용"}</span>`;
  };
  const decorateInsightActions=()=>{
    document.querySelectorAll("#insights .insight").forEach(card=>{
      const body=card.querySelector(":scope > div:last-child");if(!body)return;
      const evidence=body.querySelector(":scope > span"),action=body.querySelector(":scope > small");
      if(evidence){
        evidence.classList.add("insight-evidence");
        if(!String(evidence.textContent||"").startsWith("판단 근거 · "))evidence.textContent=`판단 근거 · ${String(evidence.textContent||"").trim()}`;
      }
      if(action){
        action.classList.add("insight-action");
        const text=String(action.textContent||"").trim().replace(/^기획 포인트\s*·\s*/,"").replace(/^권고 행동\s*·\s*/,"");
        action.textContent=`권고 행동 · ${text}`;
      }
    });
  };
  const positionSummary=(own,rank)=>{
    const top=products12.slice(0,5),parts=[`당사 위치 · 전체 ${rank}위`];
    if(top.length){const avg=top.reduce((sum,p)=>sum+Number(p.max||0),0)/top.length;parts.push(`TOP5 평균 대비 ${formatBp(own.max-avg)}`)}
    if(rank>5&&top.length>=5){const gap=Math.max(0,Number(top[4].max)-Number(own.max));parts.push(`5위선까지 +${Math.round(gap*100)}bp`)}
    else if(rank<=5)parts.push("TOP5 진입권");
    return parts.join(" · ");
  };
  const decorateOwnPosition=()=>{
    const host=document.getElementById("top5");if(!host)return;
    host.querySelectorAll('[data-own-position="row"],[data-own-position="empty"]').forEach(row=>{if(row.dataset.clarityAdded==="1")row.remove();else{row.removeAttribute("data-own-position");row.classList.remove("our-position-row");row.querySelector(".our-position-badge")?.remove();row.querySelector(".our-position-note")?.remove()}});
    const own=products12.find(product=>product.institution===OUR_INSTITUTION)||null;
    if(!own){const row=document.createElement("tr");row.className="our-position-empty";row.dataset.ownPosition="empty";row.dataset.clarityAdded="1";row.innerHTML='<td colspan="5">현재 선택 범위에 고려저축은행 비교상품이 없습니다.</td>';host.appendChild(row);return}
    const rank=products12.filter(product=>product.max>own.max+1e-9).length+1,top=products12.slice(0,5),index=top.indexOf(own),summary=positionSummary(own,rank);
    if(index>=0){
      const row=[...host.querySelectorAll("tr")][index],bank=row?.querySelector(".bank"),cell=row?.querySelector("td:nth-child(2)");if(!row||!cell)return;
      row.dataset.ownPosition="row";row.classList.add("our-position-row");
      if(bank&&!cell.querySelector(".our-position-badge")){const badge=document.createElement("span");badge.className="our-position-badge";badge.textContent="당사";bank.insertAdjacentElement("afterend",badge)}
      let note=cell.querySelector(".our-position-note");if(!note){note=document.createElement("span");note.className="our-position-note";cell.appendChild(note)}note.textContent=summary;return;
    }
    const spread=Number.isFinite(own.base)?own.max-own.base:null,family=own.productFamily==="savings"?"savings":"deposit",row=document.createElement("tr");
    row.className="our-position-row our-position-appended";row.dataset.ownPosition="row";row.dataset.clarityAdded="1";
    row.innerHTML=`<td><span class="our-rank">${rank}위</span></td><td><span class="bank">${esc(own.institution)}</span><span class="our-position-badge">당사</span><span class="product-family-badge ${family}" aria-label="상품군 ${family==="savings"?"적금":"예금"}">${family==="savings"?"적금":"예금"}</span><span class="product" title="${esc(own.product)}">${esc(own.product)}</span><span class="our-position-note">${esc(summary)}</span></td><td>${Number.isFinite(own.base)?own.base.toFixed(2)+"%":"—"}</td><td>${Number.isFinite(spread)?`${spread>=0?"+":""}${spread.toFixed(2)}%p`:"—"}</td><td class="strongrate">${own.max.toFixed(2)}%</td>`;
    host.appendChild(row);
  };
  const priorRenderProductScopeControls=renderProductScopeControls;
  renderProductScopeControls=function(){priorRenderProductScopeControls();renderScopeContract()};
  const priorRenderMarket=renderMarket;
  renderMarket=function(){priorRenderMarket();decorateOwnPosition();renderScopeContract()};
  const priorRenderInsightsEnhanced=renderInsightsEnhanced;
  renderInsightsEnhanced=function(){priorRenderInsightsEnhanced();decorateInsightActions()};
  renderScopeContract();
})();
</script>
'''.strip("\n")


def inject_dashboard_strategy_decision_clarity(html: str) -> str:
    """Strategy에 범위 경계·당사 위치·행동형 인사이트 표현을 추가한다."""
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        return html
    if 'data-product-mode="deposit"' not in html:
        return html
    if 'id="dashboard-strategy-scope-readability-script"' not in html:
        raise DashboardBuildError("Strategy decision clarity가 상품군 가독성 runtime보다 먼저 주입됐다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy decision clarity 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", CLARITY_STYLE + "\n</head>", 1)
    return rendered.replace("</body>", CLARITY_SCRIPT + "\n</body>", 1)
