"""상품군 후속 UX: 공유 URL, empty-state, 적금 추이 자동 분리."""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

FOLLOWUP_STYLE_MARKER = 'id="dashboard-product-scope-followup-style"'

FOLLOWUP_STYLE = r"""
<style id="dashboard-product-scope-followup-style">
.product-empty-state{margin-top:8px;padding:7px 9px;border:1px solid rgba(212,179,111,.25);border-radius:8px;background:rgba(92,72,35,.11);color:#ad9465;font-size:10px;line-height:1.45}
.product-empty-state[hidden]{display:none!important}.strategy-product-empty{grid-column:1/-1;margin:0;padding:8px 10px}
.savings-subtype-trend{margin:10px 0 0;padding:10px 11px;border:1px solid rgba(128,200,166,.12);border-radius:11px;background:rgba(5,16,13,.28)}.savings-subtype-trend[hidden]{display:none!important}.savings-subtype-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.savings-subtype-head b{font-size:10px;color:#c5d8ce}.savings-subtype-head small{color:#788b81;font-size:9px;text-align:right}.savings-subtype-legend{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0 5px;color:#879a90;font-size:9px}.savings-subtype-legend span{display:flex;align-items:center;gap:5px}.savings-subtype-legend i{display:inline-block;width:18px;height:2px;border-radius:99px}.savings-subtype-legend i.installment{background:#80c8a6}.savings-subtype-legend i.flexible{background:#d4b36f}.savings-subtype-chart-scroll{overflow-x:auto;overflow-y:hidden;overscroll-behavior-inline:contain}.savings-subtype-chart{display:block;width:100%;min-width:620px;height:190px}.savings-subtype-chart .grid{stroke:rgba(213,225,219,.09);stroke-width:1}.savings-subtype-chart .axis{fill:#6f8178;font:9px var(--mono)}.savings-subtype-chart .line{fill:none;stroke-width:2.3;vector-effect:non-scaling-stroke}.savings-subtype-chart .line.installment{stroke:#80c8a6}.savings-subtype-chart .line.flexible{stroke:#d4b36f}.savings-subtype-chart .dot.installment{fill:#80c8a6}.savings-subtype-chart .dot.flexible{fill:#d4b36f}.savings-subtype-chart .value{font:800 10px var(--mono)}.savings-subtype-chart .value.installment{fill:#9bd5b8}.savings-subtype-chart .value.flexible{fill:#d4b36f}.savings-subtype-policy{margin:6px 0 0;color:#74877d;font-size:9px;line-height:1.5}
</style>
"""

SEARCH_ALIAS_RUNTIME = r'''
  const normalizeProductScopeAliases = () => {
    const p = new URLSearchParams(location.search);
    const family = p.get("family");
    const rawSavings = p.get("savings");
    const term = Number(p.get("term"));
    let changed = false;
    if (family === "deposit") {
      if (p.get("type") !== PRODUCT_DEPOSIT_TYPE) { p.set("type", PRODUCT_DEPOSIT_TYPE); changed = true; }
    } else if (family === "savings") {
      const selected = rawSavings === null
        ? [...PRODUCT_SAVINGS_TYPES]
        : rawSavings === "none"
          ? []
          : rawSavings.split(",").filter((type) => PRODUCT_SAVINGS_TYPES.includes(type));
      const encoded = selected.join(",");
      if (p.get("type") !== encoded) { p.set("type", encoded); changed = true; }
    }
    if (GLOBAL_TERMS.includes(term)) {
      const encoded = String(term);
      if (p.get("tmin") !== encoded) { p.set("tmin", encoded); changed = true; }
      if (p.get("tmax") !== encoded) { p.set("tmax", encoded); changed = true; }
    }
    if (changed) {
      const q = p.toString();
      history.replaceState(null, "", q ? `?${q}` : location.pathname);
    }
  };
  const restoreProductScopeAliasState = () => {
    const p = new URLSearchParams(location.search);
    if (p.get("family") === "savings") {
      emptySavingsSelected = !PRODUCT_SAVINGS_TYPES.some((type) => state.picked.type.has(type));
    } else if (p.get("family") === "deposit") {
      emptySavingsSelected = false;
    }
  };
  const decorateProductScopeUrl = (p) => {
    const family = activeProductFamily();
    p.set("family", family);
    p.set("term", String(activeGlobalTerm()));
    if (family === "savings") {
      const selected = PRODUCT_SAVINGS_TYPES.filter((type) => state.picked.type.has(type));
      p.set("savings", selected.length ? selected.join(",") : "none");
    } else {
      p.delete("savings");
    }
  };
'''.strip("\n")

SEARCH_EMPTY_SCRIPT = r'''
<script id="dashboard-search-product-empty-script">
(()=>{
  const update=()=>{
    const detail=document.querySelector(".product-savings-detail");
    if(!detail)return;
    let note=detail.querySelector(".product-empty-state");
    if(!note){
      note=document.createElement("div");
      note.className="product-empty-state";
      note.textContent="선택된 적금 유형이 없습니다. 정기적금 또는 자유적금을 선택하면 아래 결과가 표시됩니다.";
      detail.appendChild(note);
    }
    note.hidden=detail.querySelectorAll('input[data-group="type"]:checked').length>0;
  };
  document.addEventListener("change",e=>{if(e.target.closest?.('.product-savings-detail'))queueMicrotask(update)});
  document.addEventListener("click",e=>{if(e.target.closest?.('[data-product-family]'))queueMicrotask(update)});
  new MutationObserver(update).observe(document.body,{childList:true,subtree:true});
  update();
})();
</script>
'''.strip("\n")

STRATEGY_FOLLOWUP_SCRIPT = r'''
<script id="dashboard-strategy-product-followup-script">
(()=>{
  const POLICY_LABELS={
    large_max_gap:"최대 금리격차가 커서 분리",
    material_mean_gap:"평균 격차와 상품비중 영향이 커서 분리",
    divergent_direction:"정기·자유 적금의 추세 방향이 달라 분리",
    difference_not_material:"차이가 작아 통합",
    insufficient_overlap:"공통 이력 관측이 부족해 통합",
  };
  const queryState=()=>{
    const p=new URLSearchParams(location.search),family=p.get("family"),term=Number(p.get("term")),raw=p.get("savings");
    const savings=raw===null?["installment_savings","flexible_savings"]:raw==="none"?[]:raw.split(",").filter(x=>PRODUCT_SAVINGS_TYPES.has(x));
    return{hasFamily:family==="deposit"||family==="savings",family,hasTerm:GLOBAL_TERMS.includes(term),term,savings};
  };
  const syncUrl=()=>{
    const p=new URLSearchParams(location.search);
    p.set("family",productMode);
    p.set("term",String(scopeTerm));
    if(productMode==="savings")p.set("savings",savingsTypes.size?[...savingsTypes].sort().join(","):"none");
    else p.delete("savings");
    const q=p.toString();history.replaceState(null,"",q?`${location.pathname}?${q}${location.hash}`:`${location.pathname}${location.hash}`);
  };
  const ensureEmpty=()=>{
    const host=document.getElementById("market-scope");if(!host)return;
    let note=document.getElementById("strategy-product-empty");
    if(!note){note=document.createElement("div");note.id="strategy-product-empty";note.className="product-empty-state strategy-product-empty";note.textContent="선택된 적금 유형이 없습니다. 정기적금 또는 자유적금을 선택하면 아래 시장 지표가 표시됩니다.";const controls=host.querySelector(".strategy-product-scope");controls?.insertAdjacentElement("afterend",note)}
    note.hidden=!(productMode==="savings"&&savingsTypes.size===0);
  };
  const ensureTrendPanel=()=>{
    let panel=document.getElementById("savings-subtype-trend");if(panel)return panel;
    const note=document.getElementById("trend-note");if(!note)return null;
    panel=document.createElement("div");panel.id="savings-subtype-trend";panel.className="savings-subtype-trend";panel.hidden=true;
    panel.innerHTML='<div class="savings-subtype-head"><b>적금 유형별 평균금리 추이</b><small id="savings-subtype-policy-copy"></small></div><div class="savings-subtype-legend"><span><i class="installment"></i>정기적금</span><span><i class="flexible"></i>자유적금</span></div><div class="savings-subtype-chart-scroll"><svg class="savings-subtype-chart" id="savings-subtype-chart" viewBox="0 0 1000 190" preserveAspectRatio="xMidYMid meet" role="img" aria-label="정기적금과 자유적금 평균금리 변화추이"></svg></div><p class="savings-subtype-policy" id="savings-subtype-policy-note"></p>';
    note.parentNode.insertBefore(panel,note);return panel;
  };
  const pointMap=(scope)=>new Map(((data.strategy?.product_history?.scopes?.[scope]?.[String(scopeTerm)]?.rate_trend?.points)||[]).filter(p=>Number.isFinite(Number(p.mean_max_rate))).map(p=>[String(p.date),p]));
  const drawSubtypeChart=(installment,flexible)=>{
    const svg=document.getElementById("savings-subtype-chart");if(!svg)return;
    const dates=[...new Set([...installment.keys(),...flexible.keys()])].sort(),vals=dates.flatMap(d=>[installment.get(d),flexible.get(d)].filter(Boolean).map(p=>Number(p.mean_max_rate))).filter(Number.isFinite);
    if(dates.length<2||!vals.length){svg.innerHTML='<text x="500" y="95" text-anchor="middle" class="axis">유형별 추이 관측이 부족합니다.</text>';return}
    const lo=Math.min(...vals),hi=Math.max(...vals),pad=Math.max(.03,(hi-lo)*.18),min=Math.max(0,lo-pad),max=hi+pad,x0=72,x1=952,y0=18,y1=145,span=Math.max(.01,max-min),sx=i=>dates.length===1?(x0+x1)/2:x0+(x1-x0)*i/(dates.length-1),sy=v=>y1-(v-min)/span*(y1-y0);
    const grid=[0,.33,.66,1].map(q=>{const y=y0+(y1-y0)*q,v=max-span*q;return`<line class="grid" x1="${x0}" y1="${y}" x2="${x1}" y2="${y}"/><text class="axis" x="8" y="${y+3}">${v.toFixed(2)}%</text>`}).join("");
    const build=(map,klass)=>{const pts=dates.map((d,i)=>map.has(d)?{x:sx(i),y:sy(Number(map.get(d).mean_max_rate)),value:Number(map.get(d).mean_max_rate)}:null).filter(Boolean),path=pts.map((p,i)=>`${i?"L":"M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");if(!pts.length)return"";const last=pts.at(-1);return`<path class="line ${klass}" d="${path}"/>${pts.map(p=>`<circle class="dot ${klass}" cx="${p.x}" cy="${p.y}" r="3"/>`).join("")}<text class="value ${klass}" x="${last.x}" y="${Math.max(10,last.y-8)}" text-anchor="end">${last.value.toFixed(2)}%</text>`};
    const labelIdx=[0,Math.floor((dates.length-1)/2),dates.length-1].filter((v,i,a)=>a.indexOf(v)===i),labels=labelIdx.map(i=>{const d=new Date(`${dates[i]}T00:00:00`),label=Number.isNaN(d.getTime())?dates[i]:`${String(d.getMonth()+1).padStart(2,"0")}/${String(d.getDate()).padStart(2,"0")}`;return`<text class="axis" x="${sx(i)}" y="174" text-anchor="middle">${label}</text>`}).join("");
    svg.innerHTML=grid+build(installment,"installment")+build(flexible,"flexible")+labels;
  };
  const renderAdaptiveTrend=()=>{
    const panel=ensureTrendPanel();if(!panel)return;
    if(productMode!=="savings"||savingsTypes.size!==2){panel.hidden=true;return}
    const policy=data.strategy?.product_history?.savings_trend_display_policy?.terms?.[String(scopeTerm)]||null;
    panel.hidden=false;
    const copy=document.getElementById("savings-subtype-policy-copy"),note=document.getElementById("savings-subtype-policy-note"),chartScroll=panel.querySelector(".savings-subtype-chart-scroll"),legend=panel.querySelector(".savings-subtype-legend");
    if(!policy){copy.textContent="판정 데이터 없음";note.textContent="정기·자유 적금 비교 이력 판정값이 없어 통합 추이를 유지합니다.";chartScroll.hidden=true;legend.hidden=true;return}
    const maxGap=Number(policy.max_gap_pp),meanGap=Number(policy.mean_gap_pp),share=Number(policy.minor_product_share),split=policy.display_mode==="split";
    copy.textContent=POLICY_LABELS[policy.reason]||policy.display_mode;
    if(Number.isFinite(maxGap)&&Number.isFinite(meanGap)){note.textContent=`최대 격차 ${maxGap.toFixed(2)}%p · 평균 격차 ${meanGap.toFixed(2)}%p${Number.isFinite(share)?` · 소수 유형 비중 ${(share*100).toFixed(0)}%`:""} → ${split?"두 추이를 분리 표시":"통합 추이 유지"}`}
    else note.textContent=`공통 이력 ${Number(policy.overlap_points||0)}개 → 통합 추이 유지`;
    chartScroll.hidden=!split;legend.hidden=!split;
    if(split)drawSubtypeChart(pointMap("savings_installment"),pointMap("savings_flexible"));
  };
  const baseControls=renderProductScopeControls;
  renderProductScopeControls=function(){baseControls();ensureEmpty()};
  const baseHistory=renderProductHistoryScope;
  renderProductHistoryScope=function(){baseHistory();renderAdaptiveTrend()};
  const restore=()=>{
    if(depositUniverse===null||savingsUniverse===null)return false;
    const q=queryState();
    if(q.hasFamily){productMode=q.family;savingsTypes=new Set(q.family==="savings"?q.savings:["installment_savings","flexible_savings"]);allRows=q.family==="savings"?savingsRows:depositRows;strategyUniverse=q.family==="savings"?savingsUniverse:depositUniverse;mapSector="savings_bank"}
    if(q.hasTerm){scopeTerm=q.term;simTerm=q.term}
    if(q.hasFamily||q.hasTerm){renderProductScopeControls();rerenderForScope();syncUrl()}else{ensureEmpty();renderAdaptiveTrend()}
    return true;
  };
  let attempts=0;const timer=setInterval(()=>{attempts++;if(restore()||attempts>200)clearInterval(timer)},50);
  document.addEventListener("click",e=>{if(e.target.closest?.('[data-product-mode],[data-scope-term],#term-segment button'))queueMicrotask(()=>{syncUrl();ensureEmpty();renderAdaptiveTrend()})});
  document.addEventListener("change",e=>{if(e.target.closest?.('[data-savings-type]'))queueMicrotask(()=>{syncUrl();ensureEmpty();renderAdaptiveTrend()})});
})();
</script>
'''.strip("\n")


def _replace_required(html: str, old: str, new: str, label: str) -> str:
    if old not in html:
        raise DashboardBuildError(f"상품군 후속 UX anchor를 찾지 못했다: {label}")
    return html.replace(old, new, 1)


def _inject_search(html: str) -> str:
    rendered = _replace_required(
        html,
        "  const syncUrl = () => {",
        SEARCH_ALIAS_RUNTIME + "\n  const syncUrl = () => {",
        "search URL runtime",
    )
    rendered = _replace_required(
        rendered,
        "    const q = p.toString();\n    history.replaceState(null, \"\", q ? `?${q}` : location.pathname);",
        "    decorateProductScopeUrl(p);\n    const q = p.toString();\n    history.replaceState(null, \"\", q ? `?${q}` : location.pathname);",
        "search URL sync",
    )
    rendered = _replace_required(
        rendered,
        "  readUrl();",
        "  normalizeProductScopeAliases();\n  readUrl();\n  restoreProductScopeAliasState();",
        "search URL restore",
    )
    return rendered.replace("</body>", SEARCH_EMPTY_SCRIPT + "\n</body>", 1)


def inject_dashboard_product_scope_followup(html: str) -> str:
    if FOLLOWUP_STYLE_MARKER in html:
        return html
    rendered = html.replace("</head>", FOLLOWUP_STYLE + "\n</head>", 1)
    if 'data-product-family="deposit"' in rendered and "const syncUrl = () => {" in rendered:
        rendered = _inject_search(rendered)
    if 'data-product-mode="deposit"' in rendered:
        rendered = rendered.replace("</body>", STRATEGY_FOLLOWUP_SCRIPT + "\n</body>", 1)
    return rendered
