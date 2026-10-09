'use strict';
const API='/dashboard/tasks/api/green-plan';
const $=id=>document.getElementById(id);
const labels={todo:'计划中',doing:'进行中',blocked:'受阻',review:'待验收',done:'已验收'};
let state=null, editing=null, dirty=false, pending=null, loading=false;
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text??'');if(cls)n.className=cls;return n};
const dateText=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'未记录';
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(state.serverTime)).replaceAll('/','-');
const badge=(text,status)=>node('span',text,'badge '+status);
const completed=t=>t.status==='done';
const late=t=>!completed(t)&&t.end<today();
const soon=t=>!completed(t)&&t.end>=today()&&t.end<=new Date(new Date(today()+'T12:00:00Z').getTime()+7*86400000).toISOString().slice(0,10);
const blocked=t=>t.status==='blocked'||Boolean(t.blocker);
const depsOpen=t=>(t.depends||[]).filter(id=>!state.tasks.find(x=>x.id===id&&completed(x)));
const taskButton=(t,text)=>{const b=node('button',text||t.id);b.type='button';b.addEventListener('click',()=>openTask(t));return b};
function showError(message){$('error').hidden=!message;$('error').textContent=message;}
function signature(data){return JSON.stringify([data.tasks.map(t=>[t.id,t.revision]),data.events.map(e=>e.id),data.capabilities.map(c=>[c.id,c.status,c.detail])]);}
async function request(path,options={}){
 const r=await fetch(API+path,{credentials:'same-origin',cache:'no-store',...options});
 if(r.redirected){const e=new Error('登录已失效，请重新登录FS后核对任务。');e.status=401;throw e}
 let data;try{data=await r.json()}catch{const e=new Error('服务器返回内容无法读取');e.status=r.status;e.unconfirmed=true;throw e}
 if(!r.ok||data.error){const e=new Error(data.error||data.message||('请求失败 HTTP '+r.status));e.status=r.status;throw e}return data;
}
async function load(manual=false){
 if(loading)return;loading=true;
 try{const data=await request('');
 if(!data.tasks||!data.viewer)throw new Error('共享数据结构不完整');
 if($('taskDialog').open&&dirty){pending=data;if(!state||signature(data)!==signature(state))$('updates').hidden=false;}
 else{state=data;pending=null;render();$('updates').hidden=true;if($('taskDialog').open&&editing){const fresh=state.tasks.find(t=>t.id===editing.id);if(fresh&&fresh.revision!==editing.revision)openTask(fresh);}}
 showError('');$('syncText').textContent='共享进展已读取 · '+dateText(data.serverTime)+'（上海） · 每30秒检查变化';
 }catch(e){showError((e.status===401?'登录已失效，请重新登录FS。':e.status===403?'当前账号无权访问绿茵计划。':e.message)+(state?'；页面保留上次已读取数据。':''));$('syncText').textContent='共享数据读取失败';}finally{loading=false;}
}
function setOptions(id,values){
 const select=$(id),value=select.value;while(select.options.length>1)select.remove(1);
 values.forEach(([v,label])=>{const o=node('option',label);o.value=v;select.append(o)});select.value=value;
}
function render(){
 const p=state.project,v=state.viewer,core=state.tasks.filter(t=>t.priority==='P0'),done=core.filter(completed).length;
 $('identity').textContent=v.user+' · '+(v.isAdmin?'管理员':v.role==='editor'?'协作者':'只读');
 $('newTask').hidden=!v.isAdmin;$('release').textContent=p.targetRelease||'待确认';$('acceptance').textContent=p.targetCoreAcceptance||'待确认';
 const percent=core.length?Math.round(done/core.length*100):0;
 $('corePercent').textContent=percent+'%';$('coreProgress').value=percent;$('coreCount').textContent=done+' / '+core.length+' 项已验收 · 完成数量口径';
 $('taskCount').textContent=state.tasks.length;
 setOptions('stream',[...new Set(state.tasks.map(t=>t.stream))].filter(Boolean).map(x=>[x,x]));
 const a=$('assignee').value;$('assignee').replaceChildren(node('option','全部执行人'));$('assignee').options[0].value='';
 const un=node('option','未指派');un.value='_empty';$('assignee').append(un);
 state.members.forEach(m=>{const o=node('option',m.displayName||m.username);o.value=m.username;$('assignee').append(o)});$('assignee').value=a;
 renderOverview();renderTasks();renderPlan();renderEvents();
}
function gateDate(value){const [month,day]=value.split('/').map(Number);const year=month>=10?Number(state.project.preparedAt.slice(0,4)):Number(state.project.targetRelease.slice(0,4));return year+'-'+String(month).padStart(2,'0')+'-'+String(day).padStart(2,'0');}
function renderOverview(){
 const tasks=state.tasks;
 $('stats').replaceChildren();
 [['全部任务',tasks.length,''],['已验收',tasks.filter(completed).length,'success'],['待验收',tasks.filter(t=>t.status==='review').length,''],['未指派',tasks.filter(t=>!t.assignee&&!completed(t)).length,'warning'],['受阻 / 逾期',tasks.filter(t=>blocked(t)||late(t)).length,'warning']].forEach(([label,count,cls])=>{const d=node('div',undefined,'stat');d.append(node('strong',count,cls),node('span',label));$('stats').append(d)});
 $('riskList').replaceChildren();
 [['待指派负责人',tasks.filter(t=>!t.assignee&&!completed(t)),'没有执行人的任务不能形成真实分工。'],['阻塞与前置未完成',tasks.filter(t=>!completed(t)&&(blocked(t)||depsOpen(t).length)),'先处理阻塞，核对前置交付，再启动后续任务。'],['近期日期风险',tasks.filter(t=>late(t)||soon(t)),'已逾期及7天内截止的未验收任务。']].forEach(([title,list,desc])=>{const d=node('article',undefined,'risk-card');d.append(node('h3',title+' · '+list.length),node('p',desc));list.slice(0,3).forEach(t=>{const p=node('p');p.append(taskButton(t,t.id+' '+t.title));d.append(p)});if(!list.length)d.append(node('p','当前无此类任务'));$('riskList').append(d)});
 $('streams').replaceChildren();
 [...new Set(tasks.filter(t=>t.priority==='P0').map(t=>t.stream))].forEach(name=>{const list=tasks.filter(t=>t.priority==='P0'&&t.stream===name),n=list.filter(completed).length,d=node('article',undefined,'stream-card');d.append(node('h3',name));const p=node('p');p.append(node('strong',n+'/'+list.length),node('span','核心任务已验收'));d.append(p);const bar=node('progress');bar.max=list.length;bar.value=n;d.append(bar,node('p',n===list.length?'任务已验收，仍按业务门槛签收':'待建设 / 验收 · '+list.filter(t=>t.status==='doing').length+'项进行中'));$('streams').append(d)});
 $('milestones').replaceChildren();
 (state.project.gates||[]).forEach(g=>{const d=node('article',undefined,'milestone');d.append(node('time',g[0]),node('h3',g[1]),node('p',g[2]),node('small','签收：'+g[3]));
 const deadline=gateDate(g[0]),required=tasks.filter(t=>t.priority==='P0'&&t.end<=deadline),done=required.filter(completed).length;
 d.append(node('small','截至此门槛前置任务：已验收 '+done+' / '+required.length));const bar=node('progress');bar.max=required.length||1;bar.value=done;d.append(bar,badge(done===required.length?'前置已齐，待业务签收':deadline<today()?'需关注，前置未齐':'待推进',done===required.length?'review':deadline<today()?'warning':'todo'));d.dataset.deadline=deadline;d.dataset.required=required.length;d.dataset.accepted=done;$('milestones').append(d)});
 $('capabilities').replaceChildren();
 state.capabilities.forEach(c=>{const d=node('article',undefined,'cap-card');d.append(badge({ok:'限定检查正常',warning:'需关注',unknown:'待核实'}[c.status]||'待核实',c.status),node('h3',c.title),node('p',c.detail),node('small','观察：'+dateText(c.observedAt)));$('capabilities').append(d)});
}
function visible(){
 if(!state)return [];
 const q=$('search').value.trim().toLowerCase();
 return state.tasks.filter(t=>(!q||(/^g[0-9]+$/.test(q)?t.id.toLowerCase()===q:JSON.stringify(t).toLowerCase().includes(q)))&&(!$('priority').value||t.priority===$('priority').value)&&(!$('status').value||t.status===$('status').value)&&(!$('stream').value||t.stream===$('stream').value)&&(!$('assignee').value||($('assignee').value==='_empty'?!t.assignee:t.assignee===$('assignee').value))&&(!$('risk').value||{focus:!completed(t)&&(!t.assignee||blocked(t)||late(t)||soon(t)||depsOpen(t).length>0),blocked:blocked(t),late:late(t),soon:soon(t),mine:t.assignee===state.viewer.user}[$('risk').value]));
}
function renderTasks(){
 const list=visible();$('resultCount').textContent='显示 '+list.length+' / '+state.tasks.length+' 项 · 点击详情查看验收标准与证据';
 $('empty').hidden=Boolean(list.length);$('taskRows').replaceChildren();
 list.forEach(t=>{const tr=node('tr'),name=node('td'),owner=node('td'),dates=node('td'),status=node('td'),risk=node('td'),action=node('td');
 name.append(node('div',t.id+' · '+t.priority+' · '+t.stream,'task-id'),node('strong',t.title),node('p',t.deliverable));
 const member=state.members.find(m=>m.username===t.assignee);
 owner.append(node('strong',member?(member.displayName||member.username):(t.assignee||'待指派')),node('p',t.owner));
 dates.append(node('time',t.start+' → '+t.end));if(late(t))dates.append(node('p','已逾期','task-warning'));else if(soon(t))dates.append(node('p','7天内截止','task-warning'));
 status.append(badge(labels[t.status]||t.status,t.status));const progress=node('progress');progress.max=100;progress.value=t.progress;status.append(progress,node('small',(t.progress||0)+'% · 执行进度'));if(t.status==='done')status.append(node('p','签收：'+(t.acceptedBy||'管理员')));
 risk.append(node('p',(t.depends||[]).length?'前置：'+t.depends.join(' / '):'可独立启动'));if(t.blocker)risk.append(node('p',t.blocker,'task-warning'));else if(depsOpen(t).length)risk.append(node('p',depsOpen(t).length+'项前置未验收','task-warning'));else risk.append(node('p','无已记录阻塞'));
 action.append(taskButton(t,t.canEdit?'详情 / 更新':'查看详情'));tr.append(name,owner,dates,status,risk,action);$('taskRows').append(tr)});
}
function renderPlan(){
 $('weeks').replaceChildren();(state.project.weeks||[]).forEach((w,i)=>{const d=node('article',undefined,'week');d.append(node('time','W'+(i+1)+' · '+w[0]),node('h3',w[1]),node('p',w[2]));const chips=node('div',undefined,'week-tasks');w[3].split(/\s+/).forEach(id=>{const t=state.tasks.find(t=>t.id===id);if(t)chips.append(taskButton(t,id+' '+labels[t.status]))});d.append(chips);$('weeks').append(d)});
 $('staff').replaceChildren();(state.project.staff||[]).forEach(row=>{const tr=node('tr');row.forEach(value=>tr.append(node('td',value)));$('staff').append(tr)});
}
function eventSummary(summary){
 const names={title:'任务名称',priority:'优先级',stream:'工作线',owner:'责任岗位',assignee:'执行人',status:'状态',progress:'执行进度',start:'开始日期',end:'截止日期',depends:'前置任务',deliverable:'交付物',acceptance:'验收标准',blocker:'阻塞',notes:'进展备注',evidence:'验收证据',support:'配合岗位',effort:'投入'};
 try{const changes=JSON.parse(summary);if(!changes||typeof changes!=='object'||Array.isArray(changes))return summary;
 const value=(field,x)=>field==='status'?(labels[x]||x||'未设置'):field==='progress'?String(x??0)+'%':Array.isArray(x)?x.join(' / ')||'无':String(x??'')||'未设置';
 return Object.entries(changes).map(([field,change])=>{if(!change||typeof change!=='object'||!('new' in change))return (names[field]||field)+'：'+String(change);return (names[field]||field)+'：'+value(field,change.old)+' → '+value(field,change.new)}).join('\n')||'任务记录已保存，字段未发生变化。';
 }catch{return summary}
}
function renderEvents(){
 $('eventList').replaceChildren();
 if(!state.events.length)$('eventList').append(node('div','暂无进展记录。首次任务更新后，会在这里保留共享变化。','empty'));
 [...state.events].sort((a,b)=>b.at.localeCompare(a.at)).forEach(e=>{const d=node('article',undefined,'event');d.append(node('time',dateText(e.at)),node('h3',e.actor+' · '+(e.taskId||'项目')+' · '+({create:'新增任务',update:'更新进展'}[e.action]||e.action)),node('p',eventSummary(e.summary)));$('eventList').append(d)});
}
function tab(id){document.querySelectorAll('.view').forEach(n=>n.hidden=n.id!==id);document.querySelectorAll('[data-tab]').forEach(n=>{n.classList.toggle('active',n.dataset.tab===id);n.setAttribute('aria-selected',String(n.dataset.tab===id))});}
const fields=['title','priority','stream','owner','support','effort','assignee','status','start','end','progress','depends','deliverable','acceptance','blocker','notes','evidence'];
const structural=['title','priority','stream','owner','support','effort','assignee','start','end','depends','deliverable','acceptance'];
function openTask(t){
 editing=t||{id:null,revision:0,title:'',priority:'P0',stream:'项目统筹',owner:'',support:'',effort:'',assignee:'',status:'todo',start:today(),end:today(),progress:0,depends:[],deliverable:'',acceptance:'',blocker:'',notes:'',evidence:'',canEdit:true};dirty=false;
 const admin=state.viewer.isAdmin,canEdit=Boolean(editing.canEdit||admin),form=$('taskForm');
 $('dialogCode').textContent=t?t.id+' · '+t.priority+' · '+t.stream:'新增共享任务';$('dialogTitle').textContent=t?t.title:'新增项目任务';
 $('taskMeta').textContent=t?'配合：'+(t.support||'待确认')+' · 投入：'+(t.effort||'未估算')+'\n更新：'+dateText(t.updatedAt)+' · '+(t.updatedBy||'初始计划')+(t.acceptedAt?'\n验收：'+t.acceptedBy+' · '+dateText(t.acceptedAt):''):'管理员新增任务；保存后由服务器生成任务编号。';
 const ass=form.elements.assignee;ass.replaceChildren();const none=node('option','待指派');none.value='';ass.append(none);state.members.forEach(m=>{const o=node('option',m.displayName||m.username);o.value=m.username;o.disabled=m.active===false;if(m.active===false)o.textContent+='（已停用）';ass.append(o)});if(editing.assignee&&!state.members.some(m=>m.username===editing.assignee)){const o=node('option',editing.assignee+'（当前未列成员）');o.value=editing.assignee;ass.append(o)}
 const statuses=form.elements.status;statuses.replaceChildren();Object.entries(labels).forEach(([key,value])=>{if(key==='done'&&!admin&&editing.status!=='done')return;const o=node('option',value);o.value=key;statuses.append(o)});
 fields.forEach(k=>{const control=form.elements[k];control.value=k==='depends'?(editing[k]||[]).join(', '):(editing[k]??'');control.disabled=!canEdit||(!admin&&structural.includes(k))||(!admin&&editing.status==='done')});
 $('saveTask').hidden=!canEdit||(!admin&&editing.status==='done');$('saveResult').textContent='';$('reloadTask').hidden=true;$('formNotice').hidden=false;$('formNotice').textContent=!canEdit?'当前为只读查看；协作者仅能更新分派给自己的任务。':admin?(editing.status==='done'?'此任务已验收。如需修改验收内容，请先重开任务；签收历史仍在动态中。':'已验收需要证据及前置任务全部验收；签收由服务器记录。'):'你可以更新自己的进度、阻塞、备注和证据，完成后提交待验收。';
 $('dependencies').replaceChildren(node('span','前置任务：'));(editing.depends||[]).forEach(id=>{const dep=state.tasks.find(x=>x.id===id);if(dep)$('dependencies').append(node('span',id+' '+dep.title+'（'+labels[dep.status]+'） '));else $('dependencies').append(node('span',id+'（未知） '))});
 if(!$('taskDialog').open)$('taskDialog').showModal();
}
function closeDialog(){if(dirty&&!window.confirm('编辑内容尚未保存，确定关闭？'))return;$('taskDialog').close();dirty=false;editing=null;if(pending){state=pending;pending=null;render();$('updates').hidden=true}}
$('taskForm').addEventListener('input',()=>dirty=true);
$('taskForm').addEventListener('submit',async e=>{
 e.preventDefault();if(!editing||!state)return;
 const form=$('taskForm'),admin=state.viewer.isAdmin,payload={};
 const allowed=admin?fields:['status','progress','blocker','notes','evidence'];
 allowed.forEach(k=>payload[k]=k==='progress'?Number(form.elements[k].value):k==='depends'?form.elements[k].value.split(/[\s,，]+/).filter(Boolean):form.elements[k].value.trim());
 if(payload.status==='blocked'&&!payload.blocker){$('saveResult').textContent='受阻状态请填写具体阻塞。';return}
 if(payload.status==='done'&&!payload.evidence){$('saveResult').textContent='验收需要证据记录。';return}
 if(editing.id){Object.keys(payload).forEach(k=>{if(JSON.stringify(payload[k])===JSON.stringify(editing[k]??''))delete payload[k]});if(!Object.keys(payload).length){$('saveResult').textContent='没有字段变化，无需重复保存。';return}payload.expectedRevision=editing.revision;}
 $('saveTask').disabled=true;$('saveResult').textContent='正在保存到服务器…';
 try{const result=await request(editing.id?'/tasks/'+encodeURIComponent(editing.id):'/tasks',{method:editing.id?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!result.task||!result.task.id||(editing.id&&result.task.id!==editing.id)){const e=new Error('服务器未返回匹配的任务记录');e.unconfirmed=true;throw e}
 dirty=false;editing=null;$('taskDialog').close();pending=null;await load(true);
 }catch(err){const conflict=err.status===409&&/任务已被更新|并发更新冲突/.test(err.message);$('saveResult').textContent=conflict?'任务已被他人修改，未覆盖你的编辑。请先复制内容，再重读最新任务。':(!err.status||err.unconfirmed?'保存结果尚未确认，请先刷新核对；新增任务请勿立即重复提交。 '+err.message:err.message);$('reloadTask').hidden=!conflict;}finally{$('saveTask').disabled=false}
});
$('reloadTask').addEventListener('click',async()=>{if(!window.confirm('重读会放弃此表单未保存内容。请先复制需要保留的内容。'))return;const id=editing.id;dirty=false;await load(true);const task=state.tasks.find(t=>t.id===id);if(task)openTask(task)});
$('taskDialog').addEventListener('cancel',e=>{e.preventDefault();closeDialog()});
['closeDialog','cancelDialog'].forEach(id=>$(id).addEventListener('click',closeDialog));
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.tab)));
['search','priority','status','stream','assignee','risk'].forEach(id=>$(id).addEventListener('input',renderTasks));
$('reset').addEventListener('click',()=>{['search','priority','status','stream','assignee','risk'].forEach(id=>$(id).value='');renderTasks()});
$('showRisks').addEventListener('click',()=>{tab('tasks');$('risk').value='focus';renderTasks()});
$('refresh').addEventListener('click',()=>load(true));
$('loadUpdates').addEventListener('click',()=>{if($('taskDialog').open&&dirty){$('taskDialog').focus();return}if(pending){state=pending;pending=null;render();$('updates').hidden=true}else load(true)});
$('newTask').addEventListener('click',()=>openTask(null));
function csvCell(value){let s=Array.isArray(value)?value.join(' / '):String(value??'');if(/^[\s\u0000-\u001f]*[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"'}
$('export').addEventListener('click',()=>{if(!state)return;const keys=['id','priority','stream','title','owner','support','effort','assignee','start','end','status','progress','depends','deliverable','acceptance','blocker','notes','evidence','acceptedBy','acceptedAt'];
 const headers=['任务ID','优先级','工作线','任务','责任岗位','执行人','开始','截止','状态','进度%','前置任务','交付物','验收标准','阻塞','备注','证据','签收人','签收时间'];
 const csv='\uFEFF'+[headers,...visible().map(t=>keys.map(k=>k==='status'?labels[t[k]]:t[k]))].map(row=>row.map(csvCell).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=node('a');a.href=url;a.download='绿茵计划_共享进展_'+today()+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});
load();setInterval(()=>{if(!document.hidden)load()},30000);

