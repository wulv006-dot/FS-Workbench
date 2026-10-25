// Model facts come only from the trusted backend resolver, never editor input.
const error=code=>{throw Object.assign(new Error(code),{code,status:400});};
const object=value=>value&&typeof value==='object'&&!Array.isArray(value);
const only=(value,keys)=>object(value)&&Object.keys(value).every(k=>keys.includes(k));
const positive=value=>typeof value==='string'&&/^[1-9]\d{0,19}$/.test(value);
const label=(value,max=200)=>{if(typeof value!=='string'||!value.length||value.length>max||/[<>\u0000-\u001f]/.test(value))error('INVALID_MODEL_CARD');return value;};
export const fcPlatforms=Object.freeze({ps:'21587',xbox:'21585',pc:'21589'});
export function publicImage(value){
 if(value==null)return null;
 try{const u=new URL(value);if(u.protocol==='https:'&&u.hostname==='assets.mmoexp.com'&&!u.username&&!u.password&&!u.port&&!u.search&&!u.hash&&/\.(?:png|jpe?g|webp)$/i.test(u.pathname))return u.href;}catch{}
 return null;
}
export function projectModelCard(input){
 if(!only(input,['key','site_id','game_id','model_id','kind','title','version_label','image_url','image_provenance','site_association','platforms','verification_scope','available','authoritative','checkout_enabled'])
  ||input.site_id!=='266'||input.game_id!=='1327'||!positive(input.model_id)||input.key!=='model-266-1327-'+input.model_id
  ||input.verification_scope!=='catalog_identity_only'||input.site_association!=='observed'||input.available!==false||input.authoritative!==false||input.checkout_enabled!==false
  ||input.image_provenance!=null&&input.image_provenance!=='historical_accepted_model_asset')error('INVALID_MODEL_CARD');
 if(!['player','sbc','bundle'].includes(input.kind))error('MODEL_KIND_UNVERIFIED');
 if(!only(input.platforms,Object.keys(fcPlatforms))||Object.keys(input.platforms).length!==3)error('INVALID_MODEL_CARD');
 const goods=new Set(),platforms=Object.fromEntries(Object.keys(fcPlatforms).map(code=>{
  const p=input.platforms[code];if(!only(p,['state','product_ref','observed_quantity'])||!['verified','missing','ambiguous','offline','unknown'].includes(p.state))error('INVALID_MODEL_CARD');
  let product_ref=null;
  if(p.product_ref!=null){
   const ref=p.product_ref;
   if(!only(ref,['site_id','game_id','model_id','goods_id','sku_id'])||ref.site_id!==input.site_id||ref.game_id!==input.game_id||ref.model_id!==input.model_id||!positive(ref.goods_id)||(ref.sku_id!=null&&!positive(ref.sku_id))||goods.has(ref.goods_id)||['missing','ambiguous'].includes(p.state))error('INVALID_MODEL_CARD');
   goods.add(ref.goods_id);product_ref={site_id:ref.site_id,game_id:ref.game_id,model_id:ref.model_id,goods_id:ref.goods_id,...(ref.sku_id?{sku_id:ref.sku_id}:{})};
  }
  if(p.state==='verified'&&!product_ref)error('INVALID_MODEL_CARD');
  let observed_quantity=null;
  if(p.observed_quantity!=null){
   const q=p.observed_quantity;if(!only(q,['minimum','unit','group']))error('INVALID_MODEL_CARD');
   for(const key of ['minimum','group'])if(q[key]!=null&&(typeof q[key]!=='string'||!/^\d{1,20}(?:\.\d{1,6})?$/.test(q[key])))error('INVALID_MODEL_CARD');
   if(q.unit!=null&&(typeof q.unit!=='string'||q.unit.length>64||/[<>\u0000-\u001f]/.test(q.unit)))error('INVALID_MODEL_CARD');
   observed_quantity={minimum:q.minimum??null,unit:q.unit??null,group:q.group??null};
  }
  return [code,{state:p.state,product_ref,observed_quantity}];
 }));
 return {key:input.key,site_id:input.site_id,game_id:input.game_id,model_id:input.model_id,kind:input.kind,title:label(input.title),
  version_label:input.version_label==null?null:label(input.version_label,100),image_url:publicImage(input.image_url),image_provenance:input.image_provenance==='historical_accepted_model_asset'?input.image_provenance:null,platforms,
  verification_scope:'catalog_identity_only',site_association:'observed',available:false,authoritative:false,checkout_enabled:false};
}
export function projectModels(input){
 if(!object(input)||Object.keys(input).length>300)error('INVALID_MODEL_CARD');
 return Object.fromEntries(Object.entries(input).map(([key,value])=>{const model=projectModelCard(value);if(key!==model.key)error('INVALID_MODEL_CARD');return [key,model];}));
}
const english=(value,fallback)=>typeof value==='string'&&!/\p{Script=Han}/u.test(value)?value:fallback;
export function publicModels(input){return Object.fromEntries(Object.entries(projectModels(input)).map(([key,m])=>[key,{...m,title:english(m.title,'Model '+m.model_id),version_label:english(m.version_label,null),
 platforms:Object.fromEntries(Object.entries(m.platforms).map(([code,p])=>[code,{...p,...(p.observed_quantity?{observed_quantity:{...p.observed_quantity,unit:english(p.observed_quantity.unit,null)}}:{})}]))}]));}
export function effectiveFcCatalog(original,models={}){
 const catalog=structuredClone(original),safe=projectModels(models);catalog.fc_models=safe;
 for(const model of Object.values(safe))catalog.products[model.key]={key:model.key,title:model.title,name:model.title,kind:model.kind,version:model.version_label,
  image:model.image_url,preview_only:true,model_id:model.model_id,platforms:Object.fromEntries(Object.entries(model.platforms).map(([code,p])=>[code,
   {id:p.product_ref?.goods_id??null,aid:fcPlatforms[code],price:null,quantity:null,group:null,status:null,autoOff:null,binding_state:p.state,product_ref:p.product_ref}]))};
 return catalog;
}
export function modelVariants(models){return Object.values(projectModels(models)).flatMap(model=>Object.entries(model.platforms).map(([code,p])=>({
 key:'fc-'+model.key+'-'+code,title:model.title,model_card_key:model.key,binding_state:p.state,
 product_ref:p.product_ref??{site_id:model.site_id,game_id:model.game_id,model_id:model.model_id},platform:{code,attribute_id:fcPlatforms[code]},
 preview_only:true,available:false,quantity:null,attributes:[],observed_quantity:p.observed_quantity
})));}
