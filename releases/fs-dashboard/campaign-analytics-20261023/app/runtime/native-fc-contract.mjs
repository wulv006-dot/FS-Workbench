import core from '../activity-core.js';
import {fail,id} from './snapshot.mjs';

const fields=['category','id','group','num','attr','aid'];
const contextKeys=['intent_id','operation_id','release_id','activity_id','page_id','rule_version','benefit_binding_version'];
const requiredEvidence=['site_game_goods_identity','model_identity','platform_attribute_identity',
  'empty_selectable_properties_observed','original_fc_cart_field_serialization','original_fc_fixed_selection'];
const requireContract=(condition,code='NATIVE_FC_MAPPING_CONFLICT')=>{if(!condition)fail(code);};
const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(k=>keys.includes(k));
const positive=value=>typeof value==='string'&&/^[1-9]\d*$/.test(value)&&Number.isSafeInteger(Number(value));
const empty=value=>Array.isArray(value)&&value.length===0;

/**
 * Pure historical field projection of an already validated, saved intent and trusted
 * server-side catalog mapping. This is not authentication, a current catalog check,
 * an activity quote, a live adapter or an idempotent native operation.
 * The historical /Cart/add.html POST has no proved idempotency/activity-price contract.
 */
export function projectNativeFcIntent(intent,catalogMapping){
  requireContract(intent&&typeof intent==='object'&&!Array.isArray(intent),'NATIVE_FC_INTENT_INVALID');
  const context={};
  for(const key of contextKeys){requireContract(typeof intent[key]==='string','NATIVE_FC_INTENT_INVALID');context[key]=id(intent[key]);}
  for(const key of ['config_hash','rule_hash']){requireContract(typeof intent[key]==='string'&&/^[a-f0-9]{64}$/.test(intent[key]),'NATIVE_FC_INTENT_INVALID');context[key]=intent[key];}
  requireContract(intent.currency==='USD'&&Array.isArray(intent.lines)&&intent.lines.length>0&&intent.lines.length<=50,'NATIVE_FC_INTENT_INVALID');
  context.currency=intent.currency;
  requireContract(catalogMapping?.schema_version===1&&catalogMapping.mapping_version==='campaign-catalog-mapping-v1'
    &&catalogMapping.authoritative===false&&catalogMapping.checkout_enabled===false
    &&typeof catalogMapping.mappings_sha256==='string'&&/^[a-f0-9]{64}$/.test(catalogMapping.mappings_sha256));
  const seen=new Set();
  const lines=intent.lines.map(line=>{
    requireContract(exact(line,['line_key','product_key','product_ref','platform','quantity','attributes']),'NATIVE_FC_INTENT_INVALID');
    requireContract(typeof line.line_key==='string'&&!seen.has(line.line_key),'NATIVE_FC_INTENT_INVALID');
    const line_key=id(line.line_key);seen.add(line_key);
    requireContract(typeof line.product_key==='string'&&/^fc-[1-9]\d*-(ps|xbox|pc)$/.test(line.product_key));
    const row=catalogMapping.mappings?.[line.product_key],ref=line.product_ref;
    requireContract(row?.reference_key===line.product_key&&row.family==='fc'&&row.game_key==='fc'
      &&row.metadata_state==='observed'&&requiredEvidence.every(part=>row.verified_parts?.includes(part)));
    requireContract(row.original_status_guard_passed===true&&row.raw_status?.status===1&&row.raw_status?.auto_off===0,'NATIVE_FC_ORIGINAL_UNAVAILABLE');
    requireContract(exact(ref,['site_id','game_id','goods_id','model_id'])&&row.product_ref?.site_id==='266'
      &&row.product_ref.game_id==='1327'&&positive(row.product_ref.model_id));
    for(const key of ['site_id','game_id','goods_id'])requireContract(positive(ref[key])&&ref[key]===row.product_ref[key]);
    // Existing saved intents may omit model_id; an explicitly supplied value must match.
    if(Object.hasOwn(ref,'model_id'))requireContract(ref.model_id===row.product_ref.model_id);
    requireContract(exact(line.platform,['code','attribute_id'])&&['ps','xbox','pc'].includes(line.platform.code)
      &&line.platform.code===row.platform?.code&&positive(line.platform.attribute_id)
      &&line.platform.attribute_id===row.platform.attribute_id&&line.platform.attribute_id===row.observed_platform_attribute_id);
    const q=row.quantity,quantity=line.quantity;
    requireContract(exact(quantity,['value','unit','group'])&&q?.selection_mode==='fixed_original_choice'
      &&q.reference_unit===null&&q.meets_observed_minimum===true&&q.original_group_matches_observed_num===true
      &&positive(quantity.value)&&positive(quantity.group)&&quantity.value===q.reference_value
      &&quantity.group===q.reference_group&&quantity.group===q.observed_num&&quantity.unit==='item','NATIVE_FC_FIXED_QUANTITY_REQUIRED');
    // "item" is only the existing FS preview label; no native unit field is inferred.
    requireContract(empty(line.attributes)&&row.selection_schema==='empty_selectable_properties'
      &&empty(row.selectable_attributes)&&empty(row.sku_options),'NATIVE_FC_EMPTY_ATTRIBUTES_REQUIRED');
    for(const source of ['goods','model'])for(const name of ['saleprop','skuTableSet']){
      const observed=row.specification_evidence?.[source]?.[name];
      requireContract(observed?.present===true&&empty(observed.observed),'NATIVE_FC_EMPTY_ATTRIBUTES_REQUIRED');
    }
    const original=row.original_cart_serialization;
    requireContract(original?.contract==='fc-activity-core-payload-v1'&&original.source_artifact==='app/activity-core.js'
      &&original.verification_scope==='original_source_only'&&original.current_main_site_verified===false
      &&exact(original.fields,fields)&&Object.keys(original.fields).length===fields.length);
    const native_fields=core.payload({offer:{id:Number(ref.goods_id),group:Number(quantity.group),
      quantity:Number(quantity.value),aid:Number(line.platform.attribute_id)}});
    requireContract(fields.every(key=>native_fields[key]===original.fields[key]));
    return {context:{line_key,product_key:line.product_key,product_ref:{...ref},platform:{...line.platform},quantity:{...quantity},attributes:[]},native_fields};
  });
  return {contract:'fc-native-original-fields-v1',verification_scope:'historical_source_only',
    mapping_hash:catalogMapping.mappings_sha256,context,lines,live_checkout:false,current_main_site_verified:false,
    authoritative_quote:false,activity_price_guaranteed:false,native_idempotency_verified:false,native_unit_verified:false};
}
