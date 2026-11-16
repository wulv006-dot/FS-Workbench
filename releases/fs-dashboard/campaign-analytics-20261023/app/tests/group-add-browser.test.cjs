const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
// Trio and SBC are bought as one set: the cards have no add button of their own, the SBC
// companion pickers sit inside their cards, and one button adds the whole set to the lineup.
function fixture(view){
  const app=path.resolve(__dirname,'..'),config=structuredClone(require('../catalog.json')),keys=['201','202','203','204'].map(id=>'model-266-1327-'+id),core=keys[0],players=keys.slice(1),products=[],contracts={},bindings=[];
  for(let i=0;i<keys.length;i++){const id=String(201+i),goods=String(601+i),ref={site_id:'266',game_id:'1327',model_id:id,goods_id:goods},native='admin-'+goods,quantity={min:'1',max:'1',step:'1',unit:'item',group:'1'};
    config.products[keys[i]]={key:keys[i],title:'Fixture '+id,kind:i?'player':'sbc',preview_only:true,model_id:id,platforms:{ps:{id:goods,aid:'21587',binding_state:'verified',product_ref:ref}}};
    products.push({key:'fc-'+keys[i]+'-ps',preview_only:true,product_ref:ref,platform:{code:'ps',attribute_id:'21587'},available:false},{key:native,product_ref:ref,platform:{code:'ps',attribute_id:'21587'},quantity,attributes:[],available:true});
    contracts[id]={verified:true,model_ref:{site_id:'266',game_id:'1327',model_id:id},combinations:[{product_key:native,quantity,attributes:[],price:{source:'admin_current',base_minor:1000,currency:'USD',minor_unit_scale:2,quantity_value:'1',expires_at:'2099-01-01T00:00:00Z'}}]};
    bindings.push({activity_id:'fc27-season2',page_id:'fc27-'+view,product_key:native,quantity:{value:'1',unit:'item'},attributes:[],off_percent:10,code:'FIXTURE',native:{category:'new_items',id:goods,group:'1',num:'1',aid:'21587',attr:''}});}
  config.weekly.ids=players.slice(0,2);config.weekly.bundleIds=[];config.trio.ids=players;config.bundles.ids=[];
  config.sbc={...config.sbc,ids:[core],defaultId:core,bundleIds:[],routes:{[core]:{picks:players.slice(0,2),alternatives:[players[2]],label:{en:'Companion ideas'}}}};
  const snapshot={schema_version:1,release_id:'fixture',config_hash:'a'.repeat(64),pages:[{page_id:'fc27-'+view,activity_id:'fc27-season2',active:true,product_keys:products.map(p=>p.key)}],products,seasonal_model_contracts:contracts,native_checkout:{status:'configured',verification_ref:'fixture',valid_from:'2020-01-01T00:00:00Z',valid_until:'2099-01-01T00:00:00Z',origin:'https://www.mmoexp.com',cart_path:'/Cart.html',consumer_behavior_confirmed:true,bindings}};
  return {app,config,snapshot,players};
}
async function open(browser,view){
  const f=fixture(view),page=await browser.newPage();page.setDefaultTimeout(5000);let writes=0;
  await page.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());if(req.method()==='POST'){writes++;return route.abort();}
    if(url.pathname.endsWith('/api/campaign/config'))return route.fulfill({json:f.snapshot});
    if(url.pathname.endsWith('/api/campaign/capabilities'))return route.fulfill({json:{integration_mode:'preview',live_checkout:false}});
    const name=url.pathname.replace(/^\/events\//,''),file=path.join(f.app,name);if(!fs.existsSync(file))return route.fulfill({status:404,body:''});
    return route.fulfill({contentType:({'.js':'application/javascript','.html':'text/html','.css':'text/css'})[path.extname(file)]||'application/octet-stream',body:name==='catalog.js'?'window.FC_ACTIVITY_CONFIG='+JSON.stringify(f.config)+';':fs.readFileSync(file)});});
  await page.goto('https://www.mmoexp.com/events/'+(view==='sbc'?'Sbc-Companions.html':'Player-Trio.html'));
  await page.waitForFunction(()=>document.querySelector('[data-toggle-group]'));
  return {page,players:f.players,writes:()=>writes};
}
test('trio: no per-player add button; one button adds and removes all three together',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const {page,writes}=await open(browser,'trio'),count=()=>page.locator('#summary-count').innerText();
    assert.equal(await page.locator('[data-toggle-product]').count(),0);assert.equal(await page.locator('#product-grid .fca-card').count(),3);
    assert.equal(await count(),'0');assert(await page.locator('#review-selection').isDisabled());
    await page.locator('#product-grid [data-toggle-group]').click();
    assert.equal(await count(),'3');assert.equal(await page.locator('#product-grid [data-toggle-group]').getAttribute('aria-pressed'),'true');
    await page.locator('#review-selection').click();await page.waitForFunction(()=>document.querySelector('#review-dialog').open);
    assert.equal(await page.locator('#review-items .fca-row').count(),3,'review lists all three players');
    await page.locator('[data-close-dialog]').click();
    await page.locator('#product-grid [data-toggle-group]').click();assert.equal(await count(),'0');
    assert.equal(writes(),0,'nothing is sent before the review is confirmed');
  }finally{await browser.close();}
});
test('sbc: companion pickers live inside the cards; one button adds both, plus the service when included',async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const {page,players}=await open(browser,'sbc'),count=()=>page.locator('#summary-count').innerText();
    assert.equal(await page.locator('[data-toggle-product]').count(),0);
    assert.equal(await page.locator('#sbc-lineup .fca-card #companion-0').count(),1,'companion 1 picker is inside its card');
    assert.equal(await page.locator('#sbc-lineup .fca-card #companion-1').count(),1,'companion 2 picker is inside its card');
    assert.equal(await page.locator('#sbc-options select').count(),0);
    assert.equal(await count(),'0');
    await page.locator('input[name=core-mode][value=service]').check();
    assert.equal(await count(),'0','the SBC service is never added on its own');
    await page.locator('#sbc-lineup [data-toggle-group]').click();assert.equal(await count(),'3','service and both companions go in together');
    await page.locator('#sbc-lineup [data-toggle-group]').click();assert.equal(await count(),'0');
    await page.locator('input[name=core-mode][value=owned]').check();
    await page.locator('#sbc-lineup [data-toggle-group]').click();assert.equal(await count(),'2','owned core: only the two companions');
    await page.locator('#companion-0').selectOption(players[2]);
    assert.equal(await count(),'2','changing a companion keeps the set selected');
    assert(await page.locator('#companion-1 option[value="'+players[2]+'"]').isDisabled(),'the same player cannot fill both slots');
    await page.locator('input[name=core-mode][value=service]').check();assert.equal(await count(),'3','including the service while a set is selected adds it');
  }finally{await browser.close();}
});
