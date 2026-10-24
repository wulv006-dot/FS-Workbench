(function(root){
  'use strict';
  const failure=(code)=>Object.assign(new Error(code),{code});
  function prefix(element,location=root.location){
    const value=element?.dataset?.campaignRuntime;
    if(value && /^\/(?:[A-Za-z0-9_-]+\/)+$/.test(value))return value;
    return location?.pathname?.startsWith('/events/')?'/events/':null;
  }
  function create({element,pageId,activityId,fetch:request=root.fetch?.bind(root),storage=root.sessionStorage,location=root.location}={}){
    const base=prefix(element,location);if(!base)throw failure('STANDALONE_NOT_ENABLED');
    const key='campaign-operation:'+base+':'+activityId+':'+pageId;
    let snapshot=null,capabilities=null,pending=null;
    try{pending=JSON.parse(storage?.getItem(key)||'null');}catch{throw failure('OPERATION_STORAGE_INVALID');}
    function retain(value){pending=value;try{if(!storage)throw failure('OPERATION_STORAGE_REQUIRED');storage.setItem(key,JSON.stringify(value));}catch{throw failure('OPERATION_STORAGE_REQUIRED');}}
    async function api(route,body){
      let response;try{response=await request(base+'api/campaign/'+route,{credentials:'same-origin',cache:'no-store',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});}catch{throw failure('NETWORK_UNKNOWN');}
      let value;try{value=await response.json();}catch{throw failure('NETWORK_UNKNOWN');}
      if(!response.ok)throw Object.assign(failure(value.code||'RUNTIME_UNAVAILABLE'),{status:response.status});return value;
    }
    function page(){const p=snapshot?.pages?.find(p=>p.page_id===pageId&&p.activity_id===activityId);if(!p)throw failure('PAGE_UNAVAILABLE');return p;}
    const client={
      get config(){return snapshot;},get capabilities(){return capabilities;},get pending(){return pending&&structuredClone(pending);},
      describe(){return capabilities?.integration_mode==='integration_test'?'Integration test only — no live cart or payment.':'Preview — main-site integration pending. Prices and benefits are snapshots; no live cart or payment.';},
      async load(){[snapshot,capabilities]=await Promise.all([api('config'),api('capabilities')]);page();return {config:snapshot,capabilities};},
      async select(lines){
        if(pending?.unknown)throw failure('OPERATION_UNKNOWN');
        if(!snapshot)await client.load();const p=page();
        const selected=lines.map((line,i)=>{
          const product=snapshot.products.find(x=>x.key===line.product_key&&p.product_keys.includes(x.key));
          if(!product?.available)throw failure('PRODUCT_UNAVAILABLE');
          // IDs and price never come from the historical page catalog.
          return {line_key:'line-'+(i+1),product_key:product.key,quantity:{value:String(line.quantity?.value??product.quantity.min),unit:line.quantity?.unit??product.quantity.unit,...(product.quantity.group?{group:product.quantity.group}:{})},attributes:line.attributes||[]};
        });
        if(!selected.length)throw failure('EMPTY_SELECTION');
        const body={activity_id:activityId,page_id:pageId,rule_version:p.rule_version,benefit_binding_version:p.benefit_binding_version,currency:'USD',lines:selected};
        retain({stage:'intent',unknown:true});
        let intent;
        try{intent=await api('intents',body);}catch(error){if(error.code!=='NETWORK_UNKNOWN')retain(null);throw error;}
        retain({stage:'intent',unknown:false,intent_id:intent.intent_id,operation_id:intent.operation_id});
        try{const quote=await api('quote',{intent_id:intent.intent_id});retain({...pending,stage:'quoted',quote_id:quote.quote_id});return {intent,quote};}
        catch(error){if(error.code==='NETWORK_UNKNOWN')retain({...pending,unknown:true});throw error;}
      },
      async prepare(){
        if(pending?.unknown||pending?.stage==='prepare')throw failure('OPERATION_UNKNOWN');
        if(capabilities?.integration_mode!=='integration_test'||!capabilities.test_capabilities?.prepare_checkout)throw failure('MAIN_INTEGRATION_REQUIRED');
        if(!pending?.quote_id)throw failure('QUOTE_REQUIRED');
        const body={operation_id:pending.operation_id,intent_id:pending.intent_id,quote_id:pending.quote_id,return_route_id:'activity'};
        retain({...pending,stage:'prepare',unknown:true});
        try{const result=await api('prepare_checkout',body);retain({...pending,unknown:result.status==='unknown',result});return result;}
        catch(error){if(error.code!=='NETWORK_UNKNOWN'&&error.code!=='OPERATION_UNKNOWN')retain({...pending,unknown:false});throw error;}
      },
      async lookup(){
        if(!pending?.operation_id)throw failure('OPERATION_ID_UNAVAILABLE');
        const result=await api('operations/'+encodeURIComponent(pending.operation_id));
        // A lookup never grants permission to repeat a prepare request.
        retain({...pending,result});return result;
      }
    };return client;
  }
  const api={enabled:(element,location)=>Boolean(prefix(element,location)),create};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.CampaignStandalone=api;
})(typeof window==='undefined'?globalThis:window);
