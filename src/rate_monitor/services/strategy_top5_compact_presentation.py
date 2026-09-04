# ruff: noqa: E501
"""Strategy 경쟁사 TOP5를 업권 구분이 있는 compact 표로 정리한다.

기존 ``renderMarket`` 의 정렬/상위5개 선정과 당사 위치 행을 그대로 사용한다.
이 presentation은 업권 열과 표시 밀도만 추가하며 ranking population, tie, source,
금리 계산 계약은 변경하지 않는다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-top5-compact-style"'
SCRIPT_MARKER = 'id="strategy-top5-compact-script"'

_STYLE = r"""
<style id="strategy-top5-compact-style">
.top5-card[data-top5-compact="1"]{padding:14px 16px!important}.top5-card[data-top5-compact="1"] .head{margin-bottom:8px!important}.top5-card[data-top5-compact="1"] .head p{margin-top:2px!important}.top5-card[data-top5-compact="1"] th{padding:6px 7px 7px!important}.top5-card[data-top5-compact="1"] td{padding:7px 7px!important;vertical-align:middle!important}.top5-card[data-top5-compact="1"] th:first-child{width:48px}.top5-card[data-top5-compact="1"] .strategy-sector-head{width:78px;text-align:left!important}.top5-card[data-top5-compact="1"] .strategy-sector-cell{text-align:left!important;white-space:nowrap}.top5-card[data-top5-compact="1"] .strategy-sector-badge{display:inline-flex;align-items:center;min-height:23px;padding:3px 7px;border:1px solid rgba(91,47,100,.12);border-radius:7px;background:#f7f3f7;color:#604a64;font-size:9.5px;font-weight:820;line-height:1.1}.top5-card[data-top5-compact="1"] .strategy-sector-badge[data-sector="savings_bank"]{background:#f4f0f7;color:#5c4868}.top5-card[data-top5-compact="1"] .strategy-sector-badge[data-sector="cu"]{background:#eef7f3;color:#356451}.top5-card[data-top5-compact="1"] .strategy-sector-badge[data-sector="kfcc"]{background:#fff6ed;color:#865a31}.top5-card[data-top5-compact="1"] .strategy-sector-badge[data-sector="nh_local"]{background:#f1f5f8;color:#466273}.top5-card[data-top5-compact="1"] .bank{display:inline!important;margin-right:7px!important;font-size:10.8px!important}.top5-card[data-top5-compact="1"] .product{display:inline!important;max-width:none!important;margin:0!important;color:#625568!important;font-size:9.8px!important;white-space:nowrap!important}.top5-card[data-top5-compact="1"] .sourcehint{display:block!important;max-width:600px;margin-top:2px!important;color:#8a7e8c!important;font-size:8.9px!important;line-height:1.25!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}.top5-card[data-top5-compact="1"] .rank{width:23px!important;height:23px!important}.top5-card[data-top5-compact="1"] .our-position-note{display:inline!important;margin:0 0 0 8px!important;font-size:9.2px!important;line-height:1.3!important}.top5-card[data-top5-compact="1"] .our-position-badge{margin-left:0!important;margin-right:6px!important}.top5-card[data-top5-compact="1"] tr.our-position-row td{padding-top:8px!important;padding-bottom:8px!important}
@media(max-width:760px){.top5-card[data-top5-compact="1"]{padding:12px!important}.top5-card[data-top5-compact="1"] tbody tr{display:grid!important;grid-template-columns:28px auto minmax(0,1fr) auto!important;grid-template-areas:"r s n m" ". . b u"!important;gap:3px 7px!important;padding:8px!important}.top5-card[data-top5-compact="1"] td{padding:0!important}.top5-card[data-top5-compact="1"] td:nth-child(1){grid-area:r!important}.top5-card[data-top5-compact="1"] td:nth-child(2){grid-area:s!important}.top5-card[data-top5-compact="1"] td:nth-child(3){grid-area:n!important;min-width:0}.top5-card[data-top5-compact="1"] td:nth-child(4){grid-area:b!important}.top5-card[data-top5-compact="1"] td:nth-child(5){grid-area:u!important}.top5-card[data-top5-compact="1"] td:nth-child(6){grid-area:m!important;text-align:right!important}.top5-card[data-top5-compact="1"] .strategy-sector-badge{min-height:22px;padding:3px 6px;font-size:9px}.top5-card[data-top5-compact="1"] .bank,.top5-card[data-top5-compact="1"] .product{display:block!important;margin:0!important}.top5-card[data-top5-compact="1"] .sourcehint{max-width:100%!important}.top5-card[data-top5-compact="1"] .our-position-note{display:block!important;margin:3px 0 0!important}.top5-card[data-top5-compact="1"] .our-position-row td{padding:0!important}}
</style>
""".strip()

_SCRIPT = r'''
<script id="strategy-top5-compact-script">
(()=>{
  "use strict";
  const HEAD_CLASS="strategy-sector-head";
  const CELL_CLASS="strategy-sector-cell";
  function addHeader(card){
    const row=card?.querySelector("thead tr"),first=row?.querySelector("th");if(!row||!first)return;
    if(row.querySelector(`.${HEAD_CLASS}`))return;
    const th=document.createElement("th");th.className=HEAD_CLASS;th.scope="col";th.textContent="업권";first.insertAdjacentElement("afterend",th);
  }
  function addSectorCell(row,sector){
    if(!row||row.querySelector(`.${CELL_CLASS}`))return;
    const first=row.querySelector("td");if(!first)return;
    const td=document.createElement("td");td.className=CELL_CLASS;
    const badge=document.createElement("span");badge.className="strategy-sector-badge";badge.dataset.sector=sector||"unknown";badge.textContent=sectorLabel(sector||"")||"—";
    td.appendChild(badge);first.insertAdjacentElement("afterend",td);
  }
  function fixEmptyRow(row){
    if(!row||row.querySelector(`.${CELL_CLASS}`)||row.querySelector(".rank,.our-rank"))return false;
    const cell=row.querySelector("td[colspan]");if(!cell)return false;cell.colSpan=6;return true;
  }
  function decorate(){
    const card=document.querySelector(".top5-card"),body=document.getElementById("top5");if(!card||!body)return;
    card.dataset.top5Compact="1";addHeader(card);
    const top=products12.slice(0,5),own=products12.find(product=>product.institution===OUR_INSTITUTION)||null;
    const rows=[...body.querySelectorAll(":scope > tr")];
    let marketIndex=0;
    for(const row of rows){
      if(fixEmptyRow(row))continue;
      if(row.querySelector(".rank")){
        const product=top[marketIndex++];if(product)addSectorCell(row,product.sector);continue;
      }
      if(row.querySelector(".our-rank")&&own)addSectorCell(row,own.sector);
    }
  }
  const priorRenderMarket=renderMarket;
  renderMarket=function(){priorRenderMarket();decorate()};
  decorate();
})();
</script>
'''.strip("\n")


def inject_strategy_top5_compact(html: str) -> str:
    """Strategy TOP5 표에 업권 열과 compact presentation을 합성한다."""
    if STYLE_MARKER in html and SCRIPT_MARKER in html:
        return html
    if STYLE_MARKER in html or SCRIPT_MARKER in html:
        raise DashboardBuildError("Strategy TOP5 compact 주입 상태가 불완전하다")
    if 'id="market-scope"' not in html:
        return html
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy TOP5 compact 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _STYLE + "\n</head>", 1)
    return rendered.replace("</body>", _SCRIPT + "\n</body>", 1)
