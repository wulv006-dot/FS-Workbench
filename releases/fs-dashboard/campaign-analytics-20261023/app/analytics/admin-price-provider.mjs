// Private management producer. Only safe projected JSON crosses to the public process.
import fs from 'node:fs';
import path from 'node:path';
import {atomic} from './store.mjs';
import {backendRead} from './backend-client.mjs';
import {canonical,digest,projectRelease} from '../runtime/snapshot.mjs';
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
// One entry per drawable model. The event pool grew past the original cap of 20,
// so the ceiling follows the catalogue: the refresh stays inside one 60s cycle
// because each entry is a single bounded read.
const MAX_PRICE_ENTRIES=80;
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
 const cacheFile=path.join(publicDir,'admin-reference-prices.json');let memory=[],flight=null,generation=0,key=null,timer=null,interval=null,started=false,attemptKey=null,attemptedAt=null;
 let status={status:'blocked',reason:'PRIVATE_PRICE_POLICY_REQUIRED'};
 const clear=reason=>{memory=[];status={status:'blocked',reason:code(reason)};};
 const schedule=config=>{if(!started)return;const next=config?.refresh_interval_ms??null;if(next===interval)return;
  if(timer)clearTimer(timer);timer=null;interval=next;if(next!==null){timer=setTimer(()=>{void refresh().catch(()=>{});},next);timer.unref?.();}};
 const safeWrite=value=>{try{if(fs.lstatSync(publicDir).isSymbolicLink())throw Error();atomic(cacheFile,value);fs.chmodSync(cacheFile,0o644);}
  catch{try{fs.unlinkSync(cacheFile);}catch{}clear('PUBLIC_PRICE_CACHE_WRITE_FAILED');throw Error('PUBLIC_PRICE_CACHE_WRITE_FAILED');}};
 const unavailable=(release,reason)=>{clear(reason);if(!fs.existsSync(publicDir))return;
  safeWrite({schema_version:1,status:'unavailable',release_id:release?.release_id??null,
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
  if(current.key!==key){key=current.key;generation++;memory=[];}
  if(!current.config||!current.release){unavailable(current.release,!current.config?'PRIVATE_PRICE_POLICY_REQUIRED':'PUBLISHED_SELECTION_REQUIRED');return status;}
  const allowed=new Set(current.release.pages.find(x=>x.page_id==='seasonal-vault')?.product_keys||[]);
  const selectedByModel=new Map();
  for(const p of current.config.entries){
   const selected=current.release.products.filter(x=>allowed.has(x.key)&&Object.entries(p.model_ref).every(([k,v])=>x.product_ref?.[k]===v)&&p.verified_goods_ids.includes(x.product_ref.goods_id));
   if(selected.length!==p.verified_goods_ids.length||new Set(selected.map(x=>x.product_ref.goods_id)).size!==selected.length){unavailable(current.release,'PUBLISHED_SELECTION_REQUIRED');return status;}
   if(current.config.schema_version===2&&!current.release.seasonal_model_contracts?.[p.model_ref.model_id]){unavailable(current.release,'PRIVATE_NATIVE_CATALOG_REQUIRED');return status;}
   selectedByModel.set(p.model_ref.model_id,selected);
  }
  if(memory.length===current.config.entries.length&&memory.every(x=>now()-Date.parse(x.observation.observed_at)>=0&&now()-Date.parse(x.observation.observed_at)<x.policy.max_age_ms))return status;
  if(flight?.key===current.key)return flight.promise;
  if(attemptKey===current.key&&attemptedAt!==null&&now()-attemptedAt<current.config.refresh_interval_ms)return status;
  attemptKey=current.key;attemptedAt=now();
  const admitted=generation;
  // Publish invalidation before awaiting Admin; public reads cannot use stale success during refresh.
  unavailable(current.release,'REFERENCE_PRICE_REFRESHING');
  const promise=(async()=>{
   try{
    const products=[],raw={},observations=[],reads=new Map();
    for(const p of current.config.entries){
     const readKey=canonical([p.model_ref,p.category_id]);
     if(!reads.has(readKey))reads.set(readKey,await call({action:'model_provider_read',...p.model_ref,category_id:p.category_id},{timeout:25000}));
     const observation=reads.get(readKey);
     if(generation!==admitted)return status;
     const latest=context();
     if(latest.key!==current.key){key=latest.key;generation++;unavailable(latest.release,'PRIVATE_POLICY_OR_RELEASE_CHANGED');return status;}
     const projected=projectAdminPrices(observation,p,{now:now()});
     if(projected.status!=='reference_price_ready_not_checkout'){unavailable(current.release,projected.reason);return status;}
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
    }
    if(products.length>1000)throw Error('PUBLIC_CATALOG_LIMIT');
    safeWrite({schema_version:1,status:'ready',release_id:current.release.release_id,config_hash:current.release.config_hash,
     generated_at:new Date(now()).toISOString(),products,model_contracts:projectModelOptions(raw,products)});
    memory=observations;status={status:'reference_price_ready_not_checkout',reason:null};return status;
   }catch(error){if(generation===admitted)unavailable(current.release,code(error.code||error.message));return status;}
  })();
  flight={key:current.key,promise};try{return await promise;}finally{if(flight?.promise===promise)flight=null;}
 }
 return {refresh,start:()=>{started=true;return refresh();},stop:()=>{started=false;if(timer)clearTimer(timer);timer=null;interval=null;},
  seedOptions:()=>{const c=context();if(c.key!==key){generation++;key=c.key;unavailable(c.release,'PRIVATE_POLICY_OR_RELEASE_CHANGED');}
   const valid=memory.filter(x=>projectAdminPrices(x.observation,x.policy,{now:now()}).status==='reference_price_ready_not_checkout');
   if(valid.length!==memory.length)unavailable(c.release,'CATALOG_STALE');return {adminObservations:c.config?.schema_version===2?[]:structuredClone(valid),now:now()};},
  status:()=>structuredClone(status),cacheFile};
}
