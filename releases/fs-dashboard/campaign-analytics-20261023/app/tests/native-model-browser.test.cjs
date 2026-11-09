const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
test('dynamic model cards use exact platform quotes and original native checkout without enabling references',async()=>{
 const app=path.resolve(__dirname,'..'),config=JSON.parse(fs.readFileSync(path.join(app,'catalog.json'))),key='model-266-1327-99',quantity={min:'1',max:'1',step:'1',unit:'item',group:'1'};
 const refs=['ps','xbox','pc'].map((code,i)=>({code,aid:['21587','21585','21589'][i],ref:{site_id:'266',game_id:'1327',model_id:'99',goods_id:String(101+i)}}));
 config.products[key]={key,title:'Current fixture player/88/CM/Gold',kind:'player',preview_only:true,model_id:'99',platforms:Object.fromEntries(refs.map(({code,aid,ref})=>[code,{id:ref.goods_id,aid,binding_state:'verified',product_ref:ref}]))};config.weekly.ids=[key];
 const products=refs.flatMap(({code,aid,ref})=>[{key:'fc-'+key+'-'+code,preview_only:true,product_ref:ref,platform:{code,attribute_id:aid},available:false},{key:'admin-'+ref.goods_id,product_ref:ref,platform:{code,attribute_id:aid},quantity,attributes:[],available:false}]);
 const snapshot={schema_version:1,release_id:'fixture-release',config_hash:'a'.repeat(64),pages:[{page_id:'fc27-weekly',activity_id:'fc27-season2',active:true,product_keys:products.map(p=>p.key)}],products,seasonal_model_contracts:{99:{verified:true,model_ref:{site_id:'266',game_id:'1327',model_id:'99'},combinations:refs.map(({ref},i)=>({product_key:'admin-'+ref.goods_id,quantity,attributes:[],price:{source:'admin_current',base_minor:1000+500*i,currency:'USD',minor_unit_scale:2,quantity_value:'1',expires_at:'2099-01-01T00:00:00Z'}}))}},native_checkout:{status:'configured',verification_ref:'fixture',valid_from:'2020-01-01T00:00:00Z',valid_until:'2099-01-01T00:00:00Z',origin:'https://www.mmoexp.com',cart_path:'/Cart.html',consumer_behavior_confirmed:true,bindings:refs.slice(0,2).map(({ref,aid})=>({activity_id:'fc27-season2',page_id:'fc27-weekly',product_key:'admin-'+ref.goods_id,quantity:{value:'1',unit:'item'},attributes:[],off_percent:10,code:'FIXTURE-CODE',native:{category:'new_items',id:ref.goods_id,group:'1',num:'1',aid,attr:''}}))}};
 require('../native-code-handoff.js').publishedPlan(snapshot,{activity_id:'fc27-season2',page_id:'fc27-weekly',off_percent:10,lines:[{product_key:'admin-102',quantity:{value:'1',unit:'item'},attributes:[]}]},{origin:'https://www.mmoexp.com'});
 const browser=await chromium.launch({headless:true}),page=await browser.newPage(),posts=[],errors=[];page.setDefaultTimeout(5000);page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());assert.equal(u.origin,'https://www.mmoexp.com');
  if(u.pathname.endsWith('/api/campaign/config'))return route.fulfill({json:snapshot});
  if(u.pathname.endsWith('/api/campaign/capabilities'))return route.fulfill({json:{integration_mode:'preview',live_checkout:false}});
  if(u.pathname==='/Cart/add.html'){posts.push(Object.fromEntries(new URLSearchParams(req.postData())));return route.fulfill({json:{code:1}});}
  if(u.pathname==='/Cart.html')return route.fulfill({contentType:'text/html',body:'<!doctype html><p>Isolated cart fixture</p>'});
  if(req.method()==='POST')return route.abort();
  const name=u.pathname.replace(/^\/events\//,''),file=path.join(app,name);if(!file.startsWith(app)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({contentType:({'.html':'text/html','.js':'application/javascript','.css':'text/css'})[path.extname(file)]||'application/octet-stream',body:name==='catalog.js'?'window.FC_ACTIVITY_CONFIG='+JSON.stringify(config)+';':fs.readFileSync(file)});
 });
 try{
  await page.goto('https://www.mmoexp.com/events/Weekly-Scout.html');await page.waitForFunction(()=>document.querySelector('#product-grid .fca-price')?.textContent==='$9.00');
  assert.equal(await page.locator('#product-grid [data-toggle-product]').isEnabled(),true);
  await page.locator('input[name=platform][value=pc]').check();assert.equal(await page.locator('#product-grid .fca-price').innerText(),'$20.00');assert(await page.locator('#product-grid .fca-action').isDisabled());
  await page.locator('#review-selection').click();assert(await page.locator('#submit-selection').isDisabled());await page.locator('[data-close-dialog]').click();
  await page.locator('input[name=platform][value=xbox]').check();assert.equal(await page.locator('#product-grid .fca-price').innerText(),'$13.50');
  await page.locator('#review-selection').click();await page.waitForFunction(()=>!document.querySelector('#submit-selection').disabled);assert.equal(await page.locator('#submit-selection').isEnabled(),true);
  // A new price invalidates the prior review without any cart side effect.
  snapshot.seasonal_model_contracts[99].combinations[1].price.base_minor=1600;
  await page.locator('#submit-selection').click();await page.waitForFunction(()=>document.querySelector('#review-status').textContent.includes('quote or item mapping changed'));assert.equal(posts.length,0);
  await page.locator('[data-close-dialog]').click();await page.locator('#review-selection').click();await page.locator('#submit-selection').click();await page.waitForURL('**/Cart.html');
  assert.deepEqual(posts,[{category:'new_items',id:'102',group:'1',num:'1',attr:'',aid:'21585'}]);assert.equal(await page.evaluate(()=>sessionStorage.getItem('pending_discount_code')),'FIXTURE-CODE');assert.deepEqual(errors,[]);
 }catch(error){console.error(errors,await page.locator('#activity-message').textContent(),await page.locator('#product-grid').textContent());throw error;}finally{await browser.close();}
});
