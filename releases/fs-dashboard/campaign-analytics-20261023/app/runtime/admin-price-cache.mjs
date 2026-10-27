// Safe reference-price overlay. This public process never imports Admin transport.
// The management producer owns this file; neither editor drafts nor browsers write it.
import fs from 'node:fs';
import {projectRelease,canonical} from './snapshot.mjs';
import {projectModelOptions} from './model-options.mjs';
const exact=(x,keys)=>x&&typeof x==='object'&&!Array.isArray(x)&&Object.keys(x).every(k=>keys.includes(k));
export function readPublicPriceCache(file){
 try{const s=fs.lstatSync(file);if(!s.isFile()||s.isSymbolicLink()||s.size>4194304)return null;return JSON.parse(fs.readFileSync(file,'utf8'));}catch{return null;}
}
export function applyPublicPriceCache(snapshot,cache,{now=Date.now()}={}){
 const base=projectRelease(snapshot),result={publication_status:'published',...structuredClone(base)};
 // Never resurrect stale prices from immutable publication/history.
 for(const contract of Object.values(result.seasonal_model_contracts||{}))for(const row of contract.combinations||[])delete row.price;
 try{
  if(!exact(cache,['schema_version','status','release_id','config_hash','generated_at','products','model_contracts'])||cache.schema_version!==1||cache.status!=='ready'||cache.release_id!==base.release_id||cache.config_hash!==base.config_hash
   ||!Number.isFinite(now)||!Number.isFinite(Date.parse(cache.generated_at))||Date.parse(cache.generated_at)>now||!Array.isArray(cache.products)||!cache.products.length||cache.products.length>1000||new Set(cache.products.map(p=>p.key)).size!==cache.products.length)return result;
  const allowed=new Set(base.pages.find(p=>p.page_id==='seasonal-vault')?.product_keys||[]),products=[];
  for(const p of cache.products){
   const original=base.products.find(x=>x.key===p.key);
   if(!original||!allowed.has(p.key)||p.product_ref?.site_id!=='266'||canonical(original.product_ref)!==canonical(p.product_ref)||canonical(original.platform)!==canonical(p.platform)||p.available!==false)return result;
   // Preserve the native verified catalog. Older preview imports may be enriched
   // by the trusted producer, but never become available to server checkout.
   if(result.seasonal_model_contracts?.[p.product_ref.model_id]&&(canonical(original.quantity)!==canonical(p.quantity)||canonical(original.attributes)!==canonical(p.attributes)))return result;
   products.push({...p,title:original.title});
  }
  const contracts=projectModelOptions(cache.model_contracts,products);
  for(const [id,c] of Object.entries(contracts)){
   const existing=result.seasonal_model_contracts?.[id];
   if(existing&&(canonical(existing.model_ref)!==canonical(c.model_ref)||canonical(existing.fields)!==canonical(c.fields)))return result;
   for(const row of c.combinations){
    const p=row.price;if(!p||p.source!=='admin_current'||p.currency!=='USD'||p.minor_unit_scale!==2||Date.parse(p.expires_at)<=now||Date.parse(p.expires_at)-Date.parse(cache.generated_at)>3600000||p.quantity_value!==row.quantity.min||row.quantity.min!==row.quantity.max)return result;
    if(existing&&!existing.combinations.some(old=>old.product_key===row.product_key&&canonical(old.choices)===canonical(row.choices)&&canonical(old.attributes)===canonical(row.attributes)&&canonical(old.quantity)===canonical(row.quantity)))return result;
   }
  }
  const merged=structuredClone(result.seasonal_model_contracts||{});
  for(const [id,c] of Object.entries(contracts)){
   if(!merged[id]){merged[id]=c;continue;}
   // A partial fresh price read never deletes other verified server choices.
   for(const row of c.combinations){const target=merged[id].combinations.find(old=>old.product_key===row.product_key&&canonical(old.choices)===canonical(row.choices)&&canonical(old.attributes)===canonical(row.attributes)&&canonical(old.quantity)===canonical(row.quantity));target.price=row.price;}
  }
  const candidate={...result,products:result.products.map(p=>products.find(x=>x.key===p.key)||p),seasonal_model_contracts:merged};
  return {publication_status:'published',...projectRelease(candidate)};
 }catch{return result;}
}
