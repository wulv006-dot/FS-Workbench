import test from 'node:test';import assert from 'node:assert/strict';import {report} from '../analytics/server.mjs';
test('unconfigured query does not substitute sample data',async()=>{delete process.env.POSTHOG_QUERY_KEY;assert.equal((await report(new URLSearchParams())).status,503);});
test('PostHog errors preserve only status and parsed Retry-After for scheduled retry',async()=>{
 const original=globalThis.fetch;globalThis.fetch=async()=>({ok:false,status:429,headers:new Headers({'Retry-After':'7'})});
 try{await assert.rejects(report(new URLSearchParams({activity:'all',from:'2026-10-31',to:'2026-10-31'}),{token:'fixture',project:'1',revision:'retry-header'}),e=>e.message==='PostHog query returned 429'&&e.retryAfterMs===7000);}finally{globalThis.fetch=original;}
});
test('server validates activity/date and returns only aggregate with mocked PostHog',async()=>{
 process.env.POSTHOG_QUERY_KEY='test-only';process.env.POSTHOG_PROJECT_ID='123';
 assert.equal((await report(new URLSearchParams({activity:'unknown'}))).status,400);
 assert.equal((await report(new URLSearchParams({activity:'all',from:'2026-02-30',to:'2026-03-01'}))).status,400);
 const original=globalThis.fetch;globalThis.fetch=async(url,options)=>{assert.match(url,/\/api\/projects\/123\/query\//);const q=JSON.parse(options.body).query.query;assert.match(q,/environment = 'production'/);assert.match(q,/2026-10-25/);return {ok:true,json:async()=>({results:[]})};};
 try{const result=await report(new URLSearchParams({activity:'all',from:'2026-10-23',to:'2026-10-23'}));assert.equal(result.status,200);assert.equal(result.body.report.visits,0);assert.equal('events' in result.body,false);}finally{globalThis.fetch=original;delete process.env.POSTHOG_QUERY_KEY;delete process.env.POSTHOG_PROJECT_ID;}
});

test('real HogQL property encoding is normalized and cached results are not mistaken for fresh',async()=>{
 process.env.POSTHOG_QUERY_KEY='test-only';process.env.POSTHOG_PROJECT_ID='123';const original=globalThis.fetch;
 const row=(event,products,include)=>[event,'2026-10-23T07:00:00Z','anon','fc27-weekly','visit','session','direct','desktop','ps',event,null,products,0,include,null,null,null,null,null];
 globalThis.fetch=async(url,options)=>{assert.equal(JSON.parse(options.body).refresh,'force_blocking');return {ok:true,json:async()=>({results:[row('activity_view',null,'false'),row('activity_selection','["123","456"]','false')]})};};
 try{const r=await report(new URLSearchParams({activity:'fc27-weekly',mode:'test',from:'2026-10-23',to:'2026-10-23'}));assert.deepEqual(r.body.report.products.map(p=>p.id),['123','456']);assert.equal(r.body.report.sbcSelections,0);assert.equal(r.body.eventCount,2);}finally{globalThis.fetch=original;delete process.env.POSTHOG_QUERY_KEY;delete process.env.POSTHOG_PROJECT_ID;}
});


test('marked seasonal query preserves offer fields, separates test from production and exposes no raw customer events',async()=>{
 const original=globalThis.fetch,run='9ad7d166-f524-4ad2-9cc0-ce28e3dbf1e2',registry=[{id:'mmoexp-seasonal',view:'seasonal',name:'Halloween',path:'/events/seasonal/'}];let calls=0;
 const keys=['distinct_id','activity_id','activity_visit_id','activity_session_id','source','device','platform','event_id','product_id','product_ids','active_seconds','include_sbc','order_key','currency','activity_paid_minor','match_id','reward_journey_id','game_id','model_id','off_percent','discount_code','slot','release_id','config_hash','server_id','quantity_value','quantity_unit','test_run_id','action','target','complete','confirmed_ids','failed_count','page_id'];
 const specs=[['activity_view',{}],['activity_product_view',{product_id:'model-111'}],['activity_selection',{action:'offer_reveal'}],['activity_cart_result',{complete:'true',confirmed_ids:'["333"]'}],['activity_add_to_cart',{product_id:'333',product_ids:'["333"]',discount_code:'HWD415',complete:'true'}]];
 const rows=specs.map(([event,extra],i)=>{const props={distinct_id:'anonymous',activity_id:'mmoexp-seasonal',activity_visit_id:'visit',activity_session_id:'session',source:'direct',device:'desktop',platform:'unknown',event_id:'marked-'+i,game_id:'456',model_id:'111',off_percent:'15',slot:'random-1',release_id:'campaign-preview-14',config_hash:'a'.repeat(64),test_run_id:run,...extra};return [event,'2026-10-29T06:00:00Z',...keys.map(k=>props[k]??null)];});
 globalThis.fetch=async(_url,options)=>{calls++;const query=JSON.parse(options.body).query.query;assert.match(query,/properties\.game_id/);assert.match(query,/properties\.model_id/);assert.match(query,/properties\.discount_code/);assert.match(query,/properties\.action/);assert.match(query,/environment = 'test'/);assert(query.includes("properties.test_run_id = '"+run+"'"));assert(!/properties\.(email|password|phone)/.test(query));return {ok:true,json:async()=>({results:rows})};};
 const opts={token:'test-only',project:'123',registry,revision:999};
 try{
  const result=await report(new URLSearchParams({activity:'mmoexp-seasonal',mode:'test',testRunId:run,from:'2026-10-29',to:'2026-10-29'}),opts);assert.equal(result.status,200);assert.equal(result.body.eventCount,5);assert.equal(result.body.report.steps[2].count,1);assert.equal(result.body.report.steps[3].count,0);assert.equal(result.body.report.revenueMinor,0);assert.deepEqual(result.body.testRun.eventIds,['marked-0','marked-1','marked-2','marked-3','marked-4']);assert.equal('events' in result.body,false);
  const offer=result.body.report.seasonalOffers[0];assert.equal(offer.gameId,'456');assert.equal(offer.modelId,'111');assert.equal(offer.offPercent,15);assert.deepEqual(offer.discountCodes,['HWD415']);assert.equal(offer.exposedVisits,1);assert.equal(offer.revealedVisits,1);assert.equal(offer.cartConfirmations,1);
  assert.equal((await report(new URLSearchParams({activity:'mmoexp-seasonal',mode:'production',testRunId:run,from:'2026-10-29',to:'2026-10-29'}),opts)).status,400);assert.equal((await report(new URLSearchParams({activity:'mmoexp-seasonal',mode:'test',testRunId:"' OR 1=1",from:'2026-10-29',to:'2026-10-29'}),opts)).status,400);assert.equal(calls,1);
 }finally{globalThis.fetch=original;}
});
