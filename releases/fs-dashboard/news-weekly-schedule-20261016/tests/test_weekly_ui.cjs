'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {createHash}=require('node:crypto');
const code=fs.readFileSync(path.join(__dirname,'../source/daily.js'),'utf8');
const changes=[['每日','每周'],['每周00:05准备情报','每周六00:05（北京时间）统一采集官方情报与MMOEXP News'],
  ['ⓘ 每周采集说明','ⓘ 每周六00:05（北京时间）采集说明'],['等待夜间采集结果','等待每周采集结果'],
  ['。本站编辑内容与官方公告分开列示','。每周六00:05（北京时间）与官方情报统一采集。本站编辑内容与官方公告分开列示']];
const original=changes.slice().reverse().reduce((value,[before,after])=>value.split(after).join(before),code);
assert.equal(createHash('sha256').update(original).digest('hex'),'aeb4463af4ee5cba3bd904285a4ce4d47f2406bfb599a4c252e715f54cf9a2ca','only approved displayed text changes');
assert(!code.includes('每日'));
const ids={},element=()=>({textContent:'',innerHTML:'',listeners:{},hidden:false,classList:{add(){},remove(){}},
  after(child){ids[child.id]=child;},replaceChildren(){},append(){},scrollIntoView(){},addEventListener(name,fn){this.listeners[name]=fn;}});
for(const id of ['fcGrid','fsDailyStatus','fsDailyCoverage','fsDailySources','fsHistoryToggle','fcMeta','fcBriefCount','fcCollectBtn','rgUpdated'])ids[id]=element();
const document={readyState:'complete',body:{dataset:{}},getElementById:id=>ids[id],createElement:element};
const calls=[],intervals=[],listeners={};
const window={REGION_RELEASES:{},FS_GAME_TIMERS:[],fsVerifyGameSession:async()=>true,fsGameSessionKey:()=> 'wulv',
  fsApplyGameDaily(){},fsRenderGameRegion(){},addEventListener:(name,fn)=>listeners[name]=fn};
const snapshot={schema_version:1,status:'succeeded',version:'game-intel-'+'a'.repeat(20),events:[],
  collected_at:'2026-10-16T00:05:00+08:00',stale_after:'2099-01-01T00:00:00Z',coverage:{total_games:29,covered_games:[],missing_games:[]},source_status:[]};
const news={contract:'mmoexp-seo-news-v1',source_kind:'mmoexp_seo',version:'mmoexp-news-'+'b'.repeat(20),documents:[],
  collected_at:snapshot.collected_at,stale_after:snapshot.stale_after,status:'available',coverage:{game_keys:[]}};
const responses={'daily.json':snapshot,'daily.status.json':{status:'succeeded'},'seo-news.json':news,'seo-news.status.json':{status:'available'}};
const fetch=async url=>(calls.push(url),{ok:true,status:200,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify(responses[url])});
vm.runInNewContext(code,{document,window,fetch,URL,AbortController,Date,setTimeout:()=>1,clearTimeout(){},setInterval:(fn,ms)=>(intervals.push({fn,ms}),intervals.length)});
const drain=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
(async()=>{
  await drain();
  assert(ids.fsDailyStatus.textContent.includes('每周六00:05（北京时间）统一采集官方情报与MMOEXP News'));
  assert(ids.fsSeoNews.innerHTML.includes('每周六00:05（北京时间）与官方情报统一采集'));
  assert.equal(ids.fcCollectBtn.textContent,'ⓘ 每周六00:05（北京时间）采集说明');
  assert(ids.fcMeta.textContent.startsWith('每周官方情报'));assert(ids.rgUpdated.textContent.startsWith('每周官方来源'));
  assert.deepEqual(calls,Object.keys(responses));
  assert.equal(intervals.length,1);assert.equal(intervals[0].ms,300000);
  ids.fsHistoryToggle.listeners.click();assert.equal(ids.fsHistoryToggle.textContent,'返回每周情报');assert.equal(ids.fsSeoNews.hidden,true);
  ids.fsHistoryToggle.listeners.click();await intervals[0].fn();listeners.pageshow();await drain();
  assert.equal(intervals.length,1,'refresh/history/pageshow must not add intervals');
  assert.equal(window.FS_GAME_TIMERS.length,1);
  console.log('PASS weekly UI: text-only diff, official/News Saturday 00:05 Beijing labels, historical toggle, same 4 GETs and single 300000ms poll');
})().catch(error=>{console.error(error);process.exitCode=1;});
