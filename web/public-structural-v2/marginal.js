(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.PublicStructuralV2Marginal=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  function normalizeRate(value){
    const number=Number(value);
    if(!Number.isFinite(number)||number<0)throw new Error("rate:out_of_range");
    return Number(number.toFixed(4));
  }

  function emptyMarginals(){
    return {
      version:"public-structural-v2-marginal-v1",
      step_bp:5,
      ratio_metric_status:"not_exposed_uncalibrated_denominator",
      annualized_marginal_rate_status:"not_exposed",
      marginals:[]
    };
  }

  function buildFixed5bpMarginals(surface){
    const grid=(surface.candidate_set?.economics_grid||[]).map(normalizeRate).sort((a,b)=>a-b);
    const forecast=surface.forecast||{};
    const scenarios=forecast.scenarios||[];
    if(grid.length<2)throw new Error("economics_grid:requires_two_rates");
    if(forecast.status==="unavailable")return emptyMarginals();
    if(!scenarios.length)throw new Error("forecast_scenarios:required");
    const byRate=new Map(scenarios.map(row=>[normalizeRate(row.rate_pct),row]));
    for(const rate of grid){if(!byRate.has(rate))throw new Error("economics_grid:forecast_mismatch");}
    const marginals=[];
    for(let i=0;i<grid.length-1;i++){
      const left=grid[i],right=grid[i+1];
      if(Math.abs((right-left)-0.05)>1e-12)throw new Error("marginal:requires_exact_5bp");
      const before=byRate.get(left),after=byRate.get(right);
      marginals.push({
        from_rate_pct:left,
        to_rate_pct:right,
        step_bp:5,
        structural_total_delta:Number((after.predicted_total-before.predicted_total).toFixed(4)),
        surface_interest_delta:Number((after.surface_interest_delta-before.surface_interest_delta).toFixed(4))
      });
    }
    return {
      version:"public-structural-v2-marginal-v1",
      step_bp:5,
      ratio_metric_status:"not_exposed_uncalibrated_denominator",
      annualized_marginal_rate_status:"not_exposed",
      marginals
    };
  }

  return {buildFixed5bpMarginals};
});
