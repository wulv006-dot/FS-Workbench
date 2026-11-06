// Local-only mock data over test_browser's real renderer/runtime server.
const fs=require('node:fs'),path=require('node:path');
const {start,server}=require('./test_browser.cjs');
const repo=path.resolve(__dirname,'../../../..');
const countries=[['US','United States',32],['GB','United Kingdom',24],['DE','Germany',18],['FR','France',14],['CA','Canada',11],['AU','Australia',9],['NL','Netherlands',7],['BR','Brazil',5]];
const names={Coins:'金币',Players:'球员卡',SBC:'SBC',Packs:'Packs',Other:'其他',unknown:'待分类'};
const baseCategories=[['Coins',48,1650],['Players',32,2940],['SBC',17,980],['Packs',12,540],['Other',7,210],['unknown',4,160]];
const values=(orders,revenue_usd)=>({orders,revenue_usd,shipping_sales_cny:revenue_usd*6.8,cost_cny:revenue_usd*4.9,gross_profit_cny:revenue_usd*1.9,gross_margin_pct:27.94});
const sum=rows=>values(rows.reduce((n,r)=>n+r.orders,0),rows.reduce((n,r)=>n+r.revenue_usd,0));
const dimensionRows=(records,total)=>records.map(([key,label,weight],i)=>({key,label,name:label,code:key,...values(Math.max(1,Math.round(total.orders*weight/120)),Math.round(total.revenue_usd*weight/120)),issues:i===0?2:0}));
function points(q,categories){
 const hour=q.grain==='hour',from=Date.parse(q.start.replace(' ','T')+(q.start.length===10?'T00:00:00Z':':00Z')),until=Date.parse(q.end.replace(' ','T')+(q.end.length===10?'T00:00:00Z':':00Z'));
 const count=Math.min(hour?48:31,Math.max(1,Math.round((until-from)/(hour?3600000:86400000))+1));
 return Array.from({length:count},(_,i)=>{const key=new Date(from+i*(hour?3600000:86400000)).toISOString();const parts=categories.map((c,j)=>({...c,...values(Math.max(1,Math.round(c.orders/count)+(i+j)%3),Math.round(c.revenue_usd/count*(.8+((i+j)%5)*.1)))}));return {date:hour?key.slice(0,16).replace('T',' '):key.slice(0,10),...sum(parts),categories:parts};});
}
function detail(q,partial=false){
 const categories=baseCategories.filter(([key])=>!q.product||q.product==='all'||key===q.product).map(([key,orders,revenue])=>({key,label:names[key],...values(orders,revenue)}));
 const totals=sum(categories),trend=points(q,categories);
 const dimensions={country:dimensionRows(countries,totals),payment:dimensionRows([['paypal','PayPal',54],['stripe','Credit / debit card',36],['applepay','Apple Pay',18],['crypto','Crypto',12]],totals),device:dimensionRows([['PC','PC',73],['mobile','Mobile',41],['tablet','Tablet',6]],totals),platform:dimensionRows([['PS','PlayStation',70],['XBOX','Xbox',30],['PC','PC',16],['unknown','未知',4]],totals),site_group:dimensionRows([['main','MMOEXP 主站',90],['satellite','独立站',30]],totals),hour:dimensionRows([['08','08:00',20],['12','12:00',35],['16','16:00',40],['20','20:00',25]],totals)};
 const buckets=[['0-20','0–20',34,420],['20-50','20–50',43,1520],['50-100','50–100',28,2040],['100+','100+',15,2500]].map(([key,label,orders,revenue])=>({key,label,...values(orders,revenue),new:Math.round(orders*.3),returning:Math.round(orders*.6),unknown:1,issues:1}));
 const user_buckets=[['0-50','0–50',18,520],['50-200','50–200',24,2440],['200+','200+',11,3520]].map(([key,label,users,revenue])=>({key,label,users,revenue_usd:revenue,orders:users*2}));
 const dashboardTotals={...totals,paying_customers:53,new_customers:null,repeat_rate_pct:null,new_customer_share_pct:null};
 if(partial){dashboardTotals.known_orders=totals.orders;dashboardTotals.known_revenue_usd=totals.revenue_usd;dashboardTotals.orders=null;dashboardTotals.revenue_usd=null;for(const c of [...categories,...buckets,...trend.flatMap(r=>[r,...r.categories])]){c.known_orders=c.orders;c.known_revenue_usd=c.revenue_usd;c.orders=null;c.revenue_usd=null;}}
 const risks={status:'available',as_of:'2026-10-24T08:00:00Z',high_amount_usd:100,issues:{orders:5,amount_usd:320},waiting24:{orders:3,amount_usd:180},high_amount:{orders:2,amount_usd:280},aging:{under24:12,'24to72':3,at_least72:1,unknown_time:0,created_time_fallback:0}};
 return {contractId:'fc27-detail-analytics-v1',query:q,snapshot_id:'MOCK-'+JSON.stringify(q),as_of:'2026-10-24T08:00:00Z',refreshSeconds:900,scope_label:'MOCK 数据 · FC27 · 非生产证据',data_status:partial?'partial':'complete',customer_status:'unavailable',customer_basis:'模拟站内客户ID；新老客历史未验证',orders_without_customer_id:4,coverage:{paid_complete:!partial,missing_days:partial?['2026-10-20']:[],backlog_status:'complete'},totals:{...totals,new:0,returning:0,unknown:totals.orders,unpriced_orders:0,issues:5,unfinished:16,funding:2},site_groups:dimensions.site_group,buckets,user_buckets,signals:[],dimensions,current_risks:risks,backlog_summary:{orders:16,issues:5,unfinished:16,funding:2,revenue_usd:920},slow_orders:3,trend,orders:[{id:'MOCK-ORDER-001',site_id:'266',site_group:'main',platform:'PS',product:'Items',category:categories[0]?.key||'Coins',amount_usd:95,customer:'unknown',age_hours:32,status:'处理中',reason:'模拟等待'}],page:1,list_total:1,fc_dashboard:{contractId:'fc-dashboard-category-v1-20261106',totals:dashboardTotals,categories,trend,coverage:{classification_status:partial?'partial':'verified',reconciliation_status:'matched',native_summary_reconciled:true}},csv:'mock_order,usd\nMOCK-ORDER-001,95\n',dashboard_csv:'mock_category,orders\nCoins,48\n'};
}
function enrichSummary(value,q){
 const p=value.profile;if(!p)return value;
 const dims={countries:countries.map(([code,name,orders])=>({code,name,orders,revenueUsd:orders*54})),payments:[{name:'paypal',orders:54,revenueUsd:2920},{name:'stripe',orders:36,revenueUsd:1940},{name:'applepay',orders:18,revenueUsd:980},{name:'crypto',orders:12,revenueUsd:640}],devices:[{name:'PC',orders:73,revenueUsd:3940},{name:'Mobile',orders:41,revenueUsd:2220},{name:'Tablet',orders:6,revenueUsd:320}],channels:[{name:'www.mmoexp.com',orders:120,revenueUsd:6480}]};
 p.supplement.dimensions=dims;
 const rows=points(q,[{key:'Coins',...values(120,6480)}]).map(r=>({date:r.date,orders:r.orders,amount:r.revenue_usd}));
 p.supplement.rows=rows;p.primary.rows=rows;
 return value;
}
let installed=false;
function install(){
 if(installed)return;installed=true;
 const original=server.listeners('request');server.removeAllListeners('request');
 server.on('request',(req,res)=>{
  const u=new URL(req.url,'http://127.0.0.1'),q=Object.fromEntries(u.searchParams);
  if(u.pathname==='/business.css'){res.setHeader('Content-Type','text/css');return res.end(fs.readFileSync(path.join(repo,'ui-system/modules/native/business.css')));}
  if(u.pathname.endsWith('/range.json')&&q.mode==='fc-detail'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(detail(q,q.fixture_partial==='1'||u.searchParams.get('fixture')==='partial')));}
  const end=res.end.bind(res);res.end=(body,...args)=>{
   if(body&&q.mode==='summary')body=JSON.stringify(enrichSummary(JSON.parse(String(body)),q));
   if(body&&u.pathname==='/boot.js')body=String(body)+`\nconst preview=new URL(location.href);if(preview.searchParams.has('preview')){while(!restored)await new Promise(resolve=>setTimeout(resolve,10));window.api.apply({b_site:'all',b_profile:'FC27',b_group:'sports',b_grain:'day',b_range:'custom',b_start:preview.searchParams.get('scenario')==='single'?'2026-10-23':'2026-10-17',b_end:'2026-10-23',b_fc_product:preview.searchParams.get('product')||'all'});const theme=preview.searchParams.get('theme')||'light';for(const e of [document.documentElement,document.querySelector('#app')]){e.dataset.theme=theme;e.dataset.fsTheme=theme;}}`;
   if(body&&String(body).startsWith('<!doctype html>'))body=String(body).replace('<script type="module"',`<script>const OD=Date;window.Date=class extends OD{constructor(...a){super(...(a.length?a:['2026-10-24T08:00:00Z']));}static now(){return new OD('2026-10-24T08:00:00Z').getTime();}};</script><script type="module"`).replace(/(<p\b[^>]*>)[^<]*(<\/p>)/,'$1FC / RS 视觉修正 · MOCK DATA · 本页全部为模拟数据$2');
   return end(body,...args);
  };
  for(const listener of original)listener(req,res);
 });
}
async function serve(){install();return start();}
module.exports={serve,server,detail};
if(require.main===module)serve().then(url=>console.log('Local mock preview: '+url+'/?preview=1 (append &theme=dark or &scenario=single)')).catch(error=>{console.error(error);process.exitCode=1;});
