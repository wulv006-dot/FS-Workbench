// Server-only bridge from observed Admin tiers to the public selection contract.
// Policy is supplied by the trusted catalog provider, never an editor/browser.
import {projectModelOptions} from './model-options.mjs';
const id=v=>typeof v==='string'&&/^[1-9]\d{0,19}$/.test(v);
const blocked=reason=>({status:'blocked',reason,products:[],model_contracts:{},checkout_enabled:false});
function minor(text,scale){
 if(typeof text!=='string'||!/^\d{1,15}(?:\.\d{1,12})?$/.test(text))throw Error('PRICE_FORMAT_UNVERIFIED');
 const [whole,frac='']=text.split('.');
 // Do not silently round an Admin value without a verified rounding contract.
 if(frac.slice(scale).replace(/0/g,''))throw Error('PRICE_PRECISION_UNVERIFIED');
 const value=BigInt(whole)*10n**BigInt(scale)+BigInt(frac.slice(0,scale).padEnd(scale,'0')||'0');
 if(value>BigInt(Number.MAX_SAFE_INTEGER))throw Error('PRICE_TOO_LARGE');return Number(value);
}
export function projectAdminPrices(observation,policy,{now=Date.now()}={}){
 // Standard reference prices are US/USD; regional promotions need a separate
 // main-site checkout response and must not silently become the base anchor.
 if(policy?.baseline_region!=='us'||policy?.currency!=='USD'||policy?.regional_adjustment!=='none_verified')return blocked('US_USD_BASELINE_REQUIRED');
 if(!policy||policy.source_field!=='more.price'||policy.price_semantics!=='current_tier_total'
   ||!policy.evidence_ref||typeof policy.evidence_ref!=='string'||!/^[-a-zA-Z0-9_./:]{1,200}$/.test(policy.evidence_ref)
   ||!(/^[A-Z]{3}$/).test(policy.currency)||!Number.isInteger(policy.minor_unit_scale)||policy.minor_unit_scale<0||policy.minor_unit_scale>4)
   return blocked('PRICE_CURRENCY_SEMANTICS_UNVERIFIED');
 if(!Number.isSafeInteger(policy.max_age_ms)||policy.max_age_ms<=0||!Number.isFinite(now))return blocked('FRESHNESS_POLICY_REQUIRED');
 const at=Date.parse(observation?.observed_at);
 if(!Number.isFinite(at)||at>now||now-at>policy.max_age_ms)return blocked('CATALOG_STALE');
 if(observation.source!=='admin_readonly'||observation.coverage?.complete!==true||!Array.isArray(observation.products)||!observation.products.length)return blocked('ASSOCIATION_INCOMPLETE');
 const model=observation.model,ref=policy.model_ref;
 if(!ref||ref.site_id!=='266'||!id(ref.model_id)||!id(ref.game_id)||model?.model_id!==ref.model_id||model.game_id!==ref.game_id)return blocked('MODEL_SCOPE_MISMATCH');
 if(typeof policy.quantity_value!=='string'||!/^\d+(?:\.\d{1,6})?$/.test(policy.quantity_value)||typeof policy.quantity_unit!=='string'||!policy.quantity_unit)return blocked('EXACT_QUANTITY_REQUIRED');
 const guard=row=>[1,'1'].includes(row.raw_state?.status)&&[0,'0'].includes(row.raw_state?.auto_off);
 if(!guard(model))return blocked('MODEL_UNAVAILABLE');
 const products=[],combinations=[],seen=new Set(),platforms=new Set(),regions=new Set();
 try{for(const row of observation.products){
   const r=row.product_ref;
   if(!r||Object.entries(ref).some(([k,v])=>r[k]!==v)||!id(r.goods_id)||seen.has(r.goods_id))throw Error('PRODUCT_SCOPE_MISMATCH');seen.add(r.goods_id);
   // Do not silently remove the original default product if it is unavailable.
   if(!guard(row)||!id(row.platform_attribute_id)||!id(row.region_id))throw Error('PRODUCT_UNAVAILABLE_OR_OPTIONS_UNKNOWN');
   if(!row.specification||typeof row.specification!=='object'||Array.isArray(row.specification))throw Error('SPECIFICATION_MAPPING_REQUIRED');
   for(const s of Object.values(row.specification)){
    if(!s||typeof s.present!=='boolean')throw Error('SPECIFICATION_MAPPING_REQUIRED');
    if(s.present&&(s.observed===null||typeof s.observed!=='object'||Object.keys(s.observed).length!==0))throw Error('SPECIFICATION_MAPPING_REQUIRED');
   }
   const tiers=(row.tiers||[]).filter(t=>t.quantity===policy.quantity_value&&t.unit===policy.quantity_unit);
   if(tiers.length!==1)throw Error('EXACT_TIER_UNAVAILABLE');
   const tier=tiers[0],key='admin-'+[r.site_id,r.game_id,r.goods_id,row.platform_attribute_id].join('-');
   const quantity={min:policy.quantity_value,max:policy.quantity_value,step:'1',unit:policy.quantity_unit};
   // group is deliberately absent: an Admin num is not a proved cart encoding.
   const known=ref.game_id==='1327'?{'21587':'ps','21585':'xbox','21589':'pc'}:{};
   products.push({key,title:'Model '+ref.model_id,product_ref:{...ref,goods_id:r.goods_id},platform:{code:known[row.platform_attribute_id]||'area-'+row.platform_attribute_id,attribute_id:row.platform_attribute_id},quantity,attributes:[],available:false});
   platforms.add(row.platform_attribute_id);regions.add(row.region_id);
   combinations.push({product_key:key,choices:{platform:row.platform_attribute_id,region:row.region_id},quantity,attributes:[],price:{source:'admin_current',base_minor:minor(tier.source_price,policy.minor_unit_scale),currency:policy.currency,minor_unit_scale:policy.minor_unit_scale,quantity_value:policy.quantity_value,expires_at:new Date(at+policy.max_age_ms).toISOString()}});
 }}catch(error){return blocked(error.message);}
 const order=policy.ordered_goods_ids,ordered=Array.isArray(order)&&order.length===seen.size&&new Set(order).size===seen.size&&order.every(x=>seen.has(x))&&typeof policy.ordering_evidence==='string'&&policy.ordering_evidence.length>0;
 if(ordered)combinations.sort((a,b)=>order.indexOf(products.find(p=>p.key===a.product_key).product_ref.goods_id)-order.indexOf(products.find(p=>p.key===b.product_key).product_ref.goods_id));
 const raw={schema_version:1,verified:true,catalog_version:'admin-'+new Date(at).toISOString(),model_ref:{...ref},fields:[{id:'platform',label:'Platform',depends_on:[],values:[...platforms].map(x=>({id:x,label:'Platform '+x}))},{id:'region',label:'Server',depends_on:['platform'],values:[...regions].map(x=>({id:x,label:'Server '+x}))}],combinations,ordering_verified:Boolean(ordered),...(ordered?{ordering_evidence:policy.ordering_evidence}:{})};
 try{return {status:'reference_price_ready_not_checkout',products,model_contracts:projectModelOptions({[ref.model_id]:raw},products),checkout_enabled:false};}catch{return blocked('PUBLIC_OPTIONS_CONFLICT');}
}
