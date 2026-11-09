import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {deflateSync} from 'node:zlib';
import {makeCenterStore,initialCenterDraft} from '../center-store.mjs';
import {centerSeed,effectivePageBindings} from '../center-seed.mjs';
import {initialLayout,validateLayout,previewCatalog} from '../store.mjs';
import {effectiveFcCatalog,projectModelCard} from '../../runtime/model-cards.mjs';
import {inspectImage,makeMediaStore} from '../media-store.mjs';
import {readPublishedMedia} from '../../runtime/published-media.mjs';
import {mediaLimits} from '../../runtime/media-contract.mjs';
import {projectRelease,digest} from '../../runtime/snapshot.mjs';
import {projectFcCatalog,presentPage} from '../../runtime/presentation.mjs';
import {createCommerce} from '../../runtime/commerce.mjs';
import {createPublicServer} from '../../runtime/server.mjs';

const app=new URL('../../',import.meta.url),catalog=JSON.parse(fs.readFileSync(new URL('catalog.json',app),'utf8'));
function pngFixture(width=1,height=1){
 const chunk=(name,data)=>{const body=Buffer.concat([Buffer.from(name),data]),out=Buffer.alloc(body.length+8);out.writeUInt32BE(data.length);body.copy(out,4);let crc=0xffffffff;for(const b of body){crc^=b;for(let bit=0;bit<8;bit++)crc=crc&1?0xedb88320^(crc>>>1):crc>>>1;}out.writeUInt32BE((crc^0xffffffff)>>>0,out.length-4);return out;};
 const header=Buffer.alloc(13);header.writeUInt32BE(width);header.writeUInt32BE(height,4);header[8]=8;header[9]=6;
 return Buffer.concat([Buffer.from('89504e470d0a1a0a','hex'),chunk('IHDR',header),chunk('IDAT',deflateSync(Buffer.from([0,255,0,0,255]))),chunk('IEND',Buffer.alloc(0))]);
}
const png=pngFixture();
// A synthetic one-pixel image encoded by the local JPEG codec, no remote fixture.
const jpeg=Buffer.from('/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5/ooooA//2Q==','base64');
const model=()=>({key:'model-266-1327-900000031',site_id:'266',game_id:'1327',model_id:'900000031',kind:'player',title:'Synthetic model card',version_label:null,image_url:null,image_provenance:null,
 platforms:{ps:{state:'verified',product_ref:{site_id:'266',game_id:'1327',model_id:'900000031',goods_id:'900000041'},observed_quantity:{minimum:'1',unit:'',group:'1'}},xbox:{state:'missing',product_ref:null,observed_quantity:null},pc:{state:'unknown',product_ref:null,observed_quantity:null}},
 verification_scope:'catalog_identity_only',site_association:'observed',available:false,authoritative:false,checkout_enabled:false});
function fixture(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'model-media-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const options={dir:path.join(dir,'private'),publicDir:path.join(dir,'public'),sourceRevision:'synthetic',
 validateFcLayout:(layout,models)=>validateLayout(layout,effectiveFcCatalog(catalog,models)),seedProvider:(layout,models)=>centerSeed(previewCatalog(effectiveFcCatalog(catalog,models),layout??initialLayout(catalog)),{products:[]})};return {dir,options,store:makeCenterStore(options)};}
function request(store,card=model()){const draft=structuredClone(store.read().draft);draft.fc_layout||=structuredClone(initialLayout(catalog));draft.fc_layout.weekly=[card.key];return {revision:store.read().revision,operation_id:randomUUID(),draft,page_id:'fc27-weekly',model_id:card.model_id,kind:card.kind};}
const ref=asset=>({asset_id:asset.asset_id,alt:'English image preview',public_english_confirmed:true});

test('resolver facts preserve unknown platform/version/image and cannot manufacture a sellable offer',()=>{
 const card=projectModelCard(model());assert.equal(card.platforms.xbox.state,'missing');assert.equal(card.platforms.pc.state,'unknown');assert.equal(card.version_label,null);assert.equal(card.image_url,null);
 for(const mutate of [m=>m.site_association='not_yet_verified',m=>m.available=true,m=>m.authoritative='false',m=>m.checkout_enabled=undefined,m=>m.platforms.xbox.state='verified',m=>m.platforms.pc.product_ref={...m.platforms.ps.product_ref},m=>m.kind='unknown']){const bad=model();mutate(bad);assert.throws(()=>projectModelCard(bad));}
 const remote=model();remote.image_url='https://untrusted.invalid/image.png';assert.equal(projectModelCard(remote).image_url,null);
});

test('uploaded Admin images survive model projection and SBC accepts eighteen shared players',()=>{
 const card=model();card.image_url='https://b2c-static.p2pah.cn/images/202611/example.png';card.image_provenance='admin_model_uploaded_asset';
 assert.equal(projectModelCard(card).image_url,card.image_url);assert.equal(projectModelCard(card).image_provenance,card.image_provenance);
 const c=structuredClone(catalog),layout=structuredClone(initialLayout(catalog)),players=Array.from({length:18},(_,i)=>'normal-'+i);
 for(const key of players)c.products[key]={kind:'player'};
 for(const core of layout.sbc)layout.routes[core]={picks:players.slice(0,2),alternatives:players.slice(2)};
 assert.equal(validateLayout(layout,c).routes[layout.sbc[0]].alternatives.length,16);
 c.products.overflow={kind:'player'};layout.routes[layout.sbc[0]].alternatives.push('overflow');assert.throws(()=>validateLayout(layout,c));
});

test('one fc_layout model card publishes three metadata variants in the original card catalog, never a price or native purchase',t=>{
 const {store,options,dir}=fixture(t),card=model(),body=request(store,card),saved=store.importModel(body,'fixture',card);
 assert.deepEqual(store.recoverModel(body),saved);assert.equal(saved.draft.fc_models[card.key].platforms.pc.state,'unknown');
 const selected=effectivePageBindings(saved.draft,options.seedProvider(saved.draft.fc_layout,saved.draft.fc_models),'fc27-weekly');assert.equal(selected.source,'inherited');assert.deepEqual(selected.model_cards[0].selected_platforms,['ps','xbox','pc']);
 store.publish({revision:1,operation_id:randomUUID()},'fixture');const snapshot=JSON.parse(fs.readFileSync(path.join(dir,'public/current.json'))),publicCatalog=projectFcCatalog(catalog,snapshot),p=publicCatalog.products[card.key];
 assert.deepEqual(publicCatalog.weekly.ids,[card.key]);assert.equal(p.platforms.xbox.binding_state,'missing');assert.equal(p.platforms.pc.id,null);assert.equal(p.platforms.ps.price,null);assert.equal(p.platforms.ps.quantity,null);assert.equal(p.image,null);
 assert(snapshot.products.filter(p=>p.model_card_key===card.key).every(p=>p.available===false&&p.quantity===null));assert(!Object.hasOwn(snapshot.products.find(p=>p.key==='fc-'+card.key+'-xbox').product_ref,'goods_id'));
 const commerce=createCommerce({snapshot,dir:path.join(dir,'ops')});assert.throws(()=>commerce.intent({activity_id:'fc27-season2',page_id:'fc27-weekly',rule_version:'preview-2',benefit_binding_version:'unverified-2',currency:'USD',lines:[{line_key:'l',product_key:'fc-'+card.key+'-ps',quantity:{value:'1',unit:'item'},attributes:[]}]}),{code:'PRODUCT_UNAVAILABLE'});
});

test('server model facts cannot be forged, silently refreshed across pages, or duplicated with an accepted original card',t=>{
 const {store}=fixture(t),card=model();let saved=store.importModel(request(store,card),'fixture',card);
 const forged=structuredClone(saved.draft);forged.fc_models[card.key].title='Client changed';assert.throws(()=>store.save({revision:1,operation_id:randomUUID(),draft:forged},'fixture'),{code:'MODELS_SERVER_OWNED'});
 assert.throws(()=>store.save({revision:1,operation_id:randomUUID(),draft:saved.draft,model_refresh_digest:'0'.repeat(64)},'fixture'),{code:'MODEL_REFRESH_SERVER_OWNED'});
 const changed=model();changed.platforms.pc.state='offline';assert.throws(()=>store.importModel(request(store,changed),'fixture',changed),{code:'MODEL_BINDING_CHANGED'});
 const mixedSeries=structuredClone(saved.draft);mixedSeries.fc_layout.trio[0]=card.key;assert.equal(validateLayout(mixedSeries.fc_layout,effectiveFcCatalog(catalog,mixedSeries.fc_models)).trio[0],card.key);
 const original=model();original.model_id='43167385';original.key='model-266-1327-'+original.model_id;
 for(const [code,offer] of Object.entries(catalog.products['170014917'].platforms))original.platforms[code]={state:'verified',product_ref:{site_id:'266',game_id:'1327',model_id:original.model_id,goods_id:String(offer.id)},observed_quantity:null};
 const duplicate=request(store,original);duplicate.draft.fc_layout.weekly=['170014917',original.key];assert.throws(()=>store.importModel(duplicate,'fixture',original),{code:'DUPLICATE_PAGE_PRODUCT'});
 const restored=store.restoreDraft({revision:1,operation_id:randomUUID(),restore_revision:0},'fixture');assert.equal(Object.hasOwn(restored.draft,'fc_models'),false);assert.deepEqual(restored.draft,initialCenterDraft());
});

test('legacy explicit single-platform masks remain unchanged through model storage and a partial card projection',t=>{
 const {store}=fixture(t),card=model(),body=request(store,card);body.draft.pages[0].product_keys=['fc-'+card.key+'-ps'];
 const saved=store.importModel(body,'fixture',card),seed=centerSeed(previewCatalog(effectiveFcCatalog(catalog,saved.draft.fc_models),saved.draft.fc_layout),{products:[]});
 const binding=effectivePageBindings(saved.draft,seed,'fc27-weekly');assert.equal(binding.source,'explicit');assert.equal(binding.model_cards[0].partial,true);assert.deepEqual(binding.model_cards[0].selected_platforms,['ps']);
 assert.deepEqual(saved.draft.pages[0].product_keys,body.draft.pages[0].product_keys);assert.equal(Object.hasOwn(saved.draft.pages[1],'product_keys'),false);
});

test('public model labels and observed units follow the English policy without altering stored resolver facts',t=>{
 const {store,options}=fixture(t),card=model();card.title='合成测试模型';card.version_label='未验证版本';card.platforms.ps.observed_quantity.unit='张';
 store.importModel(request(store,card),'fixture',card);store.publish({revision:1,operation_id:randomUUID()},'fixture');
 const snapshot=JSON.parse(fs.readFileSync(path.join(options.publicDir,'current.json')));assert.equal(store.read().draft.fc_models[card.key].title,card.title);
 assert.equal(snapshot.fc_models[card.key].title,'Model '+card.model_id);assert.equal(snapshot.fc_models[card.key].version_label,null);assert.equal(snapshot.fc_models[card.key].platforms.ps.observed_quantity.unit,null);
 assert.equal(snapshot.products.find(p=>p.model_card_key===card.key).observed_quantity.unit,null);assert.doesNotThrow(()=>projectRelease(snapshot));
});

test('image format/structure/size boundaries reject SVG, mismatches, truncation, invalid CRC and excessive dimensions',()=>{
 assert.deepEqual([inspectImage(png,'image/png').width,inspectImage(png,'image/png').height],[1,1]);
 assert.deepEqual([inspectImage(jpeg,'image/jpeg').width,inspectImage(jpeg,'image/jpeg').height],[1,1]);
 const webp=fs.readFileSync(new URL('assets/weekly-hero.webp',app));assert(inspectImage(webp,'image/webp').width>1);
 for(const [bytes,mime] of [[Buffer.from('<svg/>'),'image/svg+xml'],[png,'image/jpeg'],[png.subarray(0,40),'image/png'],[Buffer.alloc(mediaLimits.fileBytes+1),'image/png']])assert.throws(()=>inspectImage(bytes,mime));
 const corrupt=Buffer.from(png);corrupt[20]^=1;assert.throws(()=>inspectImage(corrupt,'image/png'));
 assert.throws(()=>inspectImage(pngFixture(mediaLimits.dimension+1,1),'image/png'),{code:'IMAGE_DIMENSIONS_INVALID'});
});

test('project assets are content-addressed/idempotent; public copies survive umask0077 and only current references are readable',t=>{
 const {store,options}=fixture(t),oldMask=process.umask(0o077);t.after(()=>process.umask(oldMask));
 const op=randomUUID(),uploaded=store.uploadAsset(op,png,'image/png','fixture');assert.deepEqual(store.uploadAsset(op,png,'image/png','fixture'),uploaded);
 const changed=Buffer.from(png);changed[12]^=1;assert.throws(()=>store.uploadAsset(op,changed,'image/png','fixture'));
 const id=uploaded.asset.asset_id;assert.equal(fs.existsSync(path.join(options.publicDir,'assets',id)),false);
 const draft=initialCenterDraft();draft.pages[0].media={hero_desktop:ref(uploaded.asset),hero_mobile:ref(uploaded.asset),share:ref(uploaded.asset),cards:{'170014917':ref(uploaded.asset)}};
 store.save({revision:0,operation_id:randomUUID(),draft},'fixture');store.publish({revision:1,operation_id:randomUUID()},'fixture');let snapshot=JSON.parse(fs.readFileSync(path.join(options.publicDir,'current.json')));
 assert.deepEqual(readPublishedMedia(options.publicDir,snapshot,id).bytes,png);
 if(process.platform!=='win32'){assert.equal(fs.statSync(path.join(options.publicDir,'assets')).mode&0o777,0o755);assert.equal(fs.statSync(path.join(options.publicDir,'assets',id)).mode&0o777,0o644);}
 const source=fs.readFileSync(new URL('Weekly-Scout.html',app),'utf8'),body=presentPage({name:'Weekly-Scout.html',body:source,snapshot,publicBase:'https://campaign.example/events/'}).body;
 assert(body.includes('https://campaign.example/events/media/'+id));assert.match(body,/data-published-media="true"/);
 const next=structuredClone(store.read().draft);delete next.pages[0].media;store.save({revision:2,operation_id:randomUUID(),draft:next},'fixture');store.publish({revision:3,operation_id:randomUUID()},'fixture');snapshot=JSON.parse(fs.readFileSync(path.join(options.publicDir,'current.json')));
 assert.throws(()=>readPublishedMedia(options.publicDir,snapshot,id),{code:'MEDIA_NOT_FOUND'});assert.equal(fs.existsSync(path.join(options.publicDir,'assets',id)),true);assert.deepEqual(store.readAsset(id).bytes,png);
});

test('media bindings require operator English confirmation, known local assets and bounded project storage',t=>{
 const {store,options,dir}=fixture(t),asset=store.uploadAsset(randomUUID(),png,'image/png','fixture').asset;
 for(const entry of [{...ref(asset),alt:'中文'}, {...ref(asset),public_english_confirmed:false},{...ref(asset),asset_id:'../secret.png'}]){const draft=initialCenterDraft();draft.pages[0].media={hero_desktop:entry};assert.throws(()=>store.save({revision:0,operation_id:randomUUID(),draft},'fixture'));}
 const media=makeMediaStore({dir:path.join(dir,'quota'),publicDir:options.publicDir,operationsDir:path.join(dir,'quota-ops')});
 fs.mkdirSync(path.join(dir,'quota/blobs'),{recursive:true});const fd=fs.openSync(path.join(dir,'quota/blobs','0'.repeat(64)+'.png'),'w');fs.ftruncateSync(fd,mediaLimits.totalBytes);fs.closeSync(fd);
 assert.throws(()=>media.stage(randomUUID(),png,'image/png','fixture'),{code:'MEDIA_STORAGE_LIMIT'});
});

test('original upload receipts fail closed on missing/corrupt blobs or metadata without deleting or repairing the receipt',t=>{
 const {dir,options}=fixture(t);
 const faults={missing_blob:({blob})=>fs.unlinkSync(blob),missing_metadata:({metadata})=>fs.unlinkSync(metadata),
  corrupt_blob:({blob})=>fs.writeFileSync(blob,Buffer.alloc(png.length)),
  wrong_mime:({metadata})=>{const value=JSON.parse(fs.readFileSync(metadata));value.mime='image/jpeg';fs.writeFileSync(metadata,JSON.stringify(value));},
  changed_metadata:({metadata})=>{const value=JSON.parse(fs.readFileSync(metadata));value.width++;fs.writeFileSync(metadata,JSON.stringify(value));}};
 for(const [name,fault] of Object.entries(faults)){
  const root=path.join(dir,name),operationsDir=path.join(root,'operations'),media=makeMediaStore({dir:path.join(root,'media'),publicDir:options.publicDir,operationsDir}),id=randomUUID(),result=media.stage(id,png,'image/png','fixture');
  const receipt=path.join(operationsDir,id+'.json'),before=fs.readFileSync(receipt),blob=path.join(root,'media/blobs',result.asset.asset_id),metadata=path.join(root,'media/metadata',result.asset.asset_id);
  fault({blob,metadata});assert.throws(()=>media.stage(id,png,'image/png','fixture'),{code:'MEDIA_UNCONFIRMED'});assert.deepEqual(fs.readFileSync(receipt),before);
  if(name==='missing_blob')assert.equal(fs.existsSync(blob),false);if(name==='missing_metadata')assert.equal(fs.existsSync(metadata),false);
 }
});

test('interrupted media durability sync writes no success receipt and original-ID retry syncs directory parents before receipt',t=>{
 const {dir,options}=fixture(t),root=path.join(dir,'first/second/media'),operationsDir=path.join(dir,'first/second/operations'),media=makeMediaStore({dir:root,publicDir:options.publicDir,operationsDir}),id=randomUUID(),receipt=path.join(operationsDir,id+'.json');
 const open=fs.openSync,sync=fs.fsyncSync,opened=new Map(),events=[];let injected=false;
 t.mock.method(fs,'openSync',function(file,...args){const fd=open.call(fs,file,...args);opened.set(fd,path.resolve(String(file)));events.push({kind:'open',file:path.resolve(String(file))});return fd;});
 t.mock.method(fs,'fsyncSync',function(fd){const file=opened.get(fd),directory=fs.fstatSync(fd).isDirectory();
  if(!injected&&(process.platform==='win32'?!directory:directory&&file===path.dirname(root))){injected=true;throw Object.assign(Error('synthetic interrupted durability sync'),{code:'EIO'});}
  events.push({kind:'sync',file,directory});return sync.call(fs,fd);
 });
 assert.throws(()=>media.stage(id,png,'image/png','fixture'),{code:'EIO'});assert.equal(injected,true);assert.equal(fs.existsSync(receipt),false);
 events.length=0;const result=media.stage(id,png,'image/png','fixture');assert.equal(fs.existsSync(receipt),true);assert.deepEqual(media.stage(id,png,'image/png','fixture'),result);
 if(process.platform!=='win32'){
  const write=events.findIndex(event=>event.kind==='open'&&event.file.startsWith(receipt+'.'));assert(write>=0);
  for(const parent of [path.dirname(root),path.dirname(path.dirname(root)),root,path.join(root,'blobs'),path.join(root,'metadata')])assert(events.slice(0,write).some(event=>event.kind==='sync'&&event.directory&&event.file===parent),'missing prior parent sync: '+parent);
 }
 t.mock.restoreAll();
});

test('authenticated HTTP upload and original model receipt recovery feed current-only public media/config',async t=>{
 const {dir,options}=fixture(t),data=path.join(dir,'http-data'),published=path.join(dir,'http-public'),originalFetch=globalThis.fetch;
 const names=['CAMPAIGN_DATA','CAMPAIGN_ORIGIN','CAMPAIGN_PUBLIC_RELEASE_DIR','CAMPAIGN_PYTHON'],previous=Object.fromEntries(names.map(key=>[key,process.env[key]]));
 Object.assign(process.env,{CAMPAIGN_DATA:data,CAMPAIGN_ORIGIN:'http://127.0.0.1',CAMPAIGN_PUBLIC_RELEASE_DIR:published,CAMPAIGN_PYTHON:path.join(dir,'no-upstream-python')});
 globalThis.fetch=async(url,init)=>String(url).includes(':8895/verify')?new Response('',{status:init.headers.Cookie==='fixture-admin'?200:401,headers:init.headers.Cookie==='fixture-admin'?{'x-auth-user':'fixture','x-auth-role':'admin'}:{}}):originalFetch(url,init);
 let management,publicServer;
 try{
  ({server:management}=await import('../production-server.mjs'));await new Promise(resolve=>management.listen(0,'127.0.0.1',resolve));
  const root='http://127.0.0.1:'+management.address().port+'/dashboard/analytics/campaigns/analytics/',get=route=>originalFetch(root+route,{headers:{Cookie:'fixture-admin'}});
  const state=await(await get('api/center')).json();assert.equal(Object.hasOwn(state.draft,'fc_layout'),false);assert.equal(state.page_bindings['fc27-weekly'].source,'inherited');
  const headers={Cookie:'fixture-admin',Origin:'http://127.0.0.1','X-CSRF-Token':state.csrf};
  const upload=(extra={})=>originalFetch(root+'api/center/assets/upload?operation_id='+randomUUID(),{method:'POST',headers:{...headers,'Content-Type':'image/png',...extra},body:png});
  assert.equal((await upload({'X-CSRF-Token':'wrong'})).status,403);assert.equal((await upload({Origin:'https://untrusted.invalid'})).status,403);assert.equal((await upload({'Content-Type':'image/svg+xml'})).status,415);
  const uploaded=await(await upload()).json(),id=uploaded.asset.asset_id;assert.deepEqual(Buffer.from(await(await get(uploaded.preview_url)).arrayBuffer()),png);
  assert.equal((await originalFetch(root+uploaded.preview_url)).status,401);
  const local=makeCenterStore({...options,dir:path.join(data,'center'),publicDir:published}),body=request(local),saved=local.importModel(body,'fixture',model());
  const post=(route,payload)=>originalFetch(root+route,{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(payload)});
  // The configured upstream executable cannot run: this must recover the stored
  // receipt first, without resolving facts again after a lost original response.
  const recovered=await post('api/center/import-model',body);assert.equal(recovered.status,200);assert.equal((await recovered.json()).revision,saved.revision);
  const changed=structuredClone(saved.draft);changed.pages[0].media={hero_desktop:ref(uploaded.asset),share:ref(uploaded.asset)};
  assert.equal((await post('api/center',{revision:1,operation_id:randomUUID(),draft:changed})).status,200);assert.equal((await post('api/center/publish',{revision:2,operation_id:randomUUID()})).status,200);
  const assetRoot=path.join(dir,'static');fs.mkdirSync(assetRoot);const source='window.FC_ACTIVITY_CONFIG='+JSON.stringify(catalog)+';';fs.writeFileSync(path.join(assetRoot,'catalog.js'),source);
  publicServer=createPublicServer({assetRoot,staticManifest:{'catalog.js':digest(source)},snapshotProvider:()=>JSON.parse(fs.readFileSync(path.join(published,'current.json'))),publishedDir:published,dir:path.join(dir,'runtime'),origin:'http://127.0.0.1'});
  await new Promise(resolve=>publicServer.listen(0,'127.0.0.1',resolve));const publicRoot='http://127.0.0.1:'+publicServer.address().port+'/events/';
  const config=await(await originalFetch(publicRoot+'api/campaign/config')).json();assert.equal(config.page_media['fc27-weekly'].hero_desktop.url,'/events/media/'+id);assert.equal(config.live_checkout,false);
  const image=await originalFetch(publicRoot+'media/'+id);assert.equal(image.headers.get('content-type'),'image/png');assert.equal(image.headers.get('x-content-type-options'),'nosniff');assert.deepEqual(Buffer.from(await image.arrayBuffer()),png);
  assert.equal((await originalFetch(publicRoot+'media/'+id.replace(/.$/,'x'))).status,404);
  const publicCatalog=await(await originalFetch(publicRoot+'catalog.js')).text();assert(publicCatalog.includes('"page_media"'));assert(publicCatalog.includes('"binding_state":"missing"'));
  const clean=structuredClone(local.read().draft);delete clean.pages[0].media;local.save({revision:3,operation_id:randomUUID(),draft:clean},'fixture');local.publish({revision:4,operation_id:randomUUID()},'fixture');
  assert.equal((await originalFetch(publicRoot+'media/'+id)).status,404);assert.equal((await get(uploaded.preview_url)).status,200);
 }finally{
  if(publicServer)await new Promise(resolve=>publicServer.close(resolve));if(management)await new Promise(resolve=>management.close(resolve));globalThis.fetch=originalFetch;
  for(const name of names)if(previous[name]===undefined)delete process.env[name];else process.env[name]=previous[name];
 }
});
