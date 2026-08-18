# ruff: noqa: E501
"""Stage E0-6 — 외부 수신시장 환경 presentation.

이미 검증된 ``deposit_pricing_external_features``를 Strategy 화면의 보조 근거로
표시한다. 여기서는 신규 산식이나 예측을 만들지 않는다. 결측/계약 불일치는
0으로 바꾸지 않고 원래 status를 그대로 노출한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="external-market-context-style"'
SCRIPT_MARKER = 'id="external-market-context-script"'

_CSS = r"""
<style id="external-market-context-style">
.external-context{margin:0 0 12px;padding:16px;border:1px solid rgba(128,200,166,.18);border-radius:16px;background:linear-gradient(145deg,rgba(13,31,26,.97),rgba(7,20,17,.98));box-shadow:0 16px 36px rgba(0,0,0,.12)}
.external-context-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:11px}.external-context-head h2{margin:0;font-size:15px;letter-spacing:-.02em}.external-context-head p{margin:4px 0 0;color:#73877d;font-size:9.5px;line-height:1.5}.external-context-badge{padding:4px 7px;border:1px solid rgba(128,200,166,.18);border-radius:99px;color:#91aa9e;font-size:9px;white-space:nowrap}.external-context-badge.partial{border-color:rgba(212,179,111,.24);color:#bca36f}
.external-context-rates{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:8px}.external-context-card{padding:12px;border:1px solid rgba(213,225,219,.07);border-radius:11px;background:rgba(5,17,14,.28)}.external-context-card span{display:block;color:#6f8278;font-size:9px}.external-context-card b{display:block;margin-top:4px;color:#d7e5de;font:780 19px/1.1 var(--mono)}.external-context-card small{display:block;margin-top:5px;color:#62766c;font-size:9px;line-height:1.4}.external-context-card .status{color:#a99365}.external-context-flows{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}.external-flow{padding:10px;border:1px solid rgba(213,225,219,.07);border-radius:10px;background:rgba(4,14,11,.23)}.external-flow span{display:block;color:#71847a;font-size:9px}.external-flow b{display:block;margin-top:4px;color:#cbd9d2;font:760 14px/1.15 var(--mono)}.external-flow b.up{color:var(--green)}.external-flow b.down{color:var(--red)}.external-flow small{display:block;margin-top:4px;color:#60736a;font-size:9px;line-height:1.38}.external-context-note{margin-top:8px;padding-top:8px;border-top:1px solid rgba(213,225,219,.06);color:#687b72;font-size:9px;line-height:1.55}.external-context-note b{color:#9eb3a8}
@media(max-width:900px){.external-context-rates{grid-template-columns:1fr 1fr}.external-context-flows{grid-template-columns:1fr 1fr}}@media(max-width:560px){.external-context{padding:13px}.external-context-head{flex-direction:column}.external-context-rates,.external-context-flows{grid-template-columns:1fr}}
</style>
"""

_JS = r"""
<script id="external-market-context-script">
(()=>{
  "use strict";
  const raw=document.getElementById("rate-monitor-data")?.textContent||"{}";
  let payload={};
  try{payload=JSON.parse(raw)}catch{return}
  const context=payload.strategy?.external_features;
  const fallback=document.getElementById("market-flow");
  const anchor=document.getElementById("market-intelligence")||fallback;
  if(!context||!anchor||document.getElementById("external-market-context"))return;

  const statusLabel={ready:"정상",partial:"일부",no_data:"자료 없음",schema_unavailable:"스키마 미지원",source_contract_mismatch:"원천계약 불일치",insufficient_history:"이력 부족",non_consecutive_months:"연속월 아님",invalid_previous_balance:"기준잔액 오류"};
  const rate=v=>Number.isFinite(Number(v))?`${Number(v).toFixed(2)}%`:"—";
  const signedPct=v=>Number.isFinite(Number(v))?`${Number(v)>0?"+":""}${Number(v).toFixed(2)}%`:"—";
  const balance=v=>Number.isFinite(Number(v))?`${Number(v).toLocaleString("ko-KR",{maximumFractionDigits:2})}조원`:"—";
  const effective=item=>item?.data_month||String(item?.source_effective_at||"").slice(0,10)||"—";
  const itemStatus=item=>statusLabel[item?.status]||item?.status||"자료 없음";
  const rateCard=(title,item,note)=>`<div class="external-context-card"><span>${title}</span><b>${item?.status==="ready"?rate(item.value):"—"}</b><small>${item?.status==="ready"?`${effective(item)} 기준 · ${note}`:`<span class="status">${itemStatus(item)}</span>`}</small></div>`;
  const flowCard=(title,item,note)=>{const ready=item?.status==="ready",value=ready?Number(item.mom_change_pct):NaN,cls=Number.isFinite(value)?(value>0?"up":value<0?"down":""):"";return `<div class="external-flow"><span>${title}</span><b class="${cls}">${ready?signedPct(value):"—"}</b><small>${ready?`${effective(item)} · 잔액 ${balance(item.balance_trillion_krw)}`:`${itemStatus(item)}`}<br>${note}</small></div>`};

  const market=context.deposit_market||{};
  const rates=market.bank_rates||{};
  const flows=market.sector_balances||{};
  const panel=document.createElement("section");
  panel.id="external-market-context";
  panel.className="external-context";
  panel.setAttribute("aria-label","시장 자금환경");
  const badgeClass=context.status==="ready"?"":" partial";
  panel.innerHTML=`
    <div class="external-context-head"><div><h2>시장 자금환경</h2><p>기준금리·은행 신규취급 예금금리·업권 수신잔액 흐름을 금리결정의 외부 환경으로 봅니다.</p></div><span class="external-context-badge${badgeClass}">BOK · ${statusLabel[context.status]||context.status||"자료 없음"}</span></div>
    <div class="external-context-rates">
      ${rateCard("한국은행 기준금리",context.policy_rate,"통화정책 환경")}
      ${rateCard("은행 순수저축성예금 신규취급",rates.primary_realized_deposit_rate,"실제 신규취급 가중평균")}
      ${rateCard("은행 1년 정기예금 신규취급",rates.term_deposit_1y_rate,"12개월 경쟁 보조축")}
    </div>
    <div class="external-context-flows">
      ${flowCard("저축은행 수신잔액 MoM",flows.savings_bank,"업권 직접 참고")}
      ${flowCard("신협 수신잔액 MoM",flows.credit_union,"업권 직접 참고")}
      ${flowCard("새마을금고 수신잔액 MoM",flows.kfcc,"업권 직접 참고")}
      ${flowCard("광의 상호금융 수신잔액 MoM",flows.broad_mutual_finance,"NH local 대리지표 · 농·축협과 1:1 동일하지 않음")}
    </div>
    <div class="external-context-note"><b>해석 경계</b> 월별 거시 참고지표이며 당사 수신효과나 인과를 추정한 값이 아닙니다. ECOS 공표시차가 있으므로 각 카드의 기준월을 함께 확인합니다. 은행채·CD·COFIX는 Stage E v1 직접변수에서 제외합니다.</div>`;
  anchor.parentNode.insertBefore(panel,anchor);
})();
</script>
"""


def inject_external_market_context_presentation(html: str) -> str:
    """Strategy HTML에 외부 수신시장 context를 idempotent하게 주입한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("External Market Context 주입 상태가 불완전하다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("External Market Context 주입 위치를 찾지 못했다")
    if 'id="rate-monitor-data"' not in html or 'id="market-flow"' not in html:
        raise DashboardBuildError("기존 Strategy external context anchor를 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
