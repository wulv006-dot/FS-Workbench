// Trusted observed option mappings join the existing products seed. Editor drafts
// cannot supply this private input. Prices remain in the independent price feed.
import fs from 'node:fs';
import path from 'node:path';
import {projectRelease,canonical,fail} from '../runtime/snapshot.mjs';
import {projectModelOptions} from '../runtime/model-options.mjs';
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).every(k=>keys.includes(k));
export function projectNativeCatalog(value,{now=Date.now()}={}){
 if(!exact(value,['schema_version','verification_ref','observed_at','valid_until','products','model_contracts'])||value.schema_version!==1||!/^[-A-Za-z0-9_.:]{1,128}$/.test(value.verification_ref||'')
   ||!Number.isFinite(Date.parse(value.observed_at))||!Number.isFinite(Date.parse(value.valid_until))||!Number.isFinite(now)||Date.parse(value.observed_at)>now||Date.parse(value.valid_until)<=now
   ||!Array.isArray(value.products)||!value.products.length||value.products.length>1000||value.products.some(p=>p.available!==false||p.preview_only===true||p.product_ref?.site_id!=='266'||!p.product_ref?.model_id))fail('NATIVE_CATALOG_INVALID');
 const products=projectRelease({schema_version:1,publication_status:'published',release_id:'native-catalog',source_revision:'native-catalog',config_hash:'0'.repeat(64),rule_hash:'0'.repeat(64),pages:[],products:value.products}).products;
 const raw=structuredClone(value.model_contracts);for(const contract of Object.values(raw||{}))for(const combo of contract.combinations||[])delete combo.price;
 const model_contracts=projectModelOptions(raw,products);
 if(products.some(p=>!model_contracts[p.product_ref.model_id]?.combinations.some(c=>c.product_key===p.key)))fail('NATIVE_CATALOG_INVALID');
 return {products,model_contracts,valid_until:new Date(value.valid_until).toISOString()};
}
export function readNativeLaunchPolicy(stateDir,{now=Date.now()}={}){
 const file=path.join(stateDir,'policy.json');if(!fs.existsSync(file))return {checkout:{status:'unconfigured'},catalog:null};
 const d=fs.lstatSync(stateDir),s=fs.lstatSync(file);
 if(d.isSymbolicLink()||!d.isDirectory()||s.isSymbolicLink()||!s.isFile()||s.size>4194304||process.platform!=='win32'&&((d.mode&0o077)!==0||(s.mode&0o077)!==0))fail('PRIVATE_NATIVE_POLICY_REQUIRED');
 const policy=JSON.parse(fs.readFileSync(file,'utf8')),catalog=policy.native_catalog?projectNativeCatalog(policy.native_catalog,{now}):null,checkout=structuredClone(policy.native_checkout??{status:'unconfigured'});
 if(checkout.bindings?.some(b=>b.observed_serialization)){
  if(!catalog)fail('NATIVE_CATALOG_REQUIRED');
  for(const b of checkout.bindings.filter(b=>b.observed_serialization)){
   const p=catalog.products.find(p=>p.key===b.product_key),proof=b.observed_serialization;
   if(!p||p.product_ref.game_id!==proof.game_id||p.product_ref.model_id!==proof.model_id||p.product_ref.goods_id!==b.native?.id)fail('NATIVE_CATALOG_SCOPE_MISMATCH');
  }
 }
 return {checkout,catalog};
}
export function mergeNativeCatalog(seed,catalog){
 if(!catalog)return seed;catalog=structuredClone(catalog);const out=structuredClone(seed),products=out.seedProducts;
 for(const p of catalog.products){
  const index=products.findIndex(x=>x.key===p.key);
  if(index<0)products.push(p);else{
   if(canonical(products[index].product_ref)!==canonical(p.product_ref)||canonical(products[index].platform)!==canonical(p.platform))fail('NATIVE_CATALOG_SCOPE_MISMATCH');
   products[index]=p;
  }
 }
 out.seasonal_model_contracts={...(out.seasonal_model_contracts||{})};
 for(const [key,contract] of Object.entries(catalog.model_contracts)){
  const priced=out.seasonal_model_contracts[key];
  if(priced){
   // Preserve current independent reference prices only on identical options.
   for(const combo of contract.combinations){const old=priced.combinations.find(c=>c.product_key===combo.product_key&&canonical(c.choices)===canonical(combo.choices)&&canonical(c.attributes)===canonical(combo.attributes)&&canonical(c.quantity)===canonical(combo.quantity));if(old?.price)combo.price=old.price;}
  }
  out.seasonal_model_contracts[key]=contract;
 }
 out.pageProductKeys['seasonal-vault']=[...new Set([...(out.pageProductKeys['seasonal-vault']||[]),...catalog.products.map(p=>p.key)])];
 out.nativeModelKeys={};
 const previews=products.filter(p=>p.preview_only===true&&p.model_card_key);
 if(previews.length){
  const matches=new Map();
  for(const product of catalog.products){
   const identity=JSON.stringify([canonical(product.product_ref),canonical(product.platform)]);
   matches.set(identity,matches.has(identity)?null:product);
  }
  for(const preview of previews){
   const identity=JSON.stringify([canonical(preview.product_ref),canonical(preview.platform)]),match=matches.get(identity);
   if(match)out.nativeModelKeys[preview.key]=match.key;
  }
 }
 for(const pageId of ['fc27-trio','fc27-weekly','fc27-sbc']){
  const keys=out.pageProductKeys[pageId]||[];
  out.pageProductKeys[pageId]=[...new Set([...keys,...keys.flatMap(key=>out.nativeModelKeys[key]?[out.nativeModelKeys[key]]:[])])];
 }
 return out;
}
