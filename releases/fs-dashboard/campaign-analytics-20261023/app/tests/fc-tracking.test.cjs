const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
test('FC reuses published seasonal transport: new-model exposure, consent, revocation and disabled configuration',async()=>{
 const app=path.resolve(__dirname,'..'),browser=await chromium.launch({headless:true}),page=await browser.newPage(),events=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{const req=route.request(),u=new URL(req.url());if(u.origin==='https://us.i.posthog.com'){assert.equal(req.headers().cookie,undefined);assert.equal(req.headers().referer,undefined);events.push(JSON.parse(req.postData()));return route.fulfill({json:{status:1}});}assert.equal(u.origin,'https://www.mmoexp.com');return route.fulfill({contentType:'text/html',body:'<!doctype html><style>.fca-card{width:280px}</style><main id="fc-activity"></main>'});});
 try{
 await page.goto('https://www.mmoexp.com/events/Weekly-Scout.html?analytics_test=1&analytics_run=44444444-4444-4444-8444-444444444444');
 const catalog=JSON.parse(fs.readFileSync(path.join(app,'catalog.json')));catalog.mode='preview';
 await page.evaluate(c=>{window.FC_ACTIVITY_CONFIG=c;window.FC_ANALYTICS_CONFIG={enabled:false,projectToken:'fixture',allowedHosts:['www.mmoexp.com'],registry:[{id:'fc27-weekly',view:'weekly'}]};},catalog);
 await page.addScriptTag({content:fs.readFileSync(path.join(app,'activity-content.js'),'utf8')});
 await page.evaluate(()=>{const p={key:'model-266-1327-99999',model_id:'99999',preview_only:true,title:'New fixture player',name:'New fixture player',version:'Fixture series',platforms:{ps:{id:'88888',binding_state:'verified'}}};window.FC_ACTIVITY_CONFIG.products[p.key]=p;document.getElementById('fc-activity').innerHTML=window.FCActivityContent.create(window.FC_ACTIVITY_CONFIG).card(p);});
 assert.equal(await page.locator('[data-product="88888"]').count(),1);
 await page.addScriptTag({content:fs.readFileSync(path.join(app,'seasonal/activity-analytics.js'),'utf8')});
 const publication={schema_version:1,release_id:'campaign-preview-42',config_hash:'a'.repeat(64),pages:[{page_id:'fc27-weekly',activity_id:'fc27-season2',active:true}],products:[]};
 const publish=async value=>page.evaluate(p=>window.dispatchEvent(new CustomEvent('fcactivity:published',{detail:p})),value);
 await publish(publication);assert.equal(await page.evaluate(()=>!!FCActivityAnalytics.status().transmitting),false);assert.equal(events.length,0);
 await page.evaluate(()=>window.FC_ANALYTICS_CONFIG.enabled=true);await publish(publication);await page.evaluate(()=>document.getElementById('fc-activity').dispatchEvent(new CustomEvent('fcactivity:view',{detail:{view:'weekly',platform:'ps',language:'en'}})));assert.equal(events.length,0,'No transmission before consent');
 await page.getByRole('button',{name:'Allow analytics',exact:true}).click();await page.waitForFunction(()=>FCActivityAnalytics.status().transmitting);await page.locator('[data-product]').scrollIntoViewIfNeeded();await page.waitForTimeout(100);assert(events.some(e=>e.event==='activity_product_view'&&e.properties.product_id==='88888'));
 await page.evaluate(()=>document.getElementById('fc-activity').dispatchEvent(new CustomEvent('fcactivity:selection',{detail:{ids:['88888'],action:'companion'}})));await page.waitForTimeout(50);assert(events.some(e=>e.event==='activity_selection'&&e.properties.product_ids.includes('88888')));assert(events.every(e=>e.properties.environment==='test'&&e.properties.page_id==='fc27-weekly'&&e.properties.release_id==='campaign-preview-42'));assert(!events.some(e=>/purchase|begin_checkout/.test(e.event)));
 await page.getByRole('button',{name:'Analytics preferences',exact:true}).click();await page.getByRole('button',{name:'No thanks',exact:true}).click();const count=events.length;await page.evaluate(()=>document.getElementById('fc-activity').dispatchEvent(new CustomEvent('fcactivity:selection',{detail:{ids:['88888']}})));await page.waitForTimeout(50);assert.equal(events.length,count);
 await publish({...publication,pages:[{...publication.pages[0],active:false}]});assert.equal(await page.evaluate(()=>!!FCActivityAnalytics.status().enabled),false);assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
