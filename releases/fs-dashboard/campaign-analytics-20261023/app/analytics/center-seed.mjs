import {projectPreviewProduct,fail} from '../runtime/snapshot.mjs';
import {modelVariants,projectModels} from '../runtime/model-cards.mjs';
import {projectAdminPrices} from '../runtime/admin-price-projection.mjs';

// Call only with the product_read detail obtained by the trusted management route.
// No raw response, price, URL or purchase capability is copied into the draft.
export function projectImportedProduct(detail){
 if(!detail||detail.authoritative!==false||detail.checkout_enabled!==false)fail('INVALID_IMPORTED_PRODUCT');
 const ref=detail.product_ref||{},observedAid=detail.platform_attribute_id;
 if(observedAid!=null&&(typeof observedAid!=='string'||!/^\d{1,20}$/.test(observedAid)))fail('INVALID_IMPORTED_PRODUCT');
 const aid=observedAid==null||observedAid==='0'?'unknown':observedAid;
 const known={'21587':'ps','21585':'xbox','21589':'pc'},code=aid==='unknown'?'unknown':ref.game_id==='1327'&&known[aid]||'area-'+aid;
 const product_ref=Object.fromEntries(['site_id','game_id','goods_id','model_id','sku_id'].filter(k=>ref[k]!=null).map(k=>[k,ref[k]]));
 const quantity=detail.quantity_observation||{};
 return projectPreviewProduct({key:'admin-'+[ref.site_id,ref.game_id,ref.goods_id,aid].join('-')+(ref.sku_id?'-sku-'+ref.sku_id:''),
  title:detail.title==null?'商品ID '+ref.goods_id:detail.title,title_source:detail.title==null?'identity_fallback':'admin',product_ref,platform:{code,...(aid==='unknown'?{}:{attribute_id:aid})},preview_only:true,available:false,quantity:null,attributes:[],
  observed_quantity:{minimum:quantity.minimum??(detail.minimum_quantity==null?null:String(detail.minimum_quantity)),unit:quantity.raw_unit??detail.unit??null,group:quantity.raw_num??null}});
}

export function addImportedProduct(draft,pageId,detail,seed){
 const result=structuredClone(draft),page=result.pages.find(p=>p.page_id===pageId);
 if(!page)fail('INVALID_CAMPAIGN_PAGE');
 const product=projectImportedProduct(detail);
 if(pageId.startsWith('fc27-')&&product.product_ref.game_id!=='1327')fail('PAGE_PRODUCT_GAME_MISMATCH');
 const imports=result.imported_products||=[];
 if(!imports.some(p=>p.key===product.key))imports.push(product);
 if(!Object.hasOwn(page,'product_keys')){
  if(!Array.isArray(seed?.pageProductKeys?.[pageId]))fail('PAGE_SEED_REQUIRED');
  page.product_keys=[...seed.pageProductKeys[pageId]];
 }
 if(!page.product_keys.includes(product.key))page.product_keys.push(product.key);
 page.product_roles||={};if(!Object.hasOwn(page.product_roles,product.key))page.product_roles[product.key]='preview';
 return result;
}

// Original accepted product references are retained for preview, never promoted to verified sale SKUs.
export function centerSeed(fc,seasonal,{adminObservations=[],now=Date.now()}={}){
 const products=[],byOriginal={};
 for(const p of Object.values(fc.products)){
  if(p.preview_only&&p.model_id)continue;
  byOriginal[p.key]=[];
  for(const [platform,row] of Object.entries(p.platforms||{})){
   const key='fc-'+p.key+'-'+platform;byOriginal[p.key].push(key);
   const quantity=String(row.quantity||1);
   products.push({key,title:p.title||p.name,product_ref:{site_id:String(fc.siteId),game_id:String(fc.gameId),goods_id:String(row.id)},
    platform:{code:platform,attribute_id:String(row.aid)},quantity:{min:quantity,max:quantity,step:'1',unit:'item',...(row.group?{group:String(row.group)}:{})},available:false,attributes:[],...(p.image?{image:p.image}:{})});
  }
 }
 const fc_models=projectModels(fc.fc_models||{}),variants=modelVariants(fc_models);products.push(...variants);
 for(const model of Object.values(fc_models))byOriginal[model.key]=variants.filter(p=>p.model_card_key===model.key).map(p=>p.key);
 for(const p of seasonal.products){const s=p.source,quantity=String(s.quantity);
  products.push({key:'seasonal-'+p.id,title:p.name,product_ref:{site_id:String(s.siteId),game_id:String(s.gid),goods_id:String(s.goodsId)},
   platform:{code:'area-'+s.aid,attribute_id:String(s.aid)},quantity:{min:quantity,max:quantity,step:'1',unit:s.unit||'item'},available:false,attributes:[]});
 }
 const seasonal_model_contracts={},admin_projection_status=[];
 // Server-owned observations and verified policy only; not read from draft fields.
 for(const entry of adminObservations){
  const projected=projectAdminPrices(entry.observation,entry.policy,{now});
  admin_projection_status.push({model_id:entry.policy?.model_ref?.model_id??null,status:projected.status,reason:projected.reason??null});
  if(projected.status!=='reference_price_ready_not_checkout')continue;
  for(const product of projected.products){if(products.some(p=>p.key===product.key))fail('DUPLICATE_PROVIDER_PRODUCT');products.push(product);}
  for(const [id,contract] of Object.entries(projected.model_contracts)){if(seasonal_model_contracts[id])fail('DUPLICATE_PROVIDER_MODEL');seasonal_model_contracts[id]=contract;}
 }
 const keys=ids=>[...new Set(ids.flatMap(id=>byOriginal[id]||[]))];
 return {seedProducts:products,...(Object.keys(seasonal_model_contracts).length?{seasonal_model_contracts}:{}),admin_projection_status,...(Object.keys(fc_models).length?{fc_models}:{}),fc_layout:{weekly:[...fc.weekly.ids],trio:[...fc.trio.ids],bundles:[...fc.bundles.ids],sbc:[...fc.sbc.ids],defaultCore:fc.sbc.defaultId??null,
  routes:Object.fromEntries(Object.entries(fc.sbc.routes).map(([key,r])=>[key,{picks:[...r.picks],alternatives:[...(r.alternatives||[])],...(r.label?{label:structuredClone(r.label)}:{})}]))},pageProductKeys:{
  'fc27-weekly':keys([...fc.weekly.ids,...fc.bundles.ids]),
  'fc27-sbc':keys([...fc.sbc.ids,...fc.bundles.ids,...Object.values(fc.sbc.routes).flatMap(r=>[...r.picks,...r.alternatives])]),
  'fc27-trio':keys([...fc.trio.ids,...fc.bundles.ids]),
  'seasonal-vault':seasonal.products.map(p=>'seasonal-'+p.id)
 }};
}
// One read-only interpretation of legacy per-platform masks and current logical cards.
export function effectivePageBindings(draft,seed,pageId){
 const page=draft.pages.find(p=>p.page_id===pageId);if(!page)fail('INVALID_CAMPAIGN_PAGE');
 const explicit=Object.hasOwn(page,'product_keys'),product_keys=[...(explicit?page.product_keys:seed.pageProductKeys[pageId]||[])],cards={},legacy_refs=[];
 if(pageId.startsWith('fc27-'))for(const key of [...product_keys]){const native=seed.nativeModelKeys?.[key];if(native&&!product_keys.includes(native))product_keys.push(native);}
 for(const key of product_keys){const match=/^fc-(.+)-(ps|xbox|pc)$/.exec(key);if(match)(cards[match[1]]||=[]).push(match[2]);else legacy_refs.push(key);}
 return {source:explicit?'explicit':'inherited',product_keys,model_cards:Object.entries(cards).map(([key,platforms])=>({key,selected_platforms:[...new Set(platforms)],partial:platforms.length!==3})),legacy_refs};
}
