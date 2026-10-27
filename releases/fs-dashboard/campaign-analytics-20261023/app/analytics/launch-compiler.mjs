// Offline final assembly, not a publisher or Admin transport. Call only with
// the current existing release and independently read-back code records.
import nativeHandoff from '../native-code-handoff.js';
import {projectNativeCatalog} from './native-catalog.mjs';
import {canonical} from '../runtime/snapshot.mjs';
import {compileDiscountPlan} from './discount-plan.mjs';
const fail=code=>{throw Object.assign(Error(code),{code});};
const ids=v=>Array.isArray(v)?v.map(String).sort():[];
export function verifyDiscountReadbacks(plans,receipt){
 if(receipt?.status!=='readback_verified'||!Array.isArray(receipt.records)||typeof receipt.evidence_ref!=='string'||!receipt.evidence_ref)fail('DISCOUNT_READBACK_REQUIRED');
 for(const plan of plans){
  const matches=receipt.records.filter(r=>r.code===plan.fields.code);if(matches.length!==1)fail('DISCOUNT_READBACK_AMBIGUOUS');const row=matches[0],expected=plan.fields;
  for(const key of ['site_id','type','discount','repeat_qty','uid','status','attain'])if(String(row[key])!==String(expected[key]))fail('DISCOUNT_READBACK_SCOPE_MISMATCH');
  for(const key of ['gid','exclude_gids','cid'])if(JSON.stringify(ids(row[key]))!==JSON.stringify(ids(expected[key])))fail('DISCOUNT_READBACK_SCOPE_MISMATCH');
  if(row.timestart!==expected.timestart||row.timeend!==expected.timeend||row.aid!=null&&String(row.aid)!=='0')fail('DISCOUNT_READBACK_SCOPE_MISMATCH');
 }
}
export function compileLaunch({candidate,currentRelease,discountRequests,discountReceipt,fcPages,oldPrivatePolicy={},now=Date.now()}){
 if(!candidate||!currentRelease?.release_id||!Array.isArray(fcPages)||fcPages.length!==3)fail('LAUNCH_INPUT_REQUIRED');
 const plans=discountRequests.map(r=>compileDiscountPlan(r));verifyDiscountReadbacks(plans,discountReceipt);
 const catalog=projectNativeCatalog(candidate.native_catalog,{now}),checkout=structuredClone(candidate.prepared_native_checkout);
 if(checkout.status!=='configured')fail('NATIVE_CANDIDATE_REQUIRED');
 const codes=new Map(plans.map(p=>[p.fields.code,p]));
 for(const b of checkout.bindings){const plan=codes.get(b.code);if(!plan||!plan.fields.gid.includes(catalog.products.find(p=>p.key===b.product_key)?.product_ref.game_id)||Number(plan.fields.discount)!==100-b.off_percent)fail('CODE_BINDING_SCOPE_MISMATCH');}
 const pages=structuredClone(currentRelease.pages),products=structuredClone(currentRelease.products);
 for(const product of catalog.products){const previous=products.find(p=>p.key===product.key);if(previous){if(canonical(previous.product_ref)!==canonical(product.product_ref))fail('NATIVE_CATALOG_SCOPE_MISMATCH');Object.assign(previous,product);}else products.push(product);}
 const seasonal=pages.find(p=>p.page_id==='seasonal-vault'&&p.activity_id==='mmoexp-seasonal');if(!seasonal)fail('SEASONAL_PAGE_REQUIRED');seasonal.product_keys=catalog.products.map(p=>p.key);
 for(const profile of fcPages){
  const page=pages.find(p=>p.page_id===profile.page_id&&p.activity_id===profile.activity_id),plan=codes.get(profile.code);
  if(!page||!['fc27-weekly','fc27-sbc','fc27-trio'].includes(page.page_id)||!plan||Number(plan.fields.discount)!==90||JSON.stringify(plan.fields.gid)!=='["1327"]')fail('FC_SCOPE_MISMATCH');
  for(const key of page.product_keys){
   const product=products.find(p=>p.key===key);if(product?.preview_only)continue;
   const q=product?.quantity;
   if(!product||product.product_ref.site_id!=='266'||product.product_ref.game_id!=='1327'||q?.unit!=='item'||q.min!==q.max||!q.group||product.attributes?.length||!['ps','xbox','pc'].includes(product.platform.code))fail('FC_MAPPING_REQUIRED');
   checkout.bindings.push({activity_id:page.activity_id,page_id:page.page_id,product_key:key,quantity:{value:q.min,unit:'item'},attributes:[],off_percent:10,code:profile.code,native:{category:'new_items',id:product.product_ref.goods_id,group:q.group,num:q.min,attr:'',aid:product.platform.attribute_id}});
  }
 }
 // Validate all targets before returning anything that could be installed.
 const native_checkout=nativeHandoff.projectConfiguration(checkout,pages,products);
 return {schema_version:1,status:'prepared_not_installed',evidence_ref:discountReceipt.evidence_ref,expected_release_id:currentRelease.release_id,expected_config_hash:currentRelease.config_hash,
  private_policy:{...structuredClone(oldPrivatePolicy),native_catalog:structuredClone(candidate.native_catalog),admin_reference_prices:structuredClone(candidate.admin_reference_prices),native_checkout},
  publication_requirements:{preserve_existing_draft:true,whole_page_publish:true,requires_current_Admin_price_refresh:true,requires_visual_and_real_cart_Apply_validation:true},plans};
}
