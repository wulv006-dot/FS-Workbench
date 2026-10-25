import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import core from '../activity-core.js';
import {projectNativeFcIntent} from '../runtime/native-fc-contract.mjs';
import {createCommerce} from '../runtime/commerce.mjs';

const mapping=JSON.parse(fs.readFileSync(new URL('../../backend/catalog-mapping.json',import.meta.url),'utf8'));
const fc=Object.values(mapping.mappings).filter(row=>row.family==='fc');
const row=fc.find(row=>row.original_status_guard_passed&&row.platform.code==='xbox');
const line=r=>({line_key:'line-1',product_key:r.reference_key,product_ref:{...r.product_ref},platform:{...r.platform},
  quantity:{value:r.quantity.reference_value,unit:'item',group:r.quantity.reference_group},attributes:[]});
const intent=(r=row)=>({intent_id:randomUUID(),operation_id:randomUUID(),release_id:'fixture-release',activity_id:'fc27-season2',
  page_id:'fc27-weekly',rule_version:'fixture-rules',benefit_binding_version:'fixture-benefits',config_hash:'a'.repeat(64),
  rule_hash:'b'.repeat(64),currency:'USD',lines:[line(r)]});

test('all original FC fixed references reuse the existing payload algorithm and retain unavailable guards',()=>{
  assert.equal(fc.length,78);let accepted=0,rejected=0;
  for(const r of fc){const body=intent(r);
    if(!r.original_status_guard_passed){assert.throws(()=>projectNativeFcIntent(body,mapping),{code:'NATIVE_FC_ORIGINAL_UNAVAILABLE'});rejected++;continue;}
    const output=projectNativeFcIntent(body,mapping),native=output.lines[0].native_fields;
    assert.deepEqual(native,r.original_cart_serialization.fields);
    assert.deepEqual(native,core.payload({offer:{id:Number(r.product_ref.goods_id),group:Number(r.quantity.reference_group),quantity:Number(r.quantity.reference_value),aid:Number(r.platform.attribute_id)}}));
    assert.deepEqual(Object.keys(native).sort(),['aid','attr','category','group','id','num']);accepted++;
  }
  assert.deepEqual([accepted,rejected],[72,6]);
});

test('activity and operation context remains in the local envelope, with no price or idempotency promise',()=>{
  const body=intent();body.native_extra='must-not-forward';body.price_minor=1;
  const original=structuredClone(body),output=projectNativeFcIntent(body,mapping);
  assert.deepEqual(body,original);assert.deepEqual(projectNativeFcIntent(body,mapping),output);
  for(const key of ['intent_id','operation_id','release_id','activity_id','page_id','rule_version','benefit_binding_version','config_hash','rule_hash','currency'])assert.equal(output.context[key],body[key]);
  assert.deepEqual(output.lines[0].context,body.lines[0]);assert.notEqual(row.product_ref.goods_id,row.reference_key.split('-')[1]);
  assert.equal(output.lines[0].native_fields.id,row.product_ref.goods_id);assert.equal(output.lines[0].native_fields.attr,'');
  for(const key of ['live_checkout','current_main_site_verified','authoritative_quote','activity_price_guaranteed','native_idempotency_verified','native_unit_verified'])assert.equal(output[key],false);
  assert.equal(output.verification_scope,'historical_source_only');assert(!JSON.stringify(output).includes('must-not-forward'));assert(!JSON.stringify(output).includes('price_minor'));
  delete body.lines[0].product_ref.model_id;assert.doesNotThrow(()=>projectNativeFcIntent(body,mapping));
});

test('identity, fixed quantity, empty attributes and unique line context fail closed',()=>{
  for(const mutate of [
    b=>b.lines[0].product_ref.goods_id='999',b=>b.lines[0].product_ref.model_id='999',b=>b.lines[0].product_ref.site_id='999',
    b=>b.lines[0].product_ref.game_id='999',b=>b.lines[0].product_ref.sku_id='999',b=>b.lines[0].platform.code='ps',
    b=>b.lines[0].platform.attribute_id='21587',b=>b.lines[0].quantity.value='2',b=>b.lines[0].quantity.value='1.0',
    b=>b.lines[0].quantity.value=1,b=>b.lines[0].quantity.group='2',b=>b.lines[0].quantity.unit='K',
    b=>b.lines[0].attributes=[{attribute_id:'edition',value_id:'gold'}],b=>b.lines[0].native_extra='x',
    b=>b.lines.push(structuredClone(b.lines[0])),b=>b.lines[0].product_key='seasonal-1',b=>b.lines=[],b=>delete b.rule_hash
  ]){const body=intent();mutate(body);assert.throws(()=>projectNativeFcIntent(body,mapping));}
  const body=intent();body.lines.push({...structuredClone(body.lines[0]),line_key:'line-2'});
  const output=projectNativeFcIntent(body,mapping);assert.equal(output.lines.length,2);assert.deepEqual(output.lines.map(l=>l.context.line_key),['line-1','line-2']);
});

test('inconsistent original serialization and unsupported specification evidence cannot become native fields',()=>{
  for(const mutate of [
    r=>r.original_cart_serialization.fields.aid='999',r=>r.original_cart_serialization.fields.id='999',
    r=>r.original_cart_serialization.fields.num='2',r=>r.original_cart_serialization.fields.group='2',
    r=>r.original_cart_serialization.fields.attr='a=b',r=>r.original_cart_serialization.fields.category='currency',
    r=>r.original_cart_serialization.fields.activity_id='smuggled',r=>r.original_cart_serialization.current_main_site_verified=true,
    r=>r.quantity.selection_mode='arbitrary',r=>r.specification_evidence.goods.saleprop.observed=[{id:'1'}],
    r=>r.sku_options=[{id:'1'}],r=>r.observed_platform_attribute_id='999',r=>r.verified_parts=[]
  ]){const modified=structuredClone(mapping);mutate(modified.mappings[row.reference_key]);assert.throws(()=>projectNativeFcIntent(intent(),modified));}
});

test('pure projection makes no request and does not change preview or unverified-live commerce gates',async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'native-fc-contract-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const originalFetch=globalThis.fetch;let requests=0;globalThis.fetch=()=>{requests++;throw Error('network forbidden');};t.after(()=>{globalThis.fetch=originalFetch;});
  const seed=intent(),snapshot={schema_version:1,publication_status:'published',release_id:seed.release_id,source_revision:'synthetic',
    config_hash:seed.config_hash,rule_hash:seed.rule_hash,pages:[{activity_id:seed.activity_id,page_id:seed.page_id,path:'Weekly-Scout.html',
      title:'Synthetic page',rule_version:seed.rule_version,benefit_binding_version:seed.benefit_binding_version,active:true,product_keys:[row.reference_key]}],
    products:[{key:row.reference_key,title:'Synthetic product',product_ref:row.product_ref,platform:row.platform,
      quantity:{min:'1',max:'1',step:'1',unit:'item',group:'1'},attributes:[],available:true}]};
  for(const mode of ['preview','live']){
    const commerce=createCommerce({snapshot,dir,mode}),saved=commerce.intent({activity_id:seed.activity_id,page_id:seed.page_id,
      rule_version:seed.rule_version,benefit_binding_version:seed.benefit_binding_version,currency:'USD',
      lines:[{line_key:'line-1',product_key:row.reference_key,quantity:seed.lines[0].quantity,attributes:[]}]});
    assert.equal(projectNativeFcIntent(saved,mapping).live_checkout,false);
    assert.throws(()=>commerce.quote({intent_id:saved.intent_id}),{code:'MAIN_INTEGRATION_REQUIRED'});
    await assert.rejects(commerce.prepare({operation_id:saved.operation_id,intent_id:saved.intent_id,quote_id:randomUUID(),return_route_id:'activity'}),{code:'MAIN_INTEGRATION_REQUIRED'});
    assert.equal(commerce.capabilities().capabilities.cart_handoff,false);
  }
  assert.equal(requests,0);
});
