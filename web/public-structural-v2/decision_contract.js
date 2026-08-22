(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.PublicStructuralV2DecisionContract=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  function normalizeRate(value,decimals=4){
    const number=Number(value);
    if(!Number.isFinite(number)||number<0)throw new Error("rate:out_of_range");
    return Number(number.toFixed(decimals));
  }

  function buildCandidateRateSets(args){
    const decimals=4,step=0.05;
    const current=normalizeRate(args.current_rate,decimals);
    const proposal=normalizeRate(args.proposal_rate,decimals);
    const minimum=normalizeRate(args.economics_min_rate,decimals);
    const maximum=normalizeRate(args.economics_max_rate,decimals);
    if(minimum>current||maximum<current||minimum>maximum){
      throw new Error("economics_range:must_include_current");
    }
    const inputs=[
      ["current",current],["proposal",proposal],
      ["top25",normalizeRate(args.top25_cutoff,decimals)],
      ["top10",normalizeRate(args.top10_cutoff,decimals)],
      ["market_max",normalizeRate(args.market_max_rate,decimals)]
    ];
    const grouped=new Map();
    for(const [label,rate] of inputs){
      if(!grouped.has(rate))grouped.set(rate,[]);
      grouped.get(rate).push(label);
    }
    const factual_markers=[...grouped.entries()]
      .sort((a,b)=>a[0]-b[0])
      .map(([rate,labels])=>({rate_pct:rate,labels}));
    const grid=new Set([current]);
    for(let rate=normalizeRate(current-step,decimals);rate>=minimum-1e-12;rate=normalizeRate(rate-step,decimals)){
      grid.add(rate);
    }
    for(let rate=normalizeRate(current+step,decimals);rate<=maximum+1e-12;rate=normalizeRate(rate+step,decimals)){
      grid.add(rate);
    }
    const economics_grid=[...grid].sort((a,b)=>a-b);
    return {
      version:"public-structural-v2-candidate-set-v1",
      fixed_step_bp:5,
      factual_markers,
      economics_grid,
      proposal_rate:proposal,
      proposal_on_economics_grid:grid.has(proposal)
    };
  }

  function buildPublicForecast(args,inflowApi,inflowConfig){
    const generatedAt=String(args.generated_at||"").trim();
    if(!generatedAt)throw new Error("generated_at:required");
    if(!Array.isArray(args.candidate_rates)||!args.candidate_rates.length){
      throw new Error("candidate_rates:required");
    }
    const seen=new Set();
    const rates=args.candidate_rates.map(raw=>{
      const rate=normalizeRate(raw,4);
      if(seen.has(rate))throw new Error("candidate_rates:duplicate");
      seen.add(rate);
      return rate;
    }).sort((a,b)=>a-b);
    const scenarios=rates.map(rate=>{
      const result=inflowApi.predictRange({
        baseline_new_money:args.baseline_new_money,
        maturity_amount:args.maturity_amount,
        current_rollover_rate_pct:args.current_rollover_rate_pct,
        current_own_rate:args.current_own_rate,
        proposed_rate:rate,
        term_months:args.term_months
      },inflowConfig);
      const base=result.base,bounds=result.predicted_total_range;
      const publicNew=base.predicted_new_money;
      const publicRollover=base.predicted_rollover;
      const publicTotal=Number((publicNew+publicRollover).toFixed(4));
      const publicIncremental=Number((publicTotal-base.baseline_total).toFixed(4));
      return {
        rate_pct:rate,
        predicted_new_money:publicNew,
        predicted_rollover:publicRollover,
        predicted_total:publicTotal,
        incremental_total:publicIncremental,
        surface_interest_delta:base.surface_interest_delta,
        predicted_total_lower:bounds.min,
        predicted_total_upper:bounds.max
      };
    });
    return {
      version:"inflow-public-forecast-v1",
      generated_at:generatedAt,
      status:"ready",
      amount_unit:"KRW_100M",
      rate_unit:"percent",
      scenarios
    };
  }

  return {buildCandidateRateSets,buildPublicForecast};
});
