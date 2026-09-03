# ruff: noqa: E501
"""Strategy presentation for the fail-closed market special-offer radar."""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="special-offer-radar-style"'
SCRIPT_MARKER = 'id="special-offer-radar-script"'

_CSS = r"""
<style id="special-offer-radar-style">
.special-radar{margin:0 0 12px;padding:18px;overflow:hidden}.special-radar-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.special-radar-head h2{margin:0;color:var(--ink);font-size:16px;letter-spacing:-.03em}.special-radar-head p{margin:4px 0 0;color:var(--muted);font-size:10.5px;line-height:1.55}.special-radar-badge{flex:0 0 auto;padding:5px 8px;border:1px solid rgba(169,116,26,.22);border-radius:999px;background:rgba(169,116,26,.07);color:#806538;font-size:9.5px;font-weight:780}.special-radar-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}.special-radar-metric{padding:12px;border:1px solid var(--line);border-radius:11px;background:var(--panel2,#FCFAFC)}.special-radar-metric span{display:block;color:var(--muted);font-size:9.5px}.special-radar-metric b{display:block;margin-top:6px;color:var(--ink);font:780 22px/1 var(--mono)}.special-radar-metric small{display:block;margin-top:6px;color:var(--soft);font-size:9px;line-height:1.4}.special-radar-table-wrap{overflow:auto;border:1px solid var(--line);border-radius:11px;background:var(--panel,#fff)}.special-radar-table{width:100%;min-width:720px;border-collapse:collapse}.special-radar-table th{padding:8px 9px;border-bottom:1px solid var(--line);color:var(--soft);background:var(--panel2,#FCFAFC);font-size:9px;text-align:right}.special-radar-table th:first-child,.special-radar-table th:nth-child(2),.special-radar-table td:first-child,.special-radar-table td:nth-child(2){text-align:left}.special-radar-table td{padding:9px;border-bottom:1px solid var(--line);color:var(--ink);font-size:9.5px;text-align:right}.special-radar-table tr:last-child td{border-bottom:0}.special-radar-table td:first-child,.special-radar-table td:nth-child(2){font-weight:700}.special-radar-table .rate{font:780 11px var(--mono);color:var(--accent-ink,var(--green))}.special-radar-table a{color:var(--accent-ink,var(--green));font-weight:720;text-decoration:none}.special-radar-empty{display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:start;padding:14px;border:1px solid rgba(169,116,26,.16);border-radius:11px;background:rgba(169,116,26,.045);color:#6F6250}.special-radar-empty strong{display:grid;place-items:center;width:28px;height:28px;border-radius:9px;background:rgba(169,116,26,.10);color:#8A682B;font:800 12px var(--mono)}.special-radar-empty b{display:block;color:#5E4B2A;font-size:10.5px}.special-radar-empty p{margin:4px 0 0;font-size:9.5px;line-height:1.55}.special-radar-foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:9px;color:var(--soft);font-size:9px;line-height:1.5}.special-radar-foot b{color:var(--ink)}
@media(max-width:760px){.special-radar{padding:14px}.special-radar-head{flex-direction:column}.special-radar-metrics{display:flex;overflow-x:auto;overscroll-behavior-inline:contain}.special-radar-metric{flex:0 0 min(70vw,210px)}.special-radar-foot{flex-direction:column;gap:3px}}@media(max-width:420px){.special-radar-empty{grid-template-columns:1fr}.special-radar-metric{flex-basis:78vw}}
</style>
"""

_JS = r"""
<script id="special-offer-radar-script">
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const safeHref=v=>{const raw=String(v||"").trim();return /^https?:\/\//i.test(raw)?raw:null};
const payload=(()=>{try{return JSON.parse($("rate-monitor-data")?.textContent||"{}")?.strategy?.special_offer_radar||null}catch{return null}})();
if(!payload)return;
const counts=payload.counts||{};
const offers=Array.isArray(payload.offers)?payload.offers:[];
const rate=v=>Number.isFinite(Number(v))?`${Number(v).toFixed(2)}%`:"—";
const metric=(label,value,note)=>`<div class="special-radar-metric"><span>${label}</span><b>${Number(value||0).toLocaleString("ko-KR")}</b><small>${note}</small></div>`;
const evidenceLink=v=>{const href=safeHref(v);return href?`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">근거 보기</a>`:"기록됨"};
function offersTable(){if(!offers.length)return `<div class="special-radar-empty"><strong>OFF</strong><div><b>공식 근거로 확정된 특판이 아직 없습니다.</b><p>FSB 일반 공시 화면이 특판 여부를 말하지 않은 상품은 <b>unknown</b>으로 유지합니다. “특판 표기가 없음 = 일반상품”으로 추정하지 않으며, 확정 근거가 생기기 전에는 시장 특판 벤치마크와 경쟁순위에 넣지 않습니다.</p></div></div>`;return `<div class="special-radar-table-wrap"><table class="special-radar-table"><thead><tr><th>금융사</th><th>상품</th><th>대표 최고금리</th><th>기간</th><th>채널</th><th>공식 근거</th></tr></thead><tbody>${offers.map(x=>`<tr><td>${esc(x.institution_name)}</td><td>${esc(x.product_name)}</td><td class="rate">${rate(x.representative_rate)}</td><td>${x.term_months?`${Number(x.term_months)}개월`:"—"}</td><td>${esc(x.join_channel||"—")}</td><td>${evidenceLink(x.evidence_ref)}</td></tr>`).join("")}</tbody></table></div>`}
function install(){if($("special-offer-radar"))return;const anchor=$("market-flow");if(!anchor)return;const section=document.createElement("section");section.id="special-offer-radar";section.className="card special-radar";const badge=offers.length?"확정근거 있음 · 공개 OFF":"근거 축적 중 · 공개 OFF";section.innerHTML=`<div class="special-radar-head"><div><h2>시장 특판 Radar</h2><p>특판은 일반 경쟁순위와 분리해 시장 압력·벤치마킹 자료로 관리합니다. 명시적인 상품 단위 공식 근거만 확정으로 인정합니다.</p></div><span class="special-radar-badge">${badge}</span></div><div class="special-radar-metrics">${metric("확정 특판",counts.confirmed_special,"Radar에 표시 가능한 근거")}${metric("확정 일반",counts.confirmed_normal,"명시적 일반상품 근거")}${metric("판정 미제공",counts.unknown,"특판으로 간주하지 않음")}${metric("근거 충돌",counts.conflict,"자동 선택하지 않고 차단")}</div>${offersTable()}<div class="special-radar-foot"><span>기준일 <b>${esc(payload.as_of||"—")}</b> · 원천 <b>${esc(payload.source_id||"—")}</b></span><span>현재 정책: <b>Radar 활성화 OFF</b> · 일반 금리/Relative Pricing 모집단 변경 없음</span></div>`;anchor.parentNode.insertBefore(section,anchor)}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_special_offer_radar_presentation(html: str) -> str:
    """Inject a read-only Radar card without creating a mutation surface."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Special-offer Radar 주입 상태가 불완전하다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Special-offer Radar 주입 위치를 찾지 못했다")
    if 'id="rate-monitor-data"' not in html or 'id="market-flow"' not in html:
        raise DashboardBuildError("Special-offer Radar Strategy 계약을 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
