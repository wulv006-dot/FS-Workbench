function fsMainSite(profile,all=false){
 const numeric=v=>typeof v==='number'&&Number.isFinite(v);
 const missing=(source,scope)=>({value:null,status:'not_provided',source,scope});
 const take=(m,source,scope)=>m?.status==='available'&&numeric(m.value)?{...m,source,scope}:missing(source,scope);
 const admin=profile?.supplement,order=profile?.primary;
 const rows=admin?.dimensions?.channels;
 const same=admin?.period?.start===order?.period?.start&&admin?.period?.end===order?.period?.end;
 const available=admin?.status==='available'&&!!admin?.period?.start&&(!all||(admin.normalisedScope==='all-websites'&&['',0,'0'].includes(admin.filters?.site)));
 const main=!all&&available&&Array.isArray(rows)?rows.filter(r=>(r.code||r.name)==='www.mmoexp.com'):[];
 const mainRow=main.length===1?main[0]:null;
 const onlyMain=!!mainRow&&rows.length===1;
 const mainMetrics={};
 for(const key of ['orders','revenueUsd','newCustomers','payingCustomers','newCustomerRevenueUsd','repeatRatePct','newCustomerSharePct','pureSalesUsd','refundAmountUsd','refundOrders','fulfillmentRatePct','paymentSuccessRatePct','averageOrderUsd','averageCustomerUsd','minOrderAmountUsd','maxOrderAmountUsd']){
  mainMetrics[key]=available?take(admin.metrics?.[key],'Admin',all?'全部网站':onlyMain?'MMOEXP':'后台原统计范围（含其他站点），仅参考'):missing('Admin',all?'全部网站':'MMOEXP');
 }
 if(!all){
 for(const key of ['orders','revenueUsd'])mainMetrics[key]=missing('Admin','MMOEXP');
 for(const key of ['orders','revenueUsd'])if(mainRow&&numeric(mainRow[key])&&(key!=='orders'||Number.isSafeInteger(mainRow[key])&&mainRow[key]>=0))mainMetrics[key]={value:mainRow[key],status:'available',source:'Admin',scope:'MMOEXP'};
 // A zero-only response can omit site ranks. Nonzero values are never treated as site-specific without a rank.
 if(available&&(!rows||rows.length===0)&&admin.metrics?.orders?.value===0&&admin.metrics?.revenueUsd?.value===0){
  for(const key of ['orders','revenueUsd'])mainMetrics[key]={value:0,status:'available',source:'Admin',scope:'MMOEXP'};
 }
 }else if(mainMetrics.orders.value!==null&&(!Number.isSafeInteger(mainMetrics.orders.value)||mainMetrics.orders.value<0)){mainMetrics.orders=missing('Admin','全部网站');}
 for(const key of ['profitMarginPct','averageOrderUsd','averageCustomerUsd','minOrderAmountUsd','maxOrderAmountUsd','fulfillmentRatePct']){
  if(mainMetrics[key]?.value!=null)continue;
  mainMetrics[key]=same&&order?.status==='available'&&order.currency==='USD'?take(order.metrics?.[key],'Order',all?'后台全部网站参考；与 Admin 网站集合可能不同':'后台全站参考；与 Admin 主站口径不同'):missing('Order','后台全站参考');
 }
 const revenue=mainMetrics.revenueUsd.value,rate=mainMetrics.profitMarginPct.value;
 const raw=revenue!==null&&rate!==null?Math.round(Math.round(revenue*100)*Math.round(rate*100)/10000)/100:null;
 mainMetrics.estimatedProfitUsd={value:numeric(raw)?raw:null,status:numeric(raw)?'available':'not_provided',source:'Admin × Order',scope:'预估：'+(all?'全部网站':'MMOEXP')+'销售额 × Order利润率；不是后台实结利润'};
 for(const item of Object.values(mainMetrics)){if(item.value===null&&item.source==='Order')item.pendingPhase=order?.status==='pending'?(order.readPhase||'reading'):order?.status==='unavailable'?(order.readPhase||'failed'):'not_provided';}
 mainMetrics.estimatedProfitUsd.pendingPhase=revenue!==null?mainMetrics.profitMarginPct.pendingPhase:'not_provided';
 for(const item of Object.values(mainMetrics)){if(item.source==='Order'&&item.value!==null&&order?.stale&&profile?.cachePolicy!=='historical')item.stale=true;}
 mainMetrics.estimatedProfitUsd.stale=!!(mainMetrics.profitMarginPct.stale&&mainMetrics.estimatedProfitUsd.value!==null);
 return {metrics:mainMetrics,period:admin?.period,adminCapturedAt:admin?.capturedAt,orderCapturedAt:order?.capturedAt,onlyMain,
  site:all?'全部网站':'MMOEXP',policy:'admin-main-order-labelled-supplement-v1'};
}

'use strict';
const Management = (() => {
  const numeric = v => typeof v === 'number' && Number.isFinite(v);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = (v, k = 'rev') => numeric(v) ? (['rev','prof'].includes(k) ? '$' : '') + v.toLocaleString('en-US', {maximumFractionDigits:k === 'ord' ? 0 : 2}) : '—';
  const sum = values => values.length && values.every(numeric) ? values.reduce((a,b) => a+b,0) : null;
  const percent = (v,t,eligible=true) => eligible && numeric(v) && numeric(t) && t > 0 ? v/t*100 : null;
  const pct = v => numeric(v) ? v.toFixed(1)+'%' : '未评估';
  function progressConcern(actual,target,timePercent,eligible){
    const completed=percent(actual,target,eligible);
    if(completed===null||!numeric(timePercent))return null;
    const gap=completed-timePercent;return {completed,gap,state:gap>=15?'ahead':gap<=-15?'behind':'within'};
  }
  const day = () => new Date(Date.now()+8*3600000).toISOString().slice(0,10);
  const previous = value => new Date(Date.parse(value+'T00:00:00Z')-86400000).toISOString().slice(0,10);
  function validateSummary(data, profile, query) {
    return ['available','stale'].includes(data?.status) && data.scopeContractId === 'admin-main-order-labelled-supplement-v1' && data.profile?.key === profile && data.query?.start === query.start && data.query?.end === query.end;
  }
  function catalogProfiles(data) {
    if(data?.schemaVersion !== 2 || !/^catalog-[a-f0-9]{16}$/.test(data.catalogId || '') || data.snapshotId !== data.catalogId || data.scopeContractId !== 'all-websites-order-primary-admin-supplement-v1') throw Error('FS 目录合同不匹配');
    return new Set(Object.keys(data.dashboard?.profiles || {}));
  }
  function wait(ms,signal){return new Promise((resolve,reject)=>{
    if(signal?.aborted){reject(new DOMException('Cancelled','AbortError'));return;}
    const done=()=>{signal?.removeEventListener('abort',cancel);resolve();};
    const timer=setTimeout(done,ms);
    function cancel(){clearTimeout(timer);signal.removeEventListener('abort',cancel);reject(new DOMException('Cancelled','AbortError'));}
    signal?.addEventListener('abort',cancel,{once:true});
  });}
  async function pollSummary({read,profile,query,update,signal,budget=100000,now=Date.now,sleep=wait}){
    const started=now(),path='/dashboard/fs-home/range.json?'+new URLSearchParams({mode:'summary',profile,...query});
    let current=null;
    while(now()-started<budget){
      signal?.throwIfAborted();
      const remaining=budget-(now()-started);
      const response=await read(path,AbortSignal.any([...(signal?[signal]:[]),AbortSignal.timeout(Math.max(1,remaining))]));
      signal?.throwIfAborted();
      const data=await response.json();signal?.throwIfAborted();
      const queued=response.status===202||response.status===429;
      if(!queued){
        if(!response.ok)throw Error('FS 读取失败');
        if(!validateSummary(data,profile,query))throw Error('FS 返回日期或口径不匹配');
        current=data;update(data,'available');
        const sources=data.sources||{},order=sources.Order;
        const pending=sources.Admin?.status==='pending'||order?.status==='pending'||(order?.phase==='deferred'&&['collector_busy','scheduled_collection_due'].includes(order.error));
        if(!pending)return {current,timedOut:false};
      }else update(null,'pending');
      const retry=Number(data.retryAfter??data.retryAfterSeconds??response.headers?.get('Retry-After'));
      const delay=Math.min(10000,Math.max(2000,Number.isFinite(retry)&&retry>0?retry*1000:2000));
      if(now()-started+delay>=budget)break;
      await sleep(delay,signal);
    }
    return {current,timedOut:true};
  }
  async function runTwo(items,run){let index=0;async function worker(){while(index<items.length){const item=items[index++];await run(item);}}await Promise.all([worker(),worker()]);}
  async function pollAdvisor({read,jobId,signal,budget=180000,now=Date.now,sleep=wait}){
    const started=now(),path='/dashboard/fs-home/advisor.json?id='+encodeURIComponent(jobId);
    while(now()-started<budget){
      signal?.throwIfAborted();const response=await read(path,signal);const body=await response.json();signal?.throwIfAborted();
      if(!response.ok)throw Error(body.error||body.reason||body.status||'AI 任务读取失败');
      const job=body.job||body;
      if(['completed','succeeded','done','failed','unknown','cancelled','rejected'].includes(job.state))return job;
      if(now()-started+3000>=budget)break;
      await sleep(3000,signal);
    }
    throw Error('等待超时；原任务编号已保留，请点击查询已有任务');
  }
  function validateDaily(data,targets){
    if(data?.schemaVersion!==1||data.contractId!=='fs-management-daily-v1'||data.targetPeriod!==targets.period||!Array.isArray(data.projects)||data.projects.length!==targets.overview.games.length||!['available','partial','unavailable','stale','target_period_expired','no_complete_days'].includes(data.status))return false;
    const seen=new Set();
    for(const p of data.projects){
      const g=targets.overview.games.find(g=>g.profile===p.key);if(!g||seen.has(p.key))return false;seen.add(p.key);
      for(const [key,target] of [['revenue_usd','rev'],['orders','ord'],['estimated_profit_usd','prof']]){
        if(p.targets?.[key]!==g.tgt[target]||!(p.actuals?.[key]===null||numeric(p.actuals?.[key])))return false;
      }
      if(p.actuals.revenue_usd!==null&&p.actuals.revenue_usd<0||p.actuals.orders!==null&&(!Number.isSafeInteger(p.actuals.orders)||p.actuals.orders<0))return false;
      const days=data.period?.end?(Date.parse(data.period.end+'T00:00:00Z')-Date.parse(data.period.start+'T00:00:00Z'))/86400000+1:0;
      if(p.forecast?.method!=='actual / observed_complete_days * days_in_target_month'||p.forecast.observedCompleteDays!==days||p.forecast.monthDays!==31)return false;
      for(const key of ['revenue_usd','orders','estimated_profit_usd'])if(!(p.forecast.values?.[key]===null||numeric(p.forecast.values?.[key]))||p.actuals[key]===null&&p.forecast.values[key]!==null)return false;
    }
    return data.period?.start===targets.period+'-01'&&(data.period.end===null||/^\d{4}-\d{2}-\d{2}$/.test(data.period.end)&&data.period.end>=data.period.start&&data.period.end<=targets.period+'-31');
  }
  function dailyForRange(snapshot,query,mode){return mode==='daily'&&snapshot?.period?.start===query.start&&snapshot?.period?.end===query.end?snapshot:null;}
  function dailyForecastLabel(snapshot,query,mode,expired,key,metric){
    if(mode!=='daily')return '人工区间不套用每日预测';
    if(expired)return '目标期不匹配，未预测';
    const match=dailyForRange(snapshot,query,mode),field={rev:'revenue_usd',ord:'orders',prof:'estimated_profit_usd'}[metric];
    const value=match?.projects?.find(p=>p.key===key)?.forecast?.values?.[field];
    return numeric(value)?'月末线性预测 '+fmt(value,metric):'每日预测暂无有效数据';
  }
  function placeDailyPanel(doc,panel){
    const anchor=doc.getElementById('groupCards')||doc.querySelector('.wrap > .hero');
    if(anchor)anchor.after(panel,doc.getElementById('fs-controls'),doc.getElementById('fs-status'));
    else doc.getElementById('fs-status').after(panel);
  }

  function actuals(data){
    const m=fsMainSite(data.profile).metrics,stale=data.stale||data.status==='stale';
    const get=k=>!stale&&!m[k]?.stale?m[k]?.value??null:null;
    const scoped=k=>m[k]?.scope==='MMOEXP'?get(k):null;
    const rev=get('revenueUsd'),ord=get('orders');
    return {rev,ord,prof:get('estimatedProfitUsd'),new:scoped('newCustomers'),aov:numeric(rev)&&numeric(ord)&&ord>0?Math.round(rev*100/ord)/100:null,rep:scoped('repeatRatePct'),ful:scoped('fulfillmentRatePct'),mar:get('profitMarginPct')};
  }
  function weekPeriods(model,period,query){
    if(!/^\d{4}-\d{2}$/.test(period)||!/^\d{4}-\d{2}-\d{2}$/.test(query.start||'')||!/^\d{4}-\d{2}-\d{2}$/.test(query.end||''))return [];
    const bounds={w1:[1,4],w2:[5,11],w3:[12,18],w4:[19,25],w5:[26,31]};
    return model.weeks.map(w=>{const b=bounds[w.id];if(!b)throw Error('周目标日期合同不匹配');const lo=period+'-'+String(b[0]).padStart(2,'0'),hi=period+'-'+String(b[1]).padStart(2,'0'),start=lo>query.start?lo:query.start,end=hi<query.end?hi:query.end;return {id:w.id,start,end,plannedStart:lo,plannedEnd:hi,eligible:start<=end,complete:start===lo&&end===hi};});
  }
  return {numeric,esc,fmt,sum,percent,pct,progressConcern,day,previous,validateSummary,catalogProfiles,wait,pollSummary,runTwo,pollAdvisor,validateDaily,dailyForRange,dailyForecastLabel,placeDailyPanel,actuals,weekPeriods};
})();

if(typeof module !== 'undefined') module.exports = {Management,fsMainSite};
if(typeof document !== 'undefined') (async function boot(){
  const {numeric,esc,fmt,sum,percent,pct,day,previous,validateSummary,catalogProfiles} = Management;
  const $ = id => document.getElementById(id), view=document.body.dataset.view;
  let config, identity=null, role='', catalog=new Set(), generation=0, group='ALL', metric='rev', values={}, details={}, sandbox=null, busy=false, aiBusy=false, aiJob=null, dailySnapshot=null, dailyStatus=null, viewMode='daily';
  let query={start:'2026-10-01',end:previous(day())}, controller=new AbortController(),weekController=new AbortController(),weekKey='',weekValues={};
  if(query.end > '2026-10-31') query.end='2026-10-31';
  if(query.end < query.start) query.end=query.start;
  const empty=()=>({rev:null,ord:null,prof:null,new:null,aov:null,rep:null,ful:null,mar:null});
  const dailyExpired=()=>viewMode==='daily'&&(day().slice(0,7)!=='2026-10'||['target_period_expired','no_complete_days'].includes(dailyStatus?.fact_status||dailySnapshot?.status));
  const eligible=()=>query.start==='2026-10-01' && !!query.end && query.end<='2026-10-31' && !dailyExpired();
  const timePercent=()=>eligible()?(Date.parse(query.end+'T00:00:00Z')-Date.parse(query.start+'T00:00:00Z')+86400000)/86400000/31*100:null;
  const status=text=>$('fs-status').textContent=text;
  function halt(text){
    generation++; controller.abort();weekController.abort();weekValues={};weekKey='';identity=null;values={};details={};sandbox?.clear();
    document.querySelectorAll('.wrap > :not(.fs-nav):not(#fs-status)').forEach(el=>el.hidden=true);
    status(text+'；请返回 FS 工作台重新登录。');
  }
  async function read(path,signal=controller.signal){
    const r=await fetch(path,{credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.any([signal,AbortSignal.timeout(25000)])});
    if(r.status===401||r.status===403||r.type==='opaqueredirect'||r.redirected){halt('登录或访问权限失效，经营数据已清除');throw Error('session_denied');}
    return r;
  }
  async function verify(){
    const r=await read('/__auth/verify',AbortSignal.timeout(15000));
    if(!r.ok)throw Error('无法验证 FS 登录');
    const name=r.headers.get('X-Auth-User'), groups=(r.headers.get('X-Auth-Groups')||'').split(',');
    if(!name||!groups.includes('dashboard')){halt('当前账号没有经营工作区权限');throw Error('session_denied');}
    if(identity&&identity!==name){halt('账号已切换');throw Error('session_denied');}
    identity=name;role=r.headers.get('X-Auth-Role')||'';
    aiButtons();
  }
  function aiButtons(){
    if($('fs-ai'))$('fs-ai').disabled=role!=='admin'||busy||aiBusy||!!(aiJob&&!aiJob.done);
    if($('fs-ai-resume')){$('fs-ai-resume').hidden=!aiJob;$('fs-ai-resume').disabled=role!=='admin'||aiBusy;}
  }
  function controls(){
    $('fs-controls').innerHTML='<label>实际开始日期 <input id="fs-start" type="date" value="'+query.start+'"></label><label>实际结束日期 <input id="fs-end" type="date" value="'+query.end+'"></label><button id="fs-daily-refresh" type="button">查看每日分析</button><button id="fs-refresh" type="button">查询所选日期</button><span>Asia/Shanghai · 美元 · 默认截至昨日完整日</span><p>目标固定为原包 2026-10；跨月或非月初区间只展示实际，不作月目标进度比较。缺失、排队或失败不会填零。</p><details><summary>AI 经营参考</summary><p>Hermes 当前提供 FC 运营报告；全项目经营分析尚待扩展。</p><a href="/dashboard/fs-home/brain/index.html?report_kind=daily#reports">查看 FC 运营报告</a></details>';
    $('fs-daily-refresh').onclick=()=>loadDaily();$('fs-refresh').onclick=()=>load();$('fs-start').onchange=()=>load();$('fs-end').onchange=()=>load();
    const panel=document.createElement('section');panel.id='fs-daily';panel.className='panel';Management.placeDailyPanel(document,panel);

  }
  const games=()=>config.overview.games;
  const selected=()=>games().filter(g=>group==='ALL'||g.grp===group);
  const actual=g=>values[g.profile]||empty();
  function metadata(g){const d=details[g.profile];return d?d.label+' · '+d.source:'尚未读取 FS';}
  function bar(v,t){const p=percent(v,t,eligible());return '<div class="bar"><i class="now" style="width:'+ (numeric(p)?Math.max(0,Math.min(100,p)):0)+'%"></i></div>'+(p===null?'<span class="note">未评估</span>':'');}
  function overview(){
    const all=games(), rows=selected(), a=k=>sum(all.map(g=>actual(g)[k])), t=k=>sum(all.map(g=>g.tgt[k]));
    $('topKpis').innerHTML=[['全盘营收目标',fmt(t('rev')),'原包 2026-10 · 15 款'],['所选区间营收',fmt(a('rev')),'已读取 '+all.filter(g=>numeric(actual(g).rev)).length+'/15；缺项时不合计'],['所选区间订单',fmt(a('ord'),'ord'),'仅 MMOEXP 主站'],['所选区间预估利润',fmt(a('prof'),'prof'),'Admin 销售额 × Order 利润率，非实结利润']].map(x=>'<div class="kp"><div class="l">'+x[0]+'</div><div class="n">'+x[1]+'</div><div class="s">'+x[2]+'</div></div>').join('');
    $('groupCards').innerHTML=config.overview.groups.map(g=>{const list=all.filter(x=>x.grp===g.key),rev=sum(list.map(x=>actual(x).rev)),target=sum(list.map(x=>x.tgt.rev));return '<button type="button" class="gc'+(group===g.key?' on':'')+'" data-group="'+esc(g.key)+'"><div class="gh"><span class="gn">'+esc(g.key)+'</span><span class="gl">组长 '+esc(g.leader)+'</span></div><div class="pct">'+pct(percent(rev,target,eligible()))+'</div><div class="sub">实际 '+fmt(rev)+' · 目标 '+fmt(target)+'<br>完整读取 '+list.filter(x=>numeric(actual(x).rev)).length+'/'+list.length+' · 进度与预测见每日分析</div></button>';}).join('');
    $('groupCards').querySelectorAll('button').forEach(b=>b.onclick=()=>{group=group===b.dataset.group?'ALL':b.dataset.group;overview();});
    $('rows').innerHTML=rows.map(g=>{const a=actual(g)[metric],t=g.tgt[metric];return '<tr><td><a class="gname" href="'+esc(g.file)+'">'+esc(g.name)+'</a><div class="gmeta">'+esc(g.grp)+' · '+esc(g.owner)+'</div></td><td class="barcell">'+bar(a,t)+'<div class="note">'+esc(metadata(g))+'</div></td><td class="nums">'+pct(percent(a,t,eligible()))+'</td><td class="nums"><div class="act">'+fmt(a,metric)+'</div><div class="tgt">目标 '+fmt(t,metric)+'</div></td><td class="nums">'+(eligible()?'时间进度 '+pct(timePercent()):'期间不可比较')+'<div class="note">'+esc(Management.dailyForecastLabel(dailySnapshot,query,viewMode,dailyExpired(),g.profile,metric))+'</div></td></tr>';}).join('');
    const predictionLegend=document.querySelector('.legend > span:nth-child(2)');
    if(predictionLegend)predictionLegend.textContent=viewMode==='daily'?'月末线性预测与方法详见每日分析':'人工区间不套用每日预测';
    $('footrow').innerHTML='<td>所选组完整合计</td><td colspan="4">实际 '+fmt(sum(rows.map(g=>actual(g)[metric])),metric)+' · 原包目标 '+fmt(sum(rows.map(g=>g.tgt[metric])),metric)+' · 任一游戏缺项时不汇总实际</td>';
    const progress=all.map(g=>({g,p:Management.progressConcern(actual(g).rev,g.tgt.rev,timePercent(),eligible())}));
    for(const [id,state] of [['hbGood','ahead'],['hbBad','behind']]){
      const concerned=progress.filter(x=>x.p?.state===state);
      $(id).innerHTML=concerned.length?concerned.map(({g,p})=>'<div class="item"><div><a class="nm" href="'+esc(g.file)+'">'+esc(g.name)+'</a><span class="ow"> · '+esc(g.owner)+'</span><div class="ow">收入完成率 '+pct(p.completed)+' · 仅实际进度</div></div><span class="vl">'+(p.gap>=0?'+':'')+p.gap.toFixed(1)+'p</span></div>').join(''):'<div class="empty">'+(eligible()?'已读取项目中暂无达到本栏 ±15p 阈值的项目。':'所选区间非 10 月月初完整日，未评估。')+'</div>';
    }
    const unknown=progress.filter(x=>!x.p);
    $('hbPending').textContent=unknown.length?'未评估 '+unknown.length+' 款：'+unknown.map(x=>x.g.name+'（'+x.g.owner+'）').join('、'):'全部项目已有有效实际；未达 ±15p 的项目不列入关注栏。';
    $('chartBox').innerHTML='<div class="pending-slot">未接入真实逐月数据；原包历史曲线已移除。</div>';
    $('dataNote').textContent='FS 查询区间 '+query.start+' 至 '+(query.end||'尚无完整日')+' · 各游戏来源状态见表格';
    $('foot').textContent='FS 同源只读经营数据 · Admin 主站销售额/订单 · Order 利润率为后台全站参考，预估利润不是实结利润。原包目标与负责人保留；进度关注沿用 ±15p 阈值，不使用旧预测作健康判断。';
    document.querySelectorAll('#grpTab button').forEach(b=>b.classList.toggle('on',b.dataset.g===group));
    renderDaily();
  }
  function game(){
    const m=config.models[document.body.dataset.profile],a=values[m.slug]||empty(),d=details[m.slug];
    const card=(t,first)=>{const v=a[t.id],p=percent(v,t.val,(first?eligible():true)&&t.id!=='mar'),unit=t.unit==='%'?'%':t.unit==='人'?' 人':t.unit==='单'?' 单':'';return '<div class="kpi"><div class="ktop"><span class="klab">'+esc(t.lab)+'</span><span class="kbadge">'+pct(p)+'</span></div><div class="kactual">'+fmt(v,t.unit==='$'?'rev':'ord')+unit+'</div><div class="kfoot"><span>原包目标</span><b>'+fmt(t.val,t.unit==='$'?'rev':'ord')+unit+'</b></div><div class="note">'+(first?'2026-10 目标；实际为所选区间': ({aov:'Admin 主站销售额 ÷ 主站订单数；零订单时不计算',rep:'Admin 主站复购率；未提供时保持缺失',ful:'Admin 主站发货完成率；未提供时保持缺失',mar:'Order 全站参考利润率；范围不同，不评价主站目标达成'}[t.id]||'主站未提供时保持缺失'))+'</div></div>';};
    $('hero').innerHTML='<div class="in"><div class="kick">'+esc(m.kick)+'</div><h1>'+esc(m.name)+'</h1><div class="who">负责人 <b>'+esc(m.owner)+'</b> · '+esc(m.grp)+' · 原包目标周期 2026-10</div><p>FS 实际区间 '+query.start+' 至 '+query.end+'</p><p>'+esc(d?.label||'尚未读取 FS')+'</p></div>';
    $('ovSub').textContent=eligible()?'所选完整日期的时间进度 '+pct(timePercent())+'；当前完成率仅为进度参考，健康度未评估。':'所选期间与 10 月月初至今不一致，不计算月目标完成率。';
    $('ovGrid').innerHTML=m.l1.slice(0,3).map(t=>'<div class="cards"><b>'+esc(t.lab)+'</b><p>'+pct(percent(a[t.id],t.val,eligible()))+'</p>'+bar(a[t.id],t.val)+'</div>').join('');
    $('l1Grid').innerHTML=m.l1.map(t=>card(t,true)).join('');$('l2Grid').innerHTML=m.l2.map(t=>card(t,false)).join('');
    $('wkBody').innerHTML=m.weeks.map(w=>{const r=weekValues[w.id],a=r?.numbers;return '<tr><td>'+esc(w.lab)+'</td><td class="wknote">'+esc(w.note)+' · 原包规划假设<br>'+esc(r?.label||'尚未读取周实际')+(r?.period?.eligible?'<br>实际 '+esc(r.period.start)+' 至 '+esc(r.period.end)+(r.period.complete?' · 完整目标周':' · 所选区间内的部分周'):'')+'</td><td class="r">'+fmt(w.rev)+'</td><td class="r">'+fmt(a?.rev)+'</td><td>'+pct(percent(a?.rev,w.rev))+'</td><td class="r">'+fmt(w.ord,'ord')+'</td><td class="r">'+fmt(a?.ord,'ord')+'</td></tr>';}).join('');
    $('dailyChart').innerHTML='<div class="pending-slot">真实逐日营收和订单尚未接入；不使用原包旧值，也不以区间汇总拆分日数据。</div>';
    $('lawList').innerHTML='<li>当前目标进度、线性预测和每日建议见上方「每日目标分析」；人工区间只展示所选实际。原包历史判断不作为当前结论。</li>';
    $('rhythmList').innerHTML=m.rhythms.map(r=>'<li><b>'+esc(r.d)+'</b> '+esc(r.e)+' <span class="note">原包规划假设，未核实当前档期</span></li>').join('');
    $('footSrc').textContent='FS 同源只读 · '+(d?.source||'尚无来源读取证据')+' · Order 补充指标为后台全站参考；预估利润非实结。';
  }
  function render(){if(!config)return;if(view==='overview')overview();else if(view==='game')game();else sandbox?.update(values);renderDaily();}
  function renderDaily(){
    const panel=$('fs-daily');if(!panel)return;
    const expanded=!!panel.querySelector('details')?.open;
    if(viewMode!=='daily'){panel.innerHTML='<h2>人工区间查询</h2><p>下方为所选日期实际；每日预测与 AI 建议已停止套用。点击「查看每日分析」返回服务器每日结果。</p>';return;}
    const snapshot=Management.dailyForRange(dailySnapshot,query,viewMode);
    if(!snapshot){panel.innerHTML='<h2>每日目标分析</h2><p>服务器每日 00:20（Asia/Shanghai）更新。尚无可用每日结果，可点击「查询所选日期」读取实际。</p><p>最近尝试 '+esc(dailyStatus?.finished_at||dailyStatus?.started_at||'未提供')+' · '+esc(dailyStatus?.fact_status||dailyStatus?.status||'未提供')+'</p>';return;}
    const list=view==='game'?snapshot.projects.filter(p=>p.key===document.body.dataset.profile):snapshot.projects.filter(p=>group==='ALL'||games().find(g=>g.profile===p.key)?.grp===group);
    const statuses={available:'已更新',partial:'部分数据缺失',unavailable:'来源不可用',stale:'保留上版',target_period_expired:'目标周期已过期，等待确认新目标',no_complete_days:'本月尚无完整日'};
    const last=dailyStatus?.lastAttempt||snapshot.lastAttempt||{},lastAt=dailyStatus?.finished_at||dailyStatus?.started_at||last.at||'未提供';
    const lastState=dailyStatus?.status||last.status||'未提供';
    const stale=snapshot.stale||snapshot.status==='stale'||['failed','unavailable','unknown','source_unavailable','incomplete'].includes(lastState)||snapshot.period.end!==previous(day());
    const state=day().slice(0,7)!=='2026-10'||dailyStatus?.fact_status==='target_period_expired'?'target_period_expired':dailyStatus?.fact_status==='no_complete_days'?'no_complete_days':snapshot.status,canForecast=!dailyExpired();
    const advice=snapshot.advice,notes=advice?.status==='succeeded'?advice.analysis:null;
    const warning=w=>w.kind==='progress'?'进度落后 ≥15p':({revenue_usd:'营收',orders:'订单',estimated_profit_usd:'预估利润'}[w.metric]||'指标')+'线性预测低于目标';
    panel.innerHTML='<h2>每日目标分析 · '+esc(statuses[state]||state)+'</h2><p class="note">每日 00:20 · 更新 '+esc(snapshot.generatedAt)+' · 实际截至 '+esc(snapshot.period.end||'尚无完整日')+(stale?' · 保留上版或历史区间':'')+'</p><p class="fs-daily-summary"><b>本版经营建议：</b>'+esc(canForecast?notes?.summary||'AI 建议暂不可用；实际完成率与程序预测可展开查看。':'目标期不匹配，未套用旧建议')+'</p><p class="note">AI '+esc(advice?.status||'not_requested')+(advice?.error?' · '+esc(advice.error):'')+' · 最近尝试 '+esc(lastAt)+' · '+esc(lastState)+(dailyStatus?.error_code?' · '+esc(dailyStatus.error_code):'')+'</p>'+
      '<details id="fs-daily-details"'+(expanded?' open':'')+'><summary>查看 '+list.length+' 个项目的完成率、剩余日均、预测与建议</summary><p class="note">完成率与线性预测为程序计算；AI 只提供定性建议，不修改目标。实际区间 '+esc(snapshot.period.start)+' 至 '+esc(snapshot.period.end||'尚无完整日')+'。</p><p class="note">线性月末预测 = 累计实际 ÷ 已过完整日 × 目标月份天数；假设未来维持当前日均，不代表承诺。缺失指标不预测，来源统计水位未知时保留提示。</p>'+
      '<div class="board"><table><thead><tr><th>项目 / 负责人</th><th>目标完成率</th><th>剩余所需日均</th><th>月末线性预测</th><th>观察与预警</th><th>AI 定性建议</th></tr></thead><tbody>'+list.map(p=>{
        const g=games().find(g=>g.profile===p.key),forecast=p.forecast||{},vals=canForecast?forecast.values||{}:{},adviceRow=canForecast?notes?.projects?.find(x=>x.key===p.key):null,alerts=canForecast&&Array.isArray(p.warnings)?p.warnings:[];
        const completion=canForecast?p.completionPct||{}:{},required=canForecast?p.requiredDaily||{}:{};
        return '<tr><td><a href="'+esc(g.file)+'">'+esc(g.name)+'</a><div class="note">'+esc(g.owner)+' · '+esc(p.coverage?.status||'未提供')+'</div></td><td>收入 '+pct(completion.revenue_usd)+'<br>订单 '+pct(completion.orders)+'<br>预估利润 '+pct(completion.estimated_profit_usd)+'</td><td>收入 '+fmt(required.revenue_usd)+'<br>订单 '+fmt(required.orders,'ord')+'<br>预估利润 '+fmt(required.estimated_profit_usd,'prof')+'</td><td>收入 '+fmt(vals.revenue_usd)+'<br>订单 '+fmt(vals.orders,'ord')+'<br>预估利润 '+fmt(vals.estimated_profit_usd,'prof')+'</td><td>'+esc(forecast.observedCompleteDays??'—')+'/'+esc(forecast.monthDays??'—')+' 个完整日<br>'+esc(alerts.length?alerts.map(warning).join('；'):numeric(vals.revenue_usd)?'未触发进度/预测预警':'未评估')+'<div class="note">'+(p.coverage?.sourceWatermarkKnown?'有上游统计水位':'上游统计水位未提供')+'</div></td><td>'+esc(adviceRow?.advice||'AI 尚未成功返回或目标期不匹配；不套用旧建议')+'</td></tr>';
      }).join('')+'</tbody></table></div>'+(advice?.receipt?'<p class="note">AI 回执 '+esc(advice.receipt)+'</p>':'')+'</details>';
  }
  function activateDaily(data){
    dailySnapshot=data;query={...data.period};$('fs-start').value=query.start;$('fs-end').value=query.end||'';
    values={};details={};
    for(const p of data.projects){
      const native=p.sources?.Admin?.nativeMetrics||{},reference=p.sources?.Order?.referenceMetrics||{},n=k=>numeric(native[k])?native[k]:null;
      values[p.key]={...empty(),rev:p.actuals.revenue_usd,ord:p.actuals.orders,prof:p.actuals.estimated_profit_usd,new:n('newCustomers'),aov:numeric(p.actuals.revenue_usd)&&numeric(p.actuals.orders)&&p.actuals.orders>0?Math.round(p.actuals.revenue_usd*100/p.actuals.orders)/100:null,rep:n('repeatRatePct'),ful:n('fulfillmentRatePct'),mar:numeric(reference.profitMarginPct)?reference.profitMarginPct:null};
      details[p.key]={label:'每日结果 · '+(p.coverage?.status||'未提供'),source:'Admin 读取 '+(p.sources?.Admin?.capturedAt||'未提供')+' / Order 读取 '+(p.sources?.Order?.capturedAt||'未提供')};
    }
  }
  async function loadDaily(quiet=false){
    if(!identity||(quiet&&(busy||aiBusy)))return;
    controller.abort();controller=new AbortController();const signal=controller.signal,token=++generation;
    viewMode='daily';busy=true;aiButtons();$('fs-refresh').disabled=true;
    if(!quiet)status('正在读取服务器每日目标分析…');
    try{
      await verify();
      const results=await Promise.allSettled([read('/dashboard/management/daily.json',signal),read('/dashboard/management/daily.status.json',signal)]);
      if(token!==generation||!identity)return;
      if(results[1].status==='fulfilled'&&results[1].value.ok){dailyStatus=await results[1].value.json();if(token!==generation)return;}
      if(results[0].status!=='fulfilled'||!results[0].value.ok)throw Error('每日结果尚不可用');
      const data=await results[0].value.json();if(token!==generation)return;
      if(!Management.validateDaily(data,config))throw Error('每日结果合同或目标不匹配');
      activateDaily(data);
      render();status('每日目标分析 · 生成 '+data.generatedAt+' · 最近尝试与失败状态见上方 · 可人工选择日期只读查询。');
    }catch(e){if(token===generation&&identity){if(dailySnapshot)activateDaily(dailySnapshot);else{values={};details={};}render();status(e.message+'；'+(dailySnapshot?'保留上一版及其原日期。':'尚无每日结果，可人工查询 FS 实际。'));}}
    finally{if(token===generation){busy=false;if(identity){$('fs-refresh').disabled=false;aiButtons();loadWeeks();}}}
  }
  function consume(data){
    const p=data.profile,numbers=Management.actuals(data),stale=data.stale||data.status==='stale';
    return {numbers,label:stale?'缓存已过期，实际暂不展示':'FS 已返回 · 缺项不填零',source:'Admin 读取 '+(p.supplement?.capturedAt||'未提供')+' / Order 读取 '+(p.primary?.capturedAt||'未提供')+'；上游统计水位 '+(data.sources?.Admin?.sourceDataAsOf||'未提供')};
  }

  async function load(){
    if(!identity)return;
    const start=$('fs-start').value,end=$('fs-end').value;
    controller.abort();controller=new AbortController();const signal=controller.signal;
    const token=++generation;busy=false;viewMode='manual';
    if(!/^\d{4}-\d{2}-\d{2}$/.test(start)||!/^\d{4}-\d{2}-\d{2}$/.test(end)||start>end||end>=day()){
      for(const key of Object.keys(details))if(!values[key])details[key]={label:'查询已取消，等待有效日期',source:'未填零'};
      $('fs-refresh').disabled=false;aiButtons();render();status('查询已取消。请选择开始日不晚于结束日、且截至昨日的完整日区间；已有值仍标记上一有效查询日期。');return;
    }
    query={start,end};weekKey='';weekController.abort();weekValues={};values={};details={};busy=true;$('fs-refresh').disabled=true;aiButtons();
    if(aiJob)$('fs-ai-result').textContent='原 AI 任务 '+aiJob.jobId+' 已保留；可点击查询已有任务。';
    render();
    try{
      await verify();const r=await read('/dashboard/fs-home/range.json?mode=catalog',signal);if(!r.ok)throw Error('无法读取 FS 目录');const data=await r.json();if(token!==generation)return;catalog=catalogProfiles(data);
      const list=view==='game'?games().filter(g=>g.profile===document.body.dataset.profile):games();let completed=0;
      const progress=()=>status('FS 查询 '+query.start+' 至 '+query.end+' · 已完成 '+completed+'/'+list.length+' · 营收可用 '+list.filter(g=>numeric(actual(g).rev)).length+'/'+list.length+' · 最多同时读取 2 款');
      await Management.runTwo(list,async g=>{
        if(token!==generation||!identity||signal.aborted)return;
        if(!catalog.has(g.profile)){details[g.profile]={label:'FS 当前目录未支持，未请求',source:'目录无此 profile'};completed++;render();progress();return;}
        details[g.profile]={label:'正在读取；排队时跟进同一查询',source:'等待 FS'};render();progress();
        try{
          const result=await Management.pollSummary({read,profile:g.profile,query:{start,end},signal,update(data,phase){
            if(token!==generation||!identity)return;
            if(data){const result=consume(data);values[g.profile]=result.numbers;details[g.profile]={label:result.label,source:result.source};}
            else if(!values[g.profile])details[g.profile]={label:'FS 排队中；跟进同一查询',source:'尚未返回实际'};
            render();progress();
          }});
          if(token!==generation)return;
          if(result.timedOut){const previous=details[g.profile];details[g.profile]={label:'本次等待已满；部分或全部指标仍待 FS 返回',source:previous?.source||'尚未完成读取'};}
        }catch(e){if(token!==generation)return;details[g.profile]={label:values[g.profile]?'已有部分返回，后续查询失败':'读取失败，未填零',source:e.message};}
        if(token!==generation)return;completed++;render();progress();
      });
      if(token===generation)status('查询完成 · '+query.start+' 至 '+query.end+' · 营收可用 '+list.filter(g=>numeric(actual(g).rev)).length+'/'+list.length+' 款。缺失项保留待返回状态，可稍后重查。');
    }catch(e){if(token===generation)status(e.message+'；未填零。');}
    finally{if(token===generation){busy=false;if(identity){$('fs-refresh').disabled=false;aiButtons();loadWeeks();}}}
  }
  async function loadWeeks(){
    if(view!=='game'||!identity||busy)return;
    const model=config.models[document.body.dataset.profile],key=JSON.stringify([identity,model.slug,config.period,query.start,query.end]);
    if(weekKey===key)return;
    weekController.abort();weekController=new AbortController();const signal=weekController.signal;weekKey=key;weekValues={};
    const periods=Management.weekPeriods(model,config.period,query);
    for(const p of periods)weekValues[p.id]={period:p,numbers:empty(),label:p.eligible?'正在读取准确周区间':'尚无所选完整日；未填零'};
    game();
    try{
      const r=await read('/dashboard/fs-home/range.json?mode=catalog',signal);if(!r.ok)throw Error('FS 目录暂不可用');
      const supported=catalogProfiles(await r.json());if(!supported.has(model.slug))throw Error('FS 目录未支持本项目');
      await Management.runTwo(periods.filter(p=>p.eligible),async p=>{
        if(signal.aborted||weekKey!==key)return;
        try{
          const result=await Management.pollSummary({read,profile:model.slug,query:{start:p.start,end:p.end},signal,update(data){
            if(signal.aborted||weekKey!==key)return;
            if(data){const value=consume(data);weekValues[p.id]={period:p,numbers:value.numbers,label:value.label+' · '+value.source};}
            game();
          }});
          if(!signal.aborted&&weekKey===key&&result.timedOut)weekValues[p.id].label+=' · 等待已满，可重查所选日期';
        }catch(e){if(!signal.aborted&&weekKey===key)weekValues[p.id].label='周实际读取失败；未填零';}
        if(!signal.aborted&&weekKey===key)game();
      });
    }catch(e){if(!signal.aborted&&weekKey===key){for(const p of periods.filter(p=>p.eligible))weekValues[p.id].label=e.message+'；未填零';game();}}
  }
  try{
    await verify();const r=await read('targets.json');if(!r.ok)throw Error('目标资料加载失败');config=await r.json();controls();
    if(view==='sandbox')sandbox=window.createManagementSandbox(config.sandbox,identity);
    if(view==='overview'){
      $('grpTab').onclick=e=>{const b=e.target.closest('button');if(b){group=b.dataset.g;overview();}};
      $('seg').onclick=e=>{const b=e.target.closest('button');if(b){metric=b.dataset.k;$('seg').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));overview();}};
    }
    render();await loadDaily();
  }catch(e){if(identity)status(e.message+'；未展示旧实际数据。');else status('请通过 FS 登录后进入经营管理台。');}
  const timer=setInterval(()=>{if(!document.hidden&&identity)verify().then(()=>{if(viewMode==='daily')loadDaily(true);}).catch(()=>{if(identity)halt('无法重新验证会话');});},60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&identity)verify().catch(()=>{if(identity)halt('无法重新验证会话');});});
  addEventListener('pagehide',()=>{clearInterval(timer);controller.abort();weekController.abort();});
  addEventListener('pageshow',e=>{if(e.persisted)location.reload();});
})();
