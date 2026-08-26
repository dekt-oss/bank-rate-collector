"""적금 유형 분리 판단을 가볍게 설명하는 배지와 스프레드 KPI."""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="dashboard-product-scope-insight-style"'
SCRIPT_MARKER = 'id="dashboard-strategy-savings-insight-script"'

INSIGHT_STYLE = r"""
<style id="dashboard-product-scope-insight-style">
.savings-subtype-insight{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:7px 0 2px}.savings-subtype-insight[hidden]{display:none!important}.savings-subtype-badge{display:inline-flex;align-items:center;min-height:22px;padding:3px 7px;border:1px solid rgba(212,179,111,.28);border-radius:999px;background:rgba(92,72,35,.14);color:#c6aa72;font-size:9px;font-weight:800;letter-spacing:.02em}.savings-subtype-spread{display:inline-flex;align-items:baseline;gap:5px;min-height:22px;padding:3px 7px;border:1px solid rgba(128,200,166,.16);border-radius:8px;background:rgba(8,27,21,.34);color:#81958a;font-size:9px}.savings-subtype-spread strong{color:#c7ddd2;font:800 10px var(--mono)}.savings-subtype-spread small{color:#71847a;font-size:9px}.savings-subtype-spread[hidden]{display:none!important}
</style>
"""

INSIGHT_SCRIPT = r'''
<script id="dashboard-strategy-savings-insight-script">
(()=>{
  const REASON_LABELS={
    large_max_gap:"최대 금리격차 기준 충족",
    material_mean_gap:"평균 격차·상품비중 기준 충족",
    divergent_direction:"정기·자유 적금 추세 방향 분화",
  };
  const scopePointMap=(scope)=>new Map(
    ((data.strategy?.product_history?.scopes?.[scope]?.[String(scopeTerm)]?.rate_trend?.points)||[])
      .filter(p=>Number.isFinite(Number(p.mean_max_rate)))
      .map(p=>[String(p.date),p])
  );
  const latestCommonSpread=()=>{
    const installment=scopePointMap("savings_installment"),flexible=scopePointMap("savings_flexible");
    const dates=[...installment.keys()].filter(date=>flexible.has(date)).sort();
    const date=dates.at(-1);if(!date)return null;
    const installmentRate=Number(installment.get(date)?.mean_max_rate),flexibleRate=Number(flexible.get(date)?.mean_max_rate);
    if(!Number.isFinite(installmentRate)||!Number.isFinite(flexibleRate))return null;
    const spread=installmentRate-flexibleRate;
    return{date,spread,leader:spread>.0001?"정기적금 우위":spread<-.0001?"자유적금 우위":"유형간 동일"};
  };
  const ensureInsight=()=>{
    const panel=document.getElementById("savings-subtype-trend");if(!panel)return null;
    let insight=panel.querySelector(".savings-subtype-insight");
    if(!insight){
      insight=document.createElement("div");insight.className="savings-subtype-insight";insight.hidden=true;
      insight.innerHTML='<span class="savings-subtype-badge" id="savings-subtype-gap-badge">유형별 차이 확대</span><span class="savings-subtype-spread" id="savings-subtype-spread-kpi"><span>유형간 스프레드</span><strong id="savings-subtype-spread-value">-</strong><small id="savings-subtype-spread-detail"></small></span>';
      panel.querySelector(".savings-subtype-head")?.insertAdjacentElement("afterend",insight);
    }
    return insight;
  };
  const formatDate=(value)=>{const d=new Date(`${value}T00:00:00`);return Number.isNaN(d.getTime())?value:`${String(d.getMonth()+1).padStart(2,"0")}/${String(d.getDate()).padStart(2,"0")}`};
  const update=()=>{
    const insight=ensureInsight();if(!insight)return false;
    const panel=document.getElementById("savings-subtype-trend"),policy=data.strategy?.product_history?.savings_trend_display_policy?.terms?.[String(scopeTerm)]||null;
    const split=productMode==="savings"&&savingsTypes.size===2&&policy?.display_mode==="split"&&panel&&!panel.hidden;
    insight.hidden=!split;
    const badge=document.getElementById("savings-subtype-gap-badge"),kpi=document.getElementById("savings-subtype-spread-kpi");
    if(!split){if(kpi)kpi.hidden=true;return true}
    if(badge)badge.title=REASON_LABELS[policy.reason]||"적금 유형별 추이를 분리 표시";
    const latest=latestCommonSpread();
    if(!latest){if(kpi)kpi.hidden=true;return true}
    if(kpi)kpi.hidden=false;
    const value=document.getElementById("savings-subtype-spread-value"),detail=document.getElementById("savings-subtype-spread-detail");
    if(value)value.textContent=`${latest.spread>=0?"+":""}${latest.spread.toFixed(2)}%p`;
    if(detail)detail.textContent=`${latest.leader} · ${formatDate(latest.date)}`;
    return true;
  };
  const attach=()=>{
    const panel=document.getElementById("savings-subtype-trend");if(!panel)return false;
    if(panel.dataset.savingsInsightObserved!=="1"){
      new MutationObserver(()=>queueMicrotask(update)).observe(panel,{attributes:true,attributeFilter:["hidden"]});
      panel.dataset.savingsInsightObserved="1";
    }
    update();return true;
  };
  document.addEventListener("click",e=>{if(e.target.closest?.('[data-product-mode],[data-scope-term],#term-segment button'))queueMicrotask(attach)});
  document.addEventListener("change",e=>{if(e.target.closest?.('[data-savings-type]'))queueMicrotask(attach)});
  let attempts=0;const timer=setInterval(()=>{attempts++;if(attach()||attempts>200)clearInterval(timer)},50);
})();
</script>
'''.strip("\n")


def inject_dashboard_product_scope_insight(html: str) -> str:
    """Strategy 적금 전체가 분리될 때만 설명 배지와 최신 스프레드를 추가한다."""
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        return html
    if 'data-product-mode="deposit"' not in html:
        return html
    if 'id="dashboard-strategy-product-followup-script"' not in html:
        raise DashboardBuildError("적금 스프레드 KPI가 상품군 후속 runtime보다 먼저 주입됐다")
    rendered = html.replace("</head>", INSIGHT_STYLE + "\n</head>", 1)
    return rendered.replace("</body>", INSIGHT_SCRIPT + "\n</body>", 1)
