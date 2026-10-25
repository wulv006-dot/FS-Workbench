import {projectPreviewProduct,fail} from '../runtime/snapshot.mjs';

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
export function centerSeed(fc,seasonal){
 const products=[],byOriginal={};
 for(const p of Object.values(fc.products)){
  byOriginal[p.key]=[];
  for(const [platform,row] of Object.entries(p.platforms||{})){
   const key='fc-'+p.key+'-'+platform;byOriginal[p.key].push(key);
   const quantity=String(row.quantity||1);
   products.push({key,title:p.title||p.name,product_ref:{site_id:String(fc.siteId),game_id:String(fc.gameId),goods_id:String(row.id)},
    platform:{code:platform,attribute_id:String(row.aid)},quantity:{min:quantity,max:quantity,step:'1',unit:'item',...(row.group?{group:String(row.group)}:{})},available:false,attributes:[],...(p.image?{image:p.image}:{})});
  }
 }
 for(const p of seasonal.products){const s=p.source,quantity=String(s.quantity);
  products.push({key:'seasonal-'+p.id,title:p.name,product_ref:{site_id:String(s.siteId),game_id:String(s.gid),goods_id:String(s.goodsId)},
   platform:{code:'area-'+s.aid,attribute_id:String(s.aid)},quantity:{min:quantity,max:quantity,step:'1',unit:s.unit||'item'},available:false,attributes:[]});
 }
 const keys=ids=>[...new Set(ids.flatMap(id=>byOriginal[id]||[]))];
 return {seedProducts:products,fc_layout:{weekly:[...fc.weekly.ids],trio:[...fc.trio.ids],bundles:[...fc.bundles.ids],sbc:[...fc.sbc.ids],defaultCore:fc.sbc.defaultId??null,
  routes:Object.fromEntries(Object.entries(fc.sbc.routes).map(([key,r])=>[key,{picks:[...r.picks],alternatives:[...(r.alternatives||[])],...(r.label?{label:structuredClone(r.label)}:{})}]))},pageProductKeys:{
  'fc27-weekly':keys(fc.weekly.ids),
  'fc27-sbc':keys([...fc.sbc.ids,...Object.values(fc.sbc.routes).flatMap(r=>[...r.picks,...r.alternatives])]),
  'fc27-trio':keys([...fc.trio.ids,...fc.bundles.ids]),
  'seasonal-vault':seasonal.products.map(p=>'seasonal-'+p.id)
 }};
}
