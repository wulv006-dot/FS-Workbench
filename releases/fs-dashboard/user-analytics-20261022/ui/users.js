const el=id=>document.getElementById(id);
const statuses={available:'完整',partial:'部分覆盖',pending:'回补中',insufficient_history:'历史不足',not_mature:'观察中',unavailable:'待读取'};
const labels={purchasers:'区间购买客户',first_purchasers:'已确认首次购买',old_purchasers:'已确认老客购买',first_unverified:'首购身份待确认',silent_wakeup:'沉默唤醒客户',lost_return:'流失回流客户',recent:'近期购买',silent:'沉默期',lost:'流失期',long_lost:'长期流失',unverified:'状态待核'};
let catalog,snapshot,controller,serial=0,group='',cursor='',privateRequest=0;
const value=v=>v===null||v===undefined?'待读取':Number(v).toLocaleString('zh-CN');
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
  const wrap=document.createElement('div');wrap.className='table-wrap';const t=document.createElement('table'),head=t.createTHead().insertRow();
  columns.forEach(c=>{const th=document.createElement('th');th.scope='col';th.textContent=c[0];head.append(th);});
  const body=t.createTBody();rows.forEach(row=>{const tr=body.insertRow();columns.forEach(c=>{const td=tr.insertCell();td.textContent=String(c[1](row)??'待读取');});});
  wrap.append(t);el(id).replaceChildren(wrap);
}
function cards(id,keys){
  el(id).replaceChildren(...keys.map(key=>{const data=snapshot.metrics[key],b=document.createElement('button');b.className='metric';b.type='button';
    const label=document.createElement('span'),number=document.createElement('strong'),note=document.createElement('small');label.textContent=labels[key];number.textContent=value(data.value);note.textContent=(statuses[data.status]||data.status)+(data.reason?' · '+data.reason:'');
    b.append(label,number,note);b.disabled=data.value===null;b.addEventListener('click',()=>members(key));return b;}));
}
function scopeOptions(){
  const f=el('filters'),kind=f.elements.scope.value,select=f.elements.scope_id;select.replaceChildren();select.disabled=kind==='global';
  let options=kind==='global'?[['','全部已接入']]:kind==='site'?catalog.sites.map(s=>[s.id,s.label]):kind==='project'?Object.entries(catalog.projects).map(([id,p])=>[id,p.label]):[...new Set(Object.values(catalog.projects).map(p=>p.series).filter(Boolean))].map(s=>[s,s]);
  options.forEach(([id,label])=>select.add(new Option(label,id)));
  if(kind==='project')f.elements.policy_version.value=select.value==='1327'?'fc-v1':'common-v1';
}
function render(){
  el('result').hidden=false;el('private').hidden=true;group='';cursor='';privateRequest++;
  cards('interval',['purchasers','first_purchasers','old_purchasers','first_unverified','silent_wakeup','lost_return']);
  cards('stock',['recent','silent','lost','long_lost','unverified']);
  text('coverage',`${snapshot.full_company_coverage?'公司经营范围':'当前已接入范围'} · 站点 ${snapshot.coverage.sites.join(' / ')} · ${snapshot.coverage.period_complete?'区间订单已覆盖':'区间仍有覆盖缺口'} · 无法识别身份的订单 ${snapshot.coverage.missing_identity_orders} 笔。`);
  text('freshness',`统计截至 ${snapshot.query.as_of} · 最近来源读取 ${snapshot.captured_at||'待读取'}`);
  text('observation',`观察日 ${snapshot.observation_date}，仅包含截止前的有效购买。阶段人数代表已覆盖客户池。`);
  text('versions',JSON.stringify({snapshot_id:snapshot.snapshot_id,evidence_id:snapshot.evidence_id,query:snapshot.query,coverage:snapshot.coverage,data_version:snapshot.data_version},null,2));
  table('trend',[['日期',r=>r.day],['购买客户',r=>value(r.purchasers)],['进入流失',r=>value(r.entered_lost)],['流失回流',r=>value(r.lost_return)],['覆盖',r=>statuses[r.status]]],snapshot.trend);
  const c=snapshot.cohort;text('cohort',`${c.H||snapshot.query.H} 天内二购：${c.rate==null?statuses[c.status]:(c.rate*100).toFixed(1)+'%'} · 成熟分母 ${value(c.denominator)} · 已二购 ${value(c.numerator)} · 观察中 ${value(c.observing)} · 首购待核 ${value(c.first_unverified)}`);
  el('project-table').replaceChildren();el('migration').replaceChildren();text('project-status','');
}
async function query(event){
  event?.preventDefault();controller?.abort();controller=new AbortController();const version=++serial;const f=el('filters');
  const args={scope:f.elements.scope.value,scope_id:f.elements.scope_id.value,start:f.elements.start.value,end_exclusive:addDay(f.elements.end.value,1),policy_version:f.elements.policy_version.value,policy_mode:f.elements.policy_mode.value,H:f.elements.H.value};
  text('status','正在读取同一范围的快照…');
  try{const data=await read(args,'data.json',controller.signal);if(version!==serial)return;snapshot=data;render();text('status',`快照已读取 · ${statuses[data.status]}`);}
  catch(error){if(error.name==='AbortError'||version!==serial)return;text('status',error.message+(snapshot?'；保留上次完整快照及其原范围。':''));}
}
async function members(key,next=false){
  if(!snapshot)return;const current=snapshot.snapshot_id;const request=++privateRequest;group=key;el('private').hidden=false;text('private-status','正在核验管理员权限…');
  try{const data=await read({snapshot_id:current,group:key,...(next?{cursor}: {})},'private.json');if(snapshot.snapshot_id!==current||request!==privateRequest)return;
    cursor=data.next_cursor||'';text('private-status',`${labels[key]||key} · 同版总人数 ${data.total}`);table('members',[['脱敏客户',r=>r.customer_id],['真实首购',r=>r.first_paid_at||'待确认'],['已观察最早购买',r=>r.earliest_observed_at],['末购',r=>r.last_paid_at],['阶段',r=>labels[r.stage]],['距末购天数',r=>r.days_since_last],['区间订单',r=>r.period_orders]],data.rows);el('next').hidden=!cursor;el('export').hidden=false;
  }catch(error){if(request!==privateRequest)return;text('private-status',error.message);el('members').replaceChildren();el('next').hidden=true;el('export').hidden=true;}
}
el('filters').addEventListener('submit',query);el('refresh').addEventListener('click',query);
el('filters').elements.scope.addEventListener('change',scopeOptions);
el('next').addEventListener('click',()=>members(group,true));
el('projects').addEventListener('click',async()=>{if(!snapshot)return;const current=snapshot.snapshot_id;const args={...snapshot.query,view:'projects'};text('project-status','读取同一范围和截止的项目比较…');
  try{const data=await read(args);if(snapshot.snapshot_id!==current)return;if(data.data_version!==snapshot.data_version){text('project-status','数据版本已更新，请刷新整页后读取。');return;}
    table('project-table',[['项目',r=>r.label],['规则',r=>r.policy_version],['购买客户',r=>value(r.metrics.purchasers.value)],['已确认首购',r=>value(r.metrics.first_purchasers.value)],['全站老客转入',r=>value(r.acquisition.existing_global)],['长期流失',r=>value(r.metrics.long_lost.value)],['覆盖',r=>statuses[r.metrics.purchasers.status]]],data.projects);
    const rows=data.migration.flatMap(p=>p.states.map(s=>({...s,project:p.project_id})));table('migration',[['项目',r=>r.project],['项目状态',r=>labels[r.project_stage]],['整体状态',r=>labels[r.global_stage]],['人数',r=>r.count]],rows);text('project-status','项目与整体状态使用各自规则；目的项目分布可能重叠。');
  }catch(error){if(snapshot.snapshot_id===current)text('project-status',error.message);}
});
el('export').addEventListener('click',async()=>{const current=snapshot.snapshot_id,selected=group;try{const data=await read({action:'export',snapshot_id:current,group:selected},'private.json');if(snapshot.snapshot_id!==current||group!==selected)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='FS-users-'+current+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){text('private-status',error.message);}});
el('hermes').addEventListener('click',async()=>{try{await navigator.clipboard.writeText('请调用用户分析工具读取此冻结快照，并给出变化、支持证据、替代解释、缺口、负责人行动及复查指标和日期：'+JSON.stringify({snapshot_id:snapshot.snapshot_id,evidence_id:snapshot.evidence_id,query:snapshot.query}));text('handoff-status','当前证据指令已复制，等待你在 Hermes 中提交。');}catch{text('handoff-status','复制失败，请从当前口径详情取得快照编号。');}});
el('theme').addEventListener('change',event=>{if(window.FSTheme?.set)window.FSTheme.set(event.target.value);});
async function init(){try{catalog=await read({action:'catalog'});scopeOptions();const today=localDay(new Date());el('filters').elements.start.value=addDay(today,-30);el('filters').elements.end.value=addDay(today,-1);await query();}catch(error){text('status',error.message);}}
init();
