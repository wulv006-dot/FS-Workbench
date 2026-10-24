import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {randomUUID} from 'node:crypto';
import {createCommerce,createIntegrationTestAdapter} from '../commerce.mjs';
import {createPublicServer} from '../server.mjs';
import {createSnapshot,digest,loadStatic,projectRelease,validateSnapshot} from '../snapshot.mjs';

const snapshot=()=>({schema_version:1,publication_status:'published',release_id:'release-1',source_revision:'df93de3',config_hash:'a'.repeat(64),rule_hash:'b'.repeat(64),
  secret:'phx_never_expose',admin_raw:{password:'never'},capabilities:{cart_handoff:true},
  pages:['weekly','trio'].map(page_id=>({activity_id:'fc27-'+page_id,page_id,rule_version:'rules-1',benefit_binding_version:'benefits-1',path:page_id+'.html',title:'Test',active:true,product_keys:['sku-1']})),
  products:[{key:'sku-1',title:'Player',product_ref:{site_id:'266',game_id:'1327',goods_id:'123',sku_id:'456',secret:'never'},platform:{code:'ps',attribute_id:'21587'},quantity:{unit:'item',min:'1',max:'10',step:'1'},available:true,attributes:[{attribute_id:'edition',required:true,values:['gold']}],cost:1234}]});
const request=(page='weekly')=>({activity_id:'fc27-'+page,page_id:page,rule_version:'rules-1',benefit_binding_version:'benefits-1',currency:'USD',lines:[{line_key:'line-1',product_key:'sku-1',quantity:{value:'1',unit:'item'},attributes:[{attribute_id:'edition',value_id:'gold'}]}]});
function temp(t) {const dir=fs.mkdtempSync(path.join(os.tmpdir(),'campaign-runtime-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));return dir;}
function commerce(t,options={}) {return createCommerce({snapshot:snapshot(),dir:temp(t),...options});}
function checkout(c,intent=c.intent(request())) {const quote=c.quote({intent_id:intent.intent_id});return {operation_id:intent.operation_id,intent_id:intent.intent_id,quote_id:quote.quote_id,return_route_id:'activity'};}

test('published field projection excludes admin, cost and capability inputs',()=>{
  const value=projectRelease(snapshot()),serialized=JSON.stringify(value);
  assert.deepEqual(validateSnapshot(createSnapshot(snapshot())),value);
  for(const forbidden of ['phx_','admin_raw','password','secret','cost','capabilities']) assert.ok(!serialized.includes(forbidden));
  assert.throws(()=>projectRelease({...snapshot(),publication_status:'draft'}),{code:'UNPUBLISHED_RELEASE'});
  assert.throws(()=>projectRelease({...snapshot(),products:[...snapshot().products,...snapshot().products]}),{code:'INVALID_RELEASE'});
});
test('intent request receipt survives lost response, deduplicates exact retry and refuses corrupt records',t=>{
 const dir=temp(t),options={snapshot:snapshot(),dir},c=createCommerce(options),body={...request(),request_id:randomUUID()};
 assert.throws(()=>c.lookupIntent(body.request_id),{code:'INTENT_NOT_FOUND'});
 const first=c.intent(body),restarted=createCommerce(options);
 assert.deepEqual(restarted.lookupIntent(body.request_id),first);assert.deepEqual(restarted.intent(body),first);
 assert.throws(()=>restarted.intent({...body,currency:'EUR'}),{code:'REQUEST_CONFLICT'});
 const broken=randomUUID();fs.writeFileSync(path.join(dir,'preview/intents',broken+'.json'),'{');
 assert.throws(()=>restarted.lookupIntent(broken),{code:'INTENT_RECORD_UNCONFIRMED'});
 assert.throws(()=>restarted.intent({...body,request_id:broken}),{code:'INTENT_RECORD_UNCONFIRMED'});
});
test('preview and unverified live cannot quote or handoff, regardless of browser flags',async t=>{
  for(const mode of ['preview','live']) {
    const c=commerce(t,{mode}),intent=c.intent(request());
    assert.equal(c.capabilities().capabilities.cart_handoff,false);
    assert.equal(c.capabilities().catalog_source,'published_snapshot');assert.equal(c.capabilities().catalog_authoritative,false);assert.equal(c.capabilities().capabilities.live_catalog_read,false);
    assert.throws(()=>c.quote({intent_id:intent.intent_id}),{code:'MAIN_INTEGRATION_REQUIRED'});
    assert.throws(()=>c.quote({intent_id:intent.intent_id,mode:'integration_test'}),{code:'INVALID_REQUEST'});
    await assert.rejects(c.prepare({operation_id:intent.operation_id,intent_id:intent.intent_id,quote_id:randomUUID(),return_route_id:'activity'}),{code:'MAIN_INTEGRATION_REQUIRED'});
  }
  assert.throws(()=>commerce(t,{mode:'live',testAdapter:createIntegrationTestAdapter({'sku-1':10000})}),{code:'INVALID_MODE'});
});
test('product scope, specification, quantity and campaign context are enforced',t=>{
  const c=commerce(t),intent=c.intent(request());assert.equal(intent.lines[0].product_ref.goods_id,'123');
  for (const [mutate,code] of [
    [b=>b.lines[0].attributes=[],'SPEC_REQUIRED'],[b=>b.lines[0].attributes[0].value_id='other','SPEC_INVALID'],
    [b=>b.lines[0].quantity.value='0','INVALID_QUANTITY'],[b=>b.lines[0].quantity.value='1.5','INVALID_QUANTITY'],
    [b=>b.lines[0].product_key='other','PRODUCT_UNAVAILABLE'],[b=>b.rule_version='old','RULE_VERSION_CONFLICT'],
    [b=>b.lines.push(b.lines[0]),'INVALID_REQUEST'],[b=>b.lines[0].price_minor=1,'INVALID_REQUEST']]) {
    const body=request();mutate(body);assert.throws(()=>c.intent(body),{code});
  }
  const trio=c.intent(request('trio'));assert.notEqual(trio.activity_id,intent.activity_id);assert.equal(trio.lines[0].product_ref.goods_id,intent.lines[0].product_ref.goods_id);
});
test('integration test quote/result are unmistakable, repeat stable and conflicts rejected',async t=>{
  const prices={'sku-1':10000},c=commerce(t,{mode:'integration_test',testAdapter:createIntegrationTestAdapter(prices)}),body=checkout(c);
  const quote=c.quote({intent_id:body.intent_id});assert.equal(quote.authoritative,false);assert.equal(quote.test_only,true);assert.equal(quote.status,'integration_test_quoted');
  const [first,second]=await Promise.all([c.prepare(body),c.prepare(body)]);
  assert.equal(first.status,'integration_test_result');assert.equal(first.live_checkout,false);assert.equal(first.cart_mutated,false);assert.equal(first.test_only,true);assert.ok(!('checkout_url' in first));
  assert.ok(['unknown','integration_test_result'].includes(second.status));assert.deepEqual(await c.prepare(body),first);
  await assert.rejects(c.prepare({...body,quote_id:quote.quote_id}),{code:'REQUEST_CONFLICT'});
  await assert.rejects(c.prepare({...body,operation_id:randomUUID()}),{code:'REQUEST_CONFLICT'});
  assert.deepEqual(await c.lookup(body.operation_id),first);
});
test('mixed test outcomes retain every original line and never claim whole cart success',async t=>{
  const adapter={prices:{'sku-1':10000},async prepare_checkout(){return {lines:[{line_key:'line-1',status:'confirmed'},{line_key:'line-2',status:'rejected'}]};}};
  const c=commerce(t,{mode:'integration_test',testAdapter:adapter}),selection=request();selection.lines.push({...selection.lines[0],line_key:'line-2'});
  const result=await c.prepare(checkout(c,c.intent(selection)));
  assert.deepEqual(result.lines,[{line_key:'line-1',status:'confirmed'},{line_key:'line-2',status:'rejected'}]);assert.equal(result.status,'integration_test_result');assert.equal(result.cart_mutated,false);assert.equal(result.test_only,true);
});
test('expiry and current fixture price changes require another quote',async t=>{
  let time=100000;const prices={'sku-1':10000},c=commerce(t,{mode:'integration_test',testAdapter:createIntegrationTestAdapter(prices),now:()=>time});
  const body=checkout(c);prices['sku-1']=9000;await assert.rejects(c.prepare(body),{code:'PRICE_CHANGED',dispatch_state:'not_started'});
  prices['sku-1']=10000;time+=60001;await assert.rejects(c.prepare(body),{code:'QUOTE_EXPIRED',dispatch_state:'not_started'});
});
test('durable unknown lookup never reposts after restart and projects partial results safely',async t=>{
  const dir=temp(t);let calls=0,lookups=0,known=false;
  const adapter={prices:{'sku-1':10000},async prepare_checkout(){calls++;throw Error('secret backend URL and token');},async lookup_checkout_operation(id){lookups++;assert.equal(id,body.operation_id);return known?{token:'secret',checkout_url:'https://evil.invalid',lines:[{line_key:'line-1',status:'rejected',message:'password'}]}:null;}};
  let c=createCommerce({snapshot:snapshot(),dir,mode:'integration_test',testAdapter:adapter});const body=checkout(c);
  assert.equal((await c.prepare(body)).code,'OPERATION_UNKNOWN');
  c=createCommerce({snapshot:snapshot(),dir,mode:'integration_test',testAdapter:adapter});
  assert.equal((await c.prepare(body)).code,'OPERATION_UNKNOWN');assert.equal(calls,1);assert.equal(lookups,0);
  assert.equal((await c.lookup(body.operation_id)).code,'OPERATION_UNKNOWN');known=true;
  const value=await c.lookup(body.operation_id);assert.equal(value.lines[0].status,'rejected');assert.ok(!JSON.stringify(value).includes('secret'));assert.ok(!('checkout_url' in value));assert.equal(calls,1);
  const preview=createCommerce({snapshot:snapshot(),dir,mode:'preview'});assert.equal((await preview.lookup(body.operation_id)).status,'unknown');
});
test('published config reload rejects old intents and preserves original unknown operation lookup',async t=>{
  const dir=temp(t),file=path.join(dir,'current.json');let calls=0,known=false;
  const publish=value=>fs.writeFileSync(file,JSON.stringify(value));publish(snapshot());
  const adapter={prices:{'sku-1':10000},async prepare_checkout(){calls++;throw Error('uncertain');},async lookup_checkout_operation(){return known?{lines:[{line_key:'line-1',status:'confirmed'}]}:null;}};
  const c=createCommerce({snapshotProvider:()=>JSON.parse(fs.readFileSync(file,'utf8')),dir,mode:'integration_test',testAdapter:adapter});
  const original=checkout(c),unsubmitted=checkout(c);assert.equal((await c.prepare(original)).code,'OPERATION_UNKNOWN');
  const next=snapshot();next.release_id='release-2';next.config_hash='c'.repeat(64);next.pages.forEach(p=>p.rule_version='rules-2');publish(next);
  assert.equal(c.config().release_id,'release-2');assert.throws(()=>c.intent(request()),{code:'RULE_VERSION_CONFLICT'});
  assert.throws(()=>c.quote({intent_id:unsubmitted.intent_id}),{code:'RULE_VERSION_CONFLICT'});
  await assert.rejects(c.prepare(unsubmitted),{code:'RULE_VERSION_CONFLICT'});
  await assert.rejects(c.prepare(original),error=>error.code==='RULE_VERSION_CONFLICT'&&error.dispatch_state===undefined);
  const updated=request();updated.rule_version='rules-2';assert.equal(c.intent(updated).release_id,'release-2');
  assert.equal((await c.lookup(original.operation_id)).code,'OPERATION_UNKNOWN');assert.equal(calls,1);
  publish({...next,publication_status:'draft'});assert.throws(()=>c.config(),{code:'UNPUBLISHED_RELEASE'});assert.throws(()=>c.quote({intent_id:unsubmitted.intent_id}),{code:'UNPUBLISHED_RELEASE'});
  known=true;assert.equal((await c.lookup(original.operation_id)).lines[0].status,'confirmed');assert.equal(calls,1);
});
test('static whitelist rejects management/docs/traversal, hashes and symlinks',t=>{
  const root=temp(t);fs.writeFileSync(path.join(root,'index.html'),'public');const manifest={'index.html':digest('public')};
  assert.equal(loadStatic(root,manifest).get('index.html').toString(),'public');
  for(const name of ['analytics/products.html','runtime/server.mjs','state.json','README.md','../index.html','assets/../index.html','catalog.json']) assert.throws(()=>loadStatic(root,{[name]:digest('public')}));
  assert.throws(()=>loadStatic(root,{'index.html':'0'.repeat(64)}),{code:'STATIC_HASH_MISMATCH'});
  const link=path.join(root,'assets');try {fs.symlinkSync(root,link,process.platform==='win32'?'junction':'dir');}catch(error){if(error.code==='EPERM')return;throw error;}
  assert.throws(()=>loadStatic(root,{'assets/picture.png':digest('public')}),{code:'INVALID_PUBLIC_PATH'});
});
test('HTTP boundary requires exact Origin, never exposes internal files and freezes release/static bytes',async t=>{
  const root=temp(t);fs.writeFileSync(path.join(root,'index.html'),'public');
  const input=snapshot();input.pages[0].path='Weekly-Scout.html';const server=createPublicServer({assetRoot:root,staticManifest:{'index.html':digest('public')},snapshot:input,dir:temp(t),origin:'http://127.0.0.1',prefix:'/events/'});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>server.close(resolve)));
  const base='http://127.0.0.1:'+server.address().port;
  const get=async route=>{const r=await fetch(base+route);return {status:r.status,body:await r.text(),headers:r.headers};};
  input.secret='mutated';input.products[0].title='mutated';fs.writeFileSync(path.join(root,'index.html'),'changed');
  assert.equal((await get('/events/')).body,'public');assert.equal((await get('/events/')).headers.get('x-robots-tag'),'noindex, nofollow');
  const config=await get('/events/api/campaign/config');assert.equal(config.status,200);assert.ok(!config.body.includes('mutated'));assert.ok(!config.body.includes('phx_'));
  for(const url of ['/events/analytics/api/config','/events/runtime/server.mjs','/events/state.json','/events/%252e%252e/index.html','/events/%5c..%5cstate.json']) assert.equal((await get(url)).status,404);
  const raw=await new Promise((resolve,reject)=>{http.get(base+'/events/%2e%2e/index.html',r=>{r.resume();r.on('end',()=>resolve(r.statusCode));}).on('error',reject);});assert.equal(raw,404);
  const post=async origin=>fetch(base+'/events/api/campaign/intents',{method:'POST',headers:{'Content-Type':'application/json',Origin:origin},body:JSON.stringify(request())});
  assert.equal((await post('https://evil.invalid')).status,403);assert.equal((await post('http://127.0.0.1')).status,200);
  assert.equal((await fetch(base+'/events/api/campaign/config',{method:'POST',headers:{'Content-Type':'application/json',Origin:'http://127.0.0.1'},body:'{}'})).status,404);
});
test('public HTTP provider refreshes published configuration while deployment assets stay pinned',async t=>{
  const root=temp(t);fs.writeFileSync(path.join(root,'index.html'),'deployed bytes');let current=snapshot();current.pages[0].path='Weekly-Scout.html';
  const server=createPublicServer({assetRoot:root,staticManifest:{'index.html':digest('deployed bytes')},snapshotProvider:()=>current,dir:temp(t),origin:'http://127.0.0.1'});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>server.close(resolve)));
  const base='http://127.0.0.1:'+server.address().port+'/events/';
  assert.equal((await (await fetch(base+'api/campaign/config')).json()).release_id,'release-1');
  current=snapshot();current.pages[0].path='Weekly-Scout.html';current.release_id='release-2';current.secret='never';fs.writeFileSync(path.join(root,'index.html'),'edited after startup');
  const next=await (await fetch(base+'api/campaign/config')).json();assert.equal(next.release_id,'release-2');assert.ok(!('secret' in next));
  assert.equal(await (await fetch(base)).text(),'deployed bytes');
  current.publication_status='draft';assert.equal((await fetch(base+'api/campaign/config')).status,503);assert.equal((await fetch(base)).status,503);
});


test('published configuration controls actual HTML and pinned catalog response after republish',async t=>{
 const root=temp(t),html='<html><head><title>Old</title></head><body><main>Original offers</main><script src="activity.js"></script></body></html>';
 fs.writeFileSync(path.join(root,'Weekly-Scout.html'),html);
 const catalog=fs.readFileSync(new URL('../../catalog.js',import.meta.url));fs.writeFileSync(path.join(root,'catalog.js'),catalog);
 let current=snapshot();Object.assign(current.pages[0],{path:'Weekly-Scout.html',title:'Published first',description:'Verified published copy',product_keys:[]});
 const server=createPublicServer({assetRoot:root,staticManifest:{'Weekly-Scout.html':digest(html),'catalog.js':digest(catalog)},snapshotProvider:()=>current,dir:temp(t),origin:'http://127.0.0.1'});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>server.close(resolve)));
 const base='http://127.0.0.1:'+server.address().port+'/events/';
 assert.match(await(await fetch(base+'Weekly-Scout.html')).text(),/<title>Published first<\/title>/);
 const projected=JSON.parse((await(await fetch(base+'catalog.js')).text()).replace(/^window.FC_ACTIVITY_CONFIG=/,'').replace(/;$/,''));assert.deepEqual(projected.weekly.ids,[]);assert.equal(projected.manageDocumentLanguage,false);
 current.pages[0].active=false;let response=await fetch(base+'Weekly-Scout.html');assert.equal(response.status,404);assert.ok(!(await response.text()).includes('Original offers'));
 current.pages[0].active=true;current.pages[0].ends_at='2000-01-01T00:00:00Z';response=await fetch(base+'Weekly-Scout.html');assert.equal(response.status,410);
 delete current.pages[0].ends_at;current.pages[0].title='Republished exact';assert.match(await(await fetch(base+'Weekly-Scout.html')).text(),/<title>Republished exact<\/title>/);
});

 test('fresh service waits fail-closed for first publication without inventing a snapshot',t=>{
 let published=null;const c=createCommerce({snapshotProvider:()=>{if(!published)throw Error('not published');return published;},dir:temp(t)});
 assert.throws(()=>c.config());published=snapshot();assert.equal(c.config().release_id,'release-1');published=null;assert.throws(()=>c.config());
 });
