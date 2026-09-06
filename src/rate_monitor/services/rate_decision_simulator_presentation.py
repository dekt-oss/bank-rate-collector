# ruff: noqa: E501
"""Strategy Rate Decision Simulator v1 presentation wiring.

이 모듈은 기존 Public Structural v2 browser engine이 주입된 뒤 bounded
forward-candidate simulator UI와 독립 Size Peer read-model surface만 추가한다.
새 예측모형, interpolation, extrapolation 또는 규모 peer 추정은 수행하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from rate_monitor.services.dashboard_service import DashboardBuildError

STYLE_MARKER = 'id="rate-decision-simulator-v1-style"'
SCRIPT_MARKER = 'id="rate-decision-simulator-v1-bundle"'
PUBLIC_ENGINE_MARKER = 'id="public-structural-v2-engine-bundle"'
PUBLIC_SCRIPT_MARKER = 'id="public-structural-v2-cockpit-script"'

_RUNTIME_FILES = (
    "target_candidate.js",
    "rate_decision_simulator.js",
)

_CSS = r"""
<style id="rate-decision-simulator-v1-style">
.strategy-rate-decision-simulator{display:grid;gap:12px;margin:12px 0 2px;padding:14px;border:1px solid rgba(91,47,100,.14);border-radius:15px;background:linear-gradient(145deg,#fff,#fbf8fb);box-shadow:0 8px 24px rgba(77,45,88,.05);color:#3f3043;min-width:0;max-width:100%}
.strategy-rate-decision-simulator *{box-sizing:border-box}.rds-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.rds-head h3{margin:0;color:#39273e;font-size:15px;letter-spacing:-.025em}.rds-head p{margin:4px 0 0;color:#746477;font-size:10.5px;line-height:1.5}.rds-safety{flex:none;padding:5px 8px;border:1px solid rgba(169,116,26,.18);border-radius:999px;background:#fff8e9;color:#8d6119;font-size:10px;font-weight:800}
.rds-tabs,.rds-enrollment{display:inline-flex;width:max-content;max-width:100%;gap:3px;padding:3px;border:1px solid rgba(91,47,100,.10);border-radius:10px;background:#f6f2f6}.rds-tab,.rds-choice{appearance:none;border:0;border-radius:7px;background:transparent;color:#725f75;padding:7px 11px;font:760 10.5px var(--sans);cursor:pointer;white-space:nowrap}.rds-tab.active,.rds-choice.active{background:#fff;color:#5b2f64;box-shadow:0 1px 6px rgba(77,45,88,.10)}.rds-tab:focus-visible,.rds-choice:focus-visible{outline:2px solid rgba(91,47,100,.35);outline-offset:1px}
.rds-controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.rds-controls label{display:flex;align-items:center;gap:6px;color:#67566b;font-size:10.5px;font-weight:760}.rds-controls input{width:118px;padding:8px 9px;border:1px solid rgba(91,47,100,.16);border-radius:9px;background:#fff;color:#3f3043;font:760 12px var(--mono);outline:none}.rds-controls input:focus{border-color:rgba(91,47,100,.42);box-shadow:0 0 0 3px rgba(91,47,100,.08)}
.rds-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.rds-metrics>div{min-width:0;padding:11px;border:1px solid rgba(91,47,100,.09);border-radius:11px;background:#fff}.rds-metrics span{display:block;color:#79697c;font-size:9.5px}.rds-metrics b{display:block;margin-top:5px;color:#38283d;font:820 16px/1.1 var(--mono)}.rds-metrics small{display:block;margin-top:4px;color:#78697b;font-size:9px;line-height:1.45}
.rds-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.rds-grid section{min-width:0;padding:11px;border:1px solid rgba(91,47,100,.09);border-radius:11px;background:#fff}.rds-grid h4{margin:0 0 8px;color:#4b394f;font-size:10.5px}.rds-grid h4 small,.rds-size-peer-head h4 small{color:#8b7a8e;font-size:8.5px;font-weight:700}.rds-table-wrap{max-width:100%;overflow:auto;border:1px solid rgba(91,47,100,.07);border-radius:9px}.rds-table{width:100%;min-width:570px;border-collapse:collapse}.rds-table th{padding:7px 8px;border-bottom:1px solid rgba(91,47,100,.08);background:#faf8fa;color:#746477;font-size:9px;text-align:right;white-space:nowrap}.rds-table th:first-child,.rds-table td:first-child{text-align:left}.rds-table td{padding:8px;border-bottom:1px solid rgba(91,47,100,.055);color:#514154;font-size:9px;text-align:right;white-space:nowrap}.rds-table tbody tr:last-child td{border-bottom:0}.rds-empty{padding:12px;border:1px dashed rgba(91,47,100,.14);border-radius:9px;background:#fcfafc;color:#78697b;font-size:9.5px;line-height:1.5;text-align:center}
.rds-size-peer-section{min-width:0;padding:12px;border:1px solid rgba(91,47,100,.11);border-radius:12px;background:#fff}.rds-size-peer-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:9px}.rds-size-peer-head h4{margin:0;color:#453248;font-size:11.5px}.rds-size-peer-head p{max-width:720px;margin:4px 0 0;color:#7a6a7d;font-size:9.5px;line-height:1.5}.rds-size-peer-meta{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:7px}.rds-size-peer-meta span{display:inline-flex;align-items:center;min-height:22px;padding:4px 7px;border:1px solid rgba(91,47,100,.09);border-radius:999px;background:#faf8fa;color:#67566b;font-size:8.8px;font-weight:720}.rds-size-peer-count{margin:0 0 7px;color:#88798a;font-size:8.6px;line-height:1.45}.rds-size-peer-table{min-width:760px}.rds-size-peer-table th:first-child,.rds-size-peer-table td:first-child{text-align:center}.rds-size-peer-table th:nth-child(2),.rds-size-peer-table td:nth-child(2){text-align:left}.rds-size-peer-table td{vertical-align:middle}.rds-size-similarity b{display:block;color:#4f3c53;font:800 9.2px/1.2 var(--sans)}.rds-size-similarity small{display:block;margin-top:3px;color:#877789;font-size:8.2px}
.rds-evidence{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.rds-evidence>div{padding:9px 10px;border:1px solid rgba(91,47,100,.08);border-radius:9px;background:#fcfafc}.rds-evidence b{display:block;color:#5d4a61;font-size:9.5px}.rds-evidence span{display:block;margin-top:3px;color:#817184;font-size:9px;line-height:1.45}.rds-details{border-top:1px solid rgba(91,47,100,.08);padding-top:8px}.rds-details>summary{cursor:pointer;color:#756478;font-size:9.5px;font-weight:760}.rds-details[open]>summary{margin-bottom:8px}.rds-details #public-structural-v2-cockpit{margin-top:8px}
@media(max-width:900px){.rds-metrics{grid-template-columns:1fr 1fr}.rds-grid{grid-template-columns:1fr}.rds-evidence{grid-template-columns:1fr}.rds-size-peer-head{align-items:stretch;flex-direction:column}.rds-enrollment{width:100%;display:grid;grid-template-columns:1fr 1fr}}
@media(max-width:620px){.strategy-rate-decision-simulator{padding:10px}.rds-head{display:block}.rds-safety{display:inline-block;margin-top:7px}.rds-tabs{display:grid;grid-template-columns:1fr 1fr;width:100%}.rds-metrics{grid-template-columns:1fr}.rds-controls label{width:100%;justify-content:space-between}.rds-controls input{width:132px}.rds-size-peer-section{padding:10px}.rds-size-peer-meta{display:grid;grid-template-columns:1fr}.rds-size-peer-meta span{width:100%;border-radius:8px}.rds-size-peer-wrap{overflow:visible;border:0}.rds-size-peer-table,.rds-size-peer-table tbody,.rds-size-peer-table tr,.rds-size-peer-table td{display:block;width:100%;min-width:0}.rds-size-peer-table thead{display:none}.rds-size-peer-table tbody{display:grid;gap:7px}.rds-size-peer-table tr{padding:8px 9px;border:1px solid rgba(91,47,100,.09);border-radius:10px;background:#fcfafc;overflow:hidden}.rds-size-peer-table td{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:5px 0;border:0!important;text-align:right!important;white-space:normal;overflow-wrap:anywhere}.rds-size-peer-table td::before{content:attr(data-label);flex:0 0 76px;color:#88798a;font-size:8.5px;text-align:left}.rds-size-peer-table td>b,.rds-size-peer-table .rds-size-similarity>span{min-width:0}.rds-size-similarity b,.rds-size-similarity small{text-align:right}.rds-size-peer-table td[data-label="기관"] b{font-size:9.5px}.rds-size-peer-count{font-size:8.4px}}
</style>
"""


def _runtime_bundle() -> str:
    root = Path(__file__).resolve().parents[3] / "web" / "public-structural-v2"
    sources: list[str] = []
    for name in _RUNTIME_FILES:
        path = root / name
        if not path.exists():
            raise DashboardBuildError(f"Rate Decision Simulator browser runtime이 없다: {path}")
        source = path.read_text(encoding="utf-8")
        if "</script" in source.lower():
            raise DashboardBuildError(f"browser runtime에 script 종료 marker가 있다: {name}")
        sources.append(source)
    return '<script id="rate-decision-simulator-v1-bundle">\n' + "\n".join(sources) + "\n</script>"


def inject_rate_decision_simulator(html: str) -> str:
    """Public Structural v2 뒤에 Strategy Rate Decision Simulator v1을 주입한다."""
    states = (STYLE_MARKER in html, SCRIPT_MARKER in html)
    if all(states):
        return html
    if any(states):
        raise DashboardBuildError("Rate Decision Simulator v1 주입 상태가 불완전하다")
    required = (
        PUBLIC_ENGINE_MARKER,
        PUBLIC_SCRIPT_MARKER,
        'id="prediction-panel"',
        'id="rate-monitor-data"',
        'id="term-segment"',
    )
    missing = [marker for marker in required if marker not in html]
    if missing:
        raise DashboardBuildError(
            "Rate Decision Simulator v1 선행 계약이 없다: " + ", ".join(missing)
        )
    if "</head>" not in html or "</body>" not in html:
        raise DashboardBuildError("Rate Decision Simulator v1 주입 위치를 찾지 못했다")
    rendered = html.replace("</head>", _CSS + "\n</head>", 1)
    rendered = rendered.replace("</body>", _runtime_bundle() + "\n</body>", 1)
    return rendered
