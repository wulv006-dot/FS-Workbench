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

// Published profit history: the null-returning legacy short circuit no longer hides the axis,
// the per-day value labels and the hover zones.
const profitSrc=texts[1].slice(texts[1].indexOf('function renderPublishedProfitHistory('),
  texts[1].indexOf('\nfunction renderProfit(')).replace(/\r/g,'');
assert.match(texts[1],/if\(renderPublishedProfitHistory\(rate\)\)return;/);
assert.doesNotMatch(texts[1],/if\(renderPublishedProfitHistory\(\)\)return;/);
assert.match(texts[1],/p\.extra \? '<br>' \+ p\.extra : ''/);
const days=[{day:'2026-10-01',rate:22.2,sales:120,orders:3,capturedAt:'2026-10-02T01:00:00Z',stale:false,latestAttemptAt:null},
  {day:'2026-10-02',rate:-5.5,sales:40,orders:1,capturedAt:'2026-10-03T01:00:00Z',stale:false,latestAttemptAt:null},
  {day:'2026-10-03',rate:null,sales:null,orders:null,capturedAt:null,stale:false,latestAttemptAt:null},
  {day:'2026-10-04',rate:10,sales:70,orders:2,capturedAt:'2026-10-05T01:00:00Z',stale:true,latestAttemptAt:'2026-10-05T07:00:00Z'}];
const draw=(published,rateIn)=>{
  const els={},tip={};
  for(const id of ['profitWrap','pfPane','pfDiv','chartProfit','profitHint','profitLegend','lblProfit'])
    els[id]={id,style:{},textContent:'',innerHTML:''};
  const ctx={currentSelection:()=>({grain:'day',start:'2026-10-01',end:'2026-10-04'}),publishedProfitDays:()=>published,
    INSIGHTS_SNAPSHOT:{snapshotId:'snap-1'},KEY:'MMOEXP',IC:{chart:'<i></i>'},esc:String,fmtP:v=>v.toFixed(2)+'%',
    bindProfitTip:(el,series,px,w)=>{tip.el=el;tip.series=series;tip.px=px;tip.w=w;},document:{getElementById:id=>els[id]||null}};
  const fn=vm.runInNewContext(profitSrc+';renderPublishedProfitHistory',ctx);
  return {ok:fn(rateIn),els,tip};
};
const all=draw(days,0.25),svg=all.els.chartProfit.innerHTML;
assert.equal(all.ok,true);
for(const d of ['2026-10-01','2026-10-02','2026-10-04'])assert.match(svg,new RegExp('data-profit-value="'+d+'"'));
assert.match(svg,/>22\.2%</);assert.match(svg,/>-5\.5%</);assert.match(svg,/>10\.0%</);
assert.match(svg,/fill="#1a9e57"/);assert.match(svg,/fill="#d63a48"/);assert.match(svg,/opacity="0.45"/);
assert.equal(svg.match(/class="pzh" data-i="/g).length,4);
assert.equal(svg.match(/data-profit-day="/g).length,3);
assert.equal(svg.match(/data-profit-missing="/g).length,1);
assert.match(svg,/>缺失</);
assert.equal(svg.match(/opacity="\.55"/g).length,5);
assert.match(svg,/stroke-dasharray="6 5"/);assert.match(svg,/Order所选区间原值 25\.00%/);
assert.equal(all.tip.el,all.els.chartProfit);assert.equal(all.tip.series.length,4);
assert.equal(all.tip.series[0].a,120);assert.equal(all.tip.series[0].o,3);assert.equal(all.tip.series[2].r,null);
assert.match(all.tip.series[3].extra,/保留旧值/);assert.match(all.tip.series[0].extra,/来源：Order/);
assert.match(all.els.profitHint.textContent,/柱顶为该日数值/);assert.match(all.els.profitLegend.innerHTML,/当日利润率/);
assert.equal(all.els.profitWrap.style.display,'none');
const noRate=draw(days,null);assert.doesNotMatch(noRate.els.chartProfit.innerHTML,/#ff9500/);
assert.match(noRate.els.chartProfit.innerHTML,/data-profit-value="2026-10-01"/);
const empty=draw([],0.25);assert.match(empty.els.chartProfit.innerHTML,/该日期区间无完整日数据/);
assert.equal(draw(null,0.25).ok,false);
console.log('Frontend projection, client lifecycle and published profit chart checks passed.');
