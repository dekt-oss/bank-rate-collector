(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.PublicStructuralV2Inflow=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  function finite(name,value){
    const number=Number(value);
    if(!Number.isFinite(number))throw new Error(`${name}:must_be_finite_number`);
    return number;
  }

  function nonnegative(name,value){
    const number=finite(name,value);
    if(number<0)throw new Error(`${name}:must_be_non_negative`);
    return number;
  }

  function logistic(value){
    if(value>=0){const z=Math.exp(-value);return 1/(1+z);}
    const z=Math.exp(value);return z/(1+z);
  }

  function logit(probability){return Math.log(probability/(1-probability));}

  function shiftRolloverProbability(probability,logOddsDelta){
    const p0=finite("probability",probability),delta=finite("log_odds_delta",logOddsDelta);
    if(p0<0||p0>1)throw new Error("probability:out_of_range");
    if(p0===0||p0===1||Math.abs(delta)<=1e-12)return p0;
    return logistic(logit(p0)+delta);
  }

  function predictScenario(args,scenario,config){
    const baseline=nonnegative("baseline_new_money",args.baseline_new_money);
    const maturity=nonnegative("maturity_amount",args.maturity_amount);
    const rolloverPct=finite("current_rollover_rate_pct",args.current_rollover_rate_pct);
    const ownRate=finite("current_own_rate",args.current_own_rate);
    const proposedRate=finite("proposed_rate",args.proposed_rate);
    const termMonths=Number(args.term_months);
    if(rolloverPct<0||rolloverPct>100)throw new Error("current_rollover_rate_pct:out_of_range");
    if(!Number.isInteger(termMonths)||termMonths<=0)throw new Error("term_months:out_of_range");

    const p0=rolloverPct/100;
    const relativeChange=proposedRate-ownRate;
    const rateSteps=relativeChange/config.rate_step_percentage_point;
    const rawLog=scenario.new_money_log_change_per_10bp*rateSteps;
    const maxLog=config.max_abs_new_money_log_effect;
    const logEffect=Math.max(-maxLog,Math.min(maxLog,rawLog));
    const multiplier=Math.exp(logEffect);
    const predictedNew=baseline*multiplier;
    const rolloverDelta=scenario.rollover_log_odds_change_per_10bp*rateSteps;
    const p1=shiftRolloverProbability(p0,rolloverDelta);
    const predictedRollover=maturity*p1;
    const baselineTotal=baseline+maturity*p0;
    const predictedTotal=predictedNew+predictedRollover;
    const incrementalTotal=predictedTotal-baselineTotal;
    const termFactor=termMonths/12;
    const baselineInterest=baselineTotal*ownRate/100*termFactor;
    const predictedInterest=predictedTotal*proposedRate/100*termFactor;

    return {
      scenario:scenario.key,
      relative_change_pp:Number(relativeChange.toFixed(4)),
      rate_steps_10bp:Number(rateSteps.toFixed(6)),
      raw_new_money_log_effect:Number(rawLog.toFixed(6)),
      applied_new_money_log_effect:Number(logEffect.toFixed(6)),
      new_money_multiplier:Number(multiplier.toFixed(6)),
      predicted_new_money:Number(predictedNew.toFixed(4)),
      baseline_rollover_rate_pct:Number((p0*100).toFixed(4)),
      predicted_rollover_rate_pct:Number((p1*100).toFixed(4)),
      predicted_rollover:Number(predictedRollover.toFixed(4)),
      baseline_total:Number(baselineTotal.toFixed(4)),
      predicted_total:Number(predictedTotal.toFixed(4)),
      incremental_total:Number(incrementalTotal.toFixed(4)),
      baseline_surface_interest:Number(baselineInterest.toFixed(4)),
      predicted_surface_interest:Number(predictedInterest.toFixed(4)),
      surface_interest_delta:Number((predictedInterest-baselineInterest).toFixed(4))
    };
  }

  function predictRange(args,config){
    const scenarios={};
    for(const scenario of config.scenarios)scenarios[scenario.key]=predictScenario(args,scenario,config);
    const totals=Object.values(scenarios).map(row=>row.predicted_total);
    return {
      base:scenarios.base,
      scenarios,
      predicted_total_range:{min:Math.min(...totals),max:Math.max(...totals)}
    };
  }

  return {shiftRolloverProbability,predictScenario,predictRange};
});
