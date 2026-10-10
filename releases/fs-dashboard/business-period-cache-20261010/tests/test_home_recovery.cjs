const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const dir=path.join(__dirname,'../assets/');
const shell=fs.readFileSync(dir+'shell.js','utf8'),moduleText=fs.readFileSync(dir+'live-summary.js','utf8');
function classText(text){let start=text.indexOf('class LiveSummary {'),end=text.indexOf('\n}\r\n',start);if(end<0)end=text.indexOf('\n}\n',start);return text.slice(start,end+2).replace(/\r/g,'');}
assert.equal(classText(shell),classText(moduleText),'home bundle and standalone client must agree');
const selection={profile:'MMOEXP',start:'2026-10-09',end:'2026-10-09',grain:'day'};
function reply(phase,error){return {status:'available',scopeContractId:'admin-main-order-labelled-supplement-v1',query:selection,profile:{key:'MMOEXP'},sources:{Admin:{status:'available'},Order:{status:phase==='available'?'available':phase==='reading'?'pending':'unavailable',phase,error}},expiresInSeconds:7200};}
async function run(seq,{stop=false}={}){let clock=0,calls=0,sleeps=[],updates=[],client;const ctx={Date:{now:()=>clock},URLSearchParams,AbortController,Error,Object,Math,JSON,clearTimeout:()=>{},setTimeout:(fn,ms)=>{sleeps.push(ms);clock+=ms;queueMicrotask(()=>{if(stop)client.stop();fn()});return 1}};vm.createContext(ctx);vm.runInContext(classText(shell)+';this.Client=LiveSummary',ctx);client=new ctx.Client(()=>selection,x=>updates.push(x),()=>{});client.read=async()=>{const data=structuredClone(seq[Math.min(calls++,seq.length-1)]);return {status:200,ok:true,json:async()=>data}};await client.check();return{calls,updates,sleeps,clock};}
(async()=>{let total=0;for(const error of ['collector_busy','scheduled_collection_due']){const r=await run([reply('deferred',error),reply('available')]);assert.equal(r.calls,2);assert.equal(r.sleeps[0],30000);assert.equal(r.updates.at(-1).sources.Order.phase,'available');total++;}
let r=await run([reply('deferred','collector_busy')]);assert.equal(r.calls,4);assert.equal(r.clock,90000);total++;
r=await run([reply('failed','source_read_failed')]);assert.equal(r.calls,1);total++;
r=await run([reply('deferred','unknown')]);assert.equal(r.calls,1);total++;
r=await run([reply('reading'),reply('available')]);assert.deepEqual(r.sleeps,[2000]);total++;
r=await run([reply('deferred','collector_busy'),reply('available')],{stop:true});assert.equal(r.calls,1);total++;
const c={};vm.createContext(c);vm.runInContext(shell.match(/^function fsOrderLabel\(source\).*$/m)[0]+';this.label=fsOrderLabel',c);assert.ok(!c.label({phase:'deferred',stale:true}).includes('已过期'));total++;
console.log(JSON.stringify({passed:total,total,bundleConsistency:true}));})().catch(e=>{console.error(e);process.exitCode=1});
