(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.StrategyTargetCandidate=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  const CONTRACT_VERSION="strategy-target-candidate-v1";

  function finite(value){
    if(value===null||value===undefined||String(value).trim()==="")return null;
    const number=Number(value);
    return Number.isFinite(number)?number:null;
  }

  function findFirstCandidate(scenarios,targetTotal){
    const target=finite(targetTotal);
    if(target===null||target<0){
      return {version:CONTRACT_VERSION,status:"unavailable",reason:"target_invalid"};
    }
    if(!Array.isArray(scenarios)||scenarios.length===0){
      return {version:CONTRACT_VERSION,status:"unavailable",reason:"surface_empty"};
    }
    const rows=scenarios.map((row,index)=>({
      index,
      rate_pct:finite(row?.rate_pct),
      predicted_total:finite(row?.predicted_total),
    })).filter(row=>row.rate_pct!==null&&row.predicted_total!==null)
      .sort((a,b)=>a.rate_pct-b.rate_pct||a.index-b.index);
    if(rows.length===0){
      return {version:CONTRACT_VERSION,status:"unavailable",reason:"surface_has_no_finite_candidates"};
    }
    const match=rows.find(row=>row.predicted_total>=target);
    if(!match){
      return {
        version:CONTRACT_VERSION,
        status:"out_of_support",
        reason:"target_above_surface_max",
        target_total:target,
        max_candidate_total:Math.max(...rows.map(row=>row.predicted_total)),
      };
    }
    return {
      version:CONTRACT_VERSION,
      status:"ready",
      selection_semantics:"first_existing_candidate_meeting_target_no_interpolation",
      target_total:target,
      rate_pct:match.rate_pct,
      predicted_total:match.predicted_total,
      candidate_index:match.index,
    };
  }

  return {CONTRACT_VERSION,findFirstCandidate};
});