(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.PublicStructuralV2Surface=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  const VERSION="public-structural-v2-decision-surface-v1";
  const RANGE="uncalibrated_stress_range_not_prediction_interval";
  const RELATION="separate_no_direct_market_effect_in_amount_formula";
  const DISCLOSURE="구조적 수신 시나리오는 현재 대비 당사 금리변화폭에 대한 미보정 민감도입니다. 시장 순위·밀집도 변화는 금액식에 직접 반영되지 않습니다.";

  function buildSurfaceFrame(args,marketApi,marketConfig,decisionApi){
    const proposalPosition=marketApi.marketPosition({
      rows:args.market_rows,
      anchor_product_id:args.anchor_product_id,
      current_own_rate:args.current_own_rate,
      proposal_rate:args.proposal_rate
    },marketConfig);
    const candidateSet=decisionApi.buildCandidateRateSets({
      current_rate:args.current_own_rate,
      proposal_rate:args.proposal_rate,
      top25_cutoff:proposalPosition.top25_cutoff,
      top10_cutoff:proposalPosition.top10_cutoff,
      market_max_rate:proposalPosition.market_max_rate,
      economics_min_rate:args.economics_min_rate,
      economics_max_rate:args.economics_max_rate
    });
    const displayRates=[...new Set([...candidateSet.economics_grid,candidateSet.proposal_rate])]
      .sort((a,b)=>a-b);
    const marketPositions=displayRates.map(rate=>marketApi.marketPosition({
      rows:args.market_rows,
      anchor_product_id:args.anchor_product_id,
      current_own_rate:args.current_own_rate,
      proposal_rate:rate
    },marketConfig));
    return {
      version:VERSION,
      generated_at:String(args.generated_at),
      range_semantics:RANGE,
      market_amount_relation:RELATION,
      disclosure:DISCLOSURE,
      candidate_set:candidateSet,
      market_positions:marketPositions
    };
  }

  function attachForecast(frame,forecast){
    if(!frame||frame.version!==VERSION)throw new Error("surface:invalid_frame");
    if(!forecast||typeof forecast!=="object")throw new Error("surface:forecast_required");
    if(forecast.status==="ready"){
      const positionRates=(frame.market_positions||[]).map(row=>Number(row.proposal_rate).toFixed(4));
      const forecastRates=(forecast.scenarios||[]).map(row=>Number(row.rate_pct).toFixed(4));
      if(positionRates.length!==forecastRates.length||
        positionRates.some((rate,index)=>rate!==forecastRates[index])){
        throw new Error("surface:forecast_rate_axis_mismatch");
      }
    }
    return {...frame,forecast};
  }

  function buildSurface(args,marketApi,marketConfig,decisionApi,inflowApi,inflowConfig){
    const frame=buildSurfaceFrame(args,marketApi,marketConfig,decisionApi);
    const candidateRates=[...new Set([
      ...(frame.candidate_set?.economics_grid||[]),
      frame.candidate_set?.proposal_rate
    ].filter(Number.isFinite))].sort((a,b)=>a-b);
    const forecast=decisionApi.buildPublicForecast({
      generated_at:args.generated_at,
      candidate_rates:candidateRates,
      baseline_new_money:args.baseline_new_money,
      maturity_amount:args.maturity_amount,
      current_rollover_rate_pct:args.current_rollover_rate_pct,
      current_own_rate:args.current_own_rate,
      term_months:args.term_months
    },inflowApi,inflowConfig);
    return attachForecast(frame,forecast);
  }

  return {attachForecast,buildSurface,buildSurfaceFrame};
});