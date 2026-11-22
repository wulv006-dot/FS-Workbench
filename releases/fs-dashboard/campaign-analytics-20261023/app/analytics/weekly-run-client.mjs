import {fail} from '../runtime/snapshot.mjs';
const endpoint='http://127.0.0.1:8931/internal/hermes/campaign-weekly';
const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
// Credentials stay request-local. The host owns bounded delegation and original-ID recovery.
export async function weeklyRunCall({method,body,operation_id,cookie,actor,fetchImpl=fetch}){
 if(!['GET','POST'].includes(method)||typeof cookie!=='string'||!cookie||typeof actor!=='string'||!actor||/[\r\n]/.test(cookie+actor))fail('WEEKLY_SESSION_REQUIRED',403);
 if(method==='POST'){
  if(!body||Object.keys(body).some(k=>!['action','operation_id','revision','enabled','trio_review','sources'].includes(k))||!['run','configure','reconcile','resume','supplement_sources'].includes(body.action)||!uuid(body.operation_id))fail('WEEKLY_RUN_REQUEST_INVALID');
  if(body.action==='configure'&&(!Number.isSafeInteger(body.revision)||body.revision<0||typeof body.enabled!=='boolean'))fail('WEEKLY_RUN_REQUEST_INVALID');
  if(body.action!=='run'&&Object.hasOwn(body,'trio_review'))fail('WEEKLY_RUN_REQUEST_INVALID');
  if(body.action==='supplement_sources'){
   if(!body.sources||Object.keys(body).some(k=>!['action','operation_id','sources'].includes(k)))fail('WEEKLY_RUN_REQUEST_INVALID');
  }else if(Object.hasOwn(body,'sources')||body.action!=='configure'&&Object.keys(body).some(k=>!['action','operation_id','trio_review'].includes(k)))fail('WEEKLY_RUN_REQUEST_INVALID');
  operation_id=body.operation_id;
 }else if(operation_id!=null&&!uuid(operation_id))fail('INVALID_OPERATION_ID');
 let response;
 try{response=await fetchImpl(endpoint+(method==='GET'&&operation_id?'?operation_id='+operation_id:''),{method,redirect:'error',signal:AbortSignal.timeout(60000),headers:{Cookie:cookie,'X-FS-Actor':actor,'X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin','Content-Type':'application/json'},...(method==='POST'?{body:JSON.stringify(body)}:{})});}
 catch{fail('WEEKLY_HOST_UNAVAILABLE_OR_OUTCOME_UNKNOWN',502);}
 if(![200,202,404,409,422].includes(response.status)){await response.body?.cancel();fail(response.status===403?'WEEKLY_HOST_PERMISSION_DENIED':'WEEKLY_HOST_UNAVAILABLE_OR_OUTCOME_UNKNOWN',response.status===403?403:502);}
 if(Number(response.headers.get('content-length'))>1048576){await response.body?.cancel();fail('WEEKLY_HOST_RESPONSE_INVALID',502);}
 let value;try{const reader=response.body.getReader(),parts=[];let size=0;try{while(true){const chunk=await reader.read();if(chunk.done)break;size+=chunk.value.byteLength;if(size>1048576){await reader.cancel();throw Error();}parts.push(chunk.value);}}finally{reader.releaseLock();}value=JSON.parse(Buffer.concat(parts).toString('utf8'));}catch{fail('WEEKLY_HOST_RESPONSE_INVALID',502);}
 if([404,409,422].includes(response.status)){
  const known={campaign_weekly_not_found:'WEEKLY_RUN_NOT_FOUND',campaign_weekly_invalid_request:'WEEKLY_RUN_REQUEST_REJECTED',campaign_weekly_revision_conflict:'WEEKLY_RUN_REVISION_CONFLICT'};
  if(!known[value?.error]||value.operation_id!=null&&value.operation_id!==operation_id)fail('WEEKLY_HOST_RESPONSE_INVALID',502);
  throw Object.assign(new Error(known[value.error]),{code:known[value.error],status:response.status,operation_id});
 }
 if(!value||typeof value!=='object'||Array.isArray(value)||operation_id&&value.operation_id!==operation_id)fail('WEEKLY_HOST_RESPONSE_INVALID',502);
 return value;
}
