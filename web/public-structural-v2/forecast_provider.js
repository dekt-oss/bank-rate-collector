(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.PublicStructuralV2ForecastProvider=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  const VERSION="inflow-public-forecast-v1";
  const AMOUNT_UNIT="KRW_100M";
  const RATE_UNIT="percent";
  const TOP_LEVEL=new Set([
    "version","generated_at","status","amount_unit","rate_unit","scenarios"
  ]);
  const SCENARIO=new Set([
    "rate_pct","predicted_new_money","predicted_rollover","predicted_total",
    "incremental_total","surface_interest_delta","predicted_total_lower",
    "predicted_total_upper"
  ]);
  const REQUIRED_SCENARIO=[
    "rate_pct","predicted_new_money","predicted_rollover","predicted_total",
    "incremental_total","surface_interest_delta"
  ];

  class ProviderUnavailableError extends Error{
    constructor(message="forecast_provider:unavailable"){
      super(message);
      this.name="ProviderUnavailableError";
    }
  }

  function normalizeRate(value){
    const number=Number(value);
    if(!Number.isFinite(number)||number<0)throw new Error("forecast_provider:rate_invalid");
    return Number(number.toFixed(4));
  }

  function expectedRates(request){
    if(!Array.isArray(request?.candidate_rates)||!request.candidate_rates.length){
      throw new Error("forecast_provider:candidate_rates_required");
    }
    const rates=request.candidate_rates.map(normalizeRate).sort((a,b)=>a-b);
    if(new Set(rates).size!==rates.length){
      throw new Error("forecast_provider:candidate_rates_duplicate");
    }
    return rates;
  }

  function unknownKeys(object,allowed){
    return Object.keys(object).filter(key=>!allowed.has(key)).sort();
  }

  function finiteNumber(value,field){
    if(typeof value==="boolean"||value===null||value===undefined||String(value).trim()===""){
      throw new Error(`${field}:must_be_finite_number`);
    }
    const number=Number(value);
    if(!Number.isFinite(number))throw new Error(`${field}:must_be_finite_number`);
    return number;
  }

  function isClose(a,b,relTol=1e-9,absTol=1e-6){
    return Math.abs(a-b)<=Math.max(absTol,relTol*Math.max(Math.abs(a),Math.abs(b)));
  }

  function validateScenario(row,index){
    if(!row||typeof row!=="object"||Array.isArray(row)){
      throw new Error(`scenario_${index}:must_be_object`);
    }
    const unknown=unknownKeys(row,SCENARIO);
    if(unknown.length)throw new Error(`scenario_${index}:unknown_fields:${unknown.join(",")}`);
    for(const field of REQUIRED_SCENARIO){
      if(!Object.prototype.hasOwnProperty.call(row,field)){
        throw new Error(`scenario_${index}:missing_fields:${field}`);
      }
    }
    const lower=Object.prototype.hasOwnProperty.call(row,"predicted_total_lower");
    const upper=Object.prototype.hasOwnProperty.call(row,"predicted_total_upper");
    if(lower!==upper){
      throw new Error(`scenario_${index}:prediction_interval_requires_both_bounds`);
    }
    const numeric={};
    for(const key of Object.keys(row))numeric[key]=finiteNumber(row[key],`scenario_${index}.${key}`);
    if(numeric.rate_pct<0||numeric.rate_pct>100){
      throw new Error(`scenario_${index}.rate_pct:out_of_range`);
    }
    for(const field of [
      "predicted_new_money","predicted_rollover","predicted_total",
      "predicted_total_lower","predicted_total_upper"
    ]){
      if(field in numeric&&numeric[field]<0){
        throw new Error(`scenario_${index}.${field}:must_be_non_negative`);
      }
    }
    const component=numeric.predicted_new_money+numeric.predicted_rollover;
    if(!isClose(numeric.predicted_total,component)){
      throw new Error(`scenario_${index}:predicted_total_component_mismatch`);
    }
    if(lower&&!(numeric.predicted_total_lower<=numeric.predicted_total&&
      numeric.predicted_total<=numeric.predicted_total_upper)){
      throw new Error(`scenario_${index}:prediction_interval_does_not_cover_total`);
    }
  }

  function validatePublicForecast(payload,request){
    if(!payload||typeof payload!=="object"||Array.isArray(payload)){
      throw new Error("public_forecast:must_be_object");
    }
    const unknown=unknownKeys(payload,TOP_LEVEL);
    if(unknown.length)throw new Error(`public_forecast:unknown_fields:${unknown.join(",")}`);
    for(const field of TOP_LEVEL){
      if(!Object.prototype.hasOwnProperty.call(payload,field)){
        throw new Error(`public_forecast:missing_fields:${field}`);
      }
    }
    if(payload.version!==VERSION)throw new Error("public_forecast:unsupported_version");
    if(payload.amount_unit!==AMOUNT_UNIT)throw new Error("public_forecast:unsupported_amount_unit");
    if(payload.rate_unit!==RATE_UNIT)throw new Error("public_forecast:unsupported_rate_unit");
    if(typeof payload.generated_at!=="string"||!payload.generated_at.trim()){
      throw new Error("public_forecast:generated_at_required");
    }
    if(payload.status!=="ready"&&payload.status!=="unavailable"){
      throw new Error("public_forecast:unsupported_status");
    }
    if(!Array.isArray(payload.scenarios))throw new Error("public_forecast:scenarios_must_be_list");
    if(payload.status==="ready"&&!payload.scenarios.length){
      throw new Error("public_forecast:ready_requires_scenarios");
    }
    if(payload.status==="unavailable"&&payload.scenarios.length){
      throw new Error("public_forecast:unavailable_must_not_include_scenarios");
    }
    payload.scenarios.forEach(validateScenario);
    if(payload.status==="ready"){
      const expected=expectedRates(request);
      const actual=payload.scenarios.map(row=>normalizeRate(row.rate_pct));
      if(new Set(actual).size!==actual.length){
        throw new Error("forecast_provider:scenario_rates_duplicate");
      }
      if(actual.length!==expected.length||actual.some((rate,index)=>rate!==expected[index])){
        throw new Error("forecast_provider:scenario_rate_axis_mismatch");
      }
    }
    return payload;
  }

  function unavailablePublicForecast(generatedAt){
    const timestamp=String(generatedAt||"").trim();
    if(!timestamp)throw new Error("forecast_provider:generated_at_required");
    return {
      version:VERSION,
      generated_at:timestamp,
      status:"unavailable",
      amount_unit:AMOUNT_UNIT,
      rate_unit:RATE_UNIT,
      scenarios:[]
    };
  }

  function createStructuralProvider(decisionApi,inflowApi,inflowConfig){
    if(!decisionApi||typeof decisionApi.buildPublicForecast!=="function"){
      throw new Error("forecast_provider:decision_api_required");
    }
    if(!inflowApi||typeof inflowApi.predictRange!=="function"){
      throw new Error("forecast_provider:inflow_api_required");
    }
    return request=>decisionApi.buildPublicForecast(request,inflowApi,inflowConfig);
  }

  async function resolveForecast(request,provider){
    expectedRates(request);
    if(typeof provider!=="function")throw new Error("forecast_provider:provider_required");
    let payload;
    try{
      payload=await Promise.resolve(provider(request));
    }catch(error){
      if(error instanceof ProviderUnavailableError){
        return unavailablePublicForecast(request.generated_at);
      }
      throw error;
    }
    return validatePublicForecast(payload,request);
  }

  return {
    ProviderUnavailableError,
    createStructuralProvider,
    resolveForecast,
    unavailablePublicForecast,
    validatePublicForecast
  };
});
