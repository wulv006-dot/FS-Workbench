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
      if(!response.ok)throw Object.assign(failure(value.code||'RUNTIME_UNAVAILABLE'),{status:response.status,dispatch_state:value.dispatch_state});return value;
    }
    function page(){const p=snapshot?.pages?.find(p=>p.page_id===pageId&&p.activity_id===activityId);if(!p)throw failure('PAGE_UNAVAILABLE');return p;}
    const uncertain=error=>error.code==='NETWORK_UNKNOWN'||error.status>=500;
    function rememberIntent(intent){
      if(!intent?.intent_id||!intent?.operation_id)throw failure('INTENT_RESPONSE_INVALID');
      retain({...pending,stage:'intent_confirmed',unknown:false,intent_id:intent.intent_id,operation_id:intent.operation_id,intent});
    }
    async function quoteIntent(){
      if(!pending?.intent_id)throw failure('INTENT_RECOVERY_REQUIRED');
      retain({...pending,stage:'quote',unknown:true});
      try{const quote=await api('quote',{intent_id:pending.intent_id});retain({...pending,stage:'quoted',unknown:false,quote_id:quote.quote_id,quote});return {intent:pending.intent,quote};}
      catch(error){if(!uncertain(error)||error.code==='MAIN_INTEGRATION_REQUIRED')retain({...pending,unknown:false,quote_error:error.code});throw error;}
    }
    function rememberResult(result){
      const resolved=result?.operation_id===pending.operation_id&&result?.status==='integration_test_result'&&Array.isArray(result.lines)&&result.lines.length>0&&result.lines.every(line=>['confirmed','rejected'].includes(line.status));
      retain({...pending,stage:resolved?'resolved':'prepare',prepare_dispatched:true,unknown:!resolved,resolved,result});return result;
    }
    const client={
      get config(){return snapshot;},get capabilities(){return capabilities;},get pending(){return pending&&structuredClone(pending);},
      describe(){return capabilities?.integration_mode==='integration_test'?'Integration test only — no live cart or payment.':'Preview — main-site integration pending. Prices and benefits are snapshots; no live cart or payment.';},
      async load(){[snapshot,capabilities]=await Promise.all([api('config'),api('capabilities')]);page();return {config:snapshot,capabilities};},
      async reveal(game_id){
        if(pageId!=='seasonal-vault'||activityId!=='mmoexp-seasonal')throw failure('PAGE_UNAVAILABLE');
        if(!snapshot)await client.load();
        // A draw belongs to the visitor, not to one tab or one page load. Keep the
        // request id durably so a reload, a new tab or a reopened browser asks the
        // server for the same receipt instead of rolling a new one.
        const durable=(()=>{try{return root.localStorage||storage}catch{return storage}})();
        const revealKey='campaign-reveal:'+base+':'+snapshot.release_id+':'+snapshot.config_hash+':'+game_id;
        let saved;try{saved=JSON.parse(durable.getItem(revealKey)||'null');}catch{throw failure('OPERATION_STORAGE_INVALID');}
        if(!saved){saved={request_id:root.crypto.randomUUID(),game_id};const raw=JSON.stringify(saved);durable.setItem(revealKey,raw);if(durable.getItem(revealKey)!==raw)throw failure('OPERATION_STORAGE_REQUIRED');}
        if(saved.game_id!==game_id)throw failure('REQUEST_CONFLICT');
        // Same UUID on every retry: lost responses/reloads cannot reroll.
        const receipt=await api('halloween/reveal',saved);
        try{durable.setItem('campaign-receipt:'+base+':'+snapshot.release_id+':'+snapshot.config_hash+':'+game_id,JSON.stringify(receipt));}catch{ /* a read-only store keeps the in-memory draw */ }
        if(receipt.status!=='revealed'||receipt.request_id!==saved.request_id||receipt.game_id!==game_id||receipt.release_id!==snapshot.release_id||receipt.config_hash!==snapshot.config_hash)throw failure('HALLOWEEN_REVEAL_MISMATCH');
        return receipt;
      },
      // The durable receipt lets a reload paint the same draw instead of a blank card.
      cachedReveal(game_id){
        try{
          if(!snapshot)return null;
          const durable=(()=>{try{return root.localStorage||storage}catch{return storage}})();
          const raw=durable.getItem('campaign-receipt:'+base+':'+snapshot.release_id+':'+snapshot.config_hash+':'+game_id);
          const receipt=raw?JSON.parse(raw):null;
          if(!receipt||!receipt.request_id||receipt.game_id!==game_id||receipt.release_id!==snapshot.release_id||receipt.config_hash!==snapshot.config_hash)return null;
          if(receipt.status!=='revealed'||!Array.isArray(receipt.slots))return null;
          return receipt;
        }catch{return null;}
      },
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
        const body={request_id:root.crypto.randomUUID(),activity_id:activityId,page_id:pageId,rule_version:p.rule_version,benefit_binding_version:p.benefit_binding_version,currency:'USD',lines:selected};
        const receipts=[...(pending?.receipts||[]),...(pending?.resolved?[{operation_id:pending.operation_id,result:pending.result}]:[])];
        retain({stage:'intent',unknown:true,request_id:body.request_id,request_body:body,receipts});
        let intent;
        try{intent=await api('intents',body);}catch(error){if(!uncertain(error))retain({...pending,unknown:false,stage:'intent_rejected',error:error.code});throw error;}
        rememberIntent(intent);return quoteIntent();
      },
      async prepare(){
        if(pending?.prepare_dispatched)throw failure(pending.resolved?'OPERATION_RESOLVED':'OPERATION_UNKNOWN');
        if(pending?.unknown)throw failure('OPERATION_UNKNOWN');
        if(capabilities?.integration_mode!=='integration_test'||!capabilities.test_capabilities?.prepare_checkout)throw failure('MAIN_INTEGRATION_REQUIRED');
        if(!pending?.quote_id)throw failure('QUOTE_REQUIRED');
        const body={operation_id:pending.operation_id,intent_id:pending.intent_id,quote_id:pending.quote_id,return_route_id:'activity'};
        retain({...pending,stage:'prepare',unknown:true,prepare_dispatched:true});
        try{return rememberResult(await api('prepare_checkout',body));}
        catch(error){
          const notStarted=error.status===409&&error.dispatch_state==='not_started'&&['QUOTE_EXPIRED','PRICE_CHANGED','QUOTE_INVALID','RULE_VERSION_CONFLICT','PROMOTION_EXPIRED','PROMOTION_NOT_STARTED'].includes(error.code);
          retain({...pending,prepare_error:error.code,...(notStarted?{stage:'prepare_rejected',unknown:false,prepare_dispatched:false,quote_id:null,quote:null}:{})});throw error;
        }
      },
      async recover(){
        if(!pending)throw failure('OPERATION_ID_UNAVAILABLE');
        if(pending.prepare_dispatched||pending.stage==='prepare'||pending.stage==='resolved'){
          if(!pending.operation_id)throw failure('OPERATION_ID_UNAVAILABLE');
          return rememberResult(await api('operations/'+encodeURIComponent(pending.operation_id)));
        }
        if(pending.stage==='intent'){
          if(!pending.request_id||!pending.request_body)throw failure('INTENT_RECOVERY_REQUIRED');
          let intent;
          try{intent=await api('intents/request/'+encodeURIComponent(pending.request_id));}
          catch(error){
            if(error.status!==404||error.code!=='INTENT_NOT_FOUND')throw error;
            // This exact original request is safe to replay only under the durable request_id contract.
            intent=await api('intents',pending.request_body);
          }
          rememberIntent(intent);
        }
        if(pending.intent_id)return quoteIntent();
        throw failure('INTENT_RECOVERY_REQUIRED');
      },
      async lookup(){return client.recover();
      }
    };return client;
  }
  const api={enabled:(element,location)=>Boolean(prefix(element,location)),create};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.CampaignStandalone=api;
})(typeof window==='undefined'?globalThis:window);
