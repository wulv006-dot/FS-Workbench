'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/candidate/fc-detail.js','utf8');
const reader=source.slice(source.indexOf('async function fcRead('),source.indexOf('\nfunction fcDetailSync('));
const valid={contractId:'fc27-detail-analytics-v1',query:{start:'2026-10-11',end:'2026-10-11'},snapshot_id:'fc-detail-test'};
function harness(replies){
 let now=0;const requests=[],bounds=[],seen=[];
 const ctx={URLSearchParams,DOMException,scope:{signal:new AbortController().signal},Date:{now:()=>now},
  AbortSignal:{any:signals=>signals[0],timeout:ms=>{bounds.push(ms);return {}; }},
  fcWait:async(ms,signal)=>{signal.throwIfAborted();now+=ms;},
  fetch:async(url,options)=>{requests.push({url,options});const value=replies.shift();assert(value,'unexpected request');if(value.error)throw value.error;return {status:value.status||200,ok:!value.status||value.status===200,json:async()=>value.body};}};
 vm.createContext(ctx);vm.runInContext(reader+'\nthis.read=fcRead;',ctx);return {...ctx,requests,bounds,seen};
}
(async()=>{
 const cached=harness([{body:{...valid,stale:true,refreshing:true}},{body:valid}]);const seen=[];
 await cached.read({...valid.query,refresh:'true'},new AbortController().signal,d=>seen.push(d));
 assert.equal(seen.length,2);assert(!cached.requests[1].url.includes('refresh='));assert(cached.bounds.every(v=>v>0&&v<=20000));
 const network=harness([{error:new TypeError('network')},{body:valid}]);
 assert.equal((await network.read(valid.query,new AbortController().signal)).snapshot_id,valid.snapshot_id);assert.equal(network.requests.length,2);
 const denied=harness([{error:Error('session_denied')}]);await assert.rejects(denied.read(valid.query,new AbortController().signal),/session_denied/);assert.equal(denied.requests.length,1);
 const wrong=harness([{body:{...valid,query:{start:'2026-10-10',end:'2026-10-11'}}}]);await assert.rejects(wrong.read(valid.query,new AbortController().signal));
 const endless=harness(Array.from({length:310},()=>({error:new TypeError('network')})));await assert.rejects(endless.read(valid.query,new AbortController().signal),/读取超时/);assert(endless.requests.length<=307);

 const sync=source.slice(source.indexOf('function fcDetailSync('),source.indexOf('\nfunction fcDetailDraw('));
 let reads=0,resolveRead;const timers=[];const scopeController=new AbortController();
 const q={...valid.query,grain:'day',platform:'all',customer:'all',bucket:'all',site_group:'main',product:'all'};
 const ctx={Date,AbortController,KEY:'FC27',scope:{signal:scopeController.signal},document:{hidden:false},
  fcAbort:null,fcDetailTimer:null,fcDetailPending:false,fcDetailNextCheck:0,
  fcDetailState:{key:'',data:null,error:'',tab:'overview'},fcDetailInit(){},fcDetailShow(){},fcDetailDraw(){},
  fcQuery:()=>({...q}),clearTimeout(){},setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length;},
  fcRead:async(query,signal,present)=>{reads++;await new Promise(r=>{resolveRead=r;});present({...valid,query:q,as_of:new Date().toISOString(),coverage:{paid_complete:false},refreshSeconds:900});},
  kpiCards(){},renderMain(){},workspaceSync(){}};
 vm.createContext(ctx);vm.runInContext(sync+'\nthis.sync=fcDetailSync;',ctx);
 ctx.sync();ctx.sync();assert.equal(reads,1,'same view must not cancel its pending capture');resolveRead();await new Promise(r=>setImmediate(r));
 assert.equal(ctx.fcDetailPending,false);assert(timers[0].ms>898000&&timers[0].ms<=900000);
 ctx.sync();assert.equal(reads,1,'fresh same view uses cache');ctx.fcDetailNextCheck=0;ctx.sync();assert.equal(reads,2,'expired historical FC view refreshes current pool');
 assert(!/data-daily-run|query\.action='run'|X-FS-Report-Action/.test(fs.readFileSync(__dirname+'/candidate/business.js','utf8')));
 assert(fs.readFileSync(__dirname+'/candidate/business.js','utf8').includes('/dashboard/fs-home/brain/index.html?report_kind=daily#reports'));
 scopeController.abort();resolveRead();
 console.log('FC lifecycle: bounded fetch, transient retry, stale-first, strict contract, permission stop, one inflight capture, historical TTL and archive-only report passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
