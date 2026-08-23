# ruff: noqa: E501
"""Public Structural v2 Stage G factual-only rate finder presentation.

Stage F Cockpit의 structural forecast와 분리해 competitor-only 현재 시장 benchmark에서
조건충족 최소 선택금리만 보여준다. browser는 별도 JS mirror를 사용하며 proposal이나
수신금액 입력을 finder 계산에 전달하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="public-structural-v2-factual-rate-finder-style"'
ENGINE_MARKER = 'id="public-structural-v2-factual-rate-finder-engine"'
SCRIPT_MARKER = 'id="public-structural-v2-factual-rate-finder-script"'

_CSS = r"""
<style id="public-structural-v2-factual-rate-finder-style">
.psv2-finder{display:grid;gap:9px;padding:11px;border:1px solid rgba(78,150,117,.18);border-radius:12px;background:linear-gradient(145deg,#f7fbf8,#fff)}
.psv2-finder-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.psv2-finder-head b{color:#3f5148;font-size:10.5px}.psv2-finder-head span{padding:3px 6px;border:1px solid rgba(78,150,117,.18);border-radius:999px;background:#f1f8f4;color:#3f7f60;font-size:8px;font-weight:800;white-space:nowrap}
.psv2-finder-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.psv2-finder-item{min-width:0;padding:9px;border:1px solid rgba(91,47,100,.08);border-radius:9px;background:#fff}.psv2-finder-item span{display:block;color:#725f75;font-size:8.2px;font-weight:760}.psv2-finder-item strong{display:block;margin-top:5px;color:#2e7d5b;font:800 13px/1.15 var(--mono)}.psv2-finder-item strong.unavailable{color:#8f7651;font-family:var(--sans);font-size:10px}.psv2-finder-item small{display:block;margin-top:4px;color:#807083;font-size:7.8px;line-height:1.45}.psv2-finder-foot{display:flex;flex-wrap:wrap;gap:4px 12px;color:#756478;font-size:8px;line-height:1.5}.psv2-finder-foot b{color:#52665c}.psv2-finder-error{padding:10px;border:1px dashed rgba(91,47,100,.14);border-radius:9px;color:#756478;font-size:8.5px;text-align:center}
@media(max-width:760px){.psv2-finder-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:520px){.psv2-finder{padding:9px}.psv2-finder-head{display:block}.psv2-finder-head span{display:inline-block;margin-top:5px}.psv2-finder-grid{grid-template-columns:1fr}.psv2-finder-item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 8px;align-items:center}.psv2-finder-item strong{grid-column:2;grid-row:1/3;margin:0;text-align:right}.psv2-finder-item small{grid-column:1;margin:0}}
</style>
""".strip()

_SCRIPT = r"""
<script id="public-structural-v2-factual-rate-finder-script">
(()=>{
  "use strict";
  const HOST_ID="public-structural-v2-cockpit";
  const BLOCK_ID="public-structural-v2-factual-rate-finder";
  const OUR_INSTITUTION="고려저축은행";
  const SELECTION_STEP_PP=.01;
  let tablePromise=null;
  let renderQueued=false;

  const $=id=>document.getElementById(id);
  function inlineData(){
    const el=$("rate-monitor-data");
    if(!el)throw new Error("rate-monitor-data:missing");
    return JSON.parse(String(el.textContent||"").replace(/<\\\//g,"</"));
  }
  function finite(value){
    if(value===null||value===undefined||String(value).trim()==="")return null;
    const number=Number(value);
    return Number.isFinite(number)?number:null;
  }
  function decode(table,column,value){
    const lookup=table.lookups?.[column];
    return lookup&&value!==null&&value!==undefined?lookup[value]:value;
  }
  function decodedRows(table){
    const columns=table.columns||[],index=Object.fromEntries(columns.map((name,i)=>[name,i]));
    const get=(row,name)=>name in index?decode(table,name,row[index[name]]):null;
    return (table.rows||[]).map(row=>({
      sector:get(row,"sector"),product_type:get(row,"product_type"),term_months:Number(get(row,"term_months")),
      max_rate:finite(get(row,"max_rate")),product_id:String(get(row,"product_id")??""),
      institution:String(get(row,"institution")??""),product:String(get(row,"product")??""),
      source_effective_at:String(get(row,"source_effective_at")??"")
    }));
  }
  async function loadTable(){
    if(tablePromise)return tablePromise;
    const url=inlineData().table_url;
    if(!url)throw new Error("strategy-table:url_missing");
    tablePromise=fetch(url,{cache:"no-store"}).then(response=>{
      if(!response.ok)throw new Error(`strategy-table:http_${response.status}`);
      return response.json();
    }).then(decodedRows);
    return tablePromise;
  }
  function marketMode(){return document.querySelector("[data-market-mode].active")?.dataset.marketMode||"savings_bank";}
  function activeSectors(){
    const mutual=[...document.querySelectorAll("[data-sector]:checked")].map(el=>el.dataset.sector).filter(Boolean);
    const mode=marketMode();
    if(mode==="savings_bank")return["savings_bank"];
    if(mode==="mutual_finance")return mutual;
    return["savings_bank",...mutual];
  }
  function selectedTerm(){return Number(document.querySelector("#term-segment button.active")?.dataset.term||12);}
  function aggregate(rows,term,sectors){
    const allowed=new Set(sectors),map=new Map();
    for(const row of rows){
      if(!allowed.has(row.sector)||row.product_type!=="term_deposit"||row.term_months!==term||row.max_rate===null||!row.product_id)continue;
      const key=`${row.sector}\0${row.product_id}\0${term}`,old=map.get(key);
      if(!old||row.max_rate>old.max_rate||(row.max_rate===old.max_rate&&row.source_effective_at>old.source_effective_at))map.set(key,row);
    }
    return [...map.values()].sort((a,b)=>b.max_rate-a.max_rate||a.institution.localeCompare(b.institution,"ko")||a.product.localeCompare(b.product,"ko"));
  }
  function marketContext(rows){
    const term=selectedTerm(),sectors=activeSectors(),products=aggregate(rows,term,sectors);
    const anchor=products.filter(row=>row.sector==="savings_bank"&&row.institution===OUR_INSTITUTION)
      .sort((a,b)=>b.max_rate-a.max_rate||a.product_id.localeCompare(b.product_id))[0];
    if(!anchor)throw new Error("anchor:unavailable");
    return {
      marketRows:products.map(row=>({product_id:`${row.sector}:${row.product_id}`,rate:row.max_rate})),
      anchorId:`${anchor.sector}:${anchor.product_id}`,
      anchorRate:anchor.max_rate,
    };
  }
  function rate4(value){return Number.isFinite(Number(value))?`${Number(value).toFixed(4)}%`:"—";}
  function rate2(value){return Number.isFinite(Number(value))?`${Number(value).toFixed(2)}%`:"—";}
  function conditionHtml(row){
    const ready=row.status==="ready";
    const value=ready?rate2(row.minimum_selectable_rate_pct):"선택불가";
    const detail=!ready&&row.reason==="exact_tie_not_selectable_on_ui_grid"
      ?`기준선 ${rate4(row.benchmark_rate_pct)} · 1bp 입력단위에서 정확 동률 불가`
      :`기준선 ${rate4(row.benchmark_rate_pct)}`;
    return `<div class="psv2-finder-item" data-target="${row.target}" data-relation="${row.relation}"><span>${row.label}</span><strong class="${ready?"":"unavailable"}">${value}</strong><small>${detail}</small></div>`;
  }
  function signature(result){
    return result.conditions.map(row=>[
      row.target,row.relation,row.benchmark_rate_pct,row.status,row.minimum_selectable_rate_pct??null,row.reason??null
    ].join(":" )).join("|");
  }
  function blockHtml(result){
    return `<section id="${BLOCK_ID}" class="psv2-finder" data-finder-signature="${signature(result)}" aria-label="시장조건 충족 금리"><div class="psv2-finder-head"><div><b>시장조건 충족 금리</b></div><span>조건충족 값 · 자동 결정 아님</span></div><div class="psv2-finder-grid">${result.conditions.map(conditionHtml).join("")}</div><div class="psv2-finder-foot"><span><b>기준:</b> 당사 anchor를 제외한 competitor-only 현재 시장</span><span><b>1bp:</b> 현재 Strategy 입력 선택단위 · 가격결정 정책/tolerance 아님</span></div></section>`;
  }
  function insertBlock(host,html){
    const existing=$(BLOCK_ID);
    if(existing)existing.remove();
    const decision=host.querySelector(":scope > .psv2-decision");
    if(decision)decision.insertAdjacentHTML("afterend",html);
    else host.insertAdjacentHTML("afterbegin",html);
  }
  async function render(){
    const host=$(HOST_ID);
    if(!host||typeof PublicStructuralV2FactualRateFinder!=="object")return;
    try{
      const rows=await loadTable(),context=marketContext(rows);
      const result=PublicStructuralV2FactualRateFinder.factualRateConstraints({
        rows:context.marketRows,
        anchor_product_id:context.anchorId,
        current_own_rate:context.anchorRate,
        selection_step_pp:SELECTION_STEP_PP,
      });
      if(!document.body.contains(host))return;
      insertBlock(host,blockHtml(result));
    }catch(error){
      if(!document.body.contains(host))return;
      insertBlock(host,'<section id="public-structural-v2-factual-rate-finder" class="psv2-finder"><div class="psv2-finder-error">현재 선택 범위에서는 시장조건 충족 금리를 계산할 수 없습니다.</div></section>');
    }
  }
  function schedule(){
    if(renderQueued)return;
    renderQueued=true;
    queueMicrotask(()=>{renderQueued=false;render();});
  }
  function install(){
    const host=$(HOST_ID);
    if(!host)return;
    new MutationObserver(()=>{if(!$(BLOCK_ID))schedule();}).observe(host,{childList:true,subtree:true});
    document.querySelectorAll("[data-market-mode],[data-sector],#term-segment button").forEach(el=>el.addEventListener("click",()=>setTimeout(schedule,60)));
    schedule();
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
""".strip()


def _engine_bundle() -> str:
    path = Path(__file__).resolve().parents[3] / "web" / "public-structural-v2" / "factual_rate_finder.js"
    if not path.exists():
        raise DashboardBuildError(f"Stage G factual finder browser engine이 없다: {path}")
    source = path.read_text(encoding="utf-8")
    if "</script" in source.lower():
        raise DashboardBuildError("Stage G factual finder browser engine에 script 종료 marker가 있다")
    return '<script id="public-structural-v2-factual-rate-finder-engine">\n' + source + "\n</script>"


def inject_public_structural_v2_factual_rate_finder(html: str) -> str:
    """Stage F Cockpit 뒤에 factual-only 조건충족 금리 block을 주입한다."""
    states = (STYLE_MARKER in html, ENGINE_MARKER in html, SCRIPT_MARKER in html)
    if all(states):
        return html
    if any(states):
        raise DashboardBuildError("Stage G factual rate finder 주입 상태가 불완전하다")
    required = (
        'id="public-structural-v2-cockpit-script"',
        'id="public-structural-v2-cockpit-visual-refinement-script"',
        'id="rate-monitor-data"',
    )
    if any(marker not in html for marker in required):
        raise DashboardBuildError("Stage G factual rate finder 선행 계약을 찾지 못했다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Stage G factual rate finder 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    rendered = rendered.replace("</body>", _engine_bundle() + "\n" + _SCRIPT + "\n</body>", 1)
    return rendered
