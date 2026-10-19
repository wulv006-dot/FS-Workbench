const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(require('path').join(__dirname,'../candidate/page.js'),'utf8');
class E{constructor(){this.children=[];this.dataset={};this.value='';}append(x){this.children.push(x)}replaceChildren(){this.children=[]}get childElementCount(){return this.children.length}}
const elements=new Map();const $=id=>{if(!elements.has(id))elements.set(id,new E());return elements.get(id)};
let queue=[],cards=[];
const ctx={Date,Intl,Map,Set,Error,Number,String,Array,AbortController,setTimeout,clearTimeout,config:{version:1},candidateEpoch:0,candidateAbort:null,disposed:false,$,states:new Set(['available','partial','pending','unavailable']),timeText:x=>x,asText:String,candidateCard:x=>cards.push(x),node:(tag,text,host,cls)=>{const e=new E();e.text=text;host.append(e);return e},get:async(v,p)=>queue.shift()(p),setStatus:()=>{},denied:()=>{throw Error('denied')}};
vm.createContext(ctx);vm.runInContext(src.slice(src.indexOf('  function rangeDays'),src.indexOf('  async function scanRange')),ctx);
assert.equal(ctx.rangeDays('2026-09-30','2026-10-02').join(','),'2026-09-30,2026-10-01,2026-10-02');
assert.equal(ctx.rangeDays('2026-10-01','2026-10-01').length,1);
for(const pair of [['2026-02-30','2026-03-01'],['2026-10-03','2026-10-01'],['2026-01-01','2026-05-01'],['2099-01-01','2099-01-02']])assert.throws(()=>ctx.rangeDays(...pair));
const day=(status,items=[])=>({status,items,config_version:1,captured_at:'2026-10-19T00:00:00Z'});
ctx.renderRange(new Map([['a',day('available',[{order_no:'o1'}])],['b',day('partial',[{order_no:'o1'},{order_no:'o2'}])],['c',day('unavailable')]]),['a','b','c']);
assert.equal(cards.length,2);assert($('candidate-list').children.some(x=>/未取得/.test(x.text)));assert($('candidate-list').children.some(x=>/不完整/.test(x.text)));
(async()=>{
 queue=[p=>{assert.equal(p.day,'2026-10-01');return day('available')},p=>{assert.equal(p.day,'2026-10-02');return day('unavailable')}];
 await ctx.loadCandidates('2026-10-01','2026-10-02');assert.equal(queue.length,0);assert($('candidate-meta').textContent.includes('1/2'));assert(!$('candidate-list').children.some(x=>x.text==='该区间没有符合当前条件的订单。'));
 queue=[()=>day('available'),()=>day('available')];await ctx.loadCandidates('2026-10-01','2026-10-02');assert($('candidate-list').children.some(x=>x.text==='该区间没有符合当前条件的订单。'));
 queue=[()=>({...day('available'),config_version:2})];await ctx.loadCandidates('2026-10-01','2026-10-01');assert($('candidate-list').children.some(x=>/筛选条件已更新/.test(x.text)));
 let oldResolve;queue=[()=>new Promise(r=>oldResolve=r)];const old=ctx.loadCandidates('2026-10-01','2026-10-01');
 queue=[()=>day('available')];await ctx.loadCandidates('2026-10-02','2026-10-02');oldResolve(day('available',[{order_no:'old'}]));await old;assert($('candidate-meta').textContent.startsWith('2026-10-02'));
 console.log('PASS range bounds, inclusive dates, dedup, missing versus zero, config version, last request wins');
})().catch(e=>{console.error(e);process.exitCode=1});
