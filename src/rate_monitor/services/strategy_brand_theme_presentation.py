# ruff: noqa: E501,I001
"""Strategy branded light-theme polish.

General dashboard의 plum/pink/violet palette를 Strategy에 재사용하되 계산·DOM 의미·
data contract는 바꾸지 않는다. 기존 light theme 위에 typography rhythm, spacing,
radius, map palette, active-state hierarchy만 추가한다.
"""

from __future__ import annotations

from rate_monitor.services.dashboard_service import DashboardBuildError
from rate_monitor.services.strategy_light_theme_presentation import (
    SCRIPT_MARKER as LIGHT_SCRIPT_MARKER,
    STYLE_MARKER as LIGHT_STYLE_MARKER,
    inject_strategy_light_theme,
)

STYLE_MARKER = 'id="strategy-brand-theme-style"'
SCRIPT_MARKER = 'id="strategy-brand-theme-script"'

_CSS = r"""
<style id="strategy-brand-theme-style">
:root{
  --bg:#F7F4F8;--panel:#FFFFFF;--panel2:#FAF7FA;--panel3:#F3EDF4;
  --ink:#251D27;--muted:#665B68;--soft:#746877;--line:rgba(91,47,100,.12);
  --green:#2E7D5B;--green2:#4E9675;--gold:#A9741A;--red:#AC4238;--cream:#F4EDF4;
  --r:14px;--shadow:0 12px 34px rgba(77,45,88,.085);
  --sans:"Pretendard Variable","Pretendard","SUIT Variable","SUIT","Wanted Sans Variable","Wanted Sans","Noto Sans KR","Apple SD Gothic Neo","Segoe UI",Arial,sans-serif;
  --mono:"Pretendard Variable","Pretendard","Inter","Segoe UI",Arial,sans-serif;
  --brand-plum:#4D2D58;--brand-plum-2:#5B2F64;--brand-violet:#734A7E;--brand-rose:#B34A77;
  --accent:#D33A7C;--accent-ink:#5B2F64;--accent-soft:#F8EAF1;--accent-line:rgba(211,58,124,.24);
}
html{background:var(--bg)}
body{color:var(--ink);font:14px/1.54 var(--sans);letter-spacing:-.014em;background:linear-gradient(180deg,#FBF9FB 0,#F7F4F8 42%,#FAF8FA 100%);font-optical-sizing:auto;font-synthesis:none;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.mono,.kvalue,.trend-summary b,.planning-strip b,.cstat b,.rate-response-table td,.node-rate{font-family:var(--mono);font-variant-numeric:tabular-nums lining-nums;font-feature-settings:"tnum" 1,"lnum" 1;font-optical-sizing:auto}

.topbar{border:0;border-radius:16px;background:radial-gradient(circle at 12% 0%,rgba(255,255,255,.16),transparent 33%),linear-gradient(130deg,#4D2D58 0%,#784060 54%,#B34A77 118%);box-shadow:0 16px 34px rgba(77,45,88,.16),inset 0 1px rgba(255,255,255,.17)}
.topbar .identity b{color:#fff}.topbar .meta{color:rgba(255,255,255,.72)}.logo{background:rgba(255,255,255,.13);color:#fff;border:1px solid rgba(255,255,255,.22);box-shadow:inset 0 1px rgba(255,255,255,.2)}
.nav{background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.10)}.nav a{color:rgba(255,255,255,.72)}.nav a.active{color:var(--accent-ink);background:#fff;box-shadow:0 2px 8px rgba(48,26,53,.16)}
.hero{padding-top:28px}.hero h1{color:var(--ink);font-size:clamp(28px,2.45vw,36px);font-weight:780;line-height:1.08;letter-spacing:-.048em;text-wrap:balance}.hero p{max-width:74ch;color:var(--muted);font-size:12px;line-height:1.62}
.meta,.ranking-basis,.head p,.planning-basis,.kfoot,.maplegend,.foot{color:var(--muted)}

.workspace-section-label{margin:24px 2px 10px}.workspace-section-label div{gap:10px}.workspace-section-label em{color:var(--accent);font-size:10px;letter-spacing:.10em}.workspace-section-label strong{color:var(--ink);font-size:13px;font-weight:760;letter-spacing:-.025em}.workspace-section-label span{color:var(--soft);font-size:10.5px;line-height:1.45}
.card,.external-context,.market-intel,.pref-intel{border:1px solid var(--line);border-radius:14px;background:#fff;box-shadow:var(--shadow)}.card:before{height:2px;background:linear-gradient(90deg,rgba(211,58,124,.38),rgba(115,74,126,.20),transparent 62%)}
.head h2,.external-context-head h2,.market-intel-head h2,.pref-intel-head h2{color:var(--ink);font-size:16px;font-weight:760;letter-spacing:-.03em}.head p,.external-context-head p,.market-intel-head p,.pref-intel-head p{color:var(--muted);font-size:11px;line-height:1.55}

.pill,.mode-tab,.map-layer-tab,.map-switch button,.sector-toggle,.market-intel-control button,.pref-intel-control button{border-color:rgba(91,47,100,.12)!important;background:#FBF9FB!important;color:#6E6270!important;border-radius:8px!important;font-weight:650!important}.pill.active,.mode-tab.active,.map-layer-tab.active,.market-intel-control button.active,.pref-intel-control button.active{color:var(--accent-ink)!important;border-color:var(--accent-line)!important;background:var(--accent-soft)!important;box-shadow:inset 0 0 0 1px rgba(211,58,124,.04)}.scope-status b{color:var(--accent-ink)}
.evidence-card{border-color:rgba(91,47,100,.10);border-radius:11px;background:#fff;box-shadow:0 6px 18px rgba(77,45,88,.05)}.evidence-card.active{border-color:var(--accent-line);background:linear-gradient(145deg,#FFF,#FCF2F7)}.evidence-head strong{color:#392A3B}.evidence-head em,.evidence-grid{color:#776B79}.evidence-grid b{color:#4C3A50}.evidence-reason{color:#896C43}.ranking-basis:before{border-color:var(--accent-line);color:#8C3F69;background:#FCF1F6}

.kpi{min-height:116px;padding:15px!important;border-color:rgba(91,47,100,.10)!important;border-radius:12px!important;background:#fff!important}.kpi.green{background:linear-gradient(145deg,#FBFDFC,#F2F8F5)!important}.kpi.gold{background:linear-gradient(145deg,#FFFCF6,#FBF4E8)!important}.kpi.teal{background:linear-gradient(145deg,#FFF,#FAF1F7)!important}.kpi.threshold{background:linear-gradient(145deg,#FCF9FC,#F3ECF5)!important}.klabel{color:#5E5061;font-size:10.5px;font-weight:660}.basis-label{border-color:rgba(211,58,124,.14);color:#8C6B80;background:#FFF9FC}.kvalue{color:#352638;font-size:clamp(30px,2.6vw,39px);font-weight:760;line-height:1.02;letter-spacing:-.055em;font-variation-settings:"wght" 760}.green .kvalue{color:#2E7D5B}.gold .kvalue{color:#96661D}.teal .kvalue{color:#A53E6D}.threshold .kvalue{color:#68406F}.badge{border-color:rgba(211,58,124,.18);color:#8F3D69;background:#FFF5F9}.delta{color:#916220}

.workspace-decision .sim{border:1px solid rgba(115,74,126,.18);border-radius:14px;background:radial-gradient(circle at 88% 3%,rgba(211,58,124,.07),transparent 27%),linear-gradient(145deg,#FFF,#FCF9FC);box-shadow:0 20px 48px rgba(77,45,88,.10)}.workspace-decision .head h2{font-size:19px;letter-spacing:-.035em}.workspace-decision .planning-strip>div,.trend-summary>div,.planning-strip>div,.cstat,.change,.prediction-panel,.model-evidence,.rate-response-wrap,.market-position-reference summary,.workspace-legacy-pref{border-color:rgba(91,47,100,.10);border-radius:10px;background:#FCFAFC;color:#443548}
.engine-summary{border-color:rgba(115,74,126,.15);background:#F7F1F8;color:#716274}.engine-toggle{border-color:var(--accent-line);background:var(--accent-soft);color:var(--accent-ink);border-radius:8px}.engine-toggle:hover,.engine-toggle:focus-visible{border-color:rgba(211,58,124,.42);background:#F5DEE9}.simrow label,.choice-title,.prediction-head b,.rate-response-head b,.model-evidence>b{color:#433246}.nwrap,.choice-box{border-color:rgba(91,47,100,.13);border-radius:9px;background:#fff}.nwrap input,.predict-inputs input{color:#322536;background:#fff}.simrow input[type="range"]{accent-color:var(--accent)}
.simresult{border-color:rgba(91,47,100,.10);border-radius:10px;background:#fff}.simresult span,.simresult small,.rate-response-head span,.rate-response-foot,.rate-response-empty{color:#776A79}.simresult b{color:#3A2B3D}.simresult b.green{color:#2E7D5B}.simresult b.gold{color:#96661D}.position{border-color:rgba(91,47,100,.10);background:#FCFAFC}.positionhead span,.scales{color:#786C7A}.positionhead b{color:#49384D}.rail{background:#E9E1EA}.marker{background:#8A758D}.marker.own{background:var(--brand-violet)}.marker.proposed{background:var(--accent)}
.rate-response-table th{border-bottom-color:rgba(91,47,100,.10);color:#756978}.rate-response-table td{border-bottom-color:rgba(91,47,100,.07);color:#443448}.rate-response-table tr.current{background:#F3F8F5}.rate-response-table tr.proposal{background:#FFF4F8}.rate-response-table .scenario-name{color:#3A2A3E}.rate-response-table .scenario-note{color:#776A79}.rate-response-table .positive{color:#2E7D5B}.rate-response-table .negative{color:#AC4238}.rate-response-table .cost{color:#96661D}

.external-context-card,.external-flow,.market-intel-direction,.market-intel-metric,.market-intel-breadth,.pref-intel-main,.pref-intel-own{border-color:rgba(91,47,100,.09)!important;border-radius:10px!important;background:#FCFAFC!important;color:#49394D!important}.external-context-badge,.market-intel-evidence{border-color:rgba(115,74,126,.18);background:#F5EFF6;color:#68406F}.external-context-note{border-top-color:rgba(91,47,100,.08);color:#776A79}.external-context-note b{color:#4D3852}.market-intel-controls,.pref-intel-controls{border-color:rgba(91,47,100,.09);border-radius:10px;background:#FBF8FB}
.market-intel-direction strong,.market-intel-metric b,.market-intel-breadth strong{color:#3E2E42}.market-intel-direction.rising strong{color:#2E7D5B}.market-intel-direction.falling strong{color:#AC4238}.market-intel-direction.mixed strong{color:#8C587F}.market-intel-bar{background:#E9E2EA}.market-intel-bar .up{background:#4E9675}.market-intel-bar .flat{background:#A596A8}.market-intel-bar .down{background:#C96B6B}.market-intel-period{color:#776A79}.market-intel-period b{color:#513B56}
.pref-intel-badge{border-color:rgba(211,58,124,.18);background:#FFF3F8;color:#98416F}.pref-intel-caveat{border-color:rgba(169,116,26,.18);background:#FFF9EC;color:#806538}.pref-intel-caveat b{color:#6E531E}.pref-intel-summary span,.pref-intel-table th{color:#746877}.pref-intel-summary b{color:#3B2B3F}.pref-intel-table td{color:#514255}.pref-intel-table td:first-child{color:#433447}.pref-intel-own h3{color:#3B2B3F}.pref-intel-own p{color:#776A79}.pref-intel-tag{border-color:rgba(211,58,124,.16);background:#FFF2F7;color:#8F3D69}.pref-intel-raw div{background:#FBF8FB;color:#706373}

/* Readability floor for dense analytical microcopy. */
.external-context-card span,.external-context-card small,.external-flow span,.external-flow small,.market-intel-control>span,.market-intel-control button,.pref-intel-control>span,.pref-intel-control button,.market-intel-direction span,.market-intel-direction small,.market-intel-metric span,.market-intel-metric small,.market-intel-breadth,.market-intel-period,.pref-intel-caveat,.pref-intel-warning,.pref-intel-summary span,.pref-intel-table th,.pref-intel-table td,.pref-intel-own p,.pref-intel-tag,.pref-intel-raw summary,.pref-intel-raw div,.rate-response-head span,.rate-response-table th,.rate-response-table td,.rate-response-table .scenario-name,.rate-response-table .scenario-note,.rate-response-foot,.workspace-model-detail>summary,.workspace-legacy-pref>summary{font-size:10.5px!important;line-height:1.48}

.mapcard{background:#fff}.mapstage{border-color:rgba(91,47,100,.09);background:radial-gradient(circle at 50% 45%,rgba(211,58,124,.045),transparent 43%),#FCFAFC}.land,.island{fill:#EFE7F0!important;stroke:#C8BAC9!important;stroke-width:1.15px!important}.node-line{stroke:rgba(115,74,126,.22)}.node-ring{fill:rgba(115,74,126,.08);stroke:rgba(115,74,126,.60)}.node-core{fill:#734A7E}.node.top .node-ring{stroke:rgba(211,58,124,.72)}.node.top .node-core{fill:#D33A7C}.node.busan .node-ring{stroke:#B34A77}.node.busan .node-core{fill:#B34A77}.node-label{fill:#49384D!important;stroke:#FCFAFC!important}.node-rate{fill:#734A7E!important;stroke:#FCFAFC!important}.node.top .node-rate{fill:#C83375!important}.map-mode-label{border-color:rgba(91,47,100,.10);background:rgba(255,255,255,.92);color:#726575}.busan-water{fill:#F5EEF6}.busan-district{fill:#F1EAF2;stroke:#C8BAC9}.busan-district.has-data{fill:rgba(179,74,119,var(--district-alpha,.28));stroke:rgba(115,74,126,.55)}.busan-district.top{fill:rgba(211,58,124,.46);stroke:rgba(211,58,124,.72)}
.tablewrap table{color:#4A3A4E}th{color:#756978}td{border-color:rgba(91,47,100,.07)}tbody tr:hover{background:#FFF7FA}.product b{color:#3B2C3F}.product span{color:#7E7080}.chartwrap{background:linear-gradient(180deg,#FFFEFF,#FBF8FB)}

@media(max-width:760px){body{font-size:13.5px}.topbar{border-radius:14px}.hero{padding-top:22px}.hero h1{font-size:30px}.hero p{font-size:11.5px}.kpi{min-height:106px;padding:13px!important}.kvalue{font-size:31px}.workspace-decision .sim{padding:15px}.workspace-section-label{margin-top:20px}.external-context-card,.external-flow{flex-basis:min(80vw,270px)}}
</style>
"""

_JS = r"""
<script id="strategy-brand-theme-script">
(()=>{
  "use strict";
  const install=()=>{
    document.documentElement.dataset.strategyPalette="main-brand-v2";
    document.documentElement.dataset.strategyTypography="variable-ui-v2";
  };
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install();
})();
</script>
"""


def inject_strategy_brand_theme(html: str) -> str:
    """기존 Strategy light theme 위에 브랜드/typography polish를 한 번만 합성한다."""
    rendered = inject_strategy_light_theme(html)
    has_style = STYLE_MARKER in rendered
    has_script = SCRIPT_MARKER in rendered
    if has_style and has_script:
        return rendered
    if has_style != has_script:
        raise DashboardBuildError("Strategy Brand Theme 주입 상태가 불완전하다")
    if LIGHT_STYLE_MARKER not in rendered or LIGHT_SCRIPT_MARKER not in rendered:
        raise DashboardBuildError("Strategy Light Theme 이후에만 Brand Theme를 적용할 수 있다")
    if "</head>" not in rendered or "</body>" not in rendered:
        raise DashboardBuildError("Strategy Brand Theme 주입 위치를 찾지 못했다")
    rendered = rendered.replace("</head>", _CSS + "\n</head>", 1)
    return rendered.replace("</body>", _JS + "\n</body>", 1)
