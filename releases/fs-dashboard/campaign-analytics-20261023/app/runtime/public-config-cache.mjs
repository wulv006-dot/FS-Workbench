// One bounded, serialized public response. No receipts or commerce decisions.
export function publicConfigCache({ttlMs=0,now=Date.now,stamp,render}={}){
 if(!Number.isInteger(ttlMs)||ttlMs<0||ttlMs>5000||typeof render!=='function'||ttlMs>0&&typeof stamp!=='function')throw Error('INVALID_PUBLIC_CACHE_OPTIONS');
 let saved=null;
 return ()=>{
  const clock=now(),version=ttlMs?stamp():null;
  if(saved&&clock>=saved.at&&clock<saved.until&&version===saved.version)return saved.body;
  saved=null;
  const {body,expiresAt=Infinity}=render();if(typeof body!=='string')throw Error('INVALID_PUBLIC_CACHE_BODY');
  const finished=now(),until=Math.min(finished+ttlMs,expiresAt);
  if(ttlMs&&typeof version==='string'&&version&&Number.isFinite(clock)&&finished>=clock&&until>finished&&stamp()===version)saved={version,body,at:clock,until};
  return body;
 };
}

export function referenceDeadline(config){
 let deadline=Infinity;
 for(const contract of Object.values(config.seasonal_model_contracts||{}))for(const row of contract.combinations||[])if(row.price){const expires=Date.parse(row.price.expires_at);if(!Number.isFinite(expires))return -Infinity;deadline=Math.min(deadline,expires);}
 return deadline;
}
