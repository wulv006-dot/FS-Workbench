'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const API = '/dashboard/fs-home/advisor.json';
  const REPORT_PRESENTATION="自主调查、挖掘问题并作出有理由的经营判断，按重要性检查销售利润与客户商品、交付履约与支付售后、运营策略与复购、广告及自然获客、现实游戏节点与活动、既有动作及效果、风险机会和关键待决；日报周报可有侧重。数据优先用清晰紧凑图表，文字只提炼重要结论、原因、建议与可执行动作/复查，不逐项复述数字。交互服务理解，重点默认可见、明细按需展开，图表大小与信息量相称。报告配色、字体、布局、图表及阅读顺序自主，FS只作宏观参考；保持红涨绿跌、手机可读、键盘/浅暗/打印/离线下载可用。遵循现行报告方法，简单问题可简洁文本，复杂分析按需完整离线HTML；FS直接展示归档原稿，不套固定分析模板，不执行业务。";
  const active = new Set(['PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','REPORT_PENDING']);
  const labels = {PREPARING:'准备数据',DISPATCH_UNKNOWN:'派发待核对',RUNNING:'调查中',COMPLETED:'已成稿',FAILED:'失败',CANCELLED:'已取消',CANCEL_REQUESTED:'正在取消',NEEDS_RECONCILE:'需核对',REPORT_PENDING:'正在保存报告'};
  let items = [], selected = null, busy = false, timer = null, uncertain = false, submitting = false, dataRequest = null;
  const requestedKind = new URLSearchParams(location.search).get('report_kind');
  const completedResults = new Map();
  const checkedReports = new Set();
  let bulkDeleting = false;
  let refreshQueued=false;
  let poolScope="shared", pageBefore=null, nextBefore=null, poolQuery="", periodFilter=null, canGenerate=false, selectedJob=null, chatSignature="", chatBusy=false, chatUncertain=false;
  let reportKind = ['daily','weekly','monthly'].includes(requestedKind) ? requestedKind : 'all';
  function kindOf(item) { const b=item.body||{};const match=/^(?:night|brain)_(daily|weekly|monthly)_/.exec(b.request_id||'');if(match)return match[1];return b.start&&b.end?periodKind(b.start,b.end):'investigation'; }
  function periodKind(start,end) { const a=new Date(start+'T00:00:00Z'),b=new Date(end+'T00:00:00Z');if(start===end)return 'daily';if(a.getUTCDay()===1&&b-a===6*86400000)return 'weekly';if(a.getUTCDate()===1&&a.getUTCMonth()===b.getUTCMonth()&&a.getUTCFullYear()===b.getUTCFullYear()&&b.getUTCDate()===new Date(Date.UTC(b.getUTCFullYear(),b.getUTCMonth()+1,0)).getUTCDate())return 'monthly';return 'investigation'; }
  function closedPeriod(kind) { dataRequest=null;const today=new Date(new Date().toLocaleString('en-US',{timeZone:'Asia/Shanghai'}));let end=new Date(today),start;end.setHours(12,0,0,0);if(kind==='weekly'){end.setDate(end.getDate()-((end.getDay()+6)%7)-1);start=new Date(end);start.setDate(start.getDate()-6);}else if(kind==='monthly'){end.setDate(0);start=new Date(end);start.setDate(1);}else{end.setDate(end.getDate()-1);start=new Date(end);}const fmt=d=>d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');$('start').value=fmt(start);$('end').value=fmt(end);$('mode').value=kind==='daily'?'daily':'investigation';$('question').value='请基于同口径证据撰写 FC '+({daily:'昨日经营日报',weekly:'上周运营周报',monthly:'上月经营月报'}[kind]||'经营报告')+'。'+REPORT_PRESENTATION; }
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
    const eligible=new Set(visible.filter(i=>i.can_delete&&poolScope!=='trash').map(i=>i.id));
    for(const id of checkedReports)if(!eligible.has(id))checkedReports.delete(id);
    for(const item of visible){
      const row=node('div',null,$('tasks'),'reuse-options');row.style.margin='0';row.style.flexWrap='nowrap';
      if(item.can_delete&&poolScope!=='trash'){
        const label=node('label',null,row,'muted');const check=node('input',null,label);check.type='checkbox';check.checked=checkedReports.has(item.id);check.disabled=bulkDeleting;
        check.setAttribute('aria-label','选择报告 '+item.body.start+' 至 '+item.body.end+' '+item.body.question);
        check.dataset.reportSelect=item.id;check.onchange=()=>{check.checked?checkedReports.add(item.id):checkedReports.delete(item.id);bulkControls();};
      }
      const b=node('button',null,row,'task-item'+(selected===item.id?' selected':''));b.style.flex='1';b.style.minWidth='0';b.type='button';node('b',item.body.start+' — '+item.body.end,b);node('span',(labels[item.state]||item.state)+' · '+item.owner+(item.body.parent_report?' · 修订版':''),b);node('p',item.body.question,b);b.onclick=()=>poolScope==='trash'?trashDetail(item):select(item.id);
    }
    bulkControls();
  }
  const bulkBar=document.createElement('div');bulkBar.className='pool-tools';bulkBar.setAttribute('aria-label','批量管理报告');
  document.querySelector('.report-layout').before(bulkBar);
  const bulkAll=node('button','选择当前页',bulkBar,'quiet');bulkAll.type='button';
  const bulkClear=node('button','清空选择',bulkBar,'quiet');bulkClear.type='button';
  const bulkDelete=node('button','移到回收站',bulkBar,'quiet danger');bulkDelete.type='button';
  const bulkStatus=node('span','已选 0 份',bulkBar,'muted');bulkStatus.setAttribute('role','status');
  function bulkControls(){
    const allowed=items.filter(i=>(reportKind==='all'||kindOf(i)===reportKind)&&i.can_delete&&poolScope!=='trash');
    bulkAll.disabled=bulkDeleting||!allowed.length;bulkClear.disabled=bulkDeleting||!checkedReports.size;bulkDelete.disabled=bulkDeleting||!checkedReports.size;
    bulkDelete.textContent=bulkDeleting?'正在移到回收站…':'移到回收站';bulkStatus.textContent='已选 '+checkedReports.size+' 份（仅当前页）';
  }
  bulkAll.onclick=()=>{for(const i of items)if((reportKind==='all'||kindOf(i)===reportKind)&&i.can_delete&&poolScope!=='trash')checkedReports.add(i.id);list();};
  bulkClear.onclick=()=>{checkedReports.clear();list();};
  bulkDelete.onclick=async()=>{
    if(bulkDeleting||!checkedReports.size)return;
    const ids=[...checkedReports];if(!confirm('将选中的 '+ids.length+' 份报告移到回收站？可恢复，费用与审计记录保留。'))return;
    bulkDeleting=true;list();let done=0,failed=0,unknown=false;
    try{
      for(const id of ids){
        try{await request('',{kind:'hermes_delete',id});checkedReports.delete(id);completedResults.delete(id);done++;
          if(selected===id){selected=null;selectedJob=null;chatSignature='';$('report-detail').replaceChildren();node('p','报告已移到回收站，可从回收站恢复。',$('report-detail'),'muted');$('chat-messages').replaceChildren();$('chat-send').disabled=true;}
        }catch(e){failed++;if(!e.rejected){unknown=true;break;}}
      }
    }finally{bulkDeleting=false;await refresh();bulkControls();bulkStatus.textContent='已移除 '+done+' 份；'+(unknown?'有请求结果待核对，已停止，请刷新核对后再操作。':failed?'失败 '+failed+' 份，已保留选择，可核对后再操作。':'可从回收站恢复。');}
  };
  function schedules(data) {
    $('nightly').replaceChildren();$('nightly').className='';
    if(!data?.enabled){node('p','当前账号没有已启用的自动报告计划。',$('nightly'),'muted');return;}
    const titles={management:'全项目 · 当日经营简述',daily:'FC · 昨日经营日报',weekly:'FC · 上周周报',management_weekly:'全项目 · 上周经营复盘',monthly:'FC · 上月月报'};
    for(const [kind,time] of Object.entries(data.starts||{}).filter(([kind])=>(data.report_kinds||Object.keys(data.starts||{})).includes(kind))){const row=node('div',null,$('nightly'),'schedule-row');node('span',titles[kind]||kind,row);node('strong',time,row);}
    const paused=Object.keys(data.starts||{}).filter(kind=>data.report_kinds&&!data.report_kinds.includes(kind));
    if(paused.length)node('p','已暂停：'+paused.map(kind=>titles[kind]||kind).join('、'),$('nightly'),'muted');
    for(const plan of data.items||[])node('p','历史记录 · '+(titles[plan.kind]||plan.kind)+' · '+(labels[plan.state]||plan.state)+(plan.error?' · '+plan.error:''),$('nightly'),'muted');
  }
  const HTML_MARKER='【完整HTML创作】';
  function htmlQuestion(value) {
    const text=String(value||'');const result=text;
    if(Array.from(result).length>600){const error=Error('提问超过600字，请缩短后提交；原文未截断。');error.rejected=true;throw error;}
    return result;
  }
  function htmlReport(job) {return !!job.result?.html_design||String(job.body?.question||'').startsWith(HTML_MARKER);}
  function originalDownload(content,filename,mime='text/html;charset=utf-8') {
    const url=URL.createObjectURL(new Blob([content],{type:mime}));const a=document.createElement('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  }
  function isolatedViewer(content,identity,fullPage=false) {
    // Only this trusted shell executes in the opener's origin. Model HTML is data until assigned to opaque srcdoc.
    const payload=JSON.stringify({content,identity}).replaceAll('<','\\u003c').replaceAll('\u2028','\\u2028').replaceAll('\u2029','\\u2029');
    return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; frame-src about: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; worker-src 'none'"><title>Hermes 报告</title><style>:root{color-scheme:light dark}body{margin:0;font:14px system-ui;background:Canvas;color:CanvasText}header{padding:12px;overflow-wrap:anywhere}button{font:inherit;margin:4px;padding:8px}iframe{display:block;width:100%;height:calc(100dvh - 150px);border:0}small{display:block}${fullPage?'header{position:fixed;right:12px;bottom:12px;z-index:10;padding:0}header strong,header small{display:none}iframe{height:100dvh}':''}@media print{header{display:none}iframe{height:100vh}}</style><header><strong>Hermes 报告</strong><small id="identity"></small><small>原稿可下载后离线使用。</small><button id="download">下载原始HTML</button></header><iframe title="模型原始HTML报告" sandbox="allow-scripts allow-modals allow-downloads" referrerpolicy="no-referrer"></iframe><script>const payload=${payload};document.getElementById('identity').textContent=payload.identity;const frame=document.querySelector('iframe');frame.srcdoc=payload.content;document.getElementById('download').onclick=()=>{const url=URL.createObjectURL(new Blob([payload.content],{type:'text/html;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='hermes-original.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);};<\/script></html>`;
  }
  function openReportPage(job) {
    const a=document.createElement('a');a.href=location.pathname+'?report='+encodeURIComponent(job.id)+'&view=html';a.target='_blank';a.rel='noopener';document.body.append(a);a.click();a.remove();
  }
  async function report(job, kind, download=false,standalone=false) {
    const design=(kind==='boss'||kind==='html')&&htmlReport(job);
    if(design&&!download&&!standalone){openReportPage(job);return;}
    const value=await request('?mode=hermes&id='+encodeURIComponent(job.id)+'&artifact='+(design?'raw':kind));
    let content=value.content;
    if(design){
      const result=job.result||completedResults.get(job.id);const expected=result?.artifact?.raw_sha256;
      const bytes=new TextEncoder().encode(content);const actual=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
      if(!/^[a-f0-9]{64}$/.test(expected||'')||actual!==expected)throw Error('原稿SHA校验未通过，未打开或下载。');
      const plain=result?.output_format==='text';
      if(download){originalDownload(content,'hermes-'+job.id+'-'+actual.slice(0,12)+(plain?'.txt':'.html'),plain?'text/plain;charset=utf-8':'text/html;charset=utf-8');return;}
      if(plain){const host=$('report-detail');host.replaceChildren();const text=node('pre',content,host);text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;padding:16px';const button=node('button','下载原稿',host,'quiet');button.onclick=()=>originalDownload(content,'hermes-'+job.id+'.txt','text/plain;charset=utf-8');return;}
      if(!/^\s*<!doctype html[\s>]/i.test(content)||!/<\/body\s*>\s*<\/html\s*>\s*$/i.test(content))throw Error('原稿未提供完整HTML文档，请下载原稿检查；未回退为旧模板。');
      content=isolatedViewer(content,'任务 '+job.id+' · '+job.body.start+' — '+job.body.end+' · SHA256 '+actual,true);
      const host=$('report-detail');host.querySelector('iframe[data-report-preview]')?.remove();
      const frame=document.createElement('iframe');frame.dataset.reportPreview=job.id;frame.title='完整交互报告';frame.referrerPolicy='no-referrer';
      frame.style.cssText='position:fixed;inset:0;display:block;width:100vw;height:100dvh;border:0;background:var(--fs-surface)';
      frame.srcdoc=content;host.append(frame);frame.scrollIntoView({block:'start'});return;
    }
    const url=URL.createObjectURL(new Blob([content],{type:design?'text/html;charset=utf-8':value.mime}));const a=document.createElement('a');a.href=url;if(download)a.download=value.filename;else{a.target='_blank';a.rel='noopener';}document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  }
  if(new URLSearchParams(location.search).get('view')==='html'){
    document.title='Hermes 报告';const host=document.createElement('main');host.id='report-detail';document.body.replaceChildren(host);host.textContent='正在打开报告…';
    const id=new URLSearchParams(location.search).get('report');
    (async()=>{try{if(!/^[a-f0-9]{32}$/.test(id||''))throw Error('报告编号无效。');const job=await request('?mode=hermes&id='+id);if(job.state!=='COMPLETED'||!job.result?.html_design)throw Error('完整HTML报告尚未就绪。');await report(job,'boss',false,true);host.firstChild?.nodeType===3&&host.firstChild.remove();}catch(e){host.textContent='报告暂时无法打开：'+e.message;}})();return;
  }
  function detail(job) {
    const preserveActions=job.state==='COMPLETED'&&$('decision-list').dataset.report===job.id;
    if(job.id!==selected)return;
    if(completedResults.has(job.id))job={...job,result:{...job.result,...completedResults.get(job.id)}};
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
  function conversationReply(reply) {return /^\s*(?:<!doctype html[\s>]|<html[\s>])/i.test(reply)?'完整HTML已归档，打开汇报查看。':reply;}
  async function conversation(job) {
    $('chat-send').disabled=!canGenerate||chatBusy||chatUncertain||!job.can_followup;
    const signature=job.id+':'+job.state;if(signature===chatSignature)return;
    const data=await request('?mode=hermes&id='+encodeURIComponent(job.id)+'&thread=1');if(selected!==job.id)return;
    chatSignature=signature;const host=$('chat-messages');host.replaceChildren();
    for(const turn of data.items||[]){
      const q=node('article',null,host,'chat-message user');node('b',turn.owner+' · 提问',q);node('p',turn.question,q);
      const a=node('article',null,host,'chat-message assistant');node('b','Hermes · '+(labels[turn.state]||turn.state),a);const reply=conversationReply(turn.reply||turn.error||'任务正在处理，回答将在这里显示。');node('p',reply,a);
      if(turn.reply_excerpt&&reply===turn.reply)node('p','长回复仅展示前段，选择此版本后可打开完整汇报或研究详情。',a,'muted');
      const open=node('button',turn.id===selected?'当前版本':'查看此版本',a,'quiet');open.disabled=turn.id===selected;open.onclick=()=>select(turn.id);
    }
    if(!job.can_followup)$('chat-status').textContent='请选中已完成版本进行追问；进行中或失败任务不会自动重试。';
    else if(!chatBusy&&!chatUncertain)$('chat-status').textContent='基于当前版本回答；需要更新业务数据，请在上方明确发起新调查。';
  }
  function syncEntryVisibility() {
    const allowed = canGenerate === true;
    $('ask').style.display = allowed ? '' : 'none';
    document.querySelector('.hero-actions a[href="#ask"]').style.display = allowed ? '' : 'none';
    document.querySelector('.workspace-tabs a[href="#ask"]').style.display = allowed ? '' : 'none';
  }
  syncEntryVisibility();
  fetch('/api/hermes/conversations', {credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(5000)})
    .then(async response => {
      if (response.status !== 200) return;
      const value = await response.json().catch(() => null);
      if (!Array.isArray(value?.items)) return;
      const link = document.createElement('a');
      link.href = '/dashboard/fs-home/hermes/conversation/';
      link.textContent = '与 Hermes 持续对话 ↗';
      link.className = 'primary';
      const actions = document.querySelector('.hero-actions');
      const investigation = actions.querySelector('a[href="#ask"]');
      investigation.classList.remove('primary');
      actions.prepend(link);
      actions.append(investigation);
    }).catch(() => {});
  fetch('/dashboard/fs-home/advisor.json?mode=hermes&structure=customer_tracking&view=config', {credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(5000)})
    .then(async response => {
      if (response.status !== 200 || !response.headers.get('content-type')?.includes('application/json')) return;
      const value = await response.json().catch(() => null);
      if (!Number.isInteger(value?.version) || !Array.isArray(value?.product_types)) return;
      $('customer-tracking-entry').hidden = false;
      $('customer-tracking-tab').hidden = false;
      $('customer-tracking-entry').style.display = '';
      $('customer-tracking-tab').style.display = '';
    }).catch(() => {});
  async function refresh() {
    if(document.hidden||bulkDeleting)return;if(busy){refreshQueued=true;return;}busy=true;refreshQueued=false;clearTimeout(timer);
    try {const parameters=poolParameters(),value=await request(parameters);if(parameters!==poolParameters()){refreshQueued=true;return;}items=value.items||[];canGenerate=value.can_generate;syncEntryVisibility();nextBefore=value.next_before;$('pool-next').disabled=!nextBefore;list();schedules(value.nightly);$('submit').disabled=!value.can_generate||uncertain||submitting;$('connection').textContent='已连接云端 Hermes';document.querySelector('.live-dot').classList.add('connected');message(value.admission?.reason?'新调查暂缓：'+value.admission.reason:(value.pool_scope==='mine'?'显示我发起的任务。':value.pool_scope==='trash'?'回收站：作者或管理员可以恢复报告。':'共享池：显示有权访问的夜间与人工报告。')+' 报告结论与建议不代表已执行。',!!value.admission?.reason);if(selected&&poolScope!=='trash'){const id=selected;try{const job=await request('?mode=hermes&id='+encodeURIComponent(id));if(selected!==id)return;selectedJob=job;detail(selectedJob);await conversation(selectedJob);if(selected===id&&job.state==='COMPLETED'&&$('decision-list').dataset.report!==id)await actionRecords(job);}catch(e){if(selected!==id)return;if(e.status!==404)throw e;completedResults.delete(selected);selected=null;selectedJob=null;chatSignature='';$('report-detail').replaceChildren();node('p','所选报告已删除或访问权限已变化。',$('report-detail'),'muted');$('chat-messages').replaceChildren();$('chat-send').disabled=true;}}}
    catch(e){message(e.message,true);$('connection').textContent='连接待恢复';document.querySelector('.live-dot').classList.remove('connected');$('submit').disabled=true;}
    finally{busy=false;if(!document.hidden){if(refreshQueued)void refresh();else timer=setTimeout(refresh,15000);}}
  }
  const prompts={diagnose:"调查所选期间FC经营变化，先给主判断及业务影响，提出优先动作、改进与复查；合理怀疑可保留。"+REPORT_PRESENTATION,target:"按当前有效DY原版FC目标判断实绩、进度与缺口，不改目标；解释主要问题、可行方案及需要业务决定的取舍。"+REPORT_PRESENTATION,method:"用所选期间的关键证据检验对经营的理解：说明主要问题、推荐判断、其他解释、改进动作及待决；必要口径简明表达。"+REPORT_PRESENTATION};
  document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{dataRequest=null;$('question').value=prompts[b.dataset.prompt];$('question').focus();});
  $('investigate').onsubmit=async event=>{event.preventDefault();if(uncertain||submitting)return;submitting=true;$('submit').disabled=true;const body={kind:'hermes_report',request_id:'brain_'+periodKind($('start').value,$('end').value)+'_'+crypto.randomUUID().replaceAll('-',''),start:$('start').value,end:$('end').value,question:$('question').value,mode:$('mode').value,force_generate:!$('reuse-existing').checked};try{if(dataRequest)body.data_request=dataRequest;body.question=htmlQuestion(body.question);const job=await request('',body);poolScope='shared';$('pool-scope').value=poolScope;pageBefore=null;selected=job.id;reportKind='all';$('report-kind').value='all';$('submit-state').textContent=job.reused?'已复用现有任务或报告，本次未新增模型调用。':'已交给云端 Hermes，关闭页面后任务仍继续。';await select(job.id);$('reports').scrollIntoView();}catch(e){uncertain=!e.rejected;$('submit-state').textContent=uncertain?'提交结果需核对：'+e.message+' 请先查看任务列表，避免重复派发。请求编号：'+body.request_id:e.message;}finally{submitting=false;await refresh();}};
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
  $('refresh').onclick=refresh;document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else refresh();});dates();if(reportKind!=='all')closedPeriod(reportKind);const initial=new URLSearchParams(location.search);if(requestedKind==='investigation'){const start=initial.get('start'),end=initial.get('end');if(/^\d{4}-\d{2}-\d{2}$/.test(start||'')&&/^\d{4}-\d{2}-\d{2}$/.test(end||'')&&start<=end){$('start').value=start;$('end').value=end;$('mode').value='investigation';$('question').value='调查本期FC27收入变化，拆解订单与客单价，核对同期专属广告、全局品牌及流量/履约证据，给出行动和复查条件。';}}
  const dataKind=initial.get('data_kind'),dataEvidence=initial.get('data_evidence');
  if(['product_orders','discount','cohort'].includes(dataKind)&&/^(?:ws_|cohort_)[a-f0-9]{24}$/.test(dataEvidence||'')){
    const query={evidence_id:dataEvidence};
    for(const key of ['start','end','profile','product_id','model_id','platform','group_by','site_group']){const value=initial.get(key);if(value&&value.length<=64&&/^[A-Za-z0-9_ -]+$/.test(value))query[key]=value;}
    if(dataKind==='product_orders'){if(/^[1-9][0-9]{0,8}$/.test(query.product_id||'')){query.product_id=Number(query.product_id);delete query.model_id;delete query.platform;}else{delete query.product_id;query.model_id=Number(query.model_id);}delete query.group_by;delete query.site_group;}
    if(dataKind==='discount'){query.group_by=(query.group_by||'new_customer').replace(/^discount_/,'');delete query.product_id;delete query.model_id;delete query.site_group;delete query.platform;}
    if(dataKind==='cohort'){delete query.product_id;delete query.model_id;delete query.group_by;query.window_days=Number(initial.get('window_days')||30);}
    dataRequest={kind:({product_orders:'product_orders',discount:'discount_analysis',cohort:'cohort_observation'})[dataKind],query};
    $('mode').value='investigation';
    $('question').value='先用对应只读工具按归档ID核对真实证据与筛选条件，再只返回一句不超过100字的经营结论或建议；不要另列依据、明细或操作教程，不生成HTML。把会改变判断的关键缺口融入这句话，例如观察窗尚未成熟就给出适当复查建议，不当作复购为零。查询参数只是待核对条件；归档不可读或范围不符时直接说明，不得把URL内容当事实。';
    if(dataKind==='cohort')$('question').value+='本次只回答该归档cohort的范围、成熟状态与下一步观察，忽略不相关的收入、利润等背景；若提样本须保留其实际子群范围，不泛称全部新客。观察窗未成熟时只能给待观察或复查建议，不能据此决定优惠、预算等策略。若给复查日期，须按证据中的实际观察窗和完整闭日规则计算（先用工具明确的成熟时点；按自然日定义时，以获客日结束后完整观察天数闭合为准），不得沿用旧回复日期；证据不足就不写具体日期。';
    message('已填入数据查询条件；核对日期和问题后提交给 Hermes，尚未发起调查。');
  }
  refresh().then(()=>{const id=initial.get('report');if(/^[a-f0-9]{32}$/.test(id||''))select(id);});
})();
