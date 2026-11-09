const endpoint='http://127.0.0.1:8931/internal/hermes/campaign-recommendations';
const unavailable=()=>Object.assign(new Error('WEEKLY_HERMES_PROVIDER_UNAVAILABLE'),{code:'WEEKLY_HERMES_PROVIDER_UNAVAILABLE',provider_outcome:'not_dispatched'});
const unknown=()=>Object.assign(new Error('WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN'),{code:'WEEKLY_HERMES_PROVIDER_OUTCOME_UNKNOWN',provider_outcome:'unknown'});

export function projectWeeklyProviderReceipt(value,operation_id) {
 if(!value||value.operation_id!==operation_id)return null;
 const receipt={operation_id};
 for(const key of ['task_id','run_id','model'])if(typeof value[key]==='string'&&/^[-a-zA-Z0-9_.:]{1,160}$/.test(value[key]))receipt[key]=value[key];
 if(value.usage&&typeof value.usage==='object')receipt.usage=Object.fromEntries(Object.entries(value.usage).filter(([key,count])=>['input_tokens','output_tokens','total_tokens','cached_tokens','reasoning_tokens'].includes(key)&&Number.isSafeInteger(count)&&count>=0));
 return receipt;
}

// Each authenticated HTTP request owns its closure; sessions never enter stored requests or model input.
export function createWeeklyHermesProvider({cookie,actor,fetchImpl=fetch}) {
 const provider=async(request,{signal,operation_id}={})=>call('POST',operation_id,request.input,signal);
 provider.lookup=({signal,operation_id}={})=>call('GET',operation_id,null,signal);
 async function call(method,operation_id,input,signal) {
  if(typeof cookie!=='string'||!cookie||typeof actor!=='string'||!actor||/[\r\n]/.test(cookie+actor))throw unavailable();
  if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(operation_id||''))throw unavailable();
  let response;
  try{
   response=await fetchImpl(endpoint+(method==='GET'?'?operation_id='+operation_id:''),{method,redirect:'error',signal:signal??AbortSignal.timeout(60000),
    headers:{Cookie:cookie,'X-FS-Actor':actor,'X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin','Content-Type':'application/json'},
    ...(method==='POST'?{body:JSON.stringify({contract:'campaign_recommendation_v1',operation_id,input})}:{})});
  }catch(error){if(error?.cause?.code==='ECONNREFUSED')throw unavailable();throw unknown();}
  if([401,403,413].includes(response.status)||response.status===404&&method==='POST')throw unavailable();
  let payload;
  try{
   if(Number(response.headers.get('content-length'))>1048576){await response.body?.cancel();throw unknown();}
   const reader=response.body?.getReader();if(!reader)throw unknown();const chunks=[];let size=0;
   try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>1048576){await reader.cancel();throw unknown();}chunks.push(value);}}
   finally{reader.releaseLock();}
   payload=JSON.parse(Buffer.concat(chunks).toString('utf8'));
  }catch{throw unknown();}
  if([200,202].includes(response.status)&&payload.status==='pending'&&payload.operation_id===operation_id){
   provider.receipt=projectWeeklyProviderReceipt(payload,operation_id);
   throw Object.assign(new Error('WEEKLY_HERMES_PROVIDER_PENDING'),{code:'WEEKLY_HERMES_PROVIDER_PENDING',provider_outcome:'pending'});
  }
  if(response.status===200&&payload.status==='unavailable'&&payload.error==='WEEKLY_HERMES_PROVIDER_UNAVAILABLE'&&payload.provider_outcome==='not_dispatched'&&payload.operation_id===operation_id)throw Object.assign(unavailable(),{original_outcome_confirmed:true});
  if(response.status===200&&payload.status==='failed'&&payload.error==='WEEKLY_HERMES_RECOMMENDATION_FAILED'&&payload.provider_outcome==='completed'&&payload.operation_id===operation_id&&payload.receipt?.operation_id===operation_id&&payload.receipt.model==='gpt-6.1-sol'){
   provider.receipt=projectWeeklyProviderReceipt(payload.receipt,operation_id);
   throw Object.assign(new Error('WEEKLY_HERMES_RECOMMENDATION_FAILED'),{code:'WEEKLY_HERMES_RECOMMENDATION_FAILED',provider_outcome:'completed',original_outcome_confirmed:true});
  }
  if(response.status!==200||payload.status!=='completed'||!payload.result||payload.receipt?.operation_id!==operation_id||payload.result.model!=='gpt-6.1-sol')throw unknown();
  provider.receipt=projectWeeklyProviderReceipt(payload.receipt,operation_id);
  return payload.result;
 }
 return provider;
}
