'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const API = '/dashboard/fs-home/advisor.json';
  const active = new Set(['PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','REPORT_PENDING']);
  const labels = {PREPARING:'准备数据',DISPATCH_UNKNOWN:'派发待核对',RUNNING:'调查中',COMPLETED:'已成稿',FAILED:'失败',CANCELLED:'已取消',CANCEL_REQUESTED:'正在取消',NEEDS_RECONCILE:'需核对',REPORT_PENDING:'正在保存报告'};
  let items = [], selected = null, busy = false, timer = null, uncertain = false, submitting = false;
  const requestedKind = new URLSearchParams(location.search).get('report_kind');
  const completedResults = new Map();
  let refreshQueued=false;
  let poolScope="shared", pageBefore=null, nextBefore=null, poolQuery="", periodFilter=null, canGenerate=false, selectedJob=null, chatSignature="", chatBusy=false, chatUncertain=false;
  let reportKind = ['daily','weekly','monthly'].includes(requestedKind) ? requestedKind : 'all';
  function kindOf(item) { const b=item.body||{};const match=/^(?:night|brain)_(daily|weekly|monthly)_/.exec(b.request_id||'');if(match)return match[1];return b.start&&b.end?periodKind(b.start,b.end):'investigation'; }
  function periodKind(start,end) { const a=new Date(start+'T00:00:00Z'),b=new Date(end+'T00:00:00Z');if(start===end)return 'daily';if(a.getUTCDay()===1&&b-a===6*86400000)return 'weekly';if(a.getUTCDate()===1&&a.getUTCMonth()===b.getUTCMonth()&&a.getUTCFullYear()===b.getUTCFullYear()&&b.getUTCDate()===new Date(Date.UTC(b.getUTCFullYear(),b.getUTCMonth()+1,0)).getUTCDate())return 'monthly';return 'investigation'; }
  function closedPeriod(kind) { const today=new Date(new Date().toLocaleString('en-US',{timeZone:'Asia/Shanghai'}));let end=new Date(today),start;end.setHours(12,0,0,0);if(kind==='weekly'){end.setDate(end.getDate()-((end.getDay()+6)%7)-1);start=new Date(end);start.setDate(start.getDate()-6);}else if(kind==='monthly'){end.setDate(0);start=new Date(end);start.setDate(1);}else{end.setDate(end.getDate()-1);start=new Date(end);}const fmt=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');$('start').value=fmt(start);$('end').value=fmt(end);$('mode').value=kind==='daily'?'daily':'investigation';$('question').value='请基于同口径证据撰写 FC '+({daily:'昨日经营日报',weekly:'上周运营周报',monthly:'上月经营月报'}[kind]||'经营报告')+'。核对目标与实绩、量价及结构变化，区分事实和假说，给出行动优先级、停止条件与复查标准；缺项明确说明。'; }
  function node(tag, text, parent, cls) { const n=document.createElement(tag); if(text!==null)n.textContent=text; if(cls)n.className=cls; if(parent)parent.append(n); return n; }
  function message(text, error=false) { $('notice').textContent=text; $('notice').classList.toggle('error',error); }
  async function request(query='', body) {
    const response = await fetch(API+query, {method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(20000),headers:body?{'Content-Type':'application/json','X-FS-Advisor-Action':'submit'}:{},body:body?JSON.stringify(body):undefined});
    if(!response.headers.get('content-type')?.includes('application/json'))throw Error('登录状态或返回内容异常，请重新登录 FS。');
    const value=await response.json();
    if(!response.ok){const error=Error(({login_required:'请登录 FS。',admin_required:'发起调查需要管理员权限。',release_in_progress:'正在发布，请稍后重试。',invalid_period_or_question:'请核对完整日期范围与提问内容。',pilot_usage_hold:'存在需核对的模型任务，请先查看任务记录。'})[value.error]||('请求未完成：'+(value.error||response.status)));error.status=response.status;error.rejected=response.status>=400&&response.status<500;throw error;}
    return value;
  }
  function dates() { const civil=new Date(new Date().toLocaleString('en-US',{timeZone:'Asia/Shanghai'}));civil.setDate(civil.getDate()-1);const fmt=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');$('end').value=fmt(civil);$('end').max=fmt(civil);$('start').max=fmt(civil);civil.setDate(civil.getDate()-6);$('start').value=fmt(civil); }
  function list() {
    $('running').textContent=items.filter(i=>active.has(i.state)).length;
    $('completed').textContent=items.filter(i=>i.state==='COMPLETED').length;
    $('attention').textContent=items.filter(i=>['FAILED','NEEDS_RECONCILE','DISPATCH_UNKNOWN'].includes(i.state)).length;
    $('tasks').replaceChildren();
    const visible=items.filter(i=>reportKind==='all'||kindOf(i)===reportKind);
    if(!visible.length)node('p','当前筛选没有记录，可调整条件或查看更早记录。',$('tasks'),'empty');
    for(const item of visible){const b=node('button',null,$('tasks'),'task-item'+(selected===item.id?' selected':''));b.type='button';node('b',item.body.start+' — '+item.body.end,b);node('span',(labels[item.state]||item.state)+' · '+item.owner+(item.body.parent_report?' · 修订版':''),b);node('p',item.body.question,b);b.onclick=()=>poolScope==='trash'?trashDetail(item):select(item.id);}
  }
  function schedules(data) {
    $('nightly').replaceChildren();$('nightly').className='';
    if(!data?.enabled){node('p','当前账号没有已启用的自动报告计划。',$('nightly'),'muted');return;}
    for(const [title,time] of [['每日经营复盘','00:45'],['周一 · 上周周报','01:45'],['每月1日 · 上月月报','03:15']]){const row=node('div',null,$('nightly'),'schedule-row');node('span',title,row);node('strong',time,row);}
    for(const plan of data.items||[])node('p',(plan.kind==='daily'?'日报':plan.kind==='weekly'?'周报':'月报')+' · '+(labels[plan.state]||plan.state)+(plan.error?' · '+plan.error:''),$('nightly'),'muted');
  }
  const HTML_MARKER='【完整HTML创作】';
  function htmlQuestion(value) {
    const text=String(value||'');const result=text.startsWith(HTML_MARKER)?text:HTML_MARKER+text;
    if(Array.from(result).length>600){const error=Error('提问加创作标记后超过600字，请缩短后提交；原文未截断。');error.rejected=true;throw error;}
    return result;
  }
  function htmlReport(job) {return !!job.result?.html_design||String(job.body?.question||'').startsWith(HTML_MARKER);}
  function originalDownload(content,filename,mime='text/html;charset=utf-8') {
    const url=URL.createObjectURL(new Blob([content],{type:mime}));const a=document.createElement('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  }
  function isolatedViewer(content,identity) {
    // Only this trusted shell executes in the opener's origin. Model HTML is data until assigned to opaque srcdoc.
    const payload=JSON.stringify({content,identity}).replaceAll('<','\\u003c').replaceAll('\u2028','\\u2028').replaceAll('\u2029','\\u2029');
    return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; frame-src about: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; worker-src 'none'"><title>Hermes 原始HTML · 隔离阅读</title><style>:root{color-scheme:light dark}body{margin:0;font:14px system-ui;background:Canvas;color:CanvasText}header{padding:12px;overflow-wrap:anywhere}button{font:inherit;margin:4px;padding:8px}iframe{display:block;width:100%;height:calc(100dvh - 150px);border:0}small{display:block}@media print{header{display:none}iframe{height:100vh}}</style><header><strong>Hermes 原始HTML · 隔离阅读</strong><small id="identity"></small><small>原稿未重排。资源与API连接受CSP限制；沙箱不等于绝对离线。原稿可下载后离线使用。</small><button id="download">下载原始HTML</button></header><iframe title="模型原始HTML报告" sandbox="allow-scripts allow-modals allow-downloads" referrerpolicy="no-referrer"></iframe><script>const payload=${payload};document.getElementById('identity').textContent=payload.identity;const frame=document.querySelector('iframe');frame.srcdoc=payload.content;document.getElementById('download').onclick=()=>{const url=URL.createObjectURL(new Blob([payload.content],{type:'text/html;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='hermes-original.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);};<\/script></html>`;
  }
  async function report(job, kind, download=false) {
    const design=(kind==='boss'||kind==='html')&&htmlReport(job);
    const value=await request('?mode=hermes&id='+encodeURIComponent(job.id)+'&artifact='+(design?'raw':kind));
    let content=value.content;
    if(design){
      const result=job.result||completedResults.get(job.id);const expected=result?.artifact?.raw_sha256;
      const bytes=new TextEncoder().encode(content);const actual=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
      if(!/^[a-f0-9]{64}$/.test(expected||'')||actual!==expected)throw Error('原稿SHA校验未通过，未打开或下载。');
      if(download){originalDownload(content,'hermes-'+job.id+'-'+actual.slice(0,12)+'.html');return;}
      if(!/^\s*<!doctype html[\s>]/i.test(content)||!/<\/body\s*>\s*<\/html\s*>\s*$/i.test(content))throw Error('原稿未提供完整HTML文档，请下载原稿检查；未回退为旧模板。');
      content=isolatedViewer(content,'任务 '+job.id+' · '+job.body.start+' — '+job.body.end+' · SHA256 '+actual+' · 教学版本 '+(result.html_design?.manifest_sha256||'未提供'));
      const host=$('report-detail');host.querySelector('iframe[data-report-preview]')?.remove();
      const frame=document.createElement('iframe');frame.dataset.reportPreview=job.id;frame.title='完整交互报告';frame.referrerPolicy='no-referrer';
      frame.style.cssText='display:block;width:100%;height:80vh;min-height:360px;border:1px solid var(--fs-line);border-radius:var(--fs-input-radius);background:var(--fs-surface)';
      frame.srcdoc=content;host.append(frame);frame.scrollIntoView({block:'start'});return;
    }
    const url=URL.createObjectURL(new Blob([content],{type:design?'text/html;charset=utf-8':value.mime}));const a=document.createElement('a');a.href=url;if(download)a.download=value.filename;else{a.target='_blank';a.rel='noopener';}document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  }
  function detail(job) {
    const preserveActions=job.state==='COMPLETED'&&$('decision-list').dataset.report===job.id;
    if(job.id!==selected)return;
    if(completedResults.has(job.id))job={...job,result:{...job.result,...completedResults.get(job.id)}};
    // Settled artifacts are immutable; polling must not reload an interactive preview.
    if(job.state==='COMPLETED'&&$('report-detail').querySelector('iframe[data-report-preview]')?.dataset.reportPreview===job.id)return;
    if(!preserveActions){$('decision-list').replaceChildren();delete $('decision-list').dataset.report;
    node('p','当前记录尚未提供可展示的结构化行动清单。',$('decision-list'),'empty');}
    const host=$('report-detail');host.replaceChildren();node('div',(labels[job.state]||job.state)+' · '+job.owner,host,'eyebrow');
    if(job.body.parent_report){const parent=node('button','查看上一版本',host,'quiet');parent.onclick=()=>select(job.body.parent_report);}
    if(job.can_delete){const remove=node('button','删除报告',host,'quiet danger');remove.onclick=async()=>{if(!confirm('移到回收站？报告可恢复，费用及审计记录保留。'))return;remove.disabled=true;try{await request('',{kind:'hermes_delete',id:job.id});completedResults.delete(job.id);selected=null;selectedJob=null;chatSignature='';host.replaceChildren();node('p','报告已移到回收站，可从回收站恢复。',host);$('chat-messages').replaceChildren();$('chat-send').disabled=true;await refresh();}catch(e){message(e.message,true);remove.disabled=false;}};}
    node('div',job.body.parent_report?'原证据上的独立新版本':'原始报告',host,'muted');node('h3',job.body.start+' — '+job.body.end,host);node('p',job.body.question,host,'muted');
    if(job.error)node('p','状态说明：'+job.error,host,'danger');
    const progress=job.progress; if(progress?.heartbeat_at)node('p','最近进度：'+new Date(progress.heartbeat_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · '+(progress.stage||''),host,'muted');
    if(job.evidence_count!==undefined)node('p','已保存 '+job.evidence_count+' 份证据',host,'muted');
    if(job.model_usage?.calls!==null&&job.model_usage?.calls!==undefined)node('p','模型调用 '+job.model_usage.calls+' 次 · 已知用量 '+job.model_usage.total_tokens+' tokens'+(job.model_usage.unknown_calls?' · 部分用量未确认':''),host,'muted');
    $('context-receipt').textContent=job.context_loading?JSON.stringify(job.context_loading,null,2):'该任务尚无背景与技能加载回执。';
    if(job.state!=='COMPLETED'||(job.result?.model_generated!==true&&!job.result?.html_design))return;
    const result=job.result;node('p',result.summary||'报告已保存，请打开完整正文。',host);
    for(const [label,download] of [['打开汇报',false],['下载汇报',true]]){const b=node('button',label,host,'primary');b.onclick=()=>report(job,'boss',download).catch(e=>message('汇报暂未就绪：'+e.message+' 可先查看研究详情。',true));}
    for(const [label,download] of [['打开研究详情',false],['下载研究详情',true]]){const b=node('button',label,host,'quiet');b.onclick=()=>report(job,'html',download).catch(e=>message(e.message,true));}
    if(preserveActions)return;
    $('decision-list').replaceChildren();delete $('decision-list').dataset.report;
    if(!result.actions?.length)node('p','这份结果未提供结构化行动清单，请查看完整报告；不会自动补造待办。',$('decision-list'),'empty');
    for(const action of result.actions||[]){const card=node('div',null,$('decision-list'),'decision');node('h3',action.target,card);node('p',action.action,card);node('p','条件：'+action.condition,card);node('p','复查：'+action.review_at+' · '+action.success_check,card);}
  }
  const actionLabels={suggested:'建议',approved:'已确认',executed:'已执行',review_pending:'待复查',effective:'有效',ineffective:'无效',insufficient:'证据不足',adjusted:'已调整'};
  const actionNext={suggested:['approved','adjusted'],approved:['executed','adjusted'],executed:['review_pending','insufficient','adjusted'],review_pending:['effective','ineffective','insufficient','adjusted'],insufficient:['review_pending','adjusted'],effective:['adjusted'],ineffective:['adjusted'],adjusted:['approved']};
  async function actionRecords(job){
    if(job.state!=='COMPLETED'||selected!==job.id)return;
    try{
    const value=await request('?mode=hermes&id='+encodeURIComponent(job.id)+'&actions=1');if(selected!==job.id)return;
    const host=$('decision-list');host.replaceChildren();host.dataset.report=job.id;const reload=node('button','刷新行动回执',host,'quiet');reload.type='button';reload.onclick=()=>actionRecords(job).catch(e=>message(e.message,true));
    for(const action of value.actions||[]){
      const events=(value.events||[]).filter(e=>e.action===action.id),latest=events.at(-1),state=latest?.status||'suggested';
      const card=node('div',null,host,'decision');node('h3',action.title,card);node('p',action.steps,card);node('p','状态：'+actionLabels[state]+' · 负责人角色：'+action.role,card);node('p','基线/指标：'+action.metric+' · 护栏：'+action.stop,card);
      if(latest)node('p',latest.actor+' · '+latest.recorded_at+' · '+latest.note+' · 复查 '+(latest.review_at||'未安排'),card);
      if(!value.can_update)continue;
      const form=node('form',null,card),status=node('select',null,form);status.setAttribute('aria-label','行动状态');for(const next of actionNext[state]){const option=node('option',actionLabels[next],status);option.value=next;}
      const note=node('textarea',null,form);note.required=true;note.maxLength=2000;note.setAttribute('aria-label','执行或效果回执与证据');note.placeholder='填写实际动作或效果证据、基线与混杂因素；保存记录不会执行业务动作。';
      const review=node('input',null,form);review.type='datetime-local';review.setAttribute('aria-label','北京时间复查日期');
      const save=node('button','保存行动记录',form,'quiet');save.type='submit';const message=node('p','人工确认记录；不会改价、改预算或自动派单。',form);message.setAttribute('role','status');let uncertainBody=null;
      form.onsubmit=async event=>{event.preventDefault();if(['executed','review_pending'].includes(status.value)&&!review.value){message.textContent='已执行和待复查状态需要复查日期。';return;}
        const body=uncertainBody||{kind:'hermes_action',id:job.id,action:action.id,request_id:'action_'+crypto.randomUUID().replaceAll('-',''),expected_version:latest?.version||0,status:status.value,note:note.value,review_at:review.value?review.value+':00+08:00':''};save.disabled=true;
        try{await request('',body);await actionRecords(job);}catch(error){if(!error.rejected)uncertainBody=body;message.textContent=error.message+(uncertainBody?' 重试将核对同一记录，不重复执行。':'');save.disabled=false;}
      };
    }
    if(!value.actions?.length)node('p','本报告没有可记录的结构化行动；请查看完整研究，未自动补造。',host,'empty');
    }catch(error){
      if(selected!==job.id)return;
      const host=$('decision-list');host.replaceChildren();delete host.dataset.report;
      node('p','行动记录暂不可用：'+error.message+'；未把读取失败当作没有行动。',host,'danger');
      const retry=node('button','重试读取行动记录',host,'quiet');retry.type='button';retry.onclick=()=>actionRecords(job);
    }
  }
  async function select(id) {selected=id;list();try{const job=await request('?mode=hermes&id='+encodeURIComponent(id));if(selected!==id)return;selectedJob=job;detail(job);await conversation(job);if(job.state==='COMPLETED'&&!completedResults.has(id)){const artifact=await request('?mode=hermes&id='+encodeURIComponent(id)+'&artifact=json');completedResults.set(id,JSON.parse(artifact.content));detail(job);}if(selected===id)await actionRecords(job);}catch(e){message(e.message,true);}}
  function poolParameters() {
    const p=new URLSearchParams({mode:'hermes',scope:poolScope});if(pageBefore)p.set('before',pageBefore);if(poolQuery)p.set('q',poolQuery);if(periodFilter){p.set('start',periodFilter.start);p.set('end',periodFilter.end);}return '?'+p;
  }
  function trashDetail(item) {
    selected=item.id;selectedJob=null;chatSignature='';list();$('chat-send').disabled=true;$('chat-messages').replaceChildren();
    const host=$('report-detail');host.replaceChildren();node('h3',item.body.start+' — '+item.body.end,host);node('p',item.body.question,host);node('p','作者：'+item.owner+' · 删除人：'+item.deleted_by,host,'muted');
    const restore=node('button','恢复报告',host,'primary');restore.onclick=async()=>{restore.disabled=true;try{await request('',{kind:'hermes_restore',id:item.id});poolScope='shared';$('pool-scope').value=poolScope;pageBefore=null;selected=null;await refresh();await select(item.id);}catch(e){message(e.message,true);restore.disabled=false;}};
  }
  async function conversation(job) {
    $('chat-send').disabled=!canGenerate||chatBusy||chatUncertain||!job.can_followup;
    const signature=job.id+':'+job.state;if(signature===chatSignature)return;
    const data=await request('?mode=hermes&id='+encodeURIComponent(job.id)+'&thread=1');if(selected!==job.id)return;
    chatSignature=signature;const host=$('chat-messages');host.replaceChildren();
    for(const turn of data.items||[]){
      const q=node('article',null,host,'chat-message user');node('b',turn.owner+' · 提问',q);node('p',turn.question,q);
      const a=node('article',null,host,'chat-message assistant');node('b','Hermes · '+(labels[turn.state]||turn.state),a);node('p',turn.reply||turn.error||'任务正在处理，回答将在这里显示。',a);
      if(turn.reply_excerpt)node('p','长回复仅展示前段，选择此版本后可打开完整汇报或研究详情。',a,'muted');
      const open=node('button',turn.id===selected?'当前版本':'查看此版本',a,'quiet');open.disabled=turn.id===selected;open.onclick=()=>select(turn.id);
    }
    if(!job.can_followup)$('chat-status').textContent='请选中已完成版本进行追问；进行中或失败任务不会自动重试。';
    else if(!chatBusy&&!chatUncertain)$('chat-status').textContent='基于当前版本回答；需要更新业务数据，请在上方明确发起新调查。';
  }
  async function refresh() {
    if(document.hidden)return;if(busy){refreshQueued=true;return;}busy=true;refreshQueued=false;clearTimeout(timer);
    try {const parameters=poolParameters(),value=await request(parameters);if(parameters!==poolParameters()){refreshQueued=true;return;}items=value.items||[];canGenerate=value.can_generate;nextBefore=value.next_before;$('pool-next').disabled=!nextBefore;list();schedules(value.nightly);$('submit').disabled=!value.can_generate||uncertain||submitting;$('connection').textContent='已连接云端 Hermes';document.querySelector('.live-dot').classList.add('connected');message(value.admission?.reason?'新调查暂缓：'+value.admission.reason:(value.pool_scope==='mine'?'显示我发起的任务。':value.pool_scope==='trash'?'回收站：作者或管理员可以恢复报告。':'共享池：显示有权访问的夜间与人工报告。')+' 报告结论与建议不代表已执行。',!!value.admission?.reason);if(selected&&poolScope!=='trash'){const id=selected;try{const job=await request('?mode=hermes&id='+encodeURIComponent(id));if(selected!==id)return;selectedJob=job;detail(selectedJob);await conversation(selectedJob);if(selected===id&&job.state==='COMPLETED'&&$('decision-list').dataset.report!==id)await actionRecords(job);}catch(e){if(selected!==id)return;if(e.status!==404)throw e;completedResults.delete(selected);selected=null;selectedJob=null;chatSignature='';$('report-detail').replaceChildren();node('p','所选报告已删除或访问权限已变化。',$('report-detail'),'muted');$('chat-messages').replaceChildren();$('chat-send').disabled=true;}}}
    catch(e){message(e.message,true);$('connection').textContent='连接待恢复';document.querySelector('.live-dot').classList.remove('connected');$('submit').disabled=true;}
    finally{busy=false;if(!document.hidden){if(refreshQueued)void refresh();else timer=setTimeout(refresh,15000);}}
  }
  const prompts={diagnose:'调查所选期间 FC 经营变化。先核对数据范围与基准，再比较量价和结构变化；给出支持证据、其他可能解释，以及最值得做的下一步和复查条件。',target:'依据当前有效的 DY 原版 FC 目标，核对所选期间实绩、周期进度和缺口。目标版本或指标范围不一致时明确说明；提出需要什么证据才能判断原因，以及下一步可验证的行动。',method:'请先说明你已加载的业务背景和技能版本，再用所选期间的具体证据解释：销售额、订单数、客单价、复购率、当前未结池、预估利润和目标达成率的定义、分母、时间范围与来源。没有实际字段就说明缺口，最后指出哪些结论能下、哪些还不能下。'};
  document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{$('question').value=prompts[b.dataset.prompt];$('question').focus();});
  $('investigate').onsubmit=async event=>{event.preventDefault();if(uncertain||submitting)return;submitting=true;$('submit').disabled=true;const body={kind:'hermes_report',request_id:'brain_'+periodKind($('start').value,$('end').value)+'_'+crypto.randomUUID().replaceAll('-',''),start:$('start').value,end:$('end').value,question:$('question').value,mode:$('mode').value,force_generate:!$('reuse-existing').checked};try{body.question=htmlQuestion(body.question);const job=await request('',body);poolScope='shared';$('pool-scope').value=poolScope;pageBefore=null;selected=job.id;reportKind='all';$('report-kind').value='all';$('submit-state').textContent=job.reused?'已复用现有任务或报告，本次未新增模型调用。':'已交给云端 Hermes，关闭页面后任务仍继续。';await select(job.id);$('reports').scrollIntoView();}catch(e){uncertain=!e.rejected;$('submit-state').textContent=uncertain?'提交结果需核对：'+e.message+' 请先查看任务列表，避免重复派发。请求编号：'+body.request_id:e.message;}finally{submitting=false;await refresh();}};
  $('report-kind').value=reportKind;$('report-kind').onchange=()=>{reportKind=$('report-kind').value;list();};
  document.querySelectorAll('[data-period]').forEach(b=>b.onclick=()=>{closedPeriod(b.dataset.period);$('ask').scrollIntoView();});
  $('pool-scope').onchange=()=>{poolScope=$('pool-scope').value;pageBefore=null;selected=null;selectedJob=null;chatSignature='';$('chat-send').disabled=true;refresh();};
  $('pool-search-button').onclick=()=>{poolQuery=$('pool-search').value.trim();pageBefore=null;refresh();};
  $('pool-search').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('pool-search-button').click();}};
  $('pool-clear').onclick=()=>{poolQuery='';periodFilter=null;pageBefore=null;$('pool-search').value='';refresh();};
  $('find-period').onclick=()=>{poolScope='shared';$('pool-scope').value=poolScope;periodFilter={start:$('start').value,end:$('end').value};poolQuery='';$('pool-search').value='';pageBefore=null;refresh();$('reports').scrollIntoView();};
  $('pool-next').onclick=()=>{if(nextBefore){pageBefore=nextBefore;refresh();}};$('pool-first').onclick=()=>{pageBefore=null;refresh();};
  $('chat-form').onsubmit=async event=>{
    event.preventDefault();if(chatBusy||chatUncertain||!selectedJob?.can_followup||!canGenerate)return;
    const parent=selectedJob,body={kind:'hermes_report',request_id:'brain_followup_'+crypto.randomUUID().replaceAll('-',''),start:parent.body.start,end:parent.body.end,mode:parent.body.mode,question:$('chat-question').value,parent_report:parent.id};
    chatBusy=true;$('chat-send').disabled=true;
    try{if(htmlReport(parent))body.question=htmlQuestion(body.question);const job=await request('',body);$('chat-question').value='';$('chat-status').textContent=job.reused?'相同追问已存在，直接查看，不新增模型调用。':'已提交追问，新版本将在完成后显示，原报告保留。';poolScope='shared';$('pool-scope').value=poolScope;await select(job.id);}
    catch(e){chatUncertain=!e.rejected;$('chat-status').textContent=chatUncertain?'提交结果需核对，请先查看任务列表，避免重复生成。请求编号：'+body.request_id:e.message;}
    finally{chatBusy=false;$('chat-send').disabled=!canGenerate||chatUncertain||!selectedJob?.can_followup;await refresh();}
  };
  $('refresh').onclick=refresh;document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else refresh();});dates();if(reportKind!=='all')closedPeriod(reportKind);const initial=new URLSearchParams(location.search);if(requestedKind==='investigation'){const start=initial.get('start'),end=initial.get('end');if(/^\d{4}-\d{2}-\d{2}$/.test(start||'')&&/^\d{4}-\d{2}-\d{2}$/.test(end||'')&&start<=end){$('start').value=start;$('end').value=end;$('mode').value='investigation';$('question').value='调查本期FC27收入变化，拆解订单与客单价，核对同期专属广告、全局品牌及流量/履约证据，给出行动和复查条件。';}}refresh().then(()=>{const id=initial.get('report');if(/^[a-f0-9]{32}$/.test(id||''))select(id);});
})();
