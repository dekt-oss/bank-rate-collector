(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.StrategyEnrollmentFilter=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  const CONTRACT_VERSION="strategy-enrollment-filter-v1";
  const MODES=Object.freeze({ALL:"all",REMOTE:"remote",FACE:"face"});
  const REMOTE_CHANNELS=new Set(["internet","mobile","telephone"]);
  const FACE_CHANNELS=new Set(["branch","agent"]);
  const REMOTE_NAME=/(비대면|인터넷|모바일|스마트폰|스마트뱅킹|온라인|e[-\s]?뱅킹|^e[-\s])/i;
  const FACE_NAME=/(^|[^비])대면/;

  function text(value){return String(value??"").trim();}
  function classify(row){
    const channel=text(row?.join_channel||row?.channel).toLowerCase();
    const product=text(row?.product);
    const tags=text(row?.preference_tags);
    if(REMOTE_CHANNELS.has(channel)){
      return {mode:MODES.REMOTE,evidence:"join_channel"};
    }
    if(FACE_CHANNELS.has(channel)){
      return {mode:MODES.FACE,evidence:"join_channel"};
    }
    const remoteExplicit=REMOTE_NAME.test(product)||/(^|[|,\s])DIGITAL_CHANNEL([|,\s]|$)/.test(tags);
    const faceExplicit=FACE_NAME.test(product);
    if(remoteExplicit&&!faceExplicit){
      return {mode:MODES.REMOTE,evidence:"explicit_product_or_preference"};
    }
    if(faceExplicit&&!remoteExplicit){
      return {mode:MODES.FACE,evidence:"explicit_product"};
    }
    return {mode:"unknown",evidence:channel==="any"?"ambiguous_any":"insufficient"};
  }

  function matches(row,mode){
    const selected=text(mode)||MODES.ALL;
    if(selected===MODES.ALL)return true;
    return classify(row).mode===selected;
  }

  function label(mode){
    return mode===MODES.REMOTE?"비대면":mode===MODES.FACE?"대면":"전체";
  }

  return {CONTRACT_VERSION,MODES,classify,matches,label};
});