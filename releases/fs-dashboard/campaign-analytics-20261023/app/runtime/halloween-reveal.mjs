// Reuse the public runtime's private durable directory; no Admin/cart writes.
import fs from 'node:fs';
import path from 'node:path';
import {randomInt} from 'node:crypto';
import {atomic} from '../analytics/store.mjs';
import {canonical,digest,fail} from './snapshot.mjs';
import {eligibleHalloweenPool} from './halloween-contract.mjs';

const uuid=value=>{if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value||''))fail('INVALID_REQUEST');return value;};
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).every(k=>keys.includes(k));
export function createHalloweenReveals({dir,current,now=Date.now,catalogProvider}={}){
 const location=id=>path.join(dir,'halloween-reveals',uuid(id)+'.json');
 function context(gameId){
  const release=current(),h=release.halloween,page=release.pages.find(p=>p.page_id==='seasonal-vault'&&p.activity_id==='mmoexp-seasonal'),game=h?.games.find(g=>g.id===gameId),clock=now();
  if(!page?.active||!game||h.status!=='configured')fail('HALLOWEEN_NOT_CONFIGURED',409);
  if(!Number.isFinite(clock)||clock<Date.parse(h.starts_at)||clock>Date.parse(h.ends_at)||page.starts_at&&clock<Date.parse(page.starts_at)||page.ends_at&&clock>Date.parse(page.ends_at))fail('PROMOTION_EXPIRED',409);
  const config=release.native_checkout;
  if(config?.status!=='configured'||clock<Date.parse(config.valid_from)||clock>Date.parse(config.valid_until))fail('NATIVE_CHECKOUT_UNCONFIGURED',409);
  const tiers=h.probabilities.filter(p=>p.weight>0).map(p=>p.off_percent),allowed=new Set(page.product_keys);
  // A private, observed native binding is required for each selectable tier.
  // Catalog identity or a reference price alone never grants a purchase path.
  const supported=(model,discounts,quantity=null)=>{
   const contract=release.seasonal_model_contracts?.[model];
   return contract?.model_ref.game_id===game.admin_game_id&&discounts.every(off=>contract.combinations.some(combo=>{
    const product=release.products.find(p=>p.key===combo.product_key);
    return product&&!product.preview_only&&allowed.has(product.key)&&combo.price?.source==='admin_current'&&combo.price.base_minor>0&&Date.parse(combo.price.expires_at)>clock&&config.bindings.some(b=>b.page_id===page.page_id&&b.product_key===product.key&&b.off_percent===off&&b.quantity.unit===combo.quantity.unit&&b.quantity.value===(quantity?.value??combo.quantity.min)&&(!quantity||b.quantity.unit===quantity.unit&&combo.quantity.min===quantity.value&&combo.quantity.max===quantity.value)&&canonical(b.attributes)===canonical(combo.attributes));
   }));
  };
  const quantityMode=game.random_source.mode==='quantity_tiers';
  if(!supported(game.fixed_model,[game.fixed_off_percent],quantityMode?game.fixed_quantity:null))fail('HALLOWEEN_FIXED_MAPPING_REQUIRED',409);
  if(quantityMode){
   if(!game.random_quantities.every(q=>supported(game.fixed_model,tiers,q)))fail('HALLOWEEN_POOL_INCOMPLETE',409);
   return {release,h,game,models:[game.fixed_model],quantities:game.random_quantities};
  }
  const source=game.random_source;
  let observation;
  if(source.mode==='category_dynamic'){
   // Only a trusted server provider may supply current complete category data.
   // Never treat the editor's bounded search result as a whole dynamic pool.
   observation=catalogProvider?.(game,release);
   if(!observation||!Number.isFinite(Date.parse(observation.observed_at))||!Number.isFinite(Date.parse(observation.expires_at))||Date.parse(observation.observed_at)>clock||Date.parse(observation.expires_at)<=clock)fail('HALLOWEEN_CATALOG_STALE',409);
  }else observation={complete:true,models:game.random_models.map(model_id=>({site_id:'266',game_id:game.admin_game_id,category_id:source.category_id,model_id,sellable:supported(model_id,tiers)}))};
  const pool=eligibleHalloweenPool(game,observation);
  const models=pool.models.filter(model=>supported(model,tiers));
  if(pool.status!=='eligible_not_drawn'||models.length<2)fail('HALLOWEEN_POOL_INCOMPLETE',409);
  return {release,h,game,models};
 }
 function read(requestId){
  const file=location(requestId);if(!fs.existsSync(file))fail('HALLOWEEN_REVEAL_NOT_FOUND',404);
  let receipt;try{const stat=fs.lstatSync(file);if(stat.isSymbolicLink()||!stat.isFile()||stat.size>16000)throw Error();receipt=JSON.parse(fs.readFileSync(file,'utf8'));}catch{fail('HALLOWEEN_REVEAL_UNKNOWN',409);}
  if(receipt.status!=='revealed'||receipt.request_id!==requestId)fail('HALLOWEEN_REVEAL_UNKNOWN',409);
  const {release,game,models,h}=context(receipt.game_id);
  if(receipt.release_id!==release.release_id||receipt.config_hash!==release.config_hash||receipt.rule_hash!==release.rule_hash)fail('RULE_VERSION_CONFLICT',409);
  if(!exact(receipt,['status','request_id','request_hash','game_id','release_id','config_hash','rule_hash','created_at','slots'])||receipt.request_hash!==digest(canonical({request_id:requestId,game_id:receipt.game_id}))
    ||!Array.isArray(receipt.slots)||receipt.slots.length!==3||new Set(receipt.slots.map(s=>canonical([s?.model_id,s?.quantity||null]))).size!==3
    ||receipt.slots.some((s,i)=>!exact(s,['slot','model_id','off_percent','quantity'])||s.slot!==['fixed','random-1','random-2'][i]||(i===0?s.model_id!==game.fixed_model||s.off_percent!==game.fixed_off_percent:!models.includes(s.model_id)||!h.probabilities.some(p=>p.off_percent===s.off_percent&&p.weight>0))))fail('HALLOWEEN_REVEAL_UNKNOWN',409);
  if(game.random_source.mode==='quantity_tiers'){
   if(receipt.slots.some((s,i)=>canonical(s.quantity)!==canonical(i===0?{value:game.fixed_quantity.value,unit:game.fixed_quantity.unit}:game.random_quantities.find(q=>canonical(q)===canonical(s.quantity)))))fail('HALLOWEEN_REVEAL_UNKNOWN',409);
  }else if(receipt.slots.some(s=>s.quantity))fail('HALLOWEEN_REVEAL_UNKNOWN',409);
  return receipt;
 }
 return {
  read,
  reveal(body){
   if(!exact(body,['request_id','game_id'])||typeof body.game_id!=='string')fail('INVALID_REQUEST');
   const file=location(body.request_id),hash=digest(canonical(body));
   if(fs.existsSync(file)){const prior=read(body.request_id);if(prior.request_hash!==hash)fail('REQUEST_CONFLICT',409);return prior;}
   const {release,h,game,models,quantities}=context(body.game_id);
   fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o700});
   // Reserve UNKNOWN before sampling. A crash/corrupt record must not reroll.
   let fd;try{fd=fs.openSync(file,'wx',0o600);fs.writeFileSync(fd,JSON.stringify({status:'unknown',request_id:body.request_id,request_hash:hash}));fs.fsyncSync(fd);}
   catch(error){if(error.code==='EEXIST'){const prior=read(body.request_id);if(prior.request_hash!==hash)fail('REQUEST_CONFLICT',409);return prior;}throw error;}finally{if(fd!==undefined)fs.closeSync(fd);}
   if(process.platform!=='win32'){const parent=fs.openSync(path.dirname(file),'r');try{fs.fsyncSync(parent);}finally{fs.closeSync(parent);}}
   const candidates=quantities?[...quantities]:[...models],slots=[{slot:'fixed',model_id:game.fixed_model,off_percent:game.fixed_off_percent,...(quantities?{quantity:{value:game.fixed_quantity.value,unit:game.fixed_quantity.unit}}:{})}];
   for(const slot of ['random-1','random-2']){
    const choice=candidates.splice(randomInt(candidates.length),1)[0],model_id=quantities?game.fixed_model:choice,ticket=randomInt(10000);let cumulative=0;
    const tier=h.probabilities.find(p=>(cumulative+=p.weight)>ticket);
    slots.push({slot,model_id,off_percent:tier.off_percent,...(quantities?{quantity:choice}:{})});
   }
   const receipt={status:'revealed',request_id:body.request_id,request_hash:hash,game_id:body.game_id,release_id:release.release_id,config_hash:release.config_hash,rule_hash:release.rule_hash,created_at:new Date(now()).toISOString(),slots};
   atomic(file,receipt);return receipt;
  },
  resolve(body){
   if(!exact(body,['request_id','game_id','slot','model_id','off_percent','quantity']))fail('INVALID_REQUEST');
   const receipt=read(body.request_id);
   if(receipt.game_id!==body.game_id||!receipt.slots.some(row=>row.slot===body.slot&&row.model_id===body.model_id&&row.off_percent===body.off_percent&&canonical(row.quantity||null)===canonical(body.quantity||null)))fail('HALLOWEEN_REVEAL_MISMATCH',409);
   return {status:'selection_confirmed',request_id:receipt.request_id,game_id:receipt.game_id,release_id:receipt.release_id,config_hash:receipt.config_hash,slot:body.slot,model_id:body.model_id,off_percent:body.off_percent,...(body.quantity?{quantity:body.quantity}:{})};
  }
 };
}
