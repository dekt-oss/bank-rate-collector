# ruff: noqa: E501
"""Stage C2 시장이력 의사결정 브리핑 presentation.

C1의 ``market_intelligence`` 파생계약을 그대로 읽어 Strategy 화면에 표시한다.
여기서는 새로운 시장 수치를 계산하지 않는다. 지원되지 않는 scope도 0으로
대체하지 않고 C1 status/reason을 그대로 사용자에게 보여준다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="market-intelligence-briefing-style"'
SCRIPT_MARKER = 'id="market-intelligence-briefing-script"'

_CSS = r"""
<style id="market-intelligence-briefing-style">
.market-intel{margin:0 0 12px;padding:16px;border:1px solid rgba(128,200,166,.20);border-radius:16px;background:linear-gradient(145deg,rgba(15,35,29,.96),rgba(8,23,19,.97));box-shadow:0 16px 36px rgba(0,0,0,.14)}
.market-intel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:12px}.market-intel-head h2{margin:0;font-size:15px;letter-spacing:-.02em}.market-intel-head p{margin:4px 0 0;color:#73877d;font-size:9.5px}.market-intel-evidence{padding:4px 7px;border:1px solid rgba(128,200,166,.18);border-radius:99px;color:#91aa9e;font-size:9px;white-space:nowrap}
.market-intel-controls{display:flex;flex-wrap:wrap;gap:7px 12px;padding:9px 10px;margin-bottom:10px;border:1px solid rgba(213,225,219,.07);border-radius:11px;background:rgba(4,14,11,.23)}.market-intel-control{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.market-intel-control>span{margin-right:2px;color:#687c72;font-size:9px;font-weight:760}.market-intel-control button{border:1px solid var(--line);border-radius:8px;background:#091813;color:#7d8f86;padding:5px 8px;font-size:9px;font-weight:760;cursor:pointer}.market-intel-control button.active{color:#d9eee3;border-color:rgba(128,200,166,.42);background:rgba(73,125,97,.22)}
.market-intel-status{display:grid;grid-template-columns:minmax(180px,.8fr) minmax(0,2.2fr);gap:10px;margin-bottom:10px}.market-intel-direction{padding:13px;border:1px solid rgba(213,225,219,.08);border-radius:12px;background:rgba(7,19,16,.38)}.market-intel-direction span{display:block;color:#71847a;font-size:9px}.market-intel-direction strong{display:block;margin-top:3px;color:#dce9e2;font-size:22px;letter-spacing:-.04em}.market-intel-direction small{display:block;margin-top:4px;color:#708178;font-size:9px;line-height:1.45}.market-intel-direction.rising strong{color:var(--green)}.market-intel-direction.falling strong{color:#d98989}.market-intel-direction.mixed strong{color:var(--gold)}
.market-intel-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}.market-intel-metric{padding:11px;border:1px solid rgba(213,225,219,.07);border-radius:11px;background:rgba(5,17,14,.26)}.market-intel-metric span{display:block;color:#6f8278;font-size:9px}.market-intel-metric b{display:block;margin-top:4px;color:#d7e5de;font:780 18px/1.1 var(--mono)}.market-intel-metric small{display:block;margin-top:4px;color:#60736a;font-size:9px;line-height:1.35}.market-intel-metric b.up{color:var(--green)}.market-intel-metric b.down{color:var(--red)}
.market-intel-breadth{display:grid;grid-template-columns:auto minmax(120px,1fr) auto;align-items:center;gap:9px;padding:9px 11px;border:1px solid rgba(213,225,219,.07);border-radius:11px;background:rgba(4,14,11,.22);color:#71847a;font-size:9px}.market-intel-breadth strong{color:#b7c9c0}.market-intel-bar{display:flex;height:8px;border-radius:99px;overflow:hidden;background:rgba(255,255,255,.05)}.market-intel-bar i{display:block;height:100%}.market-intel-bar .up{background:#80c8a6}.market-intel-bar .flat{background:#687b72}.market-intel-bar .down{background:#d98989}.market-intel-period{margin-top:8px;color:#65786e;font-size:9px;line-height:1.45}.market-intel-period b{color:#91a79c}.market-intel-empty{padding:18px 13px;border:1px dashed rgba(212,179,111,.22);border-radius:11px;background:rgba(73,55,24,.08);color:#ae9d75;font-size:9.5px;line-height:1.6;text-align:center}
@media(max-width:900px){.market-intel-status{grid-template-columns:1fr}.market-intel-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.market-intel{padding:13px}.market-intel-head{flex-direction:column}.market-intel-metrics{grid-template-columns:1fr 1fr}.market-intel-breadth{grid-template-columns:1fr}.market-intel-controls{display:grid;gap:8px}.market-intel-control{align-items:flex-start}}
</style>
"""

_JS = r"""
<script id="market-intelligence-briefing-script">
(()=>{
  "use strict";
  const $=id=>document.getElementById(id);
  const raw=$("rate-monitor-data")?.textContent||"{}";
  let payload={};
  try{payload=JSON.parse(raw)}catch{return}
  const intelligence=payload.strategy?.market_intelligence;
  const anchor=$("market-flow");
  if(!intelligence||!anchor||$("market-intelligence"))return;

  const sectors={savings_bank:"저축은행",cu:"신협",kfcc:"새마을금고",nh_local:"농·축협"};
  const directions={rising:"상승",falling:"하락",flat:"보합",mixed:"혼조",insufficient:"근거 부족"};
  const state={sector:"savings_bank",term:12,window:30};
  const signedBp=v=>Number.isFinite(Number(v))?`${Number(v)>0?"+":""}${Number(v).toFixed(1)}bp`:"—";
  const pct=v=>Number.isFinite(Number(v))?`${(Number(v)*100).toFixed(0)}%`:"—";
  const shortDate=v=>{if(!v)return"—";const s=String(v);return s.slice(0,10).replaceAll("-",".")};
  const scope=()=>intelligence.scopes?.find(x=>x.sector===state.sector&&Number(x.term_months)===state.term&&Number(x.window_days)===state.window);
  const metricClass=v=>Number(v)>0?"up":Number(v)<0?"down":"";

  const panel=document.createElement("section");
  panel.id="market-intelligence";
  panel.className="market-intel";
  panel.setAttribute("aria-label","최근 시장 금리 경쟁 방향");
  panel.innerHTML=`
    <div class="market-intel-head"><div><h2>최근 시장 금리 경쟁 방향</h2><p>7일·30일 실제 snapshot을 stable product 기준으로 비교해 금리결정 근거를 요약합니다.</p></div><span class="market-intel-evidence">C1 Historical Evidence</span></div>
    <div class="market-intel-controls" aria-label="시장동향 조회 조건">
      <div class="market-intel-control" data-control="sector"><span>업권</span>${Object.entries(sectors).map(([k,v])=>`<button type="button" data-mi-sector="${k}">${v}</button>`).join("")}</div>
      <div class="market-intel-control" data-control="term"><span>기간</span>${[6,12,24,36].map(v=>`<button type="button" data-mi-term="${v}">${v}개월</button>`).join("")}</div>
      <div class="market-intel-control" data-control="window"><span>비교</span>${[7,30].map(v=>`<button type="button" data-mi-window="${v}">${v}D</button>`).join("")}</div>
    </div>
    <div id="market-intelligence-body"></div>`;
  anchor.parentNode.insertBefore(panel,anchor);

  function setActive(){
    panel.querySelectorAll("[data-mi-sector]").forEach(b=>b.classList.toggle("active",b.dataset.miSector===state.sector));
    panel.querySelectorAll("[data-mi-term]").forEach(b=>b.classList.toggle("active",Number(b.dataset.miTerm)===state.term));
    panel.querySelectorAll("[data-mi-window]").forEach(b=>b.classList.toggle("active",Number(b.dataset.miWindow)===state.window));
  }

  function render(){
    setActive();
    const item=scope(),body=$("market-intelligence-body");
    if(!body)return;
    if(!item||item.status!=="supported"){
      const reason=item?.reason||"현재 수집 이력으로 이 범위의 시장변화를 계산할 수 없습니다.";
      const label=item?.status==="unsupported_rate_contract"?"과거 최고금리 계약 미지원":"비교 이력 부족";
      body.innerHTML=`<div class="market-intel-empty"><b>${sectors[state.sector]} · ${state.term}개월 · ${state.window}D</b><br>${label}<br>${reason}<br>근거가 확보되기 전에는 0 또는 추정값으로 대체하지 않습니다.</div>`;
      return;
    }
    const total=Number(item.comparable_product_count)||0,up=Number(item.up_count)||0,down=Number(item.down_count)||0,flat=Number(item.unchanged_count)||0;
    const upW=total?up/total*100:0,downW=total?down/total*100:0,flatW=Math.max(0,100-upW-downW);
    const own=item.our_company;
    const fourthValue=own?signedBp(own.spread_change_bp):signedBp(item.comparable_mean_change_bp);
    const fourthTitle=own?"당사 spread 변화":"비교상품 평균 변화";
    const fourthNote=own?`시장 중앙값 대비 ${signedBp(own.spread_vs_median_end_bp)}`:`동일 상품 ${total.toLocaleString("ko-KR")}개`;
    const dir=item.direction||"mixed";
    body.innerHTML=`
      <div class="market-intel-status">
        <div class="market-intel-direction ${dir}"><span>${sectors[state.sector]} · ${state.term}개월 · ${state.window}D</span><strong>${directions[dir]||dir}</strong><small>실제 관측 ${Number(item.observed_days).toFixed(1)}일 · 비교상품 ${total.toLocaleString("ko-KR")}개</small></div>
        <div class="market-intel-metrics">
          <div class="market-intel-metric"><span>시장 중앙값 변화</span><b class="${metricClass(item.median_change_bp)}">${signedBp(item.median_change_bp)}</b><small>현재 ${Number(item.end?.median_rate).toFixed(2)}%</small></div>
          <div class="market-intel-metric"><span>상위 10% 진입선 변화</span><b class="${metricClass(item.upper_decile_change_bp)}">${signedBp(item.upper_decile_change_bp)}</b><small>현재 ${Number(item.end?.upper_decile_cutoff).toFixed(2)}%</small></div>
          <div class="market-intel-metric"><span>금리변경 breadth</span><b>${Number(item.breadth_score)>0?"+":""}${Number(item.breadth_score).toFixed(2)}</b><small>인상 ${up} · 인하 ${down} · 유지 ${flat}</small></div>
          <div class="market-intel-metric"><span>${fourthTitle}</span><b class="${metricClass(own?own.spread_change_bp:item.comparable_mean_change_bp)}">${fourthValue}</b><small>${fourthNote}</small></div>
        </div>
      </div>
      <div class="market-intel-breadth"><strong>시장 참여 폭</strong><div class="market-intel-bar" aria-label="인상 유지 인하 비중"><i class="up" style="width:${upW}%"></i><i class="flat" style="width:${flatW}%"></i><i class="down" style="width:${downW}%"></i></div><span>인상 ${pct(item.up_share)} · 인하 ${pct(item.down_share)} · 상위군 churn ${pct(item.top_decile_churn_rate)}</span></div>
      <div class="market-intel-period"><b>실측 비교기간</b> ${shortDate(item.start_snapshot_at)} → ${shortDate(item.end_snapshot_at)} · 요청 window 대비 ${(Number(item.coverage_ratio)*100).toFixed(0)}% · 상위 10% 진입 ${item.top_decile_entrants} / 이탈 ${item.top_decile_exits}</div>`;
  }

  panel.addEventListener("click",event=>{
    const button=event.target.closest("button");if(!button)return;
    if(button.dataset.miSector)state.sector=button.dataset.miSector;
    if(button.dataset.miTerm)state.term=Number(button.dataset.miTerm);
    if(button.dataset.miWindow)state.window=Number(button.dataset.miWindow);
    render();
  });
  render();
})();
</script>
"""


def inject_market_intelligence_presentation(html: str) -> str:
    """Strategy HTML에 C1 기반 C2 브리핑을 idempotent하게 주입한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Market Intelligence 주입 상태가 불완전하다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Market Intelligence 주입 위치를 찾지 못했다")
    if 'id="rate-monitor-data"' not in html or 'id="market-flow"' not in html:
        raise DashboardBuildError("기존 Strategy market-flow 계약을 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
