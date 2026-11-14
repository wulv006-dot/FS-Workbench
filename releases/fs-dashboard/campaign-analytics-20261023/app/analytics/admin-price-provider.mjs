// Private management producer. Only safe projected JSON crosses to the public process.
import fs from 'node:fs';
import path from 'node:path';
import {atomic} from './store.mjs';
import {backendRead} from './backend-client.mjs';
import {canonical,digest,projectRelease} from '../runtime/snapshot.mjs';
import {readPublicPriceCache} from '../runtime/admin-price-cache.mjs';
import {projectAdminPrices} from '../runtime/admin-price-projection.mjs';
import {projectModelOptions} from '../runtime/model-options.mjs';
const code=x=>typeof x==='string'&&/^[A-Z][A-Z0-9_]{0,79}$/.test(x)?x:'ADMIN_PRICE_UNAVAILABLE';
export function readAdminPricePolicy(stateDir){
 const file=path.join(stateDir,'policy.json');
 if(!fs.existsSync(file))return null;
 const d=fs.lstatSync(stateDir),s=fs.lstatSync(file);
 if(d.isSymbolicLink()||!d.isDirectory()||s.isSymbolicLink()||!s.isFile()||s.size>4194304
   ||process.platform!=='win32'&&((d.mode&0o077)!==0||(s.mode&0o077)!==0))throw Error('PRIVATE_PRICE_POLICY_REQUIRED');
 return JSON.parse(fs.readFileSync(file,'utf8')).admin_reference_prices??null;
}
// Retained Halloween contracts and successive FC drafts share the bounded catalogue.
const MAX_PRICE_ENTRIES=300;
function configuration(value,now){
 if(!value||![1,2].includes(value.schema_version)||Object.keys(value).some(k=>!['schema_version','refresh_interval_ms','entries'].includes(k))
   ||!Number.isSafeInteger(value.refresh_interval_ms)||value.refresh_interval_ms<60000||value.refresh_interval_ms>300000
   ||!Array.isArray(value.entries)||!value.entries.length||value.entries.length>MAX_PRICE_ENTRIES)return null;
 const fields=['category_id','model_ref','baseline_region','regional_adjustment','currency','minor_unit_scale','source_field','price_semantics','rounding_contract','evidence_ref','max_age_ms','quantity_value','quantity_unit','verified_goods_ids','ordered_goods_ids','ordering_evidence','descriptive_baseprop'];
 const seen=new Set(),numeric=x=>typeof x==='string'&&/^[1-9]\d{0,19}$/.test(x);
 for(const p of value.entries){
  const ref=p?.model_ref;
  if(!p||Object.keys(p).some(k=>!fields.includes(k))||!numeric(p.category_id)||ref?.site_id!=='266'||!numeric(ref.game_id)||!numeric(ref.model_id)||seen.has(canonical([ref.model_id,p.quantity_value,p.quantity_unit]))
    ||p.minor_unit_scale!==2||!Array.isArray(p.verified_goods_ids)||!p.verified_goods_ids.length||p.verified_goods_ids.length>200||p.verified_goods_ids.some(x=>!numeric(x))||new Set(p.verified_goods_ids).size!==p.verified_goods_ids.length
    ||!Number.isSafeInteger(p.max_age_ms)||value.refresh_interval_ms>p.max_age_ms||p.max_age_ms>3600000||projectAdminPrices(undefined,p,{now}).reason!=='CATALOG_STALE')return null;
  seen.add(canonical([ref.model_id,p.quantity_value,p.quantity_unit]));
 }
 // Preserve the existing v1 private policy scope. A multi-model producer must be
 // deliberately configured with the new reviewed v2 entries, never inferred.
 if(value.schema_version===1){const p=value.entries[0];if(value.entries.length!==1||p.category_id!=='9623'||canonical(p.model_ref)!==canonical({site_id:'266',game_id:'1327',model_id:'41217957'})||p.quantity_value!=='1000'||p.quantity_unit!=='K'||canonical(p.verified_goods_ids)!==canonical(['163329311']))return null;}
 return structuredClone(value);
}
export function makeAdminPriceProvider({publicDir,readPolicy,readSnapshot=()=>JSON.parse(fs.readFileSync(path.join(publicDir,'current.json'),'utf8')),
 call=backendRead,now=Date.now,setTimer=setInterval,clearTimer=clearInterval}={}){
 const cacheFile=path.join(publicDir,'admin-reference-prices.json');let memory=[],sticky=new Map(),flight=null,generation=0,key=null,timer=null,interval=null,started=false,attemptKey=null,attemptedAt=null;
 let status={status:'blocked',reason:'PRIVATE_PRICE_POLICY_REQUIRED'};
 const clear=reason=>{memory=[];status={status:'blocked',reason:code(reason)};};
 const schedule=config=>{if(!started)return;const next=config?.refresh_interval_ms??null;if(next===interval)return;
  if(timer)clearTimer(timer);timer=null;interval=next;if(next!==null){timer=setTimer(()=>{void refresh().catch(()=>{});},next);timer.unref?.();}};
 const safeWrite=value=>{try{if(fs.lstatSync(publicDir).isSymbolicLink())throw Error();atomic(cacheFile,value);fs.chmodSync(cacheFile,0o644);}
  catch{try{fs.unlinkSync(cacheFile);}catch{}clear('PUBLIC_PRICE_CACHE_WRITE_FAILED');throw Error('PUBLIC_PRICE_CACHE_WRITE_FAILED');}};
 const unavailable=(release,reason)=>{clear(reason);if(!fs.existsSync(publicDir))return;
  safeWrite({schema_version:1,status:reason==='REFERENCE_PRICE_REFRESHING'?'refreshing':'unavailable',release_id:release?.release_id??null,
   config_hash:release?.config_hash??null,generated_at:new Date(now()).toISOString(),products:[],model_contracts:{}});};
 function context(){
  let config,release;
  try{config=configuration(readPolicy(),now());}catch{config=null;}
  schedule(config);
  try{release=projectRelease(readSnapshot());}catch{release=null;}
  return {config,release,key:digest(canonical({config,release:release?{release_id:release.release_id,config_hash:release.config_hash}:null}))};
 }
 async function refresh(){
  const current=context();
  if(current.key!==key){key=current.key;generation++;memory=[];sticky=new Map();}
  if(!current.config||!current.release){unavailable(current.release,!current.config?'PRIVATE_PRICE_POLICY_REQUIRED':'PUBLISHED_SELECTION_REQUIRED');return status;}
  const allowed=new Set(current.release.pages.filter(x=>['seasonal-vault','fc27-trio','fc27-weekly','fc27-sbc'].includes(x.page_id)).flatMap(x=>x.product_keys||[]));
  const selectedByModel=new Map(),activeEntries=[];
  for(const p of current.config.entries){
   const scoped=current.release.products.filter(x=>allowed.has(x.key)&&Object.entries(p.model_ref).every(([k,v])=>x.product_ref?.[k]===v));
   // Private policy retains previous weekly selections. Only wholly unselected
   // models are inactive; selected models still require every verified mapping.
   if(!scoped.length)continue;
   const selected=scoped.filter(x=>!x.model_card_key&&p.verified_goods_ids.includes(x.product_ref.goods_id));
   if(selected.length!==p.verified_goods_ids.length||new Set(selected.map(x=>x.product_ref.goods_id)).size!==selected.length){unavailable(current.release,'PUBLISHED_SELECTION_REQUIRED');return status;}
   if(current.config.schema_version===2&&!current.release.seasonal_model_contracts?.[p.model_ref.model_id]){unavailable(current.release,'PRIVATE_NATIVE_CATALOG_REQUIRED');return status;}
   selectedByModel.set(p.model_ref.model_id,selected);activeEntries.push(p);
  }
  if(!activeEntries.length){unavailable(current.release,'PUBLISHED_SELECTION_REQUIRED');return status;}
  // Start the next read before prices expire; a full catalogue sweep takes minutes.
  if(memory.length===activeEntries.length&&memory.every(x=>now()-Date.parse(x.observation.observed_at)>=0&&now()-Date.parse(x.observation.observed_at)<x.policy.max_age_ms-current.config.refresh_interval_ms))return status;
  if(flight?.key===current.key)return flight.promise;
  if(attemptKey===current.key&&attemptedAt!==null&&now()-attemptedAt<current.config.refresh_interval_ms)return status;
  attemptKey=current.key;attemptedAt=now();
  const admitted=generation;
  // The public overlay checks each price's expiry while the next read is in flight.
  if(!memory.length){
   const previous=readPublicPriceCache(cacheFile);
   if(previous?.status!=='ready'||previous.release_id!==current.release.release_id||previous.config_hash!==current.release.config_hash)unavailable(current.release,'REFERENCE_PRICE_REFRESHING');
  }
  const promise=(async()=>{
   try{
    const products=[],raw={},observations=[],reads=new Map(),missing=[];
    // Warm every distinct model read concurrently. The projection below stays
    // sequential, so ordering and the generation checks are unchanged; only the
    // Admin round trips overlap. Without this a 44-model pool cannot finish
    // inside one refresh window.
    const warmEntries=new Map();
    for(const p of activeEntries){
     const readKey=canonical([p.model_ref,p.category_id]);
     if(!warmEntries.has(readKey))warmEntries.set(readKey,p);
    }
    const warmList=[...warmEntries.entries()];
    // Cache the promise, not the value: a failure surfaces exactly once in the
    // sequential pass below instead of being retried by it.
    // One Admin sweep per game replaces one sweep per model. The list route is the call
    // that stalls for 40-70s on roughly a third of attempts (2026-10-28: the same query
    // measured 130ms and 70s within one minute), so 49 independent sweeps could never all
    // finish inside one window. Games are read one after another, and a game's failure
    // stays with its own models, so a stalled game no longer voids every other price.
    const games=new Map();
    for(const [readKey,p] of warmList){
      const gameKey=canonical([p.model_ref.site_id,p.model_ref.game_id]);
      if(!games.has(gameKey))games.set(gameKey,[]);
      games.get(gameKey).push([readKey,p]);
    }
    for(const gameMembers of games.values())for(let offset=0;offset<gameMembers.length;offset+=100){
      const members=gameMembers.slice(offset,offset+100);
      const items=members.map(([readKey,p])=>({key:readKey,site_id:p.model_ref.site_id,
        game_id:p.model_ref.game_id,model_id:p.model_ref.model_id,category_id:p.category_id}));
      const started=[];
      let readings=null,failure=null;
      // A full 44-model sweep with its own per-model detail reads measured 196s on
      // 2026-10-28; the child budget has to sit above that or the whole game is killed
      // mid-flight and reported as a failure that never happened.
      try{readings=(await call({action:'model_provider_batch',site_id:'266',items},{timeout:300000}))?.readings||null;}
      catch(error){failure=error;}
      for(const [readKey] of members){
        const reading=readings?.[readKey];
        const pending=reading?.status==='ok'?Promise.resolve(reading.data)
          :Promise.reject(failure||Object.assign(new Error(reading?.error||'BATCH_READING_MISSING'),{status:502}));
        pending.catch(()=>{});
        reads.set(readKey,pending);started.push(pending);
      }
      await Promise.allSettled(started);
    }
    for(const p of activeEntries){
     const readKey=canonical([p.model_ref,p.category_id]);
     // A failed read is not fatal on its own: the entry's own freshness window decides
     // whether the last good observation may still stand in for it. Awaiting the rejected
     // promise here used to throw straight to the outer catch and void every other price.
     let observation=null;
     try{observation=await reads.get(readKey);}catch{observation=null;}
     if(generation!==admitted)return status;
     const latest=context();
     if(latest.key!==current.key){key=latest.key;generation++;unavailable(latest.release,'PRIVATE_POLICY_OR_RELEASE_CHANGED');return status;}
     let projected=projectAdminPrices(observation,p,{now:now()});
     if(projected.status!=='reference_price_ready_not_checkout'){
      // The Admin catalogue stalls for up to a minute on a single read now and then (the
      // same query measured 130ms and 70s within one minute on 2026-10-28). Every entry
      // already carries a freshness window, so fall back to this entry's last good
      // observation while it is still inside max_age_ms instead of throwing away every
      // other model's price because one read was slow.
      const prior=sticky.get(canonical(p));
      if(prior){projected=projectAdminPrices(prior.observation,p,{now:now()});if(projected.status==='reference_price_ready_not_checkout')observation=prior.observation;}
     }
     if(projected.status!=='reference_price_ready_not_checkout'){missing.push(code(projected.reason));continue;}
     if(current.config.schema_version===1&&(projected.products.length!==1||projected.products[0].platform.attribute_id!=='21587'||projected.model_contracts[p.model_ref.model_id].combinations.some(row=>row.choices.platform!=='21587'||row.choices.region!=='7645')))throw Error('PUBLIC_OPTIONS_CONFLICT');
     const selected=selectedByModel.get(p.model_ref.model_id),remap=new Map(projected.products.map(x=>[x.key,selected.find(s=>s.product_ref.goods_id===x.product_ref.goods_id)?.key]));
     if([...remap.values()].some(x=>!x))throw Error('PUBLISHED_SELECTION_REQUIRED');
     const freshProducts=projected.products.map(x=>{
      const known=selected.find(s=>s.key===remap.get(x.key));
      if(current.release.seasonal_model_contracts?.[p.model_ref.model_id]){
       if(canonical(known.product_ref)!==canonical(x.product_ref)||known.platform.attribute_id!==x.platform.attribute_id||!current.release.seasonal_model_contracts[p.model_ref.model_id].combinations.some(c=>c.product_key===known.key&&canonical(c.quantity)===canonical(x.quantity)&&canonical(c.attributes)===canonical(x.attributes)))throw Error('PUBLIC_OPTIONS_CONFLICT');
       return {...structuredClone(known),available:false};
      }
      return {...x,key:known.key,title:known.title};
     });
     for(const p of freshProducts){const previous=products.find(x=>x.key===p.key);if(previous&&canonical(previous)!==canonical(p))throw Error('PUBLIC_OPTIONS_CONFLICT');if(!previous)products.push(p);}
     const contracts=structuredClone(projected.model_contracts);for(const c of Object.values(contracts))for(const row of c.combinations)row.product_key=remap.get(row.product_key);
     for(const [model,c] of Object.entries(contracts)){
      const verified=current.release.seasonal_model_contracts?.[model];
      if(verified){
       const combinations=verified.combinations.flatMap(row=>{
        const prices=c.combinations.filter(x=>x.product_key===row.product_key&&canonical(x.attributes)===canonical(row.attributes)&&canonical(x.quantity)===canonical(row.quantity));
        return prices.length===1?[{...structuredClone(row),price:prices[0].price}]:[];
       });
       if(!combinations.length)throw Error('PUBLIC_OPTIONS_CONFLICT');
       contracts[model]={...structuredClone(verified),combinations};
      }
     }
     for(const [model,c] of Object.entries(contracts)){
      if(!raw[model])raw[model]=c;
      else for(const row of c.combinations){if(raw[model].combinations.some(old=>canonical(old.choices)===canonical(row.choices)))throw Error('DUPLICATE_PRICE_TIER');raw[model].combinations.push(row);}
     }
     observations.push({observation,policy:p});
     // Keep each good read across cycles: one slow model later in the same cycle must not
     // erase a model that was read successfully a minute ago, otherwise a cycle can never
     // converge while the upstream keeps stalling.
     sticky.set(canonical(p),{observation,policy:p});
    }
    if(!products.length){unavailable(current.release,missing[0]||'ADMIN_PRICE_UNAVAILABLE');return status;}
    if(products.length>1000)throw Error('PUBLIC_CATALOG_LIMIT');
    safeWrite({schema_version:1,status:'ready',release_id:current.release.release_id,config_hash:current.release.config_hash,
     generated_at:new Date(now()).toISOString(),products,model_contracts:projectModelOptions(raw,products)});
    memory=observations;status={status:missing.length?'reference_price_partial_not_checkout':'reference_price_ready_not_checkout',reason:missing[0]||null};return status;
   }catch(error){if(generation===admitted)unavailable(current.release,code(error.code||error.message));return status;}
  })();
  flight={key:current.key,promise};try{return await promise;}finally{if(flight?.promise===promise)flight=null;}
 }
 return {refresh,start:()=>{started=true;return refresh();},stop:()=>{started=false;if(timer)clearTimer(timer);timer=null;interval=null;},
  seedOptions:()=>{const c=context();if(c.key!==key){generation++;key=c.key;unavailable(c.release,'PRIVATE_POLICY_OR_RELEASE_CHANGED');}
   const valid=memory.filter(x=>projectAdminPrices(x.observation,x.policy,{now:now()}).status==='reference_price_ready_not_checkout');
   if(memory.length&&!valid.length)unavailable(c.release,'CATALOG_STALE');return {adminObservations:c.config?.schema_version===2?[]:structuredClone(valid),now:now()};},
  status:()=>structuredClone(status),cacheFile};
}
