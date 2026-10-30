const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.join(__dirname,'../source');
const m=require(path.join(root,'management-live.js'));
const vm=require('node:vm');
const d={contract:'fs-management-daily-v2',dataScope:'all-websites-v1',snapshotId:'management-'+'a'.repeat(24),businessDate:'2026-10-25',timezone:'Asia/Shanghai',projects:[{profile:'RS'}]};
assert(m.validSnapshot(d));
assert(!m.validSnapshot({...d,dataScope:undefined}));
assert.equal(m.metricNote({month:{notes:{new:'Admin 全站原生统计'}}},'new'),'Admin 全站原生统计');
assert.equal(m.sum([100,200]),300);assert.equal(m.sum([100,null]),null);
assert.deepEqual(m.subtotal([100,null,200]),{value:300,count:2,total:3,complete:false});
assert.deepEqual(m.subtotal([null,undefined]),{value:null,count:0,total:2,complete:false});
assert.deepEqual(m.subtotal([0,0]),{value:0,count:2,total:2,complete:true});
assert.deepEqual(m.subtotal([-10,5]),{value:-5,count:2,total:2,complete:true});
assert.deepEqual(m.subtotal([NaN,Infinity,true,'',4]),{value:4,count:1,total:5,complete:false});
assert.deepEqual(m.subtotal([]),{value:null,count:0,total:0,complete:false});
for(const name of ['management-live.js','index.html']) assert(!fs.readFileSync(path.join(root,name),'utf8').includes('主站'));
new Function(fs.readFileSync(path.join(root,'management-live.js'),'utf8'));
assert(!m.adviceValid({status:'succeeded',snapshotId:'old-main'},d));
const source=fs.readFileSync(path.join(root,'management-live.js'),'utf8');
const overview=source.slice(source.indexOf('function overview(){'),source.indexOf('function platformChart(){'));
const names=['FC27','NBA2K27','NFL27','MLB26','CFB27','POE2','D4','AION2','DARK_AND_DARKER','RS','MAPLESTORY_CLASSIC','ARC_RAIDERS','WOW_FOREVER','ARENA_BREAKOUT_INFINITE','COD_BO7'];
function renderFixture({missing=['MLB26'],missingByMetric={},group='ALL',metric='rev',zero=false}={}){
 const groups=['球类运营组','RPG运营组','综合运营组'];
 const projects=names.map((profile,i)=>({profile,name:profile,group:groups[i<5?0:i<9?1:2],owner:'fixture',
  month:{values:{rev:(missingByMetric.rev||missing).includes(profile)?null:zero?0:100,ord:(missingByMetric.ord||missing).includes(profile)?null:10,prof:(missingByMetric.prof||missing).includes(profile)?null:20}},
  targets:{rev:1000,ord:100,prof:200},forecast:{rev:200,ord:20,prof:40}}));
 const elements=Object.fromEntries(['overviewPeriod','timeLegend','topKpis','groupCards','rows','footrow','hbGood','hbBad','dataNote','foot','grpTab'].map(id=>[id,{innerHTML:'',textContent:'',querySelectorAll:()=>[]}]));
 const bars=[],config={overview:{groups:groups.map(key=>({key,leader:'fixture'})),games:names.map(profile=>({profile,file:profile.toLowerCase()+'.html',tier:'S'}))}};
 const context={...m,config,data:{projects,targetPeriod:'2026-10',period:{end:'2026-10-29',observed:29,month_days:31},profitPolicy:'fixture estimate'},
  $:id=>elements[id],group,metric,monthEligible:()=>true,timeP:()=>50,rows:()=>projects.filter(p=>group==='ALL'||p.group===group),
  bar:(a,t,p)=>{bars.push([a,t,p]);return 'fixture bar';},badges:()=>'',platformChart:()=>{}};
 vm.runInNewContext(overview+'overview();',context);
 return {elements,bars,projects};
}
let view=renderFixture();
assert.match(view.elements.topKpis.innerHTML,/全盘营收目标[\s\S]*\$15,000/);
assert.match(view.elements.topKpis.innerHTML,/已知 MTD 营收小计[\s\S]*\$1,400[\s\S]*项目覆盖 14\/15 · 完成 未评估/);
assert.match(view.elements.topKpis.innerHTML,/参考利润率 未评估/);
assert.match(view.elements.groupCards.innerHTML,/球类运营组[\s\S]*已知 MTD 小计 \$400 · 项目覆盖 4\/5[\s\S]*月末线性预测 未评估/);
assert.match(view.elements.footrow.innerHTML,/已知小计 · 项目覆盖 14\/15[\s\S]*未评估[\s\S]*\$1,400/);
assert.deepEqual(view.bars.at(-1),[null,15000,null]);
assert.match(view.elements.rows.innerHTML,/data-file="fc27.html"[\s\S]*10.0%/);
assert.match(view.elements.rows.innerHTML,/data-file="mlb26.html"[\s\S]*未评估/);
view=renderFixture({group:'球类运营组',metric:'ord'});
assert.match(view.elements.footrow.innerHTML,/已知小计 · 项目覆盖 4\/5[\s\S]*>40</);
assert.deepEqual(view.bars.at(-1),[null,500,null]);
view=renderFixture({missingByMetric:{ord:[],prof:['MLB26','AION2']}});
assert.match(view.elements.topKpis.innerHTML,/MTD 订单[\s\S]*项目覆盖 15\/15/);
assert.match(view.elements.topKpis.innerHTML,/已知 MTD 预估利润小计[\s\S]*项目覆盖 13\/15/);
assert.match(view.elements.topKpis.innerHTML,/已知 MTD 营收小计[\s\S]*项目覆盖 14\/15/);
view=renderFixture({missing:names});
assert.match(view.elements.topKpis.innerHTML,/已知 MTD 营收小计[\s\S]*>—<[\s\S]*项目覆盖 0\/15/);
assert.doesNotMatch(view.elements.footrow.innerHTML,/class="act">\$0/);
view=renderFixture({zero:true});
assert.match(view.elements.topKpis.innerHTML,/已知 MTD 营收小计[\s\S]*>\$0<[\s\S]*项目覆盖 14\/15 · 完成 未评估/);
view=renderFixture({missing:[]});
assert.match(view.elements.topKpis.innerHTML,/当前 MTD 营收[\s\S]*\$1,500[\s\S]*项目覆盖 15\/15 · 完成 10.0%/);
assert.match(view.elements.footrow.innerHTML,/合计 · 项目覆盖 15\/15/);
assert.deepEqual(view.bars.at(-1),[1500,15000,3000]);
console.log('all-sites management frontend contracts passed');
