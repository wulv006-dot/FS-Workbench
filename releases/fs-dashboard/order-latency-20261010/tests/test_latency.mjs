import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {LiveSummary} from '../assets/live-summary.js';
for(const name of ['shell.js','business.js']){
 const text=fs.readFileSync(new URL('../assets/'+name,import.meta.url),'utf8'),lo=text.indexOf('function fsMainSite('),hi=text.indexOf('\nfunction fsReferenceTotal',lo);
 const {project,format}=vm.runInNewContext(text.slice(lo,hi)+';({project:fsMainSite,format:fsMetricText})');
 const period={start:'2026-10-09 00:00',end:'2026-10-10 00:00'},admin={status:'available',period,metrics:{averageOrderUsd:{value:0,status:'available'}},dimensions:{channels:[{code:'www.mmoexp.com',orders:1,revenueUsd:100}]}};
 for(const phase of ['queued','reading','failed','deferred']){
  const m=project({supplement:admin,primary:{status:['queued','reading'].includes(phase)?'pending':'unavailable',period,readPhase:phase,currency:'USD'}}).metrics;
  assert.equal(m.orders.value,1);assert.equal(m.averageOrderUsd.value,0);assert.equal(m.estimatedProfitUsd.pendingPhase,phase);
  assert(!format(m.profitMarginPct,x=>x).includes('源未提供'));
 }
 const m=project({supplement:admin,primary:{status:'available',period,currency:'USD',metrics:{}}}).metrics;
 assert.equal(format(m.profitMarginPct,x=>x),'源未提供');
 const retained=project({supplement:admin,primary:{status:'available',period,currency:'USD',stale:true,readPhase:'reading',metrics:{profitMarginPct:{value:20,status:'available'}}}}).metrics;
 assert.equal(retained.estimatedProfitUsd.value,20);assert.equal(retained.estimatedProfitUsd.stale,true);assert(format(retained.profitMarginPct,x=>x).includes('已过期'));
}
const shell=fs.readFileSync(new URL('../assets/shell.js',import.meta.url),'utf8');
assert(shell.includes("import {lifecycle,protectedRead,sessionIdentity,moduleAvailable} from './runtime.js';"));
const realTimer=globalThis.setTimeout,realNow=Date.now;let clock=0,sleeps=[];
globalThis.setTimeout=(fn,ms)=>{clock+=ms;sleeps.push(ms);queueMicrotask(fn);return 1;};Date.now=()=>clock;
try{
 const selection={profile:'FC27',start:'2026-10-09',end:'2026-10-09',grain:'day'},updates=[],client=new LiveSummary(()=>selection,x=>updates.push(x),()=>{});let reads=0;
 client.read=async()=>new Response(JSON.stringify({status:'available',scopeContractId:'admin-main-order-labelled-supplement-v1',profile:{key:'FC27'},query:selection,sources:{Admin:{status:'available'},Order:{status:++reads<3?'pending':'available'}}}),{status:200});
 await client.check();assert.equal(reads,3);assert.equal(updates.length,3);assert.deepEqual(sleeps,[2000,2000]);assert.equal(client.pending,null);
 // A slow source has a finite follow-up budget and does not make fresh Admin stale.
 reads=0;clock=0;sleeps=[];updates.length=0;client.read=async()=>{reads++;return new Response(JSON.stringify({status:'available',scopeContractId:'admin-main-order-labelled-supplement-v1',profile:{key:'FC27'},query:selection,sources:{Admin:{status:'available'},Order:{status:'pending'}}}),{status:200});};
 await client.check();assert.equal(clock,98000);assert.equal(reads,50);assert.equal(updates.at(-1).status,'available');client.stop();
}finally{globalThis.setTimeout=realTimer;Date.now=realNow;}
console.log('Field phases, zero preservation, prompt source follow-up and finite budget passed.');
