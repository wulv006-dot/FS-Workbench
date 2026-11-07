const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../../../..');
(async()=>{
 for(const file of ['ui-system/modules/native/shell.js',...['shell.js','home-shell.js','legacy-shell.js'].map(n=>'releases/fs-dashboard/dashboard-refresh-20261025/source/'+n)]){
  const text=fs.readFileSync(path.join(root,file),'utf8').replace(/\r\n/g,'\n'),code=text.slice(text.indexOf('class LiveSummary'),text.indexOf('\nimport '));
  const selection={profile:'MMOEXP',start:'2026-11-06',end:'2026-11-06',grain:'day'};
  let shown=false,state;
  const context={AbortController,URLSearchParams,setTimeout,clearTimeout,fetch:async()=>({ok:true,status:200,json:async()=>({status:'available',scopeContractId:'admin-paid-order-labelled-supplement-v2',profile:{key:'MMOEXP'},query:selection,sources:{}})}),selection,update:()=>shown=true,state:s=>state=s};
  await vm.runInNewContext(code+';new LiveSummary(()=>selection,update,state).check()',context);
  assert.equal(shown,true,file+' accepts current backend contract');assert.equal(state.phase,'available');
  const home=text.slice(text.indexOf('function homeData(){'),text.indexOf('\n}\n',text.indexOf('function homeData(){'))+2);
  let selected;const heading={},kpis={setAttribute:(k,v)=>kpis[k]=v};
  const homeContext={AbortController,watcher:null,homeController:null,epoch:0,LiveSummary:class{constructor(select){selected=select();}start(){}},FSHomeMetrics:{beijingDate:()=>'2026-11-01'},document:{querySelector:s=>s==='.home-kpis'?kpis:heading},$:()=>({}),readonly:()=>{}};
  vm.runInNewContext(text.slice(0,text.indexOf('class LiveSummary'))+home+';homeData()',homeContext);
  assert.equal(selected.start,'2026-10-31');assert.equal(selected.end,'2026-10-31');assert.equal(heading.textContent,'昨日经营');assert.equal(kpis['aria-label'],'MMOEXP 昨日经营');
 }
 for(const name of ['business.js','home-business.js','legacy-business.js']){
  const text=fs.readFileSync(path.join(__dirname,'../source',name),'utf8'),begin=text.indexOf('function fcUpdateMetrics()'),end=text.indexOf('function fcRing(',begin);
  const cards=['orders','revenueUsd','averageOrderUsd','profitCny','profitMarginPct'].map(key=>({dataset:{metric:key},strong:{},small:{},querySelector:s=>s==='strong'?cards.find(c=>c.dataset.metric===key).strong:cards.find(c=>c.dataset.metric===key).small}));
  const context={KEY:'FC27',exactPermissionDenied:()=>false,fcSameQuery:()=>false,fcDetailState:{},fcQuery:()=>({site_group:'all'}),fcNativeAdminMetrics:()=>({site:'全部网站',cutoff:'2026-11-07 00:00',metrics:{orders:{status:'available',value:4},revenueUsd:{status:'available',value:100}}}),currentExact:()=>({profile:{}}),shippingMetrics:()=>({profitCny:{status:'available',value:30},profitMarginPct:{status:'available',value:20}}),scope:{summaryPolling:false},fcDetailPending:true,document:{querySelectorAll:()=>cards,querySelector:()=>null},fcSetText:(node,text)=>{if(node)node.textContent=text;},fcMoney:v=>'$'+v.toFixed(2),fmtN:String,fcName:String,fcFilters:{product:'all'}};
  vm.runInNewContext(text.slice(begin,end)+';fcUpdateMetrics()',context);
  assert.deepEqual(cards.map(c=>c.strong.textContent),['4','$100.00','$25.00','¥30.00','20.00%'],name+' summary visible while details pending');
  context.fcNativeAdminMetrics=()=>null;
  vm.runInNewContext('fcUpdateMetrics()',context);
  assert.ok(cards.every(c=>c.strong.textContent==='待读取'),name+' restricted filters cannot borrow whole-game totals');
 }
 console.log('PASS current home contract and summary-first cards across all maintained entry points');
})().catch(e=>{console.error(e);process.exitCode=1;});
