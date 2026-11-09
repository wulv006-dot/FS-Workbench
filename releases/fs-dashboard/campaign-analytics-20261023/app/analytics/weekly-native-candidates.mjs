// Reuse the installed Halloween FC field/rounding contract for a reviewable proposal.
// No policy files, coupon bindings, public prices or checkout switches are written here.
import {projectAdminPrices} from '../runtime/admin-price-projection.mjs';
import {projectNativeCatalog} from './native-catalog.mjs';
import {canonical,digest} from '../runtime/snapshot.mjs';
import {fcPlatforms} from '../runtime/model-cards.mjs';
export function weeklyNativeCandidates({source,pricePolicy,nativeCatalog,now=Date.now()}){
 const templates=(pricePolicy?.entries||[]).filter(p=>p.model_ref?.site_id==='266'&&p.model_ref.game_id==='1327'&&p.quantity_value==='1'&&p.quantity_unit==='item'&&p.source_field==='unit_price'&&p.price_semantics==='native_discounted_item_display_total');
 const result={status:'prepared_not_installed',publication:false,policy_written:false,models:[],native_catalog_candidate:null,price_policy_candidates:[]},products=[],contracts={};
 for(const observation of source.provider_observations||[]){
  const mid=observation.model.model_id,identity=source.models.find(m=>m.model_id===mid),entry={model_id:mid,platforms:[],gaps:[],quote_status:'pending',checkout_status:'pending'},known=nativeCatalog?.model_contracts?.[mid];
  // A per-model installed policy takes precedence. A shared field contract is only a proposal.
  const exact=templates.find(p=>p.model_ref.model_id===mid),template=exact||templates[0];
  for(const [code,aid] of Object.entries(fcPlatforms)){const slot=identity?.platforms[code],row=observation.products.find(p=>p.platform_attribute_id===aid&&p.product_ref.goods_id===slot?.product_ref?.goods_id);
   entry.platforms.push({code,attribute_id:aid,goods_id:slot?.product_ref?.goods_id??null,identity:slot?.state??'unknown',region_id:row?.region_id??null,quantity:row?.quantity??null,
    option_structures_observed:row?.option_structures_observed===true,price_status:'pending',native_binding:known?.combinations?.some(c=>nativeCatalog.products.some(p=>p.key===c.product_key&&p.product_ref.goods_id===slot?.product_ref?.goods_id))?'existing_verified_contract':'pending'});
  }
  if(!template){entry.gaps.push('FC_PRICE_FIELD_CONTRACT_NOT_CONFIGURED');result.models.push(entry);continue;}
  if(observation.products.some(p=>!p.option_structures_observed)){entry.gaps.push('SALEPROP_SKU_STRUCTURE_NOT_OBSERVED');result.models.push(entry);continue;}
  if(observation.products.some(p=>p.quantity?.group!=='1'||p.quantity?.minimum!=='1'||!Object.values(fcPlatforms).includes(p.platform_attribute_id))){entry.gaps.push('FIXED_ONE_ITEM_MAPPING_UNVERIFIED');result.models.push(entry);continue;}
  const policy={...structuredClone(template),category_id:observation.model.category_id,model_ref:{site_id:'266',game_id:'1327',model_id:mid},verified_goods_ids:observation.products.map(p=>p.product_ref.goods_id)};
  // Do not copy a different model's default order or evidence of SKU ordering.
  delete policy.ordered_goods_ids;delete policy.ordering_evidence;
  const projection=projectAdminPrices(observation,policy,{now});
  if(projection.status!=='reference_price_ready_not_checkout'){entry.gaps.push(projection.reason);result.models.push(entry);continue;}
  entry.quote_status=exact?'current_admin_reference':'proposed_shared_field_contract';
  entry.gaps.push('PUBLIC_CART_QUOTE_AND_SERIALIZATION_READBACK_REQUIRED','COUPON_BINDING_APPROVAL_REQUIRED');
  for(const platform of entry.platforms)platform.price_status=projection.model_contracts[mid].combinations.some(c=>projection.products.find(p=>p.key===c.product_key)?.platform.code===platform.code)?entry.quote_status:'pending';
  const selected=projection.products.map(p=>({...p,title:identity.title,quantity:{...p.quantity,group:'1'}}));
  products.push(...selected);contracts[mid]=projection.model_contracts[mid];
  result.price_policy_candidates.push({policy,approval_required:true,derived_from_model_id:template.model_ref.model_id,field_contract_evidence:template.evidence_ref,installed:false});result.models.push(entry);
 }
 if(products.length){const expiries=Object.values(contracts).flatMap(c=>c.combinations.map(x=>Date.parse(x.price.expires_at)));
  const observed_at=source.observed_at,valid_until=new Date(Math.min(...expiries)).toISOString();
  const candidate={schema_version:1,verification_ref:'weekly-observation-'+digest(canonical(products.map(p=>p.product_ref))).slice(0,24),observed_at,valid_until,products,model_contracts:contracts};
  // Exercise the same native catalogue + model-options schema as Halloween before exposing a proposal.
  projectNativeCatalog(candidate,{now});result.native_catalog_candidate=candidate;
 }
 return result;
}
