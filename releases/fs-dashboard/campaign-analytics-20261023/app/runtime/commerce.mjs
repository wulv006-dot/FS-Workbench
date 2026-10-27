import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {atomic} from '../analytics/store.mjs';
import {canonical,digest,fail,id,projectRelease} from './snapshot.mjs';
import {createHalloweenReveals} from './halloween-reveal.mjs';
import nativeHandoff from '../native-code-handoff.js';

const uuid = value => {if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value || '')) fail('INVALID_REQUEST'); return value;};
const exact = (value, keys) => {if (!value || Array.isArray(value) || typeof value !== 'object' || Object.keys(value).some(k=>!keys.includes(k))) fail('INVALID_REQUEST');};
const read = file => fs.existsSync(file) ? JSON.parse(fs.readFileSync(file,'utf8')) : null;
const decimal = value => {if (typeof value!=='string' || !/^\d{1,12}(\.\d{1,6})?$/.test(value)) fail('INVALID_QUANTITY'); return BigInt(value.split('.')[0])*1000000n+BigInt((value.split('.')[1]||'').padEnd(6,'0'));};

export function createCommerce({snapshot,snapshotProvider,dir,mode='preview',now=Date.now,testAdapter,halloweenCatalogProvider}={}) {
  if (!['preview','integration_test','live'].includes(mode)) fail('INVALID_MODE');
  if (testAdapter && mode!=='integration_test') fail('INVALID_MODE');
  if (snapshotProvider && typeof snapshotProvider!=='function') fail('INVALID_RELEASE');
  // A fresh service can start before its first authenticated publication. Every
  // business read still validates the provider and fails closed until it exists.
  const initial=snapshotProvider?null:projectRelease(snapshot),base=path.join(dir,mode), test=mode==='integration_test';
  const current=()=>snapshotProvider?projectRelease(snapshotProvider()):initial;
  const reveals=createHalloweenReveals({dir:base,current,now,catalogProvider:halloweenCatalogProvider});
  fs.mkdirSync(base,{recursive:true,mode:0o700});
  const location=(kind,key)=>path.join(base,kind,uuid(key)+'.json');
  const result=(body)=>({...body,integration_mode:mode,live_checkout:false,...(test?{test_only:true}: {})});
  const missing=()=>fail('MAIN_INTEGRATION_REQUIRED',503);
  const loadIntent=(key,release)=>{const value=read(location('intents',key));if (!value) fail('INTENT_NOT_FOUND',404);if(value.release_id!==release.release_id || value.config_hash!==release.config_hash || value.rule_hash!==release.rule_hash) fail('RULE_VERSION_CONFLICT',409);return value;};
  const active=(intent,release)=>{
    const page=release.pages.find(p=>p.page_id===intent.page_id&&p.activity_id===intent.activity_id);
    if (!page || page.rule_version!==intent.rule_version || page.benefit_binding_version!==intent.benefit_binding_version) fail('RULE_VERSION_CONFLICT',409);
    if (page.starts_at && Date.parse(page.starts_at)>now()) fail('PROMOTION_NOT_STARTED',409);
    if (!page.active || page.ends_at && Date.parse(page.ends_at)<now()) fail('PROMOTION_EXPIRED',409);
    return page;
  };
  function amounts(intent) {
    return intent.lines.map(line=>{
      const price=testAdapter?.prices?.[line.product_key];
      if (!Number.isSafeInteger(price) || price<0) fail('MAIN_INTEGRATION_REQUIRED',503);
      const numerator=BigInt(price)*decimal(line.quantity.value);
      if (numerator%1000000n) fail('INVALID_QUANTITY');
      const base_minor=Number(numerator/1000000n);
      if (!Number.isSafeInteger(base_minor)) fail('INVALID_QUANTITY');
      return {line_key:line.line_key,base_minor,payable_minor:base_minor,adjustments:[]};
    });
  }
  function projectOutcome(raw,op) {
    const rows=op.payload.lines.map(line=>{
      const row=raw?.lines?.find(r=>r.line_key===line.line_key);
      const status=['confirmed','rejected','unknown'].includes(row?.status)?row.status:'unknown';
      return {line_key:line.line_key,status};
    });
    const known=rows.every(r=>r.status!=='unknown');
    return result({operation_id:op.id,status:known?'integration_test_result':'unknown',
      ...(known?{}:{code:'OPERATION_UNKNOWN'}),lines:rows,cart_mutated:false});
  }
  const unknown=op=>projectOutcome(null,op);
  const intentRecord=requestId=>{
    let value;try{value=read(location('intents',requestId));}catch{fail('INTENT_RECORD_UNCONFIRMED',503);}
    if(value&&(!value.request_hash||value.intent_id!==requestId||!value.operation_id))fail('INTENT_RECORD_UNCONFIRMED',503);
    return value;
  };
  const intentResult=value=>{const {request_hash,...publicValue}=value;return result({status:'intent_saved',...publicValue});};
  return {
    halloweenReveal:reveals.reveal,halloweenRead:reveals.read,halloweenResolve:reveals.resolve,
    nativePlan(selection){
      const release=current(),approved=nativeHandoff.publishedPlan(release,selection,{origin:release.native_checkout?.origin,now:now()});
      if(approved.reveal_request)reveals.resolve(approved.reveal_request);
      if(selection.page_id==='seasonal-vault')for(const line of selection.lines){
        const product=release.products.find(p=>p.key===line.product_key),contract=release.seasonal_model_contracts?.[product?.product_ref?.model_id];
        if(!contract?.combinations.some(c=>c.product_key===line.product_key&&c.quantity.min===line.quantity.value&&c.quantity.max===line.quantity.value&&c.quantity.unit===line.quantity.unit&&canonical(c.attributes)===canonical(line.attributes||[])&&c.price?.source==='admin_current'&&c.price.base_minor>0&&c.price.quantity_value===line.quantity.value&&Date.parse(c.price.expires_at)>now()))fail('CURRENT_PRICE_UNAVAILABLE',409);
      }

      const bindings=release.native_checkout.bindings.filter(b=>b.activity_id===selection.activity_id&&b.page_id===selection.page_id&&b.off_percent===selection.off_percent&&selection.lines.some(line=>line.product_key===b.product_key&&line.quantity?.value===b.quantity.value&&line.quantity?.unit===b.quantity.unit&&canonical(line.attributes||[])===canonical(b.attributes)));
      if(bindings.length!==selection.lines.length)fail('NATIVE_SCOPE_MISMATCH',409);
      return {status:'native_selection_prepared',release_id:release.release_id,config_hash:release.config_hash,rule_hash:release.rule_hash,native_checkout:{...release.native_checkout,bindings}};
    },

    config:()=>structuredClone(current()),
    capabilities:()=>{current();return result({adapter_version:'fs-standalone-v1',verified_at:null,catalog_source:'published_snapshot',catalog_authoritative:false,
      capabilities:{catalog_read:true,live_catalog_read:false,authoritative_quote:false,campaign_discount:false,stacked_discounts:false,cart_handoff:false,member_identity:false,coupon_management:false,order_discount_readback:false},
      test_capabilities:{quote:test&&!!testAdapter,prepare_checkout:test&&!!testAdapter},code:'MAIN_INTEGRATION_REQUIRED'});},
    intent(body) {
      exact(body,['request_id','activity_id','page_id','rule_version','benefit_binding_version','lines','currency']);
      const request_id=body.request_id==null?randomUUID():uuid(body.request_id),request_hash=digest(canonical(body));
      const prior=intentRecord(request_id);
      if(prior){if(prior.request_hash!==request_hash)fail('REQUEST_CONFLICT',409);return intentResult(prior);}
      const release=current();
      const context={activity_id:id(body.activity_id),page_id:id(body.page_id),rule_version:id(body.rule_version),benefit_binding_version:id(body.benefit_binding_version)};
      const page=active(context,release);
      if (body.currency!=='USD' || !Array.isArray(body.lines) || !body.lines.length || body.lines.length>50) fail('INVALID_REQUEST');
      const lines=body.lines.map(line=>{
        exact(line,['line_key','product_key','quantity','attributes']);
        const p=release.products.find(p=>p.key===line.product_key&&page.product_keys.includes(p.key));
        if (!p?.available) fail('PRODUCT_UNAVAILABLE',409);
        exact(line.quantity,['value','unit','group']);
        const value=decimal(line.quantity.value),min=decimal(p.quantity.min),step=decimal(p.quantity.step);
        if (value<min || value>decimal(p.quantity.max) || (value-min)%step || line.quantity.unit!==p.quantity.unit || line.quantity.group!==p.quantity.group) fail('INVALID_QUANTITY');
        const attrs=line.attributes||[];
        if (!Array.isArray(attrs)||attrs.length>30) fail('SPEC_INVALID');
        const attributes=attrs.map(a=>{exact(a,['attribute_id','value_id']);const spec=p.attributes.find(s=>s.attribute_id===a.attribute_id);if (!spec?.values.includes(a.value_id)) fail('SPEC_INVALID');return {attribute_id:id(a.attribute_id),value_id:id(a.value_id)};}).sort((a,b)=>a.attribute_id.localeCompare(b.attribute_id));
        if (new Set(attributes.map(a=>a.attribute_id)).size!==attributes.length) fail('SPEC_INVALID');
        if (p.attributes.some(a=>a.required&&!attributes.some(b=>b.attribute_id===a.attribute_id))) fail('SPEC_REQUIRED');
        return {line_key:id(line.line_key),product_key:p.key,product_ref:p.product_ref,platform:p.platform,quantity:{value:line.quantity.value,unit:p.quantity.unit,...(p.quantity.group?{group:p.quantity.group}:{})},attributes};
      });
      if (new Set(lines.map(l=>l.line_key)).size!==lines.length) fail('INVALID_REQUEST');
      const value={request_id,request_hash,intent_id:request_id,operation_id:randomUUID(),release_id:release.release_id,config_hash:release.config_hash,rule_hash:release.rule_hash,...context,currency:body.currency,lines,created_at:new Date(now()).toISOString()};
      const file=location('intents',request_id);fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o700});
      let fd;try{fd=fs.openSync(file,'wx',0o600);fs.writeFileSync(fd,JSON.stringify(value));fs.fsyncSync(fd);}
      catch(error){if(error.code==='EEXIST'){const stored=intentRecord(request_id);if(stored.request_hash!==request_hash)fail('REQUEST_CONFLICT',409);return intentResult(stored);}throw error;}
      finally{if(fd!==undefined)fs.closeSync(fd);}
      if(process.platform!=='win32'){const parent=fs.openSync(path.dirname(file),'r');try{fs.fsyncSync(parent);}finally{fs.closeSync(parent);}}
      return intentResult(value);
    },
    lookupIntent(requestId){const value=intentRecord(uuid(requestId));if(!value)fail('INTENT_NOT_FOUND',404);return intentResult(value);},
    quote(body) {
      exact(body,['intent_id']); const release=current(),intent=loadIntent(body.intent_id,release);active(intent,release);
      if (!test || !testAdapter) return missing();
      const lines=amounts(intent),total=lines.reduce((a,l)=>a+l.payable_minor,0);
      if (!Number.isSafeInteger(total)) fail('INVALID_QUANTITY');
      const value=result({status:'integration_test_quoted',quote_id:randomUUID(),intent_id:intent.intent_id,release_id:release.release_id,
        currency:intent.currency,minor_unit_scale:2,expires_at:new Date(now()+60000).toISOString(),rule_version:intent.rule_version,
        lines,payable_minor:total,authoritative:false});
      atomic(location('quotes',value.quote_id),value);return value;
    },
    async prepare(body) {
     try {
      exact(body,['operation_id','intent_id','quote_id','return_route_id']);
      const opId=uuid(body.operation_id),file=location('operations',opId);
      const request={operation_id:opId,intent_id:uuid(body.intent_id),quote_id:uuid(body.quote_id),return_route_id:id(body.return_route_id)};
      if (request.return_route_id!=='activity') fail('INVALID_RETURN_ROUTE');
      const release=current(),intent=loadIntent(request.intent_id,release);active(intent,release);
      const payloadHash=digest(canonical(request)),prior=read(file);
      if (prior) {if (prior.hash!==payloadHash) fail('REQUEST_CONFLICT',409);return prior.result||unknown(prior);}
      if (intent.operation_id!==opId) fail('REQUEST_CONFLICT',409);
      if (!test || !testAdapter) return missing();
      const quote=read(location('quotes',request.quote_id));
      if (!quote || quote.intent_id!==intent.intent_id || quote.release_id!==release.release_id) fail('QUOTE_INVALID',409);
      if (Date.parse(quote.expires_at)<=now()) fail('QUOTE_EXPIRED',409);
      if (canonical(quote.lines)!==canonical(amounts(intent))) fail('PRICE_CHANGED',409);
      // Reserve durably before invoking an adapter. A crash or timeout stays unknown; POST never invokes it twice.
      const op={id:opId,hash:payloadHash,payload:{...request,...intent},created_at:new Date(now()).toISOString()};
      fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o700});
      let fd;
      try {fd=fs.openSync(file,'wx',0o600);fs.writeFileSync(fd,JSON.stringify(op));fs.fsyncSync(fd);}
      catch(error) {if (error.code==='EEXIST') {const existing=read(file);if (existing.hash!==payloadHash) fail('REQUEST_CONFLICT',409);return existing.result||unknown(existing);}throw error;}
      finally {if (fd!==undefined) fs.closeSync(fd);}
      if (process.platform!=='win32') {const parent=fs.openSync(path.dirname(file),'r');try {fs.fsyncSync(parent);}finally {fs.closeSync(parent);}}
      try {op.result=projectOutcome(await testAdapter.prepare_checkout(structuredClone(op.payload)),op);}
      catch {op.result=unknown(op);}
      atomic(file,op);return op.result;
     }catch(error){
      if(['QUOTE_EXPIRED','PRICE_CHANGED','QUOTE_INVALID','RULE_VERSION_CONFLICT','PROMOTION_EXPIRED','PROMOTION_NOT_STARTED'].includes(error.code)&&error.status===409){
       const file=location('operations',body.operation_id);
       if(!fs.existsSync(file))error.dispatch_state='not_started';
      }
      throw error;
     }
    },
    async lookup(operationId) {
      const file=location('operations',operationId),op=read(file);
      if (!op) return result({operation_id:operationId,status:'unknown',code:'OPERATION_UNKNOWN'});
      if (op.result?.status==='integration_test_result') return op.result;
      // Lookup is read-only at the commerce boundary. Never recover by replaying prepare_checkout.
      if (test&&testAdapter?.lookup_checkout_operation) {
        try {const found=projectOutcome(await testAdapter.lookup_checkout_operation(operationId),op);if(found.status!=='unknown'){op.result=found;atomic(file,op);return found;}} catch {}
      }
      return op.result||unknown(op);
    }
  };
}

export function createIntegrationTestAdapter(prices) {
  return {prices,async prepare_checkout(payload) {return {lines:payload.lines.map(l=>({line_key:l.line_key,status:'confirmed'}))};},async lookup_checkout_operation() {return null;}};
}
