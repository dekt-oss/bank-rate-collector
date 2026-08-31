"""Strategy 모바일 레이아웃의 최종 반응형 안전장치.

기존 계산·데이터·그래프 좌표 산식은 바꾸지 않는다. 여러 presentation이 순차
주입되며 생기는 late CSS 최소폭 충돌만 마지막 레이어에서 해소한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-mobile-responsive-style"'
SCRIPT_MARKER = 'id="strategy-mobile-responsive-script"'

_CSS = r"""
<style id="strategy-mobile-responsive-style">
@media(max-width:760px){
  .workspace-decision,.workspace-decision .sim,.workspace-decision .simform,
  .workspace-decision .prediction-panel,.workspace-decision .workspace-model-detail,
  .workspace-decision .workspace-model-detail-body,.workspace-decision .decision-sensitivity,
  .workspace-decision .decision-sensitivity-grid,.workspace-decision .predict-inputs,
  .workspace-decision .prediction-results,.workspace-decision .rate-response-wrap,
  .workspace-decision .tablewrap{min-width:0;max-width:100%}
  .workspace-decision .simform>*{min-width:0;max-width:100%}
  .workspace-decision .simrow{grid-template-columns:minmax(0,82px) minmax(0,72px) minmax(0,1fr)}
  .workspace-decision .simrow>*{min-width:0;max-width:100%}
  .workspace-decision input[type="range"]{min-width:0;width:100%}
  .workspace-decision table{min-width:0!important;max-width:100%}

  .market-flow .chartcard,.market-flow .chartwrap{min-width:0;max-width:100%}
  .market-flow .chartwrap{overflow:hidden}
  #trend-chart{display:block;width:100%!important;max-width:100%!important;min-width:0!important;height:100%!important}

  .pref-intel-main{min-width:0;max-width:100%;overflow:hidden!important}
  .pref-intel-table{width:100%!important;min-width:0!important;max-width:100%;display:block}
  .pref-intel-table thead{display:none}
  .pref-intel-table tbody{display:grid;gap:7px;padding:8px}
  .pref-intel-table tr{display:grid!important;grid-template-columns:1fr!important;gap:4px;padding:9px 10px;border:1px solid var(--line);border-radius:9px;background:var(--panel2,#FCFAFC)}
  .pref-intel-table td{display:grid!important;grid-template-columns:minmax(0,1fr) auto!important;grid-area:auto!important;gap:10px;padding:2px 0!important;border:0!important;text-align:right!important;white-space:normal;overflow-wrap:anywhere}
  .pref-intel-table td::before{color:var(--muted);font-weight:650;text-align:left}
  .pref-intel-table td:nth-child(1)::before{content:"조건"}
  .pref-intel-table td:nth-child(2)::before{content:"시장 전체"}
  .pref-intel-table td:nth-child(3)::before{content:"상위금리상품"}
  .pref-intel-table td:nth-child(4)::before{content:"차이"}

  .funding-position-table-wrap{max-width:100%;max-height:none;overflow:hidden!important}
  .funding-position-table{width:100%!important;min-width:0!important;max-width:100%;display:block}
  .funding-position-table thead{display:none}
  .funding-position-table tbody{display:grid;gap:8px;padding:8px}
  .funding-position-table tr{display:grid!important;grid-template-columns:1fr!important;gap:4px;padding:10px;border:1px solid var(--line);border-radius:10px;background:var(--panel2,#FCFAFC)}
  .funding-position-table td{display:grid!important;grid-template-columns:minmax(0,1fr) auto!important;grid-area:auto!important;gap:10px;padding:3px 0!important;border:0!important;text-align:right!important;white-space:normal;min-width:0}
  .funding-position-table td::before{color:var(--soft);font:650 10px var(--sans);text-align:left}
  .funding-position-table td:nth-child(1){padding-bottom:7px!important;margin-bottom:3px;border-bottom:1px solid var(--line)!important;font-size:11px;text-align:left!important}
  .funding-position-table td:nth-child(1)::before{content:"기관"}
  .funding-position-table td:nth-child(2)::before{content:"수신잔액"}
  .funding-position-table td:nth-child(3)::before{content:"규모 위치"}
  .funding-position-table td:nth-child(4)::before{content:"6M"}
  .funding-position-table td:nth-child(5)::before{content:"6M 성장 위치"}
  .funding-position-table td:nth-child(6)::before{content:"12M"}
  .funding-position-table td:nth-child(7)::before{content:"12M 성장 위치"}
  .funding-position-table td:nth-child(8)::before{content:"업권 중앙값 대비"}
  .funding-position-table td:nth-child(9)::before{content:"Direct Peer 16 대비"}
  .funding-position-percentile{min-width:0;justify-self:end}
  .funding-position-peer{min-width:0;flex-wrap:wrap;justify-content:flex-end}
}
@media(max-width:480px){
  .workspace-decision .simrow{grid-template-columns:1fr}
  .workspace-decision .simrow .nwrap{width:min(100%,120px)}
  .workspace-decision .prediction-head,.decision-sensitivity-head{align-items:flex-start;flex-direction:column}
  .decision-trend-toggle{width:100%;justify-content:flex-start;margin-left:0;flex-wrap:wrap}
}
</style>
"""

_JS = r"""
<script id="strategy-mobile-responsive-script">
(()=>{
  "use strict";
  const install=()=>{
    const evidence=document.querySelector("details.decision-model-evidence");
    if(evidence)evidence.removeAttribute("open");
    document.documentElement.dataset.strategyMobileResponsive="v1";
  };
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_strategy_mobile_responsive(html: str) -> str:
    """Strategy에만 최종 모바일 반응형 레이어를 한 번 주입한다."""
    if 'id="market-scope"' not in html or 'id="planning-zone"' not in html:
        return html
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Strategy 모바일 반응형 주입 상태가 불완전하다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy 모바일 반응형 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
