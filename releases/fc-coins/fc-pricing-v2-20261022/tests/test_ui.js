const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.join(__dirname,'../source');
const {pageToUnit,historyCells,estimatedMarginText,marketOffers,referenceLines}=require(path.join(root,'fc27-quote-cloud.js'));
assert(referenceLines({},null)[0][1].includes('旧回执'));
const lines=referenceLines({reference_adjustment:{anchor_usd:'10',raw_offset:'-.005',raw_weighted_usd:'9.95',sources:{ItemD2R:{status:'available',contribution:'-.0075',normalized_usd:'9.5'},U7Buy:{status:'unavailable',reason:'source_missing'}}}}, {raw_weighted_usd:'9.95',after_floor_usd:'10.5',after_cent_usd:'10.5',selected_usd:'10.5'});
assert(lines.some(([label,value])=>label==='竞价权重'&&value.includes('15%')&&value.includes('5%')));
assert(lines.some(([label,value])=>label==='ItemD2R本轮贡献'&&value.includes('-0.750%')));
assert(lines.some(([label,value])=>label==='U7Buy本轮贡献'&&value.includes('权重不转移')));
const now=Date.now(),run='same-run';
for(const platform of ['PS','XBOX','PC']){
  const row={platform,offers:[{site:'Lootbar'},{site:'U7Buy'},{site:'IGGM'},{site:'U4GM'}]};
  const offer={source:'ItemD2R',platform,run_id:run,status:'valid',currency:'USD',gross_usd:'9.85',purchase_k:'100',bonus_k:'0',effective_usd_per_k:'0.0985',captured_at:new Date(now-1000).toISOString(),comparable:true,conditional:false};
  const quote={run_id:run,evidence:{reference_market:{run_id:run,status:'available',offers:[offer]}}};
  const actual=marketOffers(quote,row,now);assert.equal(actual.length,5);assert.equal(actual[4].usd_price,'9.85');assert(actual[4].comparable);
  assert.equal(row.offers.length,4,'render must not mutate pricing sources');
  assert.equal(marketOffers({...quote,run_id:'other'},row,now)[4].usd_price,undefined,'never borrow another run');
  assert.equal(marketOffers(quote,row,now+900001)[4].comparable,false,'old capture remains visibly historical');
  assert.equal(marketOffers({run_id:run},row,now).length,5,'missing reference keeps an explicit slot');
  assert.equal(marketOffers({run_id:run},row,now)[4].usd_price,undefined);
  const conditional=structuredClone(quote);conditional.evidence.reference_market.offers[0].conditional=true;
  assert.equal(marketOffers(conditional,row,now)[4].comparable,false);
}
assert.equal(estimatedMarginText({procurement_margin_pct:'-20.555'}),'-20.55%');
assert.equal(estimatedMarginText({procurement_margin_pct:'0'}),'0.00%');
assert.equal(estimatedMarginText(null),'待历史优惠数据');
assert.equal(estimatedMarginText({procurement_margin_pct:null}),'待历史优惠数据');
assert.equal(estimatedMarginText({procurement_margin_pct:'NaN'}),'待历史优惠数据');
assert.equal(estimatedMarginText({procurement_margin_pct:null,estimated_net_usd:'0'}),'无正实收，预计亏损');
const reconciled=historyCells({job_id:'original',status:'failed',error:'original_error',reconciliation:{status:'confirmed',public_readback:'verified',mmoexp_replayed:false}});
assert(reconciled[2].includes('失败')&&reconciled[2].includes('对账已确认'));assert.equal(reconciled[3],'已核实');assert(reconciled[4].includes('original_error')&&reconciled[4].includes('Order未重放'));
for(const [page,unit] of [['9.99','0.0999'],['10','0.1000'],['0.01','0.0001'],['9999999999.99','99999999.9999']])assert.equal(pageToUnit(page),unit);
for(const invalid of ['0','NaN','Infinity','1e2','9.999','-1','1,000'])assert.throws(()=>pageToUnit(invalid));
const html=fs.readFileSync(path.join(root,'fc27-coins.html'),'utf8');
assert(html.includes('未优惠与估算平均双红线')&&html.includes('2 未优惠与平均毛利红线'));
assert(!html.includes('优惠后成本红线'));
const source=fs.readFileSync(path.join(root,'fc27-quote-cloud.js'),'utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(x=>x[1]);
assert.equal(new Set(ids).size,ids.length,'IDs must be unique');
for(const [,id] of source.matchAll(/\$\('([^']+)'\)/g))assert(ids.includes(id),`missing control ${id}`);
const policy={system_enabled:true,mode:'auto',revision:40,minimum_gross_margin_pct:'10',interval_minutes:120,platforms:['PS','XBOX','PC']};
const flush=async()=>{for(let n=0;n<8;n++)await new Promise(resolve=>setImmediate(resolve));};
async function scenario(postStatus,pollStatus,kind='collect',terminalJob=null){
  const elements=new Map(ids.map(id=>[id,{textContent:'',disabled:false,classList:{add(){},remove(){}},focus(){},append(){},replaceChildren(){},addEventListener(){}}]));
  const saved=new Map();let interval,posts=0;
  const context={document:{getElementById:id=>elements.get(id),createElement:()=>({append(){}})},
    sessionStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},
    crypto:{randomUUID:()=> 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'},setInterval:fn=>{interval=fn;},
    fetch:async(url,options)=>{
      const pathname=url.replace('/api/fc27/cloud','');let status=200,data;
      if(options.method==='POST'){
        posts++;if(postStatus===0)throw new TypeError('network lost');
        status=postStatus;data=status===200?{job_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'}:{error:'specific_error'};
      }else if(pathname.startsWith('/jobs/')){status=pollStatus;data=status===200?(terminalJob||{status:'queued'}):{error:'temporary_error'};}
      else data=pathname==='/automation'?policy:pathname==='/pricing/state'?{version:'fc-coins-decision-v2',recent:[],quote_usable:true,quote:{run_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',evidence:{checked_at:new Date().toISOString()}}}:pathname==='/player-sync'?{enabled:true}:{};
      return {ok:status<400,status,json:async()=>data};
    }};
  vm.runInNewContext(source,context);await flush();
  await elements.get(kind==='collect'?'collect':'hermes-review').onclick();await flush();
  const afterPost=saved.size;
  await interval();await flush();
  return {posts,afterPost,afterPoll:saved.size,disabled:elements.get('collect').disabled};
}
(async()=>{
  for(const [post,poll,expected] of [[0,503,1],[503,503,1],[200,503,1],[409,200,0]]){
    const value=await scenario(post,poll);
    assert.equal(value.posts,1);assert.equal(value.afterPost,expected);assert.equal(value.afterPoll,expected);
    assert.equal(value.disabled,Boolean(expected));
  }
  const unknown=await scenario(200,200,'hermes_review',{status:'ready',result:{phase:'unknown',do_not_replay:true}});
  assert.equal(unknown.posts,1);assert.equal(unknown.afterPoll,1);
  console.log('UI amount, controls and unknown recovery passed (4 transport scenarios and model unknown receipt).');
})().catch(error=>{console.error(error);process.exitCode=1;});
