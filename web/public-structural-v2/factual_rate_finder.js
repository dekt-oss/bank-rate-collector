(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.PublicStructuralV2FactualRateFinder=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  const RATE_SCALE=10000;
  const MAX_RATE_UNITS=9999999;
  const DEFAULT_SELECTION_STEP_UNITS=100;
  const FACTUAL_RATE_FINDER_VERSION="public-structural-v2-factual-rate-finder-v1";
  const BENCHMARK_UNIVERSE="competitor_only_anchor_removed";
  const SELECTION_SEMANTICS="strategy_ui_selectable_granularity_not_business_pricing_policy";

  function normalizeRateUnits(value){
    const number=Number(value);
    if(!Number.isFinite(number)||number<0)throw new Error("rate:out_of_range");
    const units=Math.round(number*RATE_SCALE);
    if(units<0||units>MAX_RATE_UNITS)throw new Error("rate:out_of_range");
    return units;
  }

  function normalizeStepUnits(value){
    const number=Number(value);
    if(!Number.isFinite(number)||number<=0)throw new Error("selection_step:out_of_range");
    const units=Math.round(number*RATE_SCALE);
    if(units<=0||units>MAX_RATE_UNITS)throw new Error("selection_step:out_of_range");
    if(Math.abs(number*RATE_SCALE-units)>1e-7)throw new Error("selection_step:not_rate_exponent_multiple");
    return units;
  }

  function toRate(units){return Number((units/RATE_SCALE).toFixed(4));}

  function cutoff(values,share){
    const ordered=[...values].sort((a,b)=>b-a);
    const count=Math.max(1,Math.ceil(ordered.length*share));
    return ordered[count-1];
  }

  function normalizedRows(rows){
    if(!Array.isArray(rows)||rows.length===0)throw new Error("market_rows:required");
    const seen=new Set();
    return rows.map(row=>{
      const productId=String(row?.product_id||"").trim();
      if(!productId)throw new Error("product_id:required");
      if(seen.has(productId))throw new Error(`duplicate_product_id:${productId}`);
      seen.add(productId);
      return {product_id:productId,rate_units:normalizeRateUnits(row?.rate)};
    });
  }

  function competitorMarketBenchmarks({rows,anchor_product_id,current_own_rate}){
    const normalized=normalizedRows(rows);
    const anchorId=String(anchor_product_id||"").trim();
    if(!anchorId)throw new Error("anchor_product_id:required");
    const currentUnits=normalizeRateUnits(current_own_rate);
    const anchors=normalized.filter(row=>row.product_id===anchorId);
    if(anchors.length!==1)throw new Error("anchor_product_id:must_match_exactly_one");
    if(anchors[0].rate_units!==currentUnits)throw new Error("anchor_rate:current_rate_mismatch");
    const competitorRates=normalized.filter(row=>row.product_id!==anchorId).map(row=>row.rate_units);
    if(competitorRates.length===0)throw new Error("competitor_only:required");
    return {
      benchmark_universe:BENCHMARK_UNIVERSE,
      competitor_count:competitorRates.length,
      top10_cutoff:toRate(cutoff(competitorRates,.10)),
      top25_cutoff:toRate(cutoff(competitorRates,.25)),
      market_max_rate:toRate(Math.max(...competitorRates)),
    };
  }

  function ceilToStep(rateUnits,stepUnits){return Math.ceil(rateUnits/stepUnits)*stepUnits;}
  function minimumReach(rateUnits,stepUnits){
    const candidate=ceilToStep(rateUnits,stepUnits);
    return candidate<=MAX_RATE_UNITS?candidate:null;
  }
  function minimumExceed(rateUnits,stepUnits){
    let candidate=ceilToStep(rateUnits,stepUnits);
    if(candidate<=rateUnits)candidate+=stepUnits;
    return candidate<=MAX_RATE_UNITS?candidate:null;
  }

  function condition({target,relation,label,benchmarkUnits,minimumUnits,reason}){
    const row={
      target,
      relation,
      label,
      benchmark_rate_pct:toRate(benchmarkUnits),
      status:minimumUnits===null?"unavailable":"ready",
    };
    if(minimumUnits===null)row.reason=reason||"minimum_selectable_rate_out_of_range";
    else row.minimum_selectable_rate_pct=toRate(minimumUnits);
    return row;
  }

  function factualRateConstraints({rows,anchor_product_id,current_own_rate,selection_step_pp=.01}){
    const stepUnits=normalizeStepUnits(selection_step_pp);
    const benchmarks=competitorMarketBenchmarks({rows,anchor_product_id,current_own_rate});
    const top10Units=normalizeRateUnits(benchmarks.top10_cutoff);
    const top25Units=normalizeRateUnits(benchmarks.top25_cutoff);
    const marketMaxUnits=normalizeRateUnits(benchmarks.market_max_rate);
    const tieUnits=marketMaxUnits%stepUnits===0?marketMaxUnits:null;
    const conditions=[
      condition({target:"top10",relation:"reach",label:"상위 10% 진입선 도달",benchmarkUnits:top10Units,minimumUnits:minimumReach(top10Units,stepUnits)}),
      condition({target:"top10",relation:"exceed",label:"상위 10% 진입선 초과",benchmarkUnits:top10Units,minimumUnits:minimumExceed(top10Units,stepUnits)}),
      condition({target:"top25",relation:"reach",label:"상위 25% 진입선 도달",benchmarkUnits:top25Units,minimumUnits:minimumReach(top25Units,stepUnits)}),
      condition({target:"top25",relation:"exceed",label:"상위 25% 진입선 초과",benchmarkUnits:top25Units,minimumUnits:minimumExceed(top25Units,stepUnits)}),
      condition({target:"market_max",relation:"tie",label:"시장 최고 동률",benchmarkUnits:marketMaxUnits,minimumUnits:tieUnits,reason:"exact_tie_not_selectable_on_ui_grid"}),
      condition({target:"market_max",relation:"exceed",label:"시장 최고 초과",benchmarkUnits:marketMaxUnits,minimumUnits:minimumExceed(marketMaxUnits,stepUnits)}),
    ];
    return {
      version:FACTUAL_RATE_FINDER_VERSION,
      status:"ready",
      benchmark_universe:BENCHMARK_UNIVERSE,
      competitor_count:benchmarks.competitor_count,
      selection_step_pp:toRate(stepUnits),
      selection_step_bp:Number(((stepUnits/RATE_SCALE)*100).toFixed(2)),
      selection_semantics:SELECTION_SEMANTICS,
      conditions,
    };
  }

  return {normalizeRateUnits,competitorMarketBenchmarks,factualRateConstraints};
});
