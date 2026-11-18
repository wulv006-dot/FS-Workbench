import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import core from '../funnel-core.cjs';
import {report} from '../server.mjs';
import {makeCouponUsage} from '../coupon-usage.mjs';
import {reportContext} from '../report-context.mjs';
import {runStatisticsRefresh,readStatisticsSnapshot} from '../statistics-refresh.mjs';

const activity='mmoexp-carnival', start=Date.parse('2026-11-19T05:00:00Z');
const fixture={release_id:'unrelated',config_hash:'unrelated',pages:[]};
const event=(visit,min,event,properties={},id=visit+':'+min)=>({
 event,timestamp:new Date(start+min*60000).toISOString(),
 properties:{activity_id:activity,activity_visit_id:visit,event_id:id,...properties}
});
const view=(visit,min=0)=>event(visit,min,'activity_view');
const claim=(visit,min,coupon_id,coupon_state='claimed')=>event(visit,min,'activity_coupon_claim',{coupon_id,coupon_state});
const select=(visit,min,action)=>event(visit,min,'activity_selection',{action});

test('Carnival counts visits per step, deduplicates actions and distinguishes the shared buy_now event',()=>{
 const rows=[view('a'), claim('a',1,1399),select('a',2,'mystery_draw'),select('a',3,'mystery_verify_pending'),
  select('a',4,'mystery_verify_unlocked'),claim('a',5,1401),select('a',6,'buy_now'),
  view('b'),claim('b',1,'1513'),select('b',2,'buy_now'),select('b',2,'buy_now'), claim('b',3,1501),
  claim('b',4,1503,'unavailable'),select('b',5,'code_copy'),
  event('c',0,'activity_view',{activity_id:'fc27-weekly'}),claim('c',1,1399),
  view('d'),event('d',1,'activity_add_to_cart',{complete:true})];
 const result=core.summarize(rows,{activity}).carnival;
 assert.deepEqual(result.steps,{visits:3,homeClaim:1,mysteryDraw:1,mysteryVerified:1,blackFridayCheckout:1,capsuleClaim:1,checkoutHandoff:2});
 assert.equal(result.actions.mystery.mystery_verify_pending,1);
 assert.equal(result.actions.mystery.buy_now,1);
 assert.equal(result.actions.blackFriday.buy_now,1);
 assert.equal(result.actions.codes.code_copy,1);
 assert.equal(core.canonicalActivity(activity),activity);
 assert.equal(core.activityMatches('fc27-season2',activity),false);
});

test('Carnival is empty before start and ignores legacy snapshots without Carnival fields',async t=>{
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'carnival-stats-'));
 t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 assert.equal(reportContext(directory,activity).url,'https://www.mmoexp.com/events/Carnival.html');
 const before={directory,published:fixture,activity,now:()=>start-1,readers:{behavior:()=>assert.fail('before start')}};
 assert.equal((await runStatisticsRefresh(before)).status,'not_started');
 const snapshot=at=>readStatisticsSnapshot({...before,kind:'today',at});
 assert.equal(snapshot(start-1).status,'not_started');
 assert.equal(snapshot(start-1).sources.behavior.lastSuccess,null);
 const sub=path.join(directory,activity);
 fs.mkdirSync(sub,{recursive:true,mode:0o700});
 const at=start+3600000, prior=snapshot(at);
 fs.writeFileSync(path.join(sub,'today.json'),JSON.stringify({schemaVersion:1,activityId:activity,
  releaseId:prior.releaseId,configHash:'carnival-2026-v1',campaignStartsAt:new Date(start).toISOString(),
  window:prior.window,sources:{behavior:{lastSuccess:{window:prior.window,summary:{report:{visits:0}}}}}}));
 assert.equal(snapshot(at).sources.behavior.lastSuccess,null);
 const behavior=()=>({status:200,body:{status:'available',generatedAt:new Date(at).toISOString(),report:core.summarize([view('a')],{activity})}});
 assert.equal((await runStatisticsRefresh({...before,now:()=>at,readers:{behavior}})).status,'success');
 assert.equal(snapshot(at).sources.behavior.lastSuccess.summary.report.carnival.steps.visits,1);
});

test('PostHog query scopes production Carnival and requests only permitted coupon template fields',async t=>{
 const original=globalThis.fetch;t.after(()=>{globalThis.fetch=original;});
 let calls=0;
 globalThis.fetch=async(_url,options)=>{
  calls++;
  const q=JSON.parse(options.body).query.query;
  assert.match(q,/properties\.activity_id IN \('mmoexp-carnival'\)/);
  assert.match(q,/properties\.release_id = 'carnival-2026'/);
  assert.match(q,/properties\.config_hash = 'carnival-2026-v1'/);
  assert.match(q,/properties\.environment = 'production'/);
  assert.match(q,/properties\.action/);
  assert.match(q,/properties\.coupon_id/);
  assert.doesNotMatch(q,/properties\.(email|uid|member_coupon_id)/);
  return {ok:true,json:async()=>({results:[]})};
 };
 const params=new URLSearchParams({activity,from:'2026-11-19',to:'2026-11-19'});
 const options={token:'fixture',project:'1',now:()=>start-1};
 assert.equal((await report(params,{now:options.now})).body.status,'not_started');
 assert.equal(calls,0);
 assert.equal((await report(params,{...options,now:()=>start})).body.report.carnival.steps.visits,0);
 assert.equal(calls,1);
});

test('Carnival coupon API rejects partial modules before caching',async ()=>{
 const modules=['home','mystery','blackFriday','capsule'].map(module=>({module,
  issued_total:1,used_total:1,used_orders:1,paid_orders:1,refunded_orders:0,unpaid_orders:0,
  paid_usd_minor:100,discount_usd_minor:15,repurchase_orders:0,repurchase_usd_minor:0,unique_buyers:1}));
 let reads=0, now=start-1;
 const read=makeCouponUsage(request=>{
  assert.deepEqual(request,{activity,action:'coupon_usage',site_id:'266',from:'2026-11-19',to:'2026-11-19'});
  reads++;
  return {activity_id:activity,status:'available',coverage:{complete:true,orders_unmatched:0},modules:reads===1?modules.slice(1):modules};
 },()=>now);
 const params=new URLSearchParams({activity,mode:'live',from:'2026-11-19',to:'2026-11-19'});
 assert.equal((await read(params)).body.status,'not_started');
 assert.equal(reads,0);
 now=start;
 assert.equal((await read(params)).status,502);
 assert.deepEqual((await read(params)).body.modules,modules);
 assert.equal((await read(params)).status,200);
 assert.equal(reads,2);
});
