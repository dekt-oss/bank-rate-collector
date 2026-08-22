(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.PublicStructuralV2MarketPosition=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  function normalizeRate(value,config){
    const number=Number(value);
    if(!Number.isFinite(number)||number<0)throw new Error("rate:out_of_range");
    return Number(number.toFixed(config.rate_normalization_decimals));
  }

  function relation(candidate,competitor){
    if(candidate>competitor)return "ahead";
    if(candidate<competitor)return "behind";
    return "tied";
  }

  function median(values){
    const ordered=[...values].sort((a,b)=>a-b),mid=Math.floor(ordered.length/2);
    return ordered.length%2?ordered[mid]:(ordered[mid-1]+ordered[mid])/2;
  }

  function cutoff(values,share){
    const ordered=[...values].sort((a,b)=>b-a);
    const count=Math.max(1,Math.ceil(ordered.length*share));
    return ordered[count-1];
  }

  function round(value,digits){return Number(value.toFixed(digits));}

  function marketPosition({rows,anchor_product_id,current_own_rate,proposal_rate},config){
    if(!Array.isArray(rows)||!rows.length)throw new Error("market_rows:required");
    const seen=new Set();
    const normalized=rows.map(row=>{
      const productId=String(row.product_id||"").trim();
      if(!productId)throw new Error("product_id:required");
      if(seen.has(productId))throw new Error(`duplicate_product_id:${productId}`);
      seen.add(productId);
      return {product_id:productId,rate:normalizeRate(row.rate,config)};
    });
    const anchorId=String(anchor_product_id||"").trim();
    if(!anchorId)throw new Error("anchor_product_id:required");
    const current=normalizeRate(current_own_rate,config);
    const proposal=normalizeRate(proposal_rate,config);
    const anchors=normalized.filter(row=>row.product_id===anchorId);
    if(anchors.length!==1)throw new Error("anchor_product_id:must_match_exactly_one");
    if(anchors[0].rate!==current)throw new Error("anchor_rate:current_rate_mismatch");

    const competitors=normalized.filter(row=>row.product_id!==anchorId);
    const competitorRates=competitors.map(row=>row.rate);
    const counterfactual=[...competitorRates,proposal];
    const n=counterfactual.length;
    const higher=competitorRates.filter(rate=>rate>proposal).length;
    const ties=competitorRates.filter(rate=>rate===proposal).length;
    const mean=counterfactual.reduce((sum,rate)=>sum+rate,0)/n;
    const med=median(counterfactual);
    const top10=cutoff(counterfactual,config.top10_share);
    const top25=cutoff(counterfactual,config.top25_share);
    const marketMax=Math.max(...counterfactual);
    const transitions={newly_outpriced:0,newly_tied:0,newly_lost_to:0,newly_tied_down:0};
    for(const row of competitors){
      const before=relation(current,row.rate),after=relation(proposal,row.rate);
      if((before==="behind"||before==="tied")&&after==="ahead")transitions.newly_outpriced++;
      if(before==="behind"&&after==="tied")transitions.newly_tied++;
      if((before==="ahead"||before==="tied")&&after==="behind")transitions.newly_lost_to++;
      if(before==="ahead"&&after==="tied")transitions.newly_tied_down++;
    }
    const within5=competitorRates.filter(rate=>Math.abs(rate-proposal)<=config.crowding_windows_pp[0]+1e-12).length;
    const within10=competitorRates.filter(rate=>Math.abs(rate-proposal)<=config.crowding_windows_pp[1]+1e-12).length;
    const gap=(right)=>round((proposal-right)*100,2);

    return {
      version:config.version,status:"ready",universe_count:n,proposal_rate:round(proposal,4),
      rank_best:higher+1,rank_worst:higher+ties+1,tie_competitor_count:ties,
      mean_rate:round(mean,4),median_rate:round(med,4),top25_cutoff:round(top25,4),
      top10_cutoff:round(top10,4),market_max_rate:round(marketMax,4),
      gap_to_mean_bp:gap(mean),gap_to_median_bp:gap(med),gap_to_top25_bp:gap(top25),
      gap_to_top10_bp:gap(top10),gap_to_market_max_bp:gap(marketMax),
      exact_tie_count:ties,within_5bp_count:within5,within_10bp_count:within10,
      top25_reached:proposal>=top25,top25_exceeded:proposal>top25,
      top10_reached:proposal>=top10,top10_exceeded:proposal>top10,
      ...transitions
    };
  }

  return {normalizeRate,marketPosition};
});
