import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {LiveSummary} from '../assets/live-summary.js';

const base=new URL('../',import.meta.url),texts=['shell.js','business.js'].map(n=>fs.readFileSync(new URL('assets/'+n,base),'utf8'));
const project=text=>{const lo=text.indexOf('function fsMainSite('),hi=text.indexOf('\nfunction fsReferenceTotal',lo);return vm.runInNewContext(text.slice(lo,hi)+';fsMainSite');};
const period={start:'2026-10-10 00:00',end:'2026-10-10 16:30'};
const admin={status:'available',period,metrics:{},dimensions:{channels:[{code:'www.mmoexp.com',orders:3,revenueUsd:100}]}};
for(const text of texts){
 const fn=project(text),p={supplement:admin,primary:{status:'unavailable',period,currency:'USD'}};
 assert.equal(fn(p).metrics.orders.value,3);assert.equal(fn(p).metrics.revenueUsd.value,100);assert.equal(fn(p).metrics.estimatedProfitUsd.value,null);
 for(const rate of [0,-10,22.16]){p.primary={status:'available',period,currency:'USD',metrics:{profitMarginPct:{status:'available',value:rate}}};assert.equal(fn(p).metrics.estimatedProfitUsd.value,rate);}
 p.primary.period={...period,end:'2026-10-10 15:00'};assert.equal(fn(p).metrics.estimatedProfitUsd.value,null);assert.equal(fn(p).metrics.orders.value,3);
 p.supplement={...admin,dimensions:{channels:[{code:'other.site',orders:500,revenueUsd:10000}]}};assert.equal(fn(p).metrics.orders.value,null);
}
const selection={profile:'MMOEXP',start:'2026-10-10',end:'2026-10-10',grain:'day'};
const value={schemaVersion:1,status:'available',scopeContractId:'admin-main-order-labelled-supplement-v1',query:selection,profile:{key:'MMOEXP',period,supplement:admin},stale:false};
const updates=[],states=[];let current={...selection};
const client=new LiveSummary(()=>current,x=>updates.push(x),x=>states.push(x));
client.read=async()=>new Response(JSON.stringify(value),{status:200});await client.check();assert.equal(updates.length,1);
client.read=async()=>{throw Error('offline');};await client.check();assert.equal(updates.at(-1).stale,true);
current={...selection,start:'2026-10-09',end:'2026-10-09'};await client.check();assert.equal(client.current,null);assert.equal(states.at(-1).phase,'unavailable');
client.read=async()=>new Response('{}',{status:403});await client.check();assert.equal(client.current,null);assert.equal(states.at(-1).status,403);
// Switching dates discards a late response even when a transport ignores abort.
let resolveOld;current=selection;client.read=()=>new Promise(resolve=>resolveOld=resolve);const old=client.check();
current={...selection,start:'2026-10-08',end:'2026-10-08'};client.read=async()=>new Response(JSON.stringify({...value,query:current}),{status:200});await client.check();
resolveOld(new Response(JSON.stringify(value),{status:200}));await old;assert.equal(client.current.query.start,'2026-10-08');client.stop();
assert.match(texts[1],/mode:'summary'/);assert.doesNotMatch(texts[1],/Today's exact native values/);
assert.match(texts[1],/clientExpiresAt/);assert.match(texts[0],/new LiveSummary/);
console.log('Frontend projection and client lifecycle checks passed.');
