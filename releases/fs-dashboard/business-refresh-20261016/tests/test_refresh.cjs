const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../source/business.js','utf8');
const section=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const ctx={};vm.createContext(ctx);
vm.runInContext(section('function fsMetricText(', '/* Preparation'),ctx);
assert.equal(ctx.fsMetricText({value:2,stale:true,pendingPhase:'failed'},String),'2（已过期，刷新失败）');
assert.equal(ctx.fsMetricText({value:2,stale:true,pendingPhase:'reading'},String),'2（已过期，更新中）');
assert.equal(ctx.fsMetricText({value:2,stale:true,pendingPhase:'deferred'},String),'2（已过期，来源繁忙）');
assert.equal(ctx.fsMetricText({value:2,stale:true},String),'2（已过期，显示上次值）');
assert.equal(ctx.fsMetricText({value:0},String),'0');
let timer;const scheduler={clearTimeout(){},setTimeout:(fn,ms)=>{timer=ms;},fsPeriodPolicy:()=>({active:()=>true}),currentSelection:()=>({}),Date:{now:()=>0},scope:{signal:{}},document:{hidden:false}};
vm.createContext(scheduler);vm.runInContext('let summaryRefreshTimer;'+section('function scheduleSummaryRefresh(',"scope.signal.addEventListener('abort',()=>clearTimeout(summaryRefreshTimer)"),scheduler);
scheduler.scheduleSummaryRefresh({sources:{Order:{status:'pending'}},clientExpiresAt:900000});assert.equal(timer,30000);
scheduler.scheduleSummaryRefresh({sources:{Order:{status:'unavailable',stale:true}},clientExpiresAt:900000});assert.equal(timer,30000);
scheduler.scheduleSummaryRefresh({sources:{Order:{status:'available'}},clientExpiresAt:900000});assert.equal(timer,901000);

(async()=>{
 const q=new URLSearchParams('mode=summary&refresh=true');let requests=[];let step=0;
 const range={URLSearchParams,AbortController,DOMException,Date,scope:{},permissionEpoch:0,requests:new Set(),deniedStatus:0,
  endpoint:'/range',setTimeout:()=>1,clearTimeout(){},pause:async()=>{},waitReason:(status)=>[202,429].includes(status)?'pending':null,rangeError:()=>Error('bad'),
  fetch:async(url)=>{requests.push(url);return {status:[429,202,200][step++],ok:true,json:async()=>({status:'available'})};}};
 vm.createContext(range);vm.runInContext(section('async function requestRange(', '\nasync function load('),range);
 await range.requestRange(q,new AbortController().signal,10000);
 assert.equal(requests.length,3);assert(requests[0].includes('refresh=true'));assert(requests[1].includes('refresh=true'));assert(!requests[2].includes('refresh='));
 // Wire explicit update to the same shared query, retaining the original lifecycle.
 assert(source.includes('refreshKeys.add(key)'));assert(source.includes("if(refreshKeys.delete(keyOf(d,key,s)))query.set('refresh','true')"));
 assert(source.includes('if(KEY===\'FC27\')fcDetailSync(true)'));
 console.log('Refresh UI: 15 assertions passed (real states, retry timing, one-shot force, existing FC lifecycle)');
})().catch(e=>{console.error(e);process.exitCode=1;});
