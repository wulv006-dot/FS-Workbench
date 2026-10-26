// Safe independent reference-price overlay. This public process never imports Admin transport.
import fs from 'node:fs';
import {projectRelease,canonical} from './snapshot.mjs';
import {projectModelOptions} from './model-options.mjs';
const exact=(x,keys)=>x&&typeof x==='object'&&!Array.isArray(x)&&Object.keys(x).every(k=>keys.includes(k));
export function readPublicPriceCache(file){
 try{const s=fs.lstatSync(file);if(!s.isFile()||s.isSymbolicLink()||s.size>250000)return null;return JSON.parse(fs.readFileSync(file,'utf8'));}catch{return null;}
}
export function applyPublicPriceCache(snapshot,cache,{now=Date.now()}={}){
 const base=projectRelease(snapshot),result={publication_status:'published',...structuredClone(base)};
 // Never fall back to an old Admin price embedded in immutable configuration/history.
 for(const contract of Object.values(result.seasonal_model_contracts||{}))for(const row of contract.combinations||[])if(row.price?.source==='admin_current')delete row.price;
 try{
  if(!exact(cache,['schema_version','status','release_id','config_hash','generated_at','products','model_contracts'])
    ||cache.schema_version!==1||cache.status!=='ready'||cache.release_id!==base.release_id||cache.config_hash!==base.config_hash
    ||!Number.isFinite(now)||!Number.isFinite(Date.parse(cache.generated_at))||Date.parse(cache.generated_at)>now
    ||!Array.isArray(cache.products)||!cache.products.length||cache.products.length>1) return result;
  const allowed=new Set(base.pages.find(p=>p.page_id==='seasonal-vault')?.product_keys||[]),products=[];
  for(const p of cache.products){
   const original=base.products.find(x=>x.key===p.key),r=p.product_ref;
   if(!original||!allowed.has(p.key)||canonical(original.product_ref)!==canonical(r)||canonical(original.platform)!==canonical(p.platform)
     ||r.site_id!=='266'||r.game_id!=='1327'||r.model_id!=='41217957'||r.goods_id!=='163329311'
     ||p.platform.attribute_id!=='21587'||p.available!==false||p.attributes?.length!==0
     ||canonical(p.quantity)!==canonical({min:'1000',max:'1000',step:'1',unit:'K'}))return result;
   products.push({...p,title:original.title});
  }
  if(!exact(cache.model_contracts,['41217957'])||!cache.model_contracts['41217957'])return result;
  const contracts=projectModelOptions(cache.model_contracts,products);
  for(const c of Object.values(contracts))for(const row of c.combinations){
   const p=row.price;
   if(!p||p.source!=='admin_current'||p.currency!=='USD'||p.minor_unit_scale!==2||p.quantity_value!=='1000'
     ||Date.parse(p.expires_at)<=now||Date.parse(p.expires_at)-Date.parse(cache.generated_at)>3600000
     ||row.choices.platform!=='21587'||row.choices.region!=='7645'||row.attributes.length
     ||canonical(row.quantity)!==canonical({min:'1000',max:'1000',step:'1',unit:'K'}))return result;
  }
  const candidate={...result,products:result.products.map(p=>products.find(x=>x.key===p.key)||p),
   seasonal_model_contracts:{...(result.seasonal_model_contracts||{}),...contracts}};
  return {publication_status:'published',...projectRelease({...candidate,publication_status:'published'})};
 }catch{return result;}
}
