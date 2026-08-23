"""Stage H browser forecast provider adapter를 Cockpit 실행 직전에 주입한다.

기존 Stage F Cockpit presentation을 재작성하지 않고 engine bundle이 로드된 뒤,
Cockpit orchestration이 실행되기 전에 provider validator와 compatibility bridge를
삽입한다. 현재 structural provider는 기존 수치를 유지하고 future async provider는
``resolveForecast`` public contract를 재사용할 수 있다.
"""

from __future__ import annotations

from pathlib import Path

from rate_monitor.services.dashboard_service import DashboardBuildError

ENGINE_MARKER = 'id="public-structural-v2-forecast-provider-engine"'
BRIDGE_MARKER = 'id="public-structural-v2-forecast-provider-bridge"'
_COCKPIT_SCRIPT_START = '<script id="public-structural-v2-cockpit-script">'

_BRIDGE = r"""
<script id="public-structural-v2-forecast-provider-bridge">
(()=>{
  "use strict";
  const surfaceApi=globalThis.PublicStructuralV2Surface;
  const providerApi=globalThis.PublicStructuralV2ForecastProvider;
  if(!surfaceApi||typeof surfaceApi.buildSurfaceFrame!=="function"||
     typeof surfaceApi.attachForecast!=="function"){
    throw new Error("forecast_provider_bridge:surface_api_missing");
  }
  if(!providerApi||typeof providerApi.createStructuralProvider!=="function"||
     typeof providerApi.validatePublicForecast!=="function"){
    throw new Error("forecast_provider_bridge:provider_api_missing");
  }

  surfaceApi.buildSurface=function(
    args,marketApi,marketConfig,decisionApi,inflowApi,inflowConfig
  ){
    const frame=surfaceApi.buildSurfaceFrame(args,marketApi,marketConfig,decisionApi);
    const candidateRates=(frame.market_positions||[]).map(row=>row.proposal_rate);
    const request={
      generated_at:args.generated_at,
      candidate_rates:candidateRates,
      baseline_new_money:args.baseline_new_money,
      maturity_amount:args.maturity_amount,
      current_rollover_rate_pct:args.current_rollover_rate_pct,
      current_own_rate:args.current_own_rate,
      term_months:args.term_months
    };
    const provider=providerApi.createStructuralProvider(
      decisionApi,inflowApi,inflowConfig
    );
    const forecast=providerApi.validatePublicForecast(provider(request),request);
    return surfaceApi.attachForecast(frame,forecast);
  };
})();
</script>
""".strip()


def _engine_script() -> str:
    path = Path(__file__).resolve().parents[3] / "web" / "public-structural-v2" / "forecast_provider.js"
    if not path.exists():
        raise DashboardBuildError(f"Public Structural v2 provider engine이 없다: {path}")
    source = path.read_text(encoding="utf-8")
    if "</script" in source.lower():
        raise DashboardBuildError("forecast provider engine에 script 종료 marker가 있다")
    return f'<script id="public-structural-v2-forecast-provider-engine">\n{source}\n</script>'


def inject_public_structural_v2_forecast_provider(html: str) -> str:
    """Cockpit 실행 전 provider engine + bridge를 fail-closed 주입한다."""
    states = (ENGINE_MARKER in html, BRIDGE_MARKER in html)
    if all(states):
        return html
    if any(states):
        raise DashboardBuildError("Public Structural v2 provider adapter 주입 상태가 불완전하다")
    required = (
        'id="public-structural-v2-engine-bundle"',
        'id="public-structural-v2-cockpit-script"',
    )
    missing = [marker for marker in required if marker not in html]
    if missing:
        raise DashboardBuildError(
            "Public Structural v2 provider adapter 선행 계약이 없다: " + ", ".join(missing)
        )
    injected = _engine_script() + "\n" + _BRIDGE + "\n" + _COCKPIT_SCRIPT_START
    return html.replace(_COCKPIT_SCRIPT_START, injected, 1)
