const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'../assets/business.js'),'utf8');
const loadSource=source.slice(source.indexOf('async function load(d,key,s,'),source.indexOf('\nfunction draw(host,d,key,s,state)'));
const labelSource=source.match(/^function fsOrderLabel\(source\).*$/m)[0];
const selection={start:'2026-10-09',end:'2026-10-09',grain:'day'};
function response(phase,error){return {status:'available',scopeContractId:'admin-main-order-labelled-supplement-v1',profile:{key:'MMOEXP',period:selection},query:selection,expiresInSeconds:7200,sources:{Admin:{status:'available'},Order:{status:phase==='available'?'available':phase==='reading'?'pending':'unavailable',phase,error}}};}
async function run(sequence,{follow=true,abortAt=null}={}){
 let now=0,calls=0,events=[],delays=[];const signal={aborted:false};
 const ctx={URLSearchParams,DOMException,Error,Number,Math,Date:{now:()=>now},deniedStatus:0,
  fsPeriodPolicy:()=>({ttl:()=>7200}),same:(a,b)=>a.start===b.start&&a.end===b.end,
  requestRange:async()=>{calls++;return structuredClone(sequence[Math.min(calls-1,sequence.length-1)]);},
  pause:async ms=>{delays.push(ms);now+=ms;if(abortAt!==null&&now>=abortAt){signal.aborted=true;throw new DOMException('Aborted','AbortError');}}
 };vm.createContext(ctx);vm.runInContext(loadSource+'\nthis.load=load;',ctx);
 let error;try{await ctx.load(null,'MMOEXP',selection,signal,()=>{},x=>events.push(x),follow);}catch(e){error=e;}
 return {calls,events,delays,now,error};
}
(async()=>{
 const cases=[];const test=async(name,f)=>{try{await f();cases.push({name,passed:true});}catch(e){cases.push({name,passed:false,error:e.message});}};
 await test('deferred collector lock retries then publishes profit',async()=>{const r=await run([response('deferred','collector_busy'),response('available')]);assert.equal(r.calls,2);assert.equal(r.events.at(-1).sources.Order.phase,'available');assert.ok(r.delays[0]>=30000);});
 await test('scheduled yield retries within bounded initial read',async()=>{const r=await run([response('deferred','scheduled_collection_due'),response('available')]);assert.equal(r.calls,2);assert.ok(r.now<100000);});
 await test('persistent contention stays bounded and retains last result',async()=>{const r=await run([response('deferred','collector_busy')]);assert.ok(r.calls>=2&&r.calls<=4);assert.ok(r.now<100000);assert.equal(r.events.at(-1).sources.Order.phase,'deferred');});
 await test('permanent failure is not automatically replayed',async()=>{const r=await run([response('failed','source_read_failed')]);assert.equal(r.calls,1);});
 await test('unknown deferred cause is not retried',async()=>{const r=await run([response('deferred','unknown')]);assert.equal(r.calls,1);});
 await test('Admin-only consumers do not wait for Order',async()=>{const r=await run([response('deferred','collector_busy')],{follow:false});assert.equal(r.calls,1);});
 await test('changing selection cancels deferred followup',async()=>{const r=await run([response('deferred','collector_busy'),response('available')],{abortAt:30000});assert.equal(r.calls,1);assert.equal(r.error?.name,'AbortError');});
 await test('ordinary pending still polls at two seconds',async()=>{const r=await run([response('reading'),response('available')]);assert.equal(r.calls,2);assert.equal(r.delays[0],2000);});
 const ctx={};vm.createContext(ctx);vm.runInContext(labelSource+';this.label=fsOrderLabel',ctx);
 await test('missing Order has no misleading expired-value label',()=>{assert.ok(!ctx.label({phase:'deferred',stale:true,capturedAt:null}).includes('已过期'));});
 await test('real retained old Order value is labelled stale',()=>{assert.ok(ctx.label({phase:'deferred',stale:true,capturedAt:'2026-10-10T00:00:00Z'}).includes('已过期'));});
 console.log(JSON.stringify({passed:cases.filter(x=>x.passed).length,total:cases.length,cases},null,2));if(cases.some(x=>!x.passed))process.exitCode=1;
})();
