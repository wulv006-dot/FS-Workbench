import test from 'node:test';import assert from 'node:assert/strict';import {report} from '../analytics/server.mjs';
test('unconfigured query does not substitute sample data',async()=>{delete process.env.POSTHOG_QUERY_KEY;assert.equal((await report(new URLSearchParams())).status,503);});
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
