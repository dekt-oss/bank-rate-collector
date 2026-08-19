# ruff: noqa: E501
"""Strategy decision workspace 전용 light theme presentation.

계산·DOM 의미·data contract는 바꾸지 않고 색상, typography, surface hierarchy만
재정의한다. 외부 font 파일/CDN에 의존하지 않으며 Pretendard를 우선 사용하고
설치되지 않은 환경에서는 한국어 시스템 sans-serif로 안전하게 fallback한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="strategy-light-theme-style"'
SCRIPT_MARKER = 'id="strategy-light-theme-script"'

_CSS = r"""
<style id="strategy-light-theme-style">
:root{
  color-scheme:light;
  --bg:#eef2f5;--panel:#ffffff;--panel2:#f7f9fb;--panel3:#f1f5f7;
  --ink:#17232d;--muted:#5f6f7b;--soft:#7c8a95;--line:rgba(42,61,78,.10);
  --green:#2f7d65;--green2:#4b957d;--gold:#9a6b25;--red:#b75555;--cream:#e8edf1;
  --r:18px;--shadow:0 12px 34px rgba(35,55,72,.08);
  --sans:"Pretendard Variable","Pretendard","Noto Sans KR","Apple SD Gothic Neo","Segoe UI",Arial,sans-serif;
  --mono:"Inter","Pretendard Variable","Pretendard","Segoe UI",Arial,sans-serif;
  --accent:#4f6f9f;--accent-soft:#edf2f9;--accent-line:rgba(79,111,159,.24);
}
html{background:var(--bg)}
body{color:var(--ink);font:14.5px/1.58 var(--sans);letter-spacing:-.012em;background:linear-gradient(180deg,#f5f7f9 0,#eef2f5 42%,#f4f6f8 100%);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.mono,.kvalue,.trend-summary b,.planning-strip b,.cstat b,.rate-response-table td,.node-rate{font-family:var(--mono);font-variant-numeric:tabular-nums lining-nums;font-feature-settings:"tnum" 1,"lnum" 1;letter-spacing:-.025em}
.topbar{border-color:rgba(42,61,78,.09);background:rgba(255,255,255,.91);box-shadow:0 8px 26px rgba(35,55,72,.08);backdrop-filter:blur(18px)}
.logo{background:linear-gradient(145deg,#e8eef7,#cfdae9);color:#294664;box-shadow:inset 0 1px rgba(255,255,255,.8)}
.identity b,.hero h1,.head h2,.workspace-section-label strong{color:#182833}
.nav{background:#f1f4f7}.nav a{color:#74838e}.nav a.active{color:#294f78;background:#fff;box-shadow:0 1px 4px rgba(35,55,72,.08),inset 0 0 0 1px rgba(79,111,159,.14)}
.meta,.hero p,.ranking-basis,.head p,.planning-basis,.kfoot,.maplegend,.foot{color:#687985}.statusdot{background:#4f9a7b;box-shadow:0 0 0 4px rgba(79,154,123,.10)}
.pill{border-color:rgba(42,61,78,.09);background:rgba(255,255,255,.72);color:#6c7c87}.pill.active{color:#315d87;border-color:var(--accent-line);background:var(--accent-soft)}
.market-scope{border:1px solid rgba(42,61,78,.08);background:#fff;box-shadow:0 8px 24px rgba(35,55,72,.05)}
.mode-tab,.map-layer-tab,.map-switch button{border-color:rgba(42,61,78,.10);background:#f7f9fb;color:#657785}.mode-tab.active,.map-layer-tab.active{color:#315d87;border-color:var(--accent-line);background:var(--accent-soft)}
.sector-toggle{border-color:rgba(42,61,78,.09);background:#f8fafb;color:#61727e}.scope-status{color:#6b7d88}.scope-status b{color:#315d87}
.evidence-card{border-color:rgba(42,61,78,.08);background:#fff;box-shadow:0 7px 20px rgba(35,55,72,.05)}.evidence-card.active{border-color:var(--accent-line);background:linear-gradient(145deg,#f9fbfe,#edf3f9)}.evidence-head strong{color:#22333f}.evidence-head em,.evidence-grid{color:#6c7d88}.evidence-grid b{color:#425563}.evidence-reason{color:#876f48}
.ranking-basis:before{border-color:var(--accent-line);color:#52749a;background:#f6f9fc}
.scope-warning,.rate-response-caveat{border-color:rgba(180,132,55,.22);background:#fff8ea;color:#856a38}.rate-response-caveat b{color:#72551f}
.error{border-color:rgba(183,85,85,.22);background:#fff2f2;color:#9b4343}
.card{border-color:rgba(42,61,78,.09);background:#fff;box-shadow:var(--shadow)}.card:before{background:linear-gradient(90deg,rgba(255,255,255,.9),transparent)}
.kpi{border-color:rgba(42,61,78,.08)!important;background:#fff!important}.kpi.green{background:linear-gradient(145deg,#f8fcfa,#eef7f3)!important}.kpi.gold{background:linear-gradient(145deg,#fffaf2,#f8f2e7)!important}.kpi.teal{background:linear-gradient(145deg,#f7fbfc,#edf5f6)!important}.kpi.threshold{background:linear-gradient(145deg,#f8fafc,#eef3f7)!important}
.klabel{color:#465965}.basis-label{border-color:rgba(79,111,159,.17);color:#678099;background:rgba(255,255,255,.64)}.kvalue{color:#263946}.green .kvalue{color:#2f7d65}.gold .kvalue{color:#946521}.teal .kvalue{color:#3f7c78}.badge{border-color:rgba(154,107,37,.23);color:#8b611f;background:#fff9ef}.delta{color:#92631e}
.chip,.external-context-badge{border-color:rgba(42,61,78,.09);background:#f5f7f9;color:#61727e}
.workspace-decision .sim{border-color:var(--accent-line);background:linear-gradient(145deg,#ffffff,#f5f8fb);box-shadow:0 18px 44px rgba(44,67,88,.10)}
.workspace-decision .planning-strip>div,.trend-summary>div,.planning-strip>div,.cstat,.change,.prediction-panel,.model-evidence,.rate-response-wrap,.market-position-reference summary,.workspace-legacy-pref{border-color:rgba(42,61,78,.09);background:#f8fafb;color:#344754}
.workspace-section-label em{color:#6682a2}.workspace-section-label span{color:#788892}
.engine-summary{border-color:rgba(79,111,159,.14);background:#f2f6fb;color:#657b8f}.engine-toggle{border-color:var(--accent-line);background:#eef3f9;color:#355d84}.engine-toggle:hover,.engine-toggle:focus-visible{border-color:rgba(79,111,159,.42);background:#e5edf6}
.simrow label,.choice-title,.prediction-head b,.rate-response-head b,.model-evidence>b{color:#2c3f4c}.nwrap,.choice-box{border-color:rgba(42,61,78,.11);background:#fff}.nwrap input,.predict-inputs input{color:#1f313d;background:#fff}.simrow input[type="range"]{accent-color:var(--accent)}
.simresult{border-color:rgba(42,61,78,.09);background:#fff}.simresult span,.simresult small,.rate-response-head span,.rate-response-foot,.rate-response-empty{color:#6a7b86}.simresult b{color:#253844}.simresult b.green{color:#2f7d65}.simresult b.gold{color:#946521}
.position{border-color:rgba(42,61,78,.09);background:#f8fafb}.positionhead span,.scales{color:#6c7d88}.positionhead b{color:#314653}.rail{background:#dfe6eb}.marker{background:#71879a}.marker.own{background:#2f7d65}.marker.proposed{background:#9a6b25}
.rate-response-table th{border-bottom-color:rgba(42,61,78,.10);color:#687985}.rate-response-table td{border-bottom-color:rgba(42,61,78,.07);color:#314653}.rate-response-table tr.current{background:#f1f7f4}.rate-response-table tr.proposal{background:#fff8ed}.rate-response-table .scenario-name{color:#263946}.rate-response-table .scenario-note{color:#7a8993}.rate-response-table .positive{color:#2f7d65}.rate-response-table .negative{color:#b75555}.rate-response-table .cost{color:#946521}
.market-position-reference summary,.workspace-legacy-pref>summary{color:#5f7280}.market-position-reference summary:after,.workspace-legacy-pref>summary:after{color:#718590}
.mapcard{background:linear-gradient(150deg,#f8fafb,#eef3f5)}.mapstage{border-color:rgba(42,61,78,.08);background:radial-gradient(circle at 50% 46%,rgba(79,111,159,.05),transparent 42%),#f6f8fa}.land,.island{stroke:rgba(73,101,121,.28)}.node-line{stroke:rgba(61,108,91,.26)}.node-ring{fill:rgba(47,125,101,.08);stroke:rgba(47,125,101,.62)}.node-core{fill:#3e8e72}.node.top .node-ring{stroke:rgba(154,107,37,.76)}.node.top .node-core{fill:#aa782c}.node.busan .node-ring{stroke:#9a6b25}.node.busan .node-core{fill:#b8812d}.node-label{fill:#314653!important;stroke:#f7f9fa!important;stroke-width:4px!important}.node-rate{fill:#2f7d65!important;stroke:#f7f9fa!important;stroke-width:4px!important}.node.top .node-rate{fill:#946521!important}.map-mode-label{border-color:rgba(42,61,78,.09);background:rgba(255,255,255,.88);color:#637681}.busan-water{fill:#e9f1f4}.busan-district{fill:#eef3f1;stroke:rgba(73,101,121,.30)}.busan-district.has-data{fill:rgba(76,151,120,var(--district-alpha,.34));stroke:rgba(47,125,101,.62)}.busan-district.top{fill:rgba(190,143,67,.50);stroke:rgba(154,107,37,.72)}
.tablewrap table{color:#314653}th{color:#6b7c87}td{border-color:rgba(42,61,78,.07)}tbody tr:hover{background:#f6f9fb}.product b{color:#263946}.product span{color:#72838e}
.chartcard,.insightcard,.preference-card{background:#fff}.chartwrap{background:linear-gradient(180deg,#fbfcfd,#f7f9fb)}.insight,.pref-intel-card,.market-intel-card,.external-context-card,.external-flow{border-color:rgba(42,61,78,.09)!important;background:#f8fafb!important;color:#344754!important}.insight b,.pref-intel-card b,.market-intel-card b,.external-context-card b,.external-flow b{color:#253844!important}.insight p,.insight small,.pref-intel-card p,.market-intel-card p,.external-context-card p,.external-flow p{color:#6b7d88!important}
.market-intel-control button,.pref-intel-control button{border-color:rgba(42,61,78,.10)!important;background:#f7f9fb!important;color:#657784!important}.market-intel-control button.active,.pref-intel-control button.active{border-color:var(--accent-line)!important;background:var(--accent-soft)!important;color:#315d87!important}
.changes summary{color:#344754}.changehead b{color:#30434f}.change span,.change small,.changestats span{color:#71828d}.change-direction{border-color:rgba(42,61,78,.09);background:#f8fafb}.change-balance{background:#e1e7eb}.change-balance i.up{background:#c66b6b}.change-balance i.down{background:#4f9b7c}
.prediction-explain{border-color:rgba(79,111,159,.13);background:#f2f6fb}.prediction-explain b{color:#2d4b66}.prediction-explain p,.model-evidence span{color:#657783}.model-evidence strong{color:#334956}.model-evidence a{color:#3f6992;border-bottom-color:rgba(63,105,146,.22)}.model-evidence .assumption-source{color:#8d6a32}
.empty{border-color:rgba(42,61,78,.12);color:#71828c;background:#fafbfc}
@media(max-width:760px){body{font-size:14px}.topbar{background:rgba(255,255,255,.95)}tbody tr{border-color:rgba(42,61,78,.09);background:#fff}.external-context-rates,.external-context-flows{scrollbar-color:#cbd5dc transparent}}
</style>
"""

_JS = r"""
<script id="strategy-light-theme-script">
(()=>{
  "use strict";
  const install=()=>{document.documentElement.dataset.strategyTheme="light-v1";};
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_strategy_light_theme(html: str) -> str:
    """Strategy HTML에 light theme를 한 번만 합성한다."""
    has_style = STYLE_MARKER in html
    has_script = SCRIPT_MARKER in html
    if has_style and has_script:
        return html
    if has_style != has_script:
        raise DashboardBuildError("Strategy Light Theme 주입 상태가 불완전하다")
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Strategy Light Theme 주입 위치를 찾지 못했다")
    if 'id="strategy-workspace-style"' not in html:
        raise DashboardBuildError("Strategy Workspace 이후에만 Light Theme를 적용할 수 있다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
