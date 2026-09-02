"""Presentation-only Relative Pricing R1 surface for Strategy.

The backend ``strategy.relative_pricing`` payload remains the sole factual source.
This injector does not query the database, choose peers, alter source precedence,
or call the uncalibrated inflow model. Client-side interaction is limited to
recomputing deterministic peer position and simple fixed-notional surface-interest
cost for a user-selected review rate under the versioned factual cost contract.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="relative-pricing-r1-style"'
SCRIPT_MARKER = 'id="relative-pricing-r1-script"'
SECTION_MARKER = 'id="relative-pricing-r1"'
_INSERT_BEFORE = '<footer class="foot">'

_CSS = r"""
<style id="relative-pricing-r1-style">
.relative-pricing-r1{margin:12px 0;background:linear-gradient(148deg,rgba(15,34,28,.98),rgba(8,23,19,.98))}
.rp-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px}
.rp-head h2{margin:0;font-size:16px;letter-spacing:-.025em}
.rp-head p{margin:4px 0 0;color:#7d9087;font-size:10px}
.rp-status{padding:5px 8px;border:1px solid rgba(128,200,166,.22);border-radius:999px;color:#a9d7c0;background:rgba(80,143,109,.12);font-size:9px;font-weight:780;white-space:nowrap}
.rp-status.blocked{border-color:rgba(212,179,111,.24);color:#d2ba84;background:rgba(112,83,36,.12)}
.rp-blocked{padding:14px;border:1px dashed rgba(212,179,111,.25);border-radius:12px;color:#a59676;background:rgba(86,66,32,.08);font-size:10px;line-height:1.6}
.rp-blocked b{display:block;margin-bottom:4px;color:#d4bd88}
.rp-controls{display:grid;grid-template-columns:minmax(280px,1.35fr) minmax(220px,.65fr);gap:10px;margin-bottom:10px}
.rp-control{padding:13px;border:1px solid rgba(213,225,219,.09);border-radius:12px;background:rgba(4,16,13,.28)}
.rp-control-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.rp-control label,.rp-control-title{color:#a9bbb2;font-size:10px;font-weight:780}
.rp-rate-pair{display:flex;align-items:baseline;gap:8px}
.rp-rate-pair strong{font:820 24px/1 var(--mono);color:#dce9e2}
.rp-rate-pair span{color:#75877e;font-size:9px}
.rp-slider{width:100%;margin:13px 0 3px;accent-color:var(--green)}
.rp-slider-scale{display:flex;justify-content:space-between;color:#5f7469;font:9px var(--mono)}
.rp-notional-row{display:flex;align-items:center;gap:7px;margin-top:11px}
.rp-notional-row input{width:105px;padding:7px 8px;border:1px solid rgba(213,225,219,.13);border-radius:8px;background:#081814;color:#e3ece7;font:760 11px var(--mono)}
.rp-notional-row span{color:#75877e;font-size:9px}
.rp-cost{margin-top:10px;font:820 21px/1.1 var(--mono);color:var(--gold)}
.rp-cost small{display:block;margin-top:5px;color:#71837a;font:9px var(--sans)}
.rp-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}
.rp-metric{padding:12px;border:1px solid rgba(213,225,219,.09);border-radius:11px;background:rgba(8,24,20,.54)}
.rp-metric span{display:block;color:#74877d;font-size:9px}
.rp-metric b{display:block;margin-top:5px;color:#d9e6df;font:800 17px var(--mono)}
.rp-metric small{display:block;margin-top:4px;color:#65786e;font-size:9px;line-height:1.4}
.rp-metric.peer b{color:#a8d7c0}
.rp-market-current{padding:12px;border:1px solid rgba(213,225,219,.08);border-radius:11px;background:rgba(8,23,19,.4)}
.rp-market-current b{display:block;color:#d8e5de;font-size:10px}
.rp-market-current span{display:block;margin-top:4px;color:#74877d;font-size:9px}
.rp-table-wrap{overflow:auto;border:1px solid rgba(213,225,219,.08);border-radius:12px}
.rp-table{width:100%;min-width:900px;border-collapse:collapse}
.rp-table th{padding:8px 9px;border-bottom:1px solid rgba(213,225,219,.09);color:#71847a;background:rgba(4,15,12,.35);font-size:9px;text-align:right;white-space:nowrap}
.rp-table th:first-child,.rp-table td:first-child{text-align:left}
.rp-table td{padding:9px;border-bottom:1px solid rgba(213,225,219,.055);color:#a9b9b1;font:730 9px var(--mono);text-align:right;white-space:nowrap}
.rp-table tbody tr:last-child td{border-bottom:0}
.rp-table .institution{color:#d8e3dd;font:760 9.5px var(--sans)}
.rp-table .higher{color:#d4b36f}
.rp-table .lower{color:#80c8a6}
.rp-table .missing{color:#786f60;font-family:var(--sans)}
.rp-table small{display:block;margin-top:2px;color:#5f7168;font:9px var(--sans)}
.rp-foot{display:flex;flex-wrap:wrap;gap:5px 12px;margin-top:9px;color:#667a70;font-size:9px}
.rp-foot b{color:#899e93}
.rp-policy{margin-top:9px}
.rp-policy summary{cursor:pointer;color:#758a80;font-size:9px}
.rp-policy pre{overflow:auto;margin:7px 0 0;padding:9px;border-radius:8px;background:#071510;color:#71867b;font:9px/1.5 var(--mono)}
@media(max-width:900px){.rp-controls{grid-template-columns:1fr}.rp-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:520px){.relative-pricing-r1{padding:14px}.rp-head{flex-direction:column;gap:8px}.rp-grid{grid-template-columns:1fr 1fr}.rp-control-top{flex-direction:column}.rp-rate-pair strong{font-size:22px}.rp-table{min-width:820px}}
</style>
"""

_SECTION = r"""
<section id="relative-pricing-r1" class="relative-pricing-r1 card pad" aria-labelledby="relative-pricing-r1-title">
  <div class="rp-head">
    <div>
      <h2 id="relative-pricing-r1-title">상대금리 · 주요 경쟁기관</h2>
      <p>공식 가입가능지역과 기관별 대표금리로 당사 위치를 비교합니다. 상품시장 순위와 기관 pricing peer 순위를 구분합니다.</p>
    </div>
    <span class="rp-status blocked" id="rp-status">근거 확인 중</span>
  </div>
  <div id="rp-blocked" class="rp-blocked">
    <b>상대금리 근거를 확인하고 있습니다.</b>
    <span>공식 가입가능지역·대표금리·Matrix 정합성 gate가 통과되어야 표시합니다.</span>
  </div>
  <div id="rp-ready" hidden>
    <div class="rp-controls">
      <div class="rp-control">
        <div class="rp-control-top">
          <div>
            <div class="rp-control-title">현재금리 / 검토금리</div>
            <div class="rp-rate-pair">
              <strong id="rp-current-rate">—</strong><span>현재</span>
              <strong id="rp-review-rate">—</strong><span>검토</span>
            </div>
          </div>
          <span class="rp-status" id="rp-scope">공식 scope</span>
        </div>
        <input class="rp-slider" id="rp-review-slider" type="range" min="1.50" max="6.00" step="0.01" value="3.70" aria-label="검토금리">
        <div class="rp-slider-scale">
          <span>1.50%</span><span>기존 Strategy 제안금리 slider 계약 · 1bp</span><span>6.00%</span>
        </div>
      </div>
      <div class="rp-control">
        <label for="rp-cost-notional">비용 계산 기준금액(수신 목표 아님)</label>
        <div class="rp-notional-row">
          <input id="rp-cost-notional" type="number" min="0" step="1" value="100" inputmode="decimal"><span>억원</span>
        </div>
        <div class="rp-cost" id="rp-cost">—<small>고정 원금 · 단리 표면이자 차이</small></div>
      </div>
    </div>
    <div class="rp-grid">
      <div class="rp-metric">
        <span>전체 상품시장 위치 · 현재 기준</span>
        <b id="rp-product-market-rank">기존 지표 연동 중</b>
        <small id="rp-product-market-note">상품 단위 시장지표와 기관 peer 지표를 합치지 않습니다.</small>
      </div>
      <div class="rp-metric peer">
        <span>주요 경쟁기관 위치 · 검토금리 반영</span>
        <b id="rp-peer-rank">—</b><small id="rp-peer-gap">—</small>
      </div>
      <div class="rp-metric peer">
        <span>검토금리보다 높은 peer</span>
        <b id="rp-higher-count">—</b><small id="rp-crowding">—</small>
      </div>
      <div class="rp-metric">
        <span>수신잔액 연결</span>
        <b id="rp-funding-coverage">—</b>
        <small id="rp-funding-note">자료없음은 0으로 간주하지 않습니다.</small>
      </div>
    </div>
    <div class="rp-table-wrap">
      <table class="rp-table">
        <thead><tr><th>기관</th><th>대표금리</th><th>검토금리 대비</th><th>금리 기준일</th><th>수신잔액</th><th>6M 증감</th><th>수신 기준월</th><th>funding 상태</th></tr></thead>
        <tbody id="rp-peer-rows"></tbody>
      </table>
    </div>
    <div class="rp-foot">
      <span><b>비교범위</b> <span id="rp-scope-foot">—</span></span>
      <span><b>pricing 정책</b> <span id="rp-pricing-policy">—</span></span>
      <span><b>Matrix 정책</b> <span id="rp-matrix-policy">—</span></span>
      <span><b>비용 계약</b> <span id="rp-cost-contract">—</span></span>
      <span><b>현재 대표금리 기준일</b> <span id="rp-current-asof">—</span></span>
      <span id="rp-temporal-note">금리 기준일과 수신 기준월은 별도 시점입니다.</span>
    </div>
    <details class="rp-policy">
      <summary>정책·정합성 근거 보기</summary><pre id="rp-policy-detail">—</pre>
    </details>
  </div>
</section>
"""

_JS = r"""
<script id="relative-pricing-r1-script">
(()=>{
  "use strict";
  const payloadNode=document.getElementById("rate-monitor-data");
  const section=document.getElementById("relative-pricing-r1");
  if(!payloadNode||!section)return;

  const data=JSON.parse(payloadNode.textContent||"{}");
  const rp=data.strategy?.relative_pricing||null;
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const number=value=>{const n=Number(value);return Number.isFinite(n)?n:null};
  const rate=value=>{const n=number(value);return n==null?"—":`${n.toFixed(2)}%`};
  const bp=value=>{const n=number(value);return n==null?"—":`${n>=0?"+":""}${n.toFixed(Math.abs(n)>=10?0:1)}bp`};
  const dateText=value=>value?String(value).slice(0,10):"자료없음";
  const moneyWon=value=>{
    const n=number(value);
    if(n==null)return"—";
    const sign=n>0?"+":n<0?"−":"";
    return `${sign}${Math.abs(Math.round(n)).toLocaleString("ko-KR")}원`;
  };
  const fundingMoney=value=>{
    const n=number(value);
    return n==null?"자료없음":`${n.toLocaleString("ko-KR",{maximumFractionDigits:0})}백만원`;
  };
  const reasonText=reason=>({
    availability_match_key_unresolved:"공식 가입가능지역이 아직 확정되지 않았습니다.",
    availability_match_key_ambiguous:"공식 가입가능지역이 둘 이상이라 임의 지역을 선택하지 않았습니다.",
    relative_pricing_rate_candidates_unresolved:"공식 scope의 canonical 대표금리 후보가 아직 확인되지 않았습니다.",
    matrix_representative_rate_temporal_mismatch:"Pricing과 Rate × Funding Matrix의 대표금리 기준일이 달라 표시를 차단했습니다.",
    matrix_representative_rate_temporal_unresolved:"대표금리 기준일 근거가 부족해 표시를 차단했습니다.",
    matrix_representative_rate_unresolved:"Rate × Funding Matrix 대표금리 근거가 부족합니다.",
    representative_rate_policy_mismatch_unexplained:"두 대표금리 정책의 차이를 설명할 근거가 없어 표시를 차단했습니다."
  }[String(reason||"")]||`근거 gate 미통과 · ${String(reason||"reason_unavailable")}`);

  if(!rp||rp.status!=="ready"||!rp.pricing_peer_position){
    $("rp-status").textContent="근거 미충족";
    $("rp-blocked").innerHTML=`<b>상대금리 비교를 아직 열지 않습니다.</b><span>${esc(reasonText(rp?.reason))}</span>`;
    return;
  }

  const current=number(rp.pricing_peer_position.current_rate_pct);
  const peers=Array.isArray(rp.peers)?rp.peers:[];
  const factualCost=rp.factual_cost||{};
  if(current==null||!peers.length){
    $("rp-status").textContent="근거 부족";
    $("rp-blocked").innerHTML="<b>기관 pricing peer를 계산할 근거가 부족합니다.</b><span>현재 대표금리와 peer 행을 모두 확인해야 합니다.</span>";
    return;
  }

  $("rp-blocked").hidden=true;
  $("rp-ready").hidden=false;
  $("rp-status").classList.remove("blocked");
  $("rp-status").textContent="R1 factual";
  $("rp-current-rate").textContent=rate(current);

  const slider=$("rp-review-slider");
  slider.value=String(Math.min(Number(slider.max),Math.max(Number(slider.min),current)));
  const customNotional=$("rp-cost-notional");
  const standardNotionalKrw=number(factualCost.standardized_notional_krw);
  if(standardNotionalKrw!=null&&standardNotionalKrw>=0){
    customNotional.value=String(standardNotionalKrw/100000000);
  }
  const scope=rp.scope||{};
  const policy=rp.policies||{};
  const reconciliation=rp.representative_rate_reconciliation||{};

  $("rp-scope").textContent=scope.availability_scope||"공식 scope";
  $("rp-scope-foot").textContent=`${scope.availability_scope||"—"} · ${scope.term_months||12}개월 · 특판 core 제외`;
  $("rp-pricing-policy").textContent=`${policy.institution_rate_reduction?.policy_id||"—"} v${policy.institution_rate_reduction?.policy_version||"—"}`;
  $("rp-matrix-policy").textContent=reconciliation.matrix_policy_id||"—";
  $("rp-cost-contract").textContent=`surface_cost v${factualCost.contract_version||policy.surface_cost?.contract_version||"—"}`;
  $("rp-current-asof").textContent=dateText(reconciliation.pricing_rate_as_of||rp.as_of);
  $("rp-policy-detail").textContent=JSON.stringify({
    scope:rp.scope,
    policies:rp.policies,
    factual_cost:rp.factual_cost,
    representative_rate_reconciliation:rp.representative_rate_reconciliation
  },null,2);

  const peerRates=peers.map(peer=>number(peer.rate_pct)).filter(Number.isFinite).sort((a,b)=>a-b);
  const median=peerRates.length%2
    ? peerRates[(peerRates.length-1)/2]
    : (peerRates[peerRates.length/2-1]+peerRates[peerRates.length/2])/2;

  function renderReview(){
    const review=number(slider.value);
    if(review==null)return;
    $("rp-review-rate").textContent=rate(review);

    const higher=peerRates.filter(value=>value>review).length;
    const lower=peerRates.filter(value=>value<review).length;
    const ties=peerRates.length-higher-lower;
    const rankBest=higher+1;
    const rankWorst=higher+ties+1;
    $("rp-peer-rank").textContent=rankBest===rankWorst
      ? `${rankBest}위 / ${peerRates.length+1}기관`
      : `${rankBest}~${rankWorst}위 / ${peerRates.length+1}기관`;
    $("rp-peer-gap").textContent=`peer 중앙 ${rate(median)} · ${bp((review-median)*100)}`;
    $("rp-higher-count").textContent=`${higher}개`;
    const within5=peerRates.filter(value=>Math.abs(value-review)<=.05+1e-9).length;
    const within10=peerRates.filter(value=>Math.abs(value-review)<=.10+1e-9).length;
    $("rp-crowding").textContent=`±5bp ${within5}개 · ±10bp ${within10}개`;

    const notional100m=Math.max(0,number(customNotional.value)??0);
    const notionalKrw=notional100m*100000000;
    const months=Number(scope.term_months||12);
    const delta=notionalKrw*((review-current)/100)*(months/12);
    $("rp-cost").innerHTML=`${moneyWon(delta)}<small>${notional100m.toLocaleString("ko-KR",{maximumFractionDigits:2})}억원 · ${months}개월 · ${$("rp-cost-contract").textContent} · 현재 ${rate(current)} 대비 단리 표면이자 차이</small>`;

    const sorted=[...peers].sort((left,right)=>
      (number(right.rate_pct)??-Infinity)-(number(left.rate_pct)??-Infinity)
      ||String(left.institution||left.institution_id).localeCompare(String(right.institution||right.institution_id),"ko")
    );
    $("rp-peer-rows").innerHTML=sorted.map(peer=>{
      const peerRate=number(peer.rate_pct);
      const gap=peerRate==null?null:(peerRate-review)*100;
      const klass=gap==null?"":gap>0?"higher":gap<0?"lower":"";
      const fundingKnown=peer.funding_status==="known"&&number(peer.funding_balance_million_krw)!=null;
      const change=number(peer.funding_change_6m_pct);
      const asofMismatch=fundingKnown&&peer.rate_as_of&&peer.funding_as_of
        &&String(peer.rate_as_of).slice(0,7)!==String(peer.funding_as_of).slice(0,7);
      return `<tr><td><span class="institution">${esc(peer.institution||peer.institution_id)}</span><small>${esc(peer.rate_source_id||"source 미확인")}</small></td><td>${rate(peerRate)}</td><td class="${klass}">${gap==null?"—":bp(gap)}</td><td>${esc(dateText(peer.rate_as_of))}</td><td class="${fundingKnown?"":"missing"}">${fundingMoney(peer.funding_balance_million_krw)}</td><td class="${change==null?"missing":""}">${change==null?"자료없음":`${change>=0?"+":""}${change.toFixed(2)}%`}</td><td class="${fundingKnown?"":"missing"}">${esc(peer.funding_as_of||"자료없음")}${asofMismatch?" *":""}</td><td class="${fundingKnown?"":"missing"}">${fundingKnown?"known":"자료없음"}</td></tr>`;
    }).join("");
  }

  const known=peers.filter(peer=>
    peer.funding_status==="known"&&number(peer.funding_balance_million_krw)!=null
  ).length;
  $("rp-funding-coverage").textContent=`${known} / ${peers.length}기관`;
  $("rp-funding-note").textContent=known===peers.length
    ? "모든 peer에 수신잔액 근거가 있습니다."
    : `known ${known} · 자료없음 ${peers.length-known} · 자료없음은 0이 아닙니다.`;
  slider.addEventListener("input",renderReview);
  customNotional.addEventListener("input",renderReview);
  renderReview();

  function captureCurrentProductMarket(){
    const rank=document.getElementById("sim-rank");
    const note=document.getElementById("sim-market-note");
    if(!rank)return false;
    const text=String(rank.textContent||"").trim();
    if(!text||text==="데이터 대기"||text.includes("없음"))return false;
    $("rp-product-market-rank").textContent=text;
    $("rp-product-market-note").textContent=`현재 ${rate(current)} · ${String(note?.textContent||"상품 단위 비교군").trim()} · 기관 peer 순위와 별도`;
    return true;
  }

  if(!captureCurrentProductMarket()){
    const rank=document.getElementById("sim-rank");
    if(rank){
      const observer=new MutationObserver(()=>{
        if(captureCurrentProductMarket())observer.disconnect();
      });
      observer.observe(rank,{childList:true,characterData:true,subtree:true});
      setTimeout(()=>observer.disconnect(),30000);
    }
  }
})();
</script>
"""


def inject_relative_pricing_presentation(html: str) -> str:
    """Add the R1 factual presentation without changing the calculation payload."""

    if STYLE_MARKER in html or SCRIPT_MARKER in html or SECTION_MARKER in html:
        return html
    if "</head>" not in html:
        raise DashboardBuildError("Strategy head 종료 지점을 찾지 못했다")
    if _INSERT_BEFORE not in html:
        raise DashboardBuildError("Strategy footer 삽입 지점을 찾지 못했다")
    if "</body>" not in html:
        raise DashboardBuildError("Strategy body 종료 지점을 찾지 못했다")

    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    rendered = rendered.replace(_INSERT_BEFORE, _SECTION + "\n" + _INSERT_BEFORE, 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
