const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'../../../..');
const selection={profile:'MMOEXP',start:'2026-11-12',end:'2026-11-12',grain:'day'};
const [homeReply,businessReply]=JSON.parse(execFileSync(process.env.PYTHON||'python',['-B','-c',`
from datetime import datetime, timezone
from json import dumps
import sys
sys.path.append('../../shipping-profit-20261024/source')
from live_summary import SummaryCache, key_of, query

profiles = {'MMOEXP': ('MMOEXP', 'MMOEXP')}
cache = SummaryCache(None, None, profiles)
now = datetime(2026, 11, 13, 8, tzinfo=timezone.utc)
base = dict(mode=['summary'], profile=['MMOEXP'], start=['2026-11-12'], end=['2026-11-12'], grain=['day'])
def reply(params):
    selection = query(params, profiles, now)
    source = dict(status='available', period=selection['period'], capturedAt=now.isoformat(), metrics={})
    cache.entries[key_of(selection)] = {
        name: dict(state='available', at=cache.clock(), value=source) for name in cache.readers
    }
    status, payload = cache.get_live(selection)
    assert status == 200
    return payload
try:
    print(dumps([reply(base), reply({**base, 'profit_site':['all'], 'profit_basis':['shipping']})]))
finally:
    cache.close()
`],{cwd:path.join(__dirname,'../source'),encoding:'utf8'}));
const v2='admin-paid-order-labelled-supplement-v2';
const unknown='unrecognized-summary-contract';
const retired='admin-main-order-labelled-supplement-v1';
(async()=>{
 for(const file of ['ui-system/modules/native/shell.js',...['shell.js','home-shell.js','legacy-shell.js'].map(n=>'releases/fs-dashboard/dashboard-refresh-20261025/source/'+n)]){
  const text=fs.readFileSync(path.join(root,file),'utf8').replace(/\r\n/g,'\n'),code=text.slice(text.indexOf('class LiveSummary'),text.indexOf('\nimport '));
  for(const [reply,expected] of [[homeReply,true],[{...homeReply,scopeContractId:v2},true],
   [{...homeReply,scopeContractId:unknown},false],[{...homeReply,scopeContractId:retired},false],
   [{...homeReply,query:{...homeReply.query,end:'2026-11-11'}},false]]){
   const shown=[], phases=[];
   const context={AbortController,URLSearchParams,setTimeout,clearTimeout,fetch:async()=>({ok:true,status:200,json:async()=>reply}),selection,update:data=>shown.push(data),state:s=>phases.push(s.phase)};
   await vm.runInNewContext(code+';new LiveSummary(()=>selection,update,state).check()',context);
   assert.deepEqual(shown,expected?[reply]:[],file+' accepts only known contracts for the selected scope');
   assert.deepEqual(phases,['loading',expected?'available':'unavailable']);
  }
  const home=text.slice(text.indexOf('function homeData(){'),text.indexOf('\n}\n',text.indexOf('function homeData(){'))+2);
  let selected;const heading={},kpis={setAttribute:(k,v)=>kpis[k]=v};
  const homeContext={AbortController,watcher:null,homeController:null,epoch:0,LiveSummary:class{constructor(select){selected=select();}start(){}},FSHomeMetrics:{beijingDate:()=>'2026-11-01'},document:{querySelector:s=>s==='.home-kpis'?kpis:heading},$:()=>({}),readonly:()=>{}};
  vm.runInNewContext(text.slice(0,text.indexOf('class LiveSummary'))+home+';homeData()',homeContext);
  assert.equal(selected.start,'2026-10-31');assert.equal(selected.end,'2026-10-31');assert.equal(heading.textContent,'昨日经营');assert.equal(kpis['aria-label'],'MMOEXP 昨日经营');
 }
 for(const name of ['business.js','home-business.js','legacy-business.js']){
  const text=fs.readFileSync(path.join(__dirname,'../source',name),'utf8'),begin=text.indexOf('function fcUpdateMetrics()'),end=text.indexOf('function fcRing(',begin);
  const businessSelection={...selection,profit_site:'all',profit_category:'-1'};
  const testLoad=text.slice(text.indexOf('async function load(d,key,s,'),text.indexOf('function draw(host,d,key,s,state)'));
  const helpers=['function shippingFields(', 'function shippingSame(', 'const same=(a,b)=>'].map(prefix=>text.split(/\r?\n/).find(line=>line.startsWith(prefix))).join('\n');
  const contextLoad={AbortController,URLSearchParams,selection:businessSelection,refreshKeys:new Set(),keyOf:()=>null,
   fsPeriodPolicy:()=>({ttl:()=>600}),deniedStatus:0};
  const runLoad=vm.runInNewContext(helpers+'\n'+testLoad+';load',contextLoad);
  for(const [reply,expected] of [[businessReply,true],[{...businessReply,scopeContractId:v2},true],
   [{...businessReply,scopeContractId:unknown},false],[{...businessReply,query:{...businessReply.query,profit_site:'main'}},false]]){
   let shown=false;
   contextLoad.requestRange=async()=>({...reply});
   const read=runLoad({},'MMOEXP',businessSelection,new AbortController().signal,null,()=>shown=true);
   if(expected)await read;
   else await assert.rejects(read,/汇总数据合同错误/);
   assert.equal(shown,expected,name+' accepts only known contracts for the selected scope');
  }
  const cards=['orders','revenueUsd','averageOrderUsd','profitCny','profitMarginPct'].map(key=>({dataset:{metric:key},strong:{},small:{},querySelector:s=>s==='strong'?cards.find(c=>c.dataset.metric===key).strong:cards.find(c=>c.dataset.metric===key).small}));
  const context={KEY:'FC27',exactPermissionDenied:()=>false,fcSameQuery:()=>false,fcDetailState:{},fcQuery:()=>({site_group:'all'}),fcNativeAdminMetrics:()=>({site:'全部网站',cutoff:'2026-11-07 00:00',metrics:{orders:{status:'available',value:4},revenueUsd:{status:'available',value:100}}}),currentExact:()=>({profile:{}}),shippingMetrics:()=>({profitCny:{status:'available',value:30},profitMarginPct:{status:'available',value:20}}),scope:{summaryPolling:false},fcDetailPending:true,document:{querySelectorAll:()=>cards,querySelector:()=>null},fcSetText:(node,text)=>{if(node)node.textContent=text;},fcMoney:v=>'$'+v.toFixed(2),fmtN:String,fcName:String,fcFilters:{product:'all'}};
  const repeatProjection=text.slice(text.indexOf('const fsRepeatReasons='),text.indexOf('function fsMetricText('));
  vm.runInNewContext(repeatProjection+text.slice(begin,end)+';fcUpdateMetrics()',context);
  assert.deepEqual(cards.map(c=>c.strong.textContent),['4','$100.00','$25.00','¥30.00','20.00%'],name+' summary visible while details pending');
  context.fcNativeAdminMetrics=()=>null;
  vm.runInNewContext('fcUpdateMetrics()',context);
  assert.ok(cards.every(c=>c.strong.textContent==='待读取'),name+' restricted filters cannot borrow whole-game totals');
 }
 console.log('PASS current home contract and summary-first cards across all maintained entry points');
})().catch(e=>{console.error(e);process.exitCode=1;});
