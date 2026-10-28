const SERIES=require('../catalog.json').trio.series;
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{createHash}=require('node:crypto'),{deflateSync}=require('node:zlib');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'products-page-flow-')),app=path.resolve(__dirname,'..'),real=global.fetch;
 const model={key:'model-266-1327-990001',site_id:'266',game_id:'1327',model_id:'990001',kind:'player',title:'Haaland / 91 / Team of the Week',version_label:'Team of the Week',image_url:null,image_provenance:null,platforms:Object.fromEntries(['ps','xbox','pc'].map((code,i)=>[code,{state:'verified',product_ref:{site_id:'266',game_id:'1327',model_id:'990001',goods_id:String(950001+i)},observed_quantity:null}])),verification_scope:'catalog_identity_only',site_association:'observed',available:false,authoritative:false,checkout_enabled:false};
 const bridge=path.join(dir,'model-fixture.py');fs.writeFileSync(bridge,`import sys,json
r=json.load(sys.stdin)
if r['action']=='benefits_read':
 print(json.dumps({'status':'ok','data':{'coupons':[{'kind':'coupon','native_id':'990077','title':'Fixture existing benefit','raw_status':'unknown'}],'discounts':[]}}));sys.exit(0)
if r['action'] in ['product_read','catalog_search']:
 p={'product_ref':{'site_id':'266','game_id':r['game_id'],'model_id':'88001','goods_id':'88002'},'title':'Fixture seasonal model','platform_attribute_id':'21587','minimum_quantity':'1','unit':'item','authoritative':False,'checkout_enabled':False}
 print(json.dumps({'status':'ok','data':{'product':p} if r['action']=='product_read' else {'items':[p],'total':1,'has_more':False,'page':1}}));sys.exit(0)
m=json.loads(${JSON.stringify(JSON.stringify(model))})
mid=r.get('model_id',m['model_id'])
m.update(model_id=mid,key='model-266-1327-'+mid,kind=r['kind'])
if mid!='990001':
 for i,code in enumerate(['ps','xbox','pc']): m['platforms'][code]['product_ref'].update(model_id=mid,goods_id=str(int(mid)*10+i))
if r['kind']=='sbc': m.update(title='Fixture SBC completion service',version_label=None)
if r['kind']=='bundle': m.update(title='Fixture original fixed bundle',version_label=None)
if mid=='990031': m.update(title='Fixture '+${JSON.stringify(SERIES)}+' player',version_label=${JSON.stringify(SERIES)})
if mid=='990032': m.update(title='Fixture Gold Rare player',version_label='Gold Rare')
if r['action']=='model_resolve': d={'model':m,'resolution_complete':True}
else:
 q=r.get('keyword','')
 if q=='未知中文': print(json.dumps({'status':'error','error':'MODEL_ALIAS_REQUIRED'}));sys.exit(0)
 d={'items':[m,{**m,'model_id':'990002','key':'model-266-1327-990002','title':'Haaland / 90 / Gold Rare','version_label':'Gold Rare'}],'total':2,'has_more':False,'name_query':{'input':q,'resolved':'Haaland' if q=='哈兰德' else q,'alias_applied':q=='哈兰德','source':'explicit_alias' if q=='哈兰德' else 'native_title'}}
print(json.dumps({'status':'ok','data':d}))
`);
 process.env.PYTHONIOENCODING='utf-8';process.env.PYTHONUTF8='1';process.env.CAMPAIGN_DATA=dir;process.env.CAMPAIGN_PUBLIC_RELEASE_DIR=path.join(dir,'public');process.env.CAMPAIGN_ORIGIN='http://127.0.0.1:8525';process.env.CAMPAIGN_PYTHON='python';process.env.CAMPAIGN_BACKEND_BRIDGE=bridge;
 global.fetch=async(url,options)=>String(url).includes(':8895/verify')?new Response('',{status:200,headers:{'x-auth-user':'fixture','x-auth-role':'admin'}}):real(url,options);
 const {initialCenterDraft}=await import('../analytics/center-store.mjs');const oldDraft=initialCenterDraft(),accepted=JSON.parse(fs.readFileSync(path.join(app,'catalog.json'))),roleKey=accepted.weekly.ids[1];const {emptyHalloween}=await import('../runtime/halloween-contract.mjs');oldDraft.halloween=emptyHalloween();oldDraft.halloween.games[0].random_source={mode:'category_snapshot',category_id:'9900',snapshot_complete:true};delete oldDraft.halloween.games[0].fixed_quantity;delete oldDraft.halloween.games[1].random_source;oldDraft.halloween.probabilities=[{off_percent:10,weight:4000},{off_percent:8,weight:3000},{off_percent:15,weight:3000}];oldDraft.pages[0].product_roles={['fc-'+roleKey+'-ps']:'preview'};fs.mkdirSync(path.join(dir,'center'));fs.writeFileSync(path.join(dir,'center/state.json'),JSON.stringify({revision:0,draft:oldDraft,published:null}));
 const {server}=await import('../analytics/production-server.mjs');await new Promise(r=>server.listen(8525,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true}),page=await browser.newPage(),base='http://127.0.0.1:8525/dashboard/analytics/campaigns/analytics/',errors=[],uploads=[];page.setDefaultTimeout(7000);page.on('pageerror',e=>errors.push(e.message));const stateFile=path.join(dir,'center/state.json'),read=()=>JSON.parse(fs.readFileSync(stateFile));let dropUpload=false,dropModel=false;const publishIds=[];
 await page.route('**/api/center/assets/upload?*',async route=>{uploads.push(new URL(route.request().url()).searchParams.get('operation_id'));if(dropUpload){dropUpload=false;await route.fetch();return route.abort();}return route.continue();});
 await page.route('**/api/center',async route=>{if(route.request().method()==='POST'&&dropModel){dropModel=false;await route.fetch();return route.abort();}return route.continue();});
 let publicServer;
 const wait=t=>page.waitForFunction(t=>document.querySelector('#center-status').textContent.includes(t),t);
 function png(){const chunk=(name,data)=>{const body=Buffer.concat([Buffer.from(name),data]),out=Buffer.alloc(body.length+8);out.writeUInt32BE(data.length);body.copy(out,4);let crc=0xffffffff;for(const b of body){crc^=b;for(let bit=0;bit<8;bit++)crc=crc&1?0xedb88320^(crc>>>1):crc>>>1;}out.writeUInt32BE((crc^0xffffffff)>>>0,out.length-4);return out;};const h=Buffer.alloc(13);h.writeUInt32BE(1);h.writeUInt32BE(1,4);h[8]=8;h[9]=6;return Buffer.concat([Buffer.from('89504e470d0a1a0a','hex'),chunk('IHDR',h),chunk('IDAT',deflateSync(Buffer.from([0,255,0,0,255]))),chunk('IEND',Buffer.alloc(0))]);}
 try{
  await page.route('**/api/center/publish',async route=>{publishIds.push(JSON.parse(route.request().postData()).operation_id);if(dropModel){dropModel=false;await route.fetch();return route.abort();}return route.continue();});
  await page.goto(base+'products.html');await wait('已读取');const original=structuredClone(read());await page.locator('#page-select').selectOption('seasonal-vault');await page.locator('#title-3').fill('Temporary local title');await page.locator('#page-select').selectOption('fc27-weekly');await page.locator('#page-select').selectOption('seasonal-vault');await page.locator('#title-3').fill(original.draft.pages[3].title);await page.locator('#page-select').selectOption('fc27-weekly');assert.deepEqual(read(),original,'switching or editing title never normalizes historical Halloween fields');
  await page.locator('[data-layout-remove="weekly:'+initialKey()+'"]').click();
  // Visible hero copy: the operator edits heading/intro/body for FC pages, blank keeps the built-in default.
  const beforeCopy=structuredClone(read().draft.pages[0]),captureCopy=async()=>{
    let captured=null;const handler=async route=>{captured=JSON.parse(route.request().postData()).draft;await route.continue();};
    await page.route('**/api/center/preview',handler);
    await page.locator('#preview-draft').click();
    for(let i=0;i<60&&!captured;i++)await page.waitForTimeout(100);
    await page.unroute('**/api/center/preview',handler);
    assert(captured,'preview posted the draft');
    return captured.pages[0];
  };
  await page.locator('#copy-heading-0').fill('Admin edited shortlist');
  await page.locator('#copy-intro-0').fill('Operator intro line.');
  const filled=await captureCopy();
  assert.equal(filled.copy.heading,'Admin edited shortlist','English copy is submitted with the draft');
  assert.equal(filled.copy.intro,'Operator intro line.');
  await page.locator('#copy-heading-0').fill('');await page.locator('#copy-intro-0').fill('');
  assert.equal('copy' in (await captureCopy()),false,'blank copy is removed instead of stored as an empty string');
  await page.locator('#model-query').fill('990001');await page.locator('#search-model').click();await page.waitForSelector('#choose-model');await page.locator('#choose-model').click();
  assert.deepEqual(read(),original,'choosing a model must not save any server draft');
  assert.match(await page.locator('[data-model-card="'+model.key+'"]').innerText(),/950001/);
  await page.locator('#title-0').fill('Whole page fixture');
  await page.locator('#read-benefits').click();await page.waitForFunction(()=>document.querySelector('#backend-state').textContent.includes('1'));
  await page.locator('#benefit-0').selectOption('0');await page.locator('[data-add="0"]').click();
  await page.locator('#media-file').setInputFiles({name:'whole.png',mimeType:'image/png',buffer:png()});await page.locator('#upload-media').click();await page.waitForFunction(()=>!document.querySelector('#media-candidate').hidden);
  await page.locator('#media-alt').fill('Whole page football artwork');
  await page.locator('#preview-draft').click();assert.match(await page.locator('#center-error').innerText(),/确认没有中文/);assert.deepEqual(read(),original);
  await page.locator('#media-confirm').check();await page.locator('#preview-draft').click();
  await page.waitForFunction(()=>!document.querySelector('#draft-preview').hidden).catch(async error=>{throw Error(error.message+' '+await page.locator('#preview-status').innerText()+' '+await page.locator('#center-error').innerText());});
  const frame=page.frameLocator('#draft-preview-frame');await frame.locator('[data-preview-model="'+model.key+'"]').waitFor();
  assert.equal(await frame.locator('title').innerText(),'Whole page fixture');
  await frame.locator('#hero-image').evaluate(img=>new Promise((resolve,reject)=>{if(img.complete&&img.naturalWidth>0)return resolve();img.addEventListener('load',resolve,{once:true});img.addEventListener('error',reject,{once:true});}));
  assert.match(await frame.locator('#hero-image').getAttribute('src'),/media/);assert.match(await frame.locator('[data-preview-model] .fca-platform-reference').innerText(),/950001/);
  await frame.locator('[data-preview-model] [data-preview-platform=pc]').click();assert.match(await frame.locator('[data-preview-model] .fca-platform-reference').innerText(),/950003/);
  assert.deepEqual(read(),original,'whole page preview must not save or publish');
  // Invalid effective dates are rejected before any publish request.
  await page.locator('#start-0').fill('2026-10-29T12:00');await page.locator('#end-0').fill('2026-10-28T12:00');await page.locator('#publish-center').click();assert.equal(publishIds.length,0);assert.deepEqual(read(),original);
  await page.locator('#start-0').fill('');await page.locator('#end-0').fill('');
  dropModel=true;await page.locator('#publish-center').click();await page.waitForFunction(()=>document.querySelector('#center-error').textContent.includes('原操作'));
  const published=structuredClone(read());assert(published.published);assert.equal(published.draft.fc_layout.weekly[0],model.key);assert.equal(published.draft.pages[0].title,'Whole page fixture');assert.equal(published.draft.pages[0].media.hero_desktop.alt,'Whole page football artwork');assert.deepEqual(published.draft.pages[0].benefit_refs,[{kind:'coupon',native_id:'990077'}]);assert.deepEqual(published.draft.pages.slice(1),original.draft.pages.slice(1));
  await page.reload();await wait('原操作已确认');assert.deepEqual(read(),published);assert.equal(publishIds.length,2);assert.equal(publishIds[0],publishIds[1]);
  // A stale revision must not partially replace either saved draft or published release.
  await page.locator('#title-0').fill('Rejected stale page');const changed=read();changed.revision++;fs.writeFileSync(stateFile,JSON.stringify(changed));const beforeConflict=structuredClone(read());await page.locator('#publish-center').click();await page.waitForFunction(()=>document.querySelector('#center-error').textContent.length>0);assert.deepEqual(read(),beforeConflict);
  await page.locator('#page-select').selectOption('seasonal-vault');await page.locator('#discover-search').fill('Fixture');await page.locator('#discover-products').click();await page.waitForFunction(()=>!document.querySelector('#discover-product').disabled);await page.locator('#discover-product').selectOption('88002');await page.locator('#inspect-product').click();await page.waitForFunction(()=>!document.querySelector('#add-product').disabled);const beforeProduct=structuredClone(read());await page.locator('#add-product').click();assert.deepEqual(read(),beforeProduct,'generic product selection remains local');
  await page.locator('[data-h-weight="8"]').fill('1000');await page.locator('[data-h-weight="15"]').fill('2000');await page.locator('[data-h-weight="10"]').fill('7000');await page.locator('#h-binding').selectOption('independent');
  await page.locator('#save-center').click();await wait('草稿已保存');assert(read().draft.pages[3].product_keys.includes('admin-266-1327-88002-21587'));assert.equal(read().draft.imported_products[0].product_ref.goods_id,'88002');assert.deepEqual(read().draft.halloween.probabilities,[{off_percent:10,weight:7000},{off_percent:8,weight:1000},{off_percent:15,weight:2000}]);assert.deepEqual(read().draft.halloween.games,original.draft.halloween.games,'changing weights preserves source completeness and omitted game fields');assert.deepEqual(read().published,beforeProduct.published,'unified save never publishes');
  assert.deepEqual(errors,[]);console.log('PASS whole-page editor: local model/media/benefit edits, actual unsaved renderer preview, one atomic publish, date validation, lost-response original-ID recovery, CAS no partial publish');
  function initialKey(){return accepted.weekly.ids[0];}
 }finally{if(publicServer)await new Promise(r=>publicServer.close(r));await browser.close();await new Promise(r=>server.close(r));global.fetch=real;fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1)});