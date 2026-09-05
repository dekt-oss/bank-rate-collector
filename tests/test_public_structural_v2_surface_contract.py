from __future__ import annotations

import json
import subprocess


def run_node(script: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_build_surface_composes_frame_forecast_and_matching_rate_axis() -> None:
    result = run_node(
        r"""
const surface = require('./web/public-structural-v2/surface.js');
const marketApi = {
  marketPosition(args) {
    return {
      proposal_rate: Number(args.proposal_rate),
      top25_cutoff: 3.40,
      top10_cutoff: 3.50,
      market_max_rate: 3.60
    };
  }
};
const decisionApi = {
  buildCandidateRateSets() {
    return {
      economics_grid: [3.40, 3.45, 3.50],
      proposal_rate: 3.47
    };
  },
  buildPublicForecast(args) {
    return {
      status: 'ready',
      scenarios: args.candidate_rates.map(rate => ({
        rate_pct: rate,
        predicted_total: rate * 100
      }))
    };
  }
};
const result = surface.buildSurface({
  generated_at: '2026-09-05T00:00:00Z',
  market_rows: [{product_id: 'ours', rate: 3.45}],
  anchor_product_id: 'ours',
  current_own_rate: 3.45,
  proposal_rate: 3.47,
  economics_min_rate: 3.40,
  economics_max_rate: 3.50,
  baseline_new_money: 100,
  maturity_amount: 200,
  current_rollover_rate_pct: 70,
  term_months: 12
}, marketApi, {}, decisionApi, {}, {});
process.stdout.write(JSON.stringify({
  exported: typeof surface.buildSurface,
  rates: result.market_positions.map(row => row.proposal_rate),
  forecastRates: result.forecast.scenarios.map(row => row.rate_pct),
  version: result.version
}));
"""
    )

    assert result["exported"] == "function"
    assert result["rates"] == [3.4, 3.45, 3.47, 3.5]
    assert result["forecastRates"] == result["rates"]
    assert result["version"] == "public-structural-v2-decision-surface-v1"


def test_build_surface_keeps_attach_forecast_axis_guard() -> None:
    result = run_node(
        r"""
const surface = require('./web/public-structural-v2/surface.js');
let message = null;
try {
  surface.attachForecast({
    version: 'public-structural-v2-decision-surface-v1',
    market_positions: [{proposal_rate: 3.45}]
  }, {
    status: 'ready',
    scenarios: [{rate_pct: 3.50}]
  });
} catch (error) {
  message = error.message;
}
process.stdout.write(JSON.stringify({message}));
"""
    )

    assert result["message"] == "surface:forecast_rate_axis_mismatch"
