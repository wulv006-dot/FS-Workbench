const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
for(const [filename,view] of [['Weekly-Scout.html','weekly'],['Sbc-Companions.html','sbc'],['Player-Trio.html','trio']])test('FC '+view+' shares consent, exposure, confirmed cart and revocation without payment claims',async()=>{
 const app=path.resolve(__dirname,'..'),browser=await chromium.launch({headless:true}),page=await browser.newPage(),events=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());if(u.origin==='https://us.i.posthog.com'){assert.equal(req.headers().cookie,undefined);assert.equal(req.headers().referer,undefined);events.push(JSON.parse(req.postData()));return route.fulfill({json:{status:1}});}assert.equal(u.origin,'https://www.mmoexp.com');return route.fulfill({contentType:'text/html',body:'<!doctype html><style>.fca-card{width:280px}</style><main id="fc-activity"></main>'});});
 try{
 await page.goto('https://www.mmoexp.com/events/'+filename+'?analytics_test=1&analytics_run=44444444-4444-4444-8444-444444444444');
 const catalog=JSON.parse(fs.readFileSync(path.join(app,'catalog.json')));catalog.mode='preview';
 await page.evaluate(({c,view})=>{window.FC_ACTIVITY_CONFIG=c;window.FC_ANALYTICS_CONFIG={enabled:false,projectToken:'fixture',allowedHosts:['www.mmoexp.com'],registry:[{id:'fc27-'+view,view}]};},{c:catalog,view});
 await page.addScriptTag({content:fs.readFileSync(path.join(app,'activity-content.js'),'utf8')});
 await page.evaluate(()=>{const p={key:'model-266-1327-99999',model_id:'99999',preview_only:true,title:'New fixture player',name:'New fixture player',version:'Fixture series',platforms:{ps:{id:'88888',binding_state:'verified'}}};window.FC_ACTIVITY_CONFIG.products[p.key]=p;document.getElementById('fc-activity').innerHTML=window.FCActivityContent.create(window.FC_ACTIVITY_CONFIG).card(p);});
 assert.equal(await page.locator('[data-product="88888"]').count(),1);
 await page.addScriptTag({content:fs.readFileSync(path.join(app,'seasonal/activity-analytics.js'),'utf8')});
 const publication={schema_version:1,release_id:'campaign-preview-42',config_hash:'a'.repeat(64),pages:[{page_id:'fc27-'+view,activity_id:'fc27-season2',active:true}],products:[]};
 const publish=async value=>page.evaluate(p=>window.dispatchEvent(new CustomEvent('fcactivity:published',{detail:p})),value);
 await publish(publication);assert.equal(await page.evaluate(()=>!!FCActivityAnalytics.status().transmitting),false);assert.equal(events.length,0);
 await page.evaluate(()=>window.FC_ANALYTICS_CONFIG.enabled=true);await publish(publication);await page.evaluate(view=>document.getElementById('fc-activity').dispatchEvent(new CustomEvent('fcactivity:view',{detail:{view,platform:'ps',language:'en'}})),view);assert.equal(events.length,0,'No transmission before consent');
 await page.getByRole('button',{name:'Allow analytics',exact:true}).click();await page.waitForFunction(()=>FCActivityAnalytics.status().transmitting);await page.locator('[data-product]').scrollIntoViewIfNeeded();await page.waitForTimeout(100);assert(events.some(e=>e.event==='activity_product_view'&&e.properties.product_id==='88888'));
 await page.evaluate(()=>document.getElementById('fc-activity').dispatchEvent(new CustomEvent('fcactivity:selection',{detail:{ids:['88888'],action:'companion'}})));await page.waitForTimeout(50);assert(events.some(e=>e.event==='activity_selection'&&e.properties.product_ids.includes('88888')));assert(events.every(e=>e.properties.environment==='test'&&e.properties.page_id==='fc27-'+view&&e.properties.release_id==='campaign-preview-42'));assert(!events.some(e=>/purchase|begin_checkout/.test(e.event)));
 await page.evaluate(()=>document.getElementById('fc-activity').dispatchEvent(new CustomEvent('fcactivity:cart-result',{detail:{outcomes:[{id:'88888',state:'confirmed'},{id:'99999',state:'unknown'}],complete:false}})));await page.waitForTimeout(50);
 const cart=events.filter(e=>e.event==='activity_add_to_cart').at(-1);assert.deepEqual(cart.properties.product_ids,['88888']);assert.equal(cart.properties.complete,false);assert(!events.some(e=>/purchase|begin_checkout/.test(e.event)));
 assert.equal(new Set(events.map(e=>e.uuid)).size,events.length);
 const visits=events.filter(e=>e.event==='activity_view').length;
 await page.evaluate(()=>{FCActivityAnalytics.setConsent(true);window.dispatchEvent(new StorageEvent('storage',{key:'mmoexp-event-analytics-consent-v1',newValue:'granted'}));});await page.waitForTimeout(50);
 assert.equal(events.filter(e=>e.event==='activity_view').length,visits,'Repeated same consent must not manufacture new visits');
 await page.getByRole('button',{name:'Analytics preferences',exact:true}).click();await page.getByRole('button',{name:'No thanks',exact:true}).click();const count=events.length;await page.evaluate(()=>document.getElementById('fc-activity').dispatchEvent(new CustomEvent('fcactivity:selection',{detail:{ids:['88888']}})));await page.waitForTimeout(50);assert.equal(events.length,count);
 await publish({...publication,pages:[{...publication.pages[0],active:false}]});assert.equal(await page.evaluate(()=>!!FCActivityAnalytics.status().enabled),false);assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
