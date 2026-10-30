const networks=new Set(['ECONNRESET','ETIMEDOUT','EAI_AGAIN','ECONNREFUSED','ENETUNREACH','EHOSTUNREACH']);
export function retryAfterMs(value,now=Date.now()){
 if(typeof value!=='string'||!value.trim())return null;
 if(/^\d+$/.test(value.trim()))return Math.min(Number.MAX_SAFE_INTEGER,Number(value.trim())*1000);
 if(!/^[A-Za-z]{3}, \d{2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} GMT$/.test(value.trim()))return null;
 const date=Date.parse(value);return Number.isFinite(date)?Math.max(0,date-now):null;
}
// Only allowlisted transient causes cross the snapshot boundary; never persist arbitrary errors.
export function transientFailure(error){
 const message=String(error?.message||''),code=error?.cause?.code||error?.code;
 let reason=null;
 if(error?.name==='TimeoutError'||['SOURCE_TIMEOUT','BACKEND_READ_TIMEOUT','LOG_READ_TIMEOUT'].includes(message))reason=message==='LOG_READ_TIMEOUT'?message:'SOURCE_TIMEOUT';
 const http=/^(?:PostHog query returned |SOURCE_HTTP_)(\d{3})$/.exec(message);
 if(http&&(Number(http[1])===408||Number(http[1])===429||Number(http[1])>=500&&Number(http[1])<=599))reason='SOURCE_HTTP_'+http[1];
 const network=/^SOURCE_NETWORK_([A-Z_]+)$/.exec(message)?.[1]||code;
 if(networks.has(network))reason='SOURCE_NETWORK_'+network;
 if(message==='LOG_ROTATED_DURING_READ')reason=message;
 if(!reason)return null;
 return {reason,...(Number.isFinite(error?.retryAfterMs)&&error.retryAfterMs>=0?{retryAfterMs:error.retryAfterMs}:{})};
}
export async function retrySource(read,{deadline,attemptTimeoutMs,clock=Date.now,sleep=ms=>new Promise(r=>setTimeout(r,ms)),isCurrent=()=>true}){
 const started=clock(),history=[];let result={status:'unavailable',reason:'RUN_TIME_BUDGET_EXHAUSTED'},stopReason=null;
 for(let attempt=1;attempt<=3;attempt++){
  if(!isCurrent()){result={status:'unavailable',reason:'SOURCE_CONTEXT_CHANGED'};stopReason='context_changed';break;}
  // Reserve the existing source's full timeout plus teardown margin; the outer 390s kill remains.
  if(clock()+attemptTimeoutMs+1000>deadline){stopReason='run_budget';break;}
  const at=clock();result=await read();
  if(!isCurrent())result={status:'unavailable',reason:'SOURCE_CONTEXT_CHANGED'};
  history.push({attempt,status:result.status,reason:result.reason||null,elapsedMs:Math.max(0,clock()-at)});
  if(result.status==='available')break;
  const transient=result.status==='unavailable'&&!result.blocked?transientFailure({message:result.reason,retryAfterMs:result.retryAfterMs}):null;
  if(!transient){stopReason=result.reason==='SOURCE_CONTEXT_CHANGED'?'context_changed':'not_retryable';break;}
  if(attempt===3){stopReason='attempt_limit';break;}
  const waitMs=Math.max([2000,5000][attempt-1],transient.retryAfterMs||0);
  if(clock()+waitMs+attemptTimeoutMs+1000>deadline){stopReason='run_budget';break;}
  history.at(-1).waitMs=waitMs;await sleep(waitMs);
 }
 return {...result,retry:{attemptCount:history.length,retryCount:Math.max(0,history.length-1),elapsedMs:Math.max(0,clock()-started),stopReason,attempts:history}};
}
