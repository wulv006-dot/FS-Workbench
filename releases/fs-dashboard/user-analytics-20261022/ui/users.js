const el=id=>document.getElementById(id);
const statuses={available:'完整',partial:'部分覆盖',pending:'回补中',insufficient_history:'历史不足',not_mature:'观察中',unavailable:'待读取'};
const labels={purchasers:'区间购买客户',first_purchasers:'已确认首次购买',old_purchasers:'已确认老客购买',first_unverified:'首购身份待确认',silent_wakeup:'沉默唤醒客户',lost_return:'流失回流客户',recent:'近期购买',silent:'沉默期',lost:'流失期',long_lost:'长期流失',unverified:'状态待核'};
Object.assign(labels,{high_value_entered_silent:'高价值且刚进入沉默',first_without_repeat:'已确认首购后尚未二购'});
let catalog,snapshot,controller,serial=0,group='',cursor='',privateRequest=0;
const value=v=>v===null||v===undefined?'待读取':Number(v).toLocaleString('zh-CN');
const time=s=>s?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'}).format(new Date(s)):'待读取';
const text=(id,t)=>{el(id).textContent=t;};
const localDay=d=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
const addDay=(s,n)=>{const d=new Date(s+'T00:00:00+08:00');d.setUTCDate(d.getUTCDate()+n);return localDay(d);};
async function read(params,path='data.json',signal){
  const response=await fetch('./'+path+'?'+new URLSearchParams(params),{credentials:'same-origin',cache:'no-store',signal});
  if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('登录状态或接口不可用');
  const data=await response.json();
  if(!response.ok)throw new Error(response.status===403?'当前账号无此范围或客户明细权限':response.status===401?'登录已过期':data.error||'查询失败');
  return data;
}
function table(id,columns,rows){
  const wrap=document.createElement('div');wrap.className='table-wrap';wrap.tabIndex=0;wrap.setAttribute('role','region');const t=document.createElement('table');const caption=t.createCaption();caption.textContent=el(id).closest('section,dialog')?.querySelector('h2')?.textContent||'当前快照数据';wrap.setAttribute('aria-label',caption.textContent);const head=t.createTHead().insertRow();
  columns.forEach(c=>{const th=document.createElement('th');th.scope='col';th.textContent=c[0];head.append(th);});
  const body=t.createTBody();rows.forEach(row=>{const tr=body.insertRow();columns.forEach(c=>{const td=tr.insertCell(),content=c[1](row);if(content instanceof Node)td.append(content);else td.textContent=String(content??'待读取');});});
  wrap.append(t);el(id).replaceChildren(wrap);
}
function cards(id,keys){
  el(id).replaceChildren(...keys.map(key=>{const data=snapshot.metrics[key],b=document.createElement(catalog.can_read_private?'button':'article');b.className='metric';if(catalog.can_read_private)b.type='button';
    const label=document.createElement('span'),number=document.createElement('strong'),note=document.createElement('small');label.textContent=labels[key];number.textContent=value(data.value);note.textContent=(statuses[data.status]||data.status)+(data.events!==undefined?' · '+data.events+'次事件':'')+(data.reason?' · '+data.reason:'');
    b.append(label,number,note);if(catalog.can_read_private){b.disabled=data.value===null;b.addEventListener('click',()=>members(key));}return b;}));
}
function svgNode(name,attributes={},content){const node=document.createElementNS('http://www.w3.org/2000/svg',name);Object.entries(attributes).forEach(([key,v])=>node.setAttribute(key,v));if(content!==undefined)node.textContent=content;return node;}
function charts(){
  const rows=snapshot.trend,colors={purchasers:'var(--fs-brand)',first_purchasers:'var(--fs-info)',lost_return:'var(--fs-violet)',recent:'var(--fs-brand)',silent:'var(--fs-warn)',lost:'var(--fs-danger)',long_lost:'var(--fs-violet)',unverified:'var(--fs-muted)'};
  for(const [id,stock] of [['trend-chart',false],['stock-chart',true]]){
    const keys=stock?['recent','silent','lost','long_lost','unverified']:['purchasers','first_purchasers','lost_return'];
    const available=rows.some(r=>stock?r.stock&&r.status==='available':r.status==='available');
    if(!available){el(id).textContent='该区间暂无可绘制的完整数据；请查看覆盖说明。';continue;}
    const max=Math.max(1,...rows.map(r=>stock?Object.values(r.stock||{}).reduce((a,b)=>a+b,0):Math.max(0,...keys.map(k=>r.status==='available'?(r[k]||0):0))));
    const svg=svgNode('svg',{viewBox:'0 0 1000 270',class:'chart',role:'img'});svg.append(svgNode('title',{},stock?'每日已覆盖客户池的阶段存量':'每日购买、确认首购与回流趋势'));
    for(let i=0;i<=4;i++){const y=220-i*47.5;svg.append(svgNode('line',{x1:55,x2:980,y1:y,y2:y}),svgNode('text',{x:48,y:y+4,'text-anchor':'end'},Math.round(max*i/4)));}
    if(stock){rows.forEach((row,i)=>{let total=0;const width=910/rows.length;keys.forEach(key=>{const count=row.stock?.[key]||0,height=count/max*190;const rect=svgNode('rect',{x:56+i*width,y:220-(total+count)/max*190,width:Math.max(1,width-2),height,fill:colors[key]});rect.append(svgNode('title',{},`${row.day} ${labels[key]} ${count}人`));svg.append(rect);total+=count;});});}
    else keys.forEach(key=>{let points=[];const flush=()=>{if(points.length)svg.append(svgNode('polyline',{points:points.join(' '),class:key}));points=[];};rows.forEach((row,i)=>{if(row.status!=='available'||row[key]===null||row[key]===undefined){flush();return;}const x=55+i*925/Math.max(1,rows.length-1),y=220-row[key]/max*190;points.push(`${x},${y}`);const circle=svgNode('circle',{cx:x,cy:y,r:3,fill:colors[key]});circle.append(svgNode('title',{},`${row.day} ${labels[key]} ${row[key]}人`));svg.append(circle);});flush();});
    if(rows.length){svg.append(svgNode('text',{x:55,y:250},rows[0].day),svgNode('text',{x:980,y:250,'text-anchor':'end'},rows.at(-1).day));}
    const legend=document.createElement('div');legend.className='chart-legend';keys.forEach(key=>{const item=document.createElement('span');item.style.setProperty('--series-color',colors[key]);item.textContent=labels[key]||key;legend.append(item);});el(id).replaceChildren(svg,legend);
  }
}
function scopeOptions(){
  const f=el('filters'),kind=f.elements.scope.value,select=f.elements.scope_id;select.replaceChildren();select.disabled=kind==='global';
  let options=kind==='global'?[['','全部已接入']]:kind==='site'?catalog.sites.map(s=>[s.id,s.label]):kind==='project'?Object.entries(catalog.projects).map(([id,p])=>[id,p.label]):[...new Set(Object.values(catalog.projects).map(p=>p.series).filter(Boolean))].map(s=>[s,s]);
  options.forEach(([id,label])=>select.add(new Option(label,id)));
  f.elements.policy_version.value=kind==='project'&&catalog.projects[select.value]?.series==='FC'||kind==='series'&&select.value==='FC'?'fc-v1':'common-v1';
}
function render(){
  el('result').hidden=false;el('private').hidden=true;group='';cursor='';privateRequest++;
  cards('interval',['purchasers','first_purchasers','old_purchasers','first_unverified','silent_wakeup','lost_return']);
  cards('interval-extra',['repeat_purchasers','entered_silent','entered_lost','entered_long_lost']);
  cards('stock',['recent','silent','lost','long_lost','unverified']);
  const q=snapshot.query,scope=q.scope==='project'?catalog.projects[q.scope_id]?.label||q.scope_id:q.scope==='site'?catalog.sites.find(s=>s.id===q.scope_id)?.label||q.scope_id:q.scope==='series'?q.scope_id:'已接入整体';
  text('coverage',`当前结果：${scope} · ${snapshot.full_company_coverage?'公司经营范围':'已接入范围'} · 站点 ${snapshot.coverage.sites.join(' / ')} · ${snapshot.coverage.period_complete?'区间订单已覆盖':'区间仍有覆盖缺口'} · 无法识别身份的订单 ${snapshot.coverage.missing_identity_orders} 笔。`);
  text('freshness',`北京时间 ${time(q.start)} 至 ${time(q.end_exclusive)}（截止不含） · 最近来源读取 ${time(snapshot.captured_at)}`);
  text('stock-title',q.state_basis==='current'?'今天，全部已覆盖客户处于什么阶段':'历史回看：截至期末的客户阶段');
  const coverage=snapshot.coverage;
  const window=coverage.history_window,target=coverage.backfill_target_start;
  const historyNote=window?`已补齐 ${window.start.slice(0,10)} 起至 ${window.end_exclusive.slice(0,10)} 的完整日订单；更早未纳入，真实首购仍可能待确认。`:`${target?'本轮只补到 '+target.slice(0,10)+'；':''}回补尚未完成，人数仍是部分客户池。`;
  text('observation',`观察日 ${snapshot.observation_date} · 按已确认邮箱一人一档，共 ${value(snapshot.metrics.known_pool.value)} 人。实际覆盖起点 ${time(coverage.covered_history_start)}，订单读至 ${time(coverage.state_data_through)}。${historyNote}${coverage.backfill?` 回补：${coverage.backfill.status==='complete'?'本轮范围完成':coverage.backfill.status==='running'?'进行中':coverage.backfill.status==='failed'?'失败待核对':'等待核对'}。`:''}`);
  table('trajectories',[['当前阶段',r=>labels[r.stage]],['所选期间的经历',r=>r.label],['人数',r=>{if(!catalog.can_read_private)return value(r.count);const b=document.createElement('button');b.type='button';b.textContent=value(r.count)+' 人 · '+labels[r.stage]+' / '+r.label;b.addEventListener('click',()=>members(r.group));return b;}]],snapshot.trajectories||[]);
  text('versions',JSON.stringify({snapshot_id:snapshot.snapshot_id,evidence_id:snapshot.evidence_id,query:snapshot.query,coverage:snapshot.coverage,data_version:snapshot.data_version},null,2));
  table('trend',[['日期',r=>r.day],['购买客户',r=>value(r.purchasers)],['确认首购',r=>value(r.first_purchasers)],['进入流失',r=>value(r.entered_lost)],['流失回流',r=>value(r.lost_return)],...['recent','silent','lost','long_lost','unverified'].map(key=>[labels[key],r=>value(r.stock?.[key])]),['覆盖',r=>statuses[r.status]]],snapshot.trend);charts();
  const c=snapshot.cohort;text('cohort',`${c.H||snapshot.query.H} 天内二购：${c.rate==null?statuses[c.status]:(c.rate*100).toFixed(1)+'%'} · 成熟分母 ${value(c.denominator)} · 已二购 ${value(c.numerator)} · 观察中 ${value(c.observing)} · 首购待核 ${value(c.first_unverified)}`);
  table('cohort-weeks',[['首购入组周',r=>r.start.slice(0,10)],['成熟分母',r=>r.denominator],['已二购',r=>r.numerator],['二购率',r=>r.rate===null?statuses[r.status]:(r.rate*100).toFixed(1)+'%'],['观察中',r=>r.observing],['首购待核',r=>r.first_unverified],['覆盖不足',r=>r.coverage_gap]],snapshot.cohort_weeks||[]);
  el('project-table').replaceChildren();el('migration').replaceChildren();text('project-status','');
  el('segments').hidden=!catalog.can_read_private;el('hermes-panel').hidden=!catalog.can_read_private;
  if(el('customer-detail').open)el('customer-detail').close();
}
async function query(event){
  event?.preventDefault();controller?.abort();controller=new AbortController();const version=++serial;const f=el('filters');
  const args={scope:f.elements.scope.value,scope_id:f.elements.scope_id.value,state_basis:f.elements.state_basis.value,start:f.elements.start.value,end_exclusive:addDay(f.elements.end.value,1),policy_version:f.elements.policy_version.value,policy_mode:f.elements.policy_mode.value,H:f.elements.H.value};
  text('status','正在读取同一范围的快照…');
  try{const data=await read(args,'data.json',controller.signal);if(version!==serial)return;snapshot=data;render();text('status',`快照已读取 · ${data.coverage.history_window?data.coverage.history_window.start.slice(0,10)+'起已覆盖 · '+statuses[data.status]:data.coverage.historical_origin?statuses[data.status]:'回补中 · 部分客户池'}`);}
  catch(error){if(error.name==='AbortError'||version!==serial)return;text('status',error.message+(snapshot?'；保留上次完整快照及其原范围。':''));}
}
async function members(key,next=false){
  if(!snapshot)return;const current=snapshot.snapshot_id;const request=++privateRequest;group=key;el('private').hidden=false;text('private-status','正在核验管理员权限…');
  const base=key.split('__')[0],paths=(snapshot.trajectories||[]).filter(r=>r.stage===base),select=el('path-filter');
  if(!next){select.replaceChildren(new Option('全部 '+(labels[base]||base),base));paths.forEach(r=>select.add(new Option(r.label+' · '+value(r.count)+' 人',r.group)));select.value=key;select.disabled=!paths.length;}
  try{const data=await read({snapshot_id:current,group:key,...(next?{cursor}: {})},'private.json');if(snapshot.snapshot_id!==current||request!==privateRequest)return;
    cursor=data.next_cursor||'';text('private-status',`${labels[base]||base}${paths.find(r=>r.group===key)?" / "+paths.find(r=>r.group===key).label:""} · 同版总人数 ${data.total}`);table('members',[['脱敏客户',r=>r.customer_id.slice(-12)],['首次购买 D0',r=>r.first_paid_at||'历史未齐，待确认'],['已观察最早购买',r=>r.earliest_observed_at],['末购',r=>r.last_paid_at],['整体末购',r=>r.global_last_paid_at],['阶段',r=>labels[r.stage]],['距末购天数',r=>r.days_since_last],['期间经历',r=>r.period_path_label],['区间订单',r=>r.period_orders],['已覆盖历史订单',r=>r.covered_history_orders],['区间整单USD',r=>'$'+r.period_sales_usd+(r.period_amount_complete?'':'（部分覆盖）')],['私有核对',r=>{const b=document.createElement('button');b.type='button';b.textContent='查看购买与沉睡时间线';b.addEventListener('click',()=>detail(r.customer_id,current));return b;}]],data.rows);el('next').hidden=!cursor;el('export').hidden=false;
  }catch(error){if(request!==privateRequest)return;text('private-status',error.message);el('members').replaceChildren();el('next').hidden=true;el('export').hidden=true;}
}
async function detail(customer,current){
  try{const data=await read({action:'detail',snapshot_id:current,customer_id:customer},'private.json');if(snapshot.snapshot_id!==current)return;text('detail-email',data.email);text('detail-note',data.note);const kinds={first_purchase:'首次观察到购买',repeat_purchase:'再次购买',silent_wakeup:'沉默后唤醒',lost_return:'流失后回流',enter:'进入阶段'};table('detail-timeline',[['时间',r=>time(r.at)],['经历',r=>kinds[r.kind]],['阶段',r=>labels[r.stage]],['第几天（从最早已覆盖购买起算）',r=>r.days_from_observed_first==null?'待核对':r.days_from_observed_first+' 天']],data.timeline||[]);table('detail-orders',[['原单',r=>r.order_no],['站点',r=>r.site],['项目',r=>catalog.projects[r.project_id]?.label||r.project_id],['付款时间',r=>r.paid_at],['原状态',r=>r.status_format||r.status],['有效购买',r=>r.valid?'是':'否'],['整单USD',r=>r.amount_usd==null?'待读取':'$'+r.amount_usd]],data.orders);el('customer-detail').showModal();}
  catch(error){text('private-status',error.message);}
}
el('customer-detail').addEventListener('close',()=>{text('detail-email','');el('detail-orders').replaceChildren();el('detail-timeline').replaceChildren();});
document.querySelectorAll('[data-group]').forEach(button=>button.addEventListener('click',()=>members(button.dataset.group)));
el('filters').addEventListener('submit',query);el('refresh').addEventListener('click',query);
el('filters').elements.scope.addEventListener('change',scopeOptions);
el('filters').elements.scope_id.addEventListener('change',()=>{const f=el('filters');f.elements.policy_version.value=f.elements.scope.value==='project'&&catalog.projects[f.elements.scope_id.value]?.series==='FC'||f.elements.scope.value==='series'&&f.elements.scope_id.value==='FC'?'fc-v1':'common-v1';});
el('path-filter').addEventListener('change',event=>members(event.target.value));
el('next').addEventListener('click',()=>members(group,true));
el('projects').addEventListener('click',()=>{if(!snapshot)return;const data=snapshot;if(!data.projects){text('project-status','当前账号或该快照未包含整体比较权限。');return;}
    const metricText=data=>`${value(data.value)}${data.status==='available'?'':` · ${statuses[data.status]||data.status}`}`;
    table('project-table',[['项目',r=>r.label],['规则',r=>r.policy_version],['购买客户',r=>metricText(r.metrics.purchasers)],['已确认首购',r=>metricText(r.metrics.first_purchasers)],['全站老客转入（已确认）',r=>value(r.acquisition.existing_global)],['长期流失',r=>metricText(r.metrics.long_lost)],['区间订单覆盖',r=>statuses[r.metrics.purchasers.status]]],data.projects);
    const rows=data.migration.flatMap(p=>p.states.map(s=>({...s,project:catalog.projects[p.project_id]?.label||p.project_id})));table('migration',[['项目',r=>r.project],['项目状态',r=>labels[r.project_stage]],['整体状态',r=>labels[r.global_stage]],['人数',r=>r.count]],rows);const destinations=data.migration.flatMap(p=>p.destinations.map(d=>({...d,from:catalog.projects[p.project_id]?.label||p.project_id})));table('destinations',[['流失项目',r=>r.from],['本期仍购买的项目',r=>catalog.projects[r.project_id]?.label||r.project_id],['重叠客户数',r=>r.purchasers]],destinations);text('project-status','同一冻结快照；项目与整体状态按所选规则计算。目的项目分布可能重叠，系列历史未齐时不判断完整版本迁移。');
});
el('export').addEventListener('click',async()=>{const current=snapshot.snapshot_id,selected=group;try{const data=await read({action:'export',snapshot_id:current,group:selected},'private.json');if(snapshot.snapshot_id!==current||group!==selected)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='FS-users-'+current+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){text('private-status',error.message);}});
const intentKey='fs-users-hermes-intent';let intent;
try{intent=JSON.parse(sessionStorage.getItem(intentKey)||'null');}catch{}
function keepIntent(){try{sessionStorage.setItem(intentKey,JSON.stringify(intent));return true;}catch{return false;}}
async function conversation(path='',body){const response=await fetch('/api/hermes/conversations'+path,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',headers:body?{'Content-Type':'application/json','X-FS-Advisor-Action':'submit'}:{},body:body?JSON.stringify(body):undefined});if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('会话入口不可用');const data=await response.json();if(!response.ok)throw new Error(data.error||'会话请求失败');return data;}
async function conversationOptions(){if(!catalog.can_read_private)return;try{const data=await conversation();const select=el('hermes-conversation');select.replaceChildren(new Option('选择一个已有会话',''));data.items.forEach(item=>select.add(new Option(item.title,item.conversation_id)));}catch(error){text('handoff-status',error.message);}}
async function reconcileIntent(){if(!intent)return;try{const data=await conversation('/'+encodeURIComponent(intent.conversation_id));const found=data.turns?.find(turn=>turn.text.includes(intent.client_request_id));if(found){intent.state='submitted';keepIntent();text('handoff-status',`原提交已核对 · ${found.state} · 会话 ${intent.conversation_id}`);el('reconcile-handoff').hidden=true;}else{text('handoff-status','尚未找到原请求，提交结果仍待核对；保留原编号，不新建或重发。');}}catch(error){text('handoff-status',error.message+'；原提交仍待核对。');}}
el('reconcile-handoff').addEventListener('click',reconcileIntent);
el('hermes').addEventListener('click',async()=>{const selected=el('hermes-conversation').value;if(!snapshot||!selected){text('handoff-status','先选择一个已有会话。');return;}if(intent?.state==='unknown'){el('reconcile-handoff').hidden=false;await reconcileIntent();return;}if(intent?.snapshot_id===snapshot.snapshot_id&&intent?.conversation_id===selected){text('handoff-status','本快照已提交；可在原会话查看，不重复生成。');return;}
  intent={conversation_id:selected,client_request_id:crypto.randomUUID(),snapshot_id:snapshot.snapshot_id,state:'unknown'};if(!keepIntent()){intent=null;text('handoff-status','浏览器无法保存原请求编号，本次尚未提交；请检查浏览器存储设置。');return;}el('hermes').disabled=true;
  const question='请用用户分析工具读取此冻结快照 '+JSON.stringify({snapshot_id:snapshot.snapshot_id,evidence_id:snapshot.evidence_id,query:snapshot.query})+'，给出变化、支持证据、替代解释、缺口、负责人行动及复查指标和日期。不要重新采集或推算缺失人数，不联系客户、发券或改价。原请求编号：'+intent.client_request_id;
  try{const receipt=await conversation('/'+encodeURIComponent(selected)+'/turns',{text:question,client_request_id:intent.client_request_id});intent.state='submitted';intent.turn_id=receipt.turn_id;keepIntent();text('handoff-status',`已提交原会话 · ${receipt.state} · 请到 Hermes 查看异步结果。`);}
  catch(error){text('handoff-status',error.message+'；提交结果待核对，保留原请求编号。');el('reconcile-handoff').hidden=false;}
  finally{el('hermes').disabled=false;}
});
el('theme').addEventListener('change',event=>{if(window.FSTheme?.set)window.FSTheme.set(event.target.value);});
async function init(){try{catalog=await read({action:'catalog'});Object.entries(catalog.metric_definitions||{}).forEach(([key,definition])=>labels[key]=definition.label);scopeOptions();const today=localDay(new Date());el('filters').elements.start.value=addDay(today,-30);el('filters').elements.end.value=addDay(today,-1);await query();await conversationOptions();if(intent?.state==='unknown'){el('reconcile-handoff').hidden=false;await reconcileIntent();}}catch(error){text('status',error.message);}}
init();
