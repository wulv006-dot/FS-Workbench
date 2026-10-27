import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {makeCenterStore,initialCenterDraft,validateDraft} from '../center-store.mjs';
import {projectImportedProduct,addImportedProduct,centerSeed} from '../center-seed.mjs';
import {projectPreviewProduct,projectRelease} from '../../runtime/snapshot.mjs';
import {presentPage,projectFcCatalog} from '../../runtime/presentation.mjs';
import {createCommerce} from '../../runtime/commerce.mjs';

const original=JSON.parse(fs.readFileSync(new URL('../../catalog.json',import.meta.url),'utf8'));
const seed={seedProducts:[{key:'fc-original-ps',title:'Original fixture',product_ref:{site_id:'266',game_id:'1327',goods_id:'123'},platform:{code:'ps',attribute_id:'21587'},quantity:{unit:'item',min:'1',max:'1',step:'1'},attributes:[],available:false}],
 pageProductKeys:{'fc27-weekly':['fc-original-ps'],'fc27-sbc':['fc-original-ps'],'fc27-trio':['fc-original-ps'],'seasonal-vault':[]}};
const detail=()=>({product_ref:{site_id:'266',game_id:'1327',goods_id:'900000001',model_id:'900000002'},title:'Synthetic new item & metadata',platform_attribute_id:'21585',
 authoritative:false,checkout_enabled:false,quantity_observation:{minimum:'5',raw_unit:'',raw_num:null},price:'never forward',secret:'never forward',url:'https://untrusted.invalid/secret'});
const request=(state,page_id='fc27-weekly',product=detail())=>({revision:state.revision,operation_id:randomUUID(),draft:structuredClone(state.draft),page_id,product_ref:{...product.product_ref}});
function fixture(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'page-catalog-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const options={dir:path.join(dir,'private'),publicDir:path.join(dir,'public'),sourceRevision:'synthetic',...seed};return {dir,options,store:makeCenterStore(options)};}

test('trusted detail projection keeps observed unknown quantities and never copies prices, URLs or raw data',()=>{
 const product=projectImportedProduct(detail());assert.equal(product.available,false);assert.equal(product.preview_only,true);assert.equal(product.quantity,null);
 assert.deepEqual(product.observed_quantity,{minimum:'5',unit:'',group:null});assert.equal(product.platform.code,'xbox');
 assert.doesNotMatch(JSON.stringify(product),/never forward|https:|price|secret|url/);
 const unknown=detail();delete unknown.quantity_observation;assert.deepEqual(projectImportedProduct(unknown).observed_quantity,{minimum:null,unit:null,group:null});
 for(const mutate of [p=>p.title='<script>',p=>p.title='unsafe\ntext',p=>p.product_ref.site_id='999',p=>p.product_ref.model_id='0',p=>p.platform_attribute_id='../x',p=>p.checkout_enabled=true]){const p=detail();mutate(p);assert.throws(()=>projectImportedProduct(p));}
 for(const mutate of [p=>p.available=true,p=>p.quantity={unit:'item',min:'1',max:'1',step:'1'},p=>p.image='https://untrusted.invalid/x',p=>p.key='admin-forged',p=>p.observed_quantity.unit='<b>']){const p=structuredClone(product);mutate(p);assert.throws(()=>projectPreviewProduct(p));}
});

test('legacy drafts retain missing selection fields while explicit empty selections and siblings survive validation',()=>{
 const draft=initialCenterDraft();assert.deepEqual(validateDraft(draft),draft);
 draft.pages[0].product_keys=[];draft.pages[1].product_keys=['fc-original-ps'];
 assert.deepEqual(validateDraft(draft).pages.map(p=>p.product_keys),[[],['fc-original-ps'],undefined,undefined]);
 const added=addImportedProduct(draft,'fc27-weekly',detail(),seed);assert.equal(added.pages[0].product_keys.length,1);assert.deepEqual(added.pages[1],draft.pages[1]);
 const inherited=addImportedProduct(initialCenterDraft(),'fc27-weekly',detail(),seed);assert.deepEqual(inherited.pages[0].product_keys,['fc-original-ps',projectImportedProduct(detail()).key]);
 assert.deepEqual(addImportedProduct(inherited,'fc27-weekly',detail(),seed),inherited);
});

test('only trusted import adds metadata; normal save cannot add, edit or delete server-owned entries',t=>{
 const {store}=fixture(t),first=store.read(),forged=structuredClone(first.draft);forged.imported_products=[projectImportedProduct(detail())];
 assert.throws(()=>store.save({revision:0,operation_id:randomUUID(),draft:forged},'fixture'),{code:'IMPORTED_PRODUCTS_SERVER_OWNED'});
 const imported=store.importProduct(request(first),'fixture',detail());assert.equal(imported.revision,1);
 for(const mutate of [d=>d.imported_products[0].title='Tampered',d=>d.imported_products[0].available=true,d=>delete d.imported_products,d=>d.imported_products=[]]){const draft=structuredClone(imported.draft);mutate(draft);assert.throws(()=>store.save({revision:1,operation_id:randomUUID(),draft},'fixture'),{code:'IMPORTED_PRODUCTS_SERVER_OWNED'});}
 const draft=structuredClone(imported.draft);draft.pages[0].product_keys=[];draft.pages[0].product_roles={};draft.pages[2].description='Sibling page retained';
 const saved=store.save({revision:1,operation_id:randomUUID(),draft},'fixture');assert.deepEqual(saved.draft.pages[0].product_keys,[]);assert.equal(saved.draft.pages[2].description,'Sibling page retained');assert.deepEqual(saved.draft.imported_products,imported.draft.imported_products);
});

test('import CAS and durable replay bind original page, product identity and complete draft',t=>{
 const {store,options}=fixture(t),body=request(store.read()),saved=store.importProduct(body,'fixture',detail());
 const restarted=makeCenterStore(options);assert.deepEqual(restarted.importProduct(body,'fixture',detail()),saved);
 for(const changed of [{...body,page_id:'fc27-sbc'},{...body,product_ref:{...body.product_ref,goods_id:'999'}}])assert.throws(()=>restarted.importProduct(changed,'fixture',detail()),{code:'REQUEST_CONFLICT'});
 assert.throws(()=>restarted.importProduct({...body,operation_id:randomUUID()},'fixture',detail()),{code:'REVISION_CONFLICT'});
 const wrong=request(restarted.read());wrong.product_ref.model_id='999';assert.throws(()=>restarted.importProduct(wrong,'fixture',detail()),{code:'IMPORTED_PRODUCT_IDENTITY_MISMATCH'});
 const other=detail();other.product_ref.game_id='552';other.platform_attribute_id='0';
 assert.throws(()=>restarted.importProduct(request(restarted.read(),'fc27-weekly',other),'fixture',other),{code:'PAGE_PRODUCT_GAME_MISMATCH'});
 const seasonal=restarted.importProduct(request(restarted.read(),'seasonal-vault',other),'fixture',other);assert.equal(seasonal.draft.pages[3].product_keys.length,1);assert.deepEqual(seasonal.draft.pages[0],saved.draft.pages[0]);
});

test('publication consumes explicit page membership, preserves old seed fallback and remains unbuyable',t=>{
 const {store,dir}=fixture(t),imported=store.importProduct(request(store.read()),'fixture',detail()),key=imported.draft.imported_products[0].key;
 const draft=structuredClone(imported.draft);draft.pages[0].product_keys=[key];draft.pages[1].product_keys=[];
 store.save({revision:1,operation_id:randomUUID(),draft},'fixture');store.publish({revision:2,operation_id:randomUUID()},'fixture');
 const snapshot=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json'))),published=projectRelease(snapshot);
 assert.deepEqual(published.pages.map(p=>p.product_keys),[[key],[],['fc-original-ps'],[]]);assert(published.products.every(p=>p.available===false));assert.equal(published.products.find(p=>p.key===key).quantity,null);
 const commerce=createCommerce({snapshot,dir:path.join(dir,'runtime')});assert.throws(()=>commerce.intent({activity_id:'fc27-season2',page_id:'fc27-weekly',rule_version:'preview-3',benefit_binding_version:'unverified-3',currency:'USD',lines:[{line_key:'l',product_key:key,quantity:{value:'1',unit:'item'},attributes:[]}]}),{code:'PRODUCT_UNAVAILABLE'});
 const unknown=structuredClone(draft);unknown.pages[0].product_keys=['admin-unknown'];unknown.pages[0].product_roles={};assert.throws(()=>store.save({revision:3,operation_id:randomUUID(),draft:unknown},'fixture'),{code:'PAGE_PRODUCT_NOT_FOUND'});
 const removed=structuredClone(draft);removed.pages[0].product_keys=[];removed.pages[0].product_roles={};store.save({revision:3,operation_id:randomUUID(),draft:removed},'fixture');store.publish({revision:4,operation_id:randomUUID()},'fixture');
 const after=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json')));assert(!after.products.some(p=>p.key===key));assert.equal(store.read().draft.imported_products.length,1);
});

test('unknown platform and title produce stable explicit display labels without inventing an aid',()=>{
 const raw=detail();raw.platform_attribute_id=null;raw.title=null;
 const projected=projectImportedProduct(raw);assert.equal(projected.key,'admin-266-1327-900000001-unknown');
 assert.deepEqual(projected.platform,{code:'unknown'});assert.equal(projected.title,'商品ID 900000001');assert.equal(projected.title_source,'identity_fallback');
 assert.deepEqual(projectPreviewProduct(projected),projected);assert.equal(projected.quantity,null);assert.equal(projected.available,false);
});

test('committed import receipt is recoverable without detail or an available upstream reader',t=>{
 const {store,options}=fixture(t),body=request(store.read()),saved=store.importProduct(body,'fixture',detail());
 const offline=makeCenterStore(options);assert.deepEqual(offline.recoverImport(body),saved);
 assert.equal(offline.recoverImport({...body,operation_id:randomUUID()}),null);
 assert.throws(()=>offline.recoverImport({...body,page_id:'fc27-sbc'}),{code:'REQUEST_CONFLICT'});
 assert.throws(()=>offline.recoverImport({...body,product_ref:{...body.product_ref,goods_id:'other'}}),{code:'REQUEST_CONFLICT'});
});

test('page roles and explicit core/companion associations persist and render beside original SBC containers',t=>{
 const {store,dir}=fixture(t);let state=store.importProduct(request(store.read(),'fc27-sbc'),'fixture',detail());
 const second=detail();second.product_ref.goods_id='900000003';second.title='Synthetic companion';
 state=store.importProduct(request(state,'fc27-sbc',second),'fixture',second);
 const core=state.draft.imported_products[0].key,companion=state.draft.imported_products[1].key,draft=structuredClone(state.draft),page=draft.pages[1];
 assert.equal(page.product_roles[core],'preview');page.product_roles={[core]:'core',[companion]:'companion'};page.sbc_companions={[core]:[companion]};
 draft.pages[0].product_keys=['fc-original-ps'];draft.pages[0].product_roles={'fc-original-ps':'player'};
 for(const mutate of [d=>d.pages[1].product_roles[core]='bundle',d=>d.pages[1].product_roles['unselected']='core',d=>d.pages[1].sbc_companions[core]=[core],d=>d.pages[1].sbc_companions[core]=[companion,companion],d=>d.pages[0].sbc_companions={}]){const wrong=structuredClone(draft);mutate(wrong);assert.throws(()=>validateDraft(wrong));}
 store.save({revision:2,operation_id:randomUUID(),draft},'fixture');store.publish({revision:3,operation_id:randomUUID()},'fixture');
 const snapshot=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json')));assert.deepEqual(snapshot.pages[1].sbc_companions,{[core]:[companion]});assert.deepEqual(snapshot.pages[1].product_roles,page.product_roles);
 const source=fs.readFileSync(new URL('../../Sbc-Companions.html',import.meta.url),'utf8'),body=presentPage({name:'Sbc-Companions.html',body:source,snapshot}).body;
 assert.match(body,/Published SBC core previews/);assert.match(body,/Configured companion previews/);assert.match(body,/Synthetic companion/);
 assert(body.indexOf('data-display-role="core"')<body.indexOf('id="sbc-lineup"'));assert(body.indexOf('data-display-role="companion"')<body.indexOf('id="sbc-options"'));
 assert.match(presentPage({name:'Weekly-Scout.html',body:'<html><head></head><body>Original</body></html>',snapshot}).body,/Published player previews/);
 const noPair=structuredClone(snapshot);noPair.pages[1].sbc_companions={};assert.match(presentPage({name:'Sbc-Companions.html',body:source,snapshot:noPair}).body,/No companions configured. This is not a complete SBC lineup/);
 const invalid=structuredClone(snapshot);invalid.pages[1].product_roles[core]='pool';assert.throws(()=>projectRelease(invalid),{code:'INVALID_PRODUCT_ROLES'});
});

test('published original FC structure carries edited SBC picks, default core and trio ordering instead of reverting to source',t=>{
 const {options,dir}=fixture(t),fc=structuredClone(original),core=fc.sbc.ids[0];
 fc.sbc.routes[core].picks=['170014917','185070945'];fc.sbc.defaultId=core;fc.trio.ids.reverse();
 const changedSeed=centerSeed(fc,{products:[]}),store=makeCenterStore({...options,...changedSeed});
 store.save({revision:0,operation_id:randomUUID(),draft:initialCenterDraft()},'fixture');store.publish({revision:1,operation_id:randomUUID()},'fixture');
 const snapshot=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json'))),catalog=projectFcCatalog(original,snapshot);
 assert.deepEqual(snapshot.fc_layout.routes[core].picks,['170014917','185070945']);assert.deepEqual(catalog.sbc.routes[core].picks,['170014917','185070945']);
 assert.equal(catalog.sbc.defaultId,core);assert.deepEqual(catalog.trio.ids,fc.trio.ids);
 const wrong=structuredClone(snapshot);wrong.fc_layout.routes[core].picks=['not-an-original-product'];assert.throws(()=>projectRelease(wrong),{code:'INVALID_FC_LAYOUT'});
});

test('FC imported previews are page-isolated, escaped and excluded from original priced layout algorithms',()=>{
 const product=projectImportedProduct(detail()),snapshot={schema_version:1,release_id:'fixture',products:[product],pages:initialCenterDraft().pages.map(p=>({...p,active:true,product_keys:p.page_id==='fc27-weekly'?[product.key]:[]}))};
 const source='<html><head><title>Original</title><link rel="stylesheet" href="activity.css"></head><body><main>Original design</main></body></html>';
 const body=presentPage({name:'Weekly-Scout.html',body:source,snapshot}).body;assert.match(body,/Synthetic new item &amp; metadata/);assert.match(body,/Price unavailable/);assert.match(body,/Purchasing is not enabled/);assert.match(body,/Original design/);
 assert.equal((presentPage({name:'Weekly-Scout.html',body,snapshot}).body.match(/id="campaign-imported-products"/g)||[]).length,1);
 for(const name of ['Sbc-Companions.html','Player-Trio.html','seasonal/index.html'])assert.doesNotMatch(presentPage({name,body:source,snapshot}).body,/Synthetic new item/);
 const catalog=projectFcCatalog(original,snapshot);assert.equal(catalog.imported_products['fc27-weekly'][0].key,product.key);assert(!Object.hasOwn(catalog.products,product.key));assert.deepEqual(catalog.sbc.ids,[]);assert.deepEqual(catalog.trio.ids,[]);assert.equal(catalog.mode,'preview');
});
