/* Uses the current FS components and same-origin administrator entry. */
(() => {
  'use strict';
  const API = '/dashboard/fs-home/advisor.json';
  const $ = id => document.getElementById(id);
  if (!$('strategy-review')) return;
  let learning = null, workspace = null;
  const labels = {DRAFT:'新规则待验证',NEEDS_DATA:'待补证',EVIDENCE_READY:'待决策',SIMULATED:'已模拟',NOT_REQUESTED:'未申请执行',NOT_EXECUTED:'未执行',NOT_ELIGIBLE:'尚不可评估效果',UNKNOWN:'执行待核实',INCONCLUSIVE:'证据不足',queued:'待复盘',running:'复盘中',completed:'已完成复盘',failed:'复盘失败',unknown:'结果待核对',candidate:'待审候选',published:'已发布',revoked:'已撤销',pass:'通过',block:'阻断',incomplete:'待补证',base_conflict:'基线已变化',needs_human_review:'待审核'};
  const label = value => labels[value] || value;
  function node(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = String(text);
    if (className) item.className = className;
    return item;
  }
  function detail(parent, title, value) {
    const box = node('details'); box.append(node('summary', title), node('pre', JSON.stringify(value,null,2))); parent.append(box);
  }
  async function request(body) {
    const response = await fetch(API, {method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(20000),headers:{'Content-Type':'application/json','X-FS-Advisor-Action':'submit'},body:JSON.stringify(body)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'unavailable');
    return value;
  }
  function message(id, text) { $(id).textContent = text; }
  function error(id, failure) {
    const text = /conflict|changed/.test(failure.message) ? '版本已变化，请刷新后重新核对。' : /denied|required|scope/.test(failure.message) ? '当前账号无此范围权限。' : '请求未完成，已保留现有记录。请刷新后核对原状态。';
    message(id,text);
  }
  function renderStrategy(data) {
    workspace=data;
    $('strategy-enabled').textContent=data.enabled?'暂停新增草案与模拟':'恢复草案与模拟';
    $('strategy-enabled').disabled=false;
    message('strategy-status', data.capabilities.status==='available' ? `可研究突破原降幅的四档共享折扣，并提出新改价规则；策略版本 ${data.capabilities.baseline_policy.revision}。新算法需验证后才能数值模拟，所有草案均未执行。` : '价格来源暂不可用；仍可查看已有研究与复查记录。');
    const list=$('strategy-records'); list.replaceChildren();
    const review=$('strategy-decision');review.replaceChildren();
    for (const row of data.drafts) {
      const card=node('article',undefined,'knowledge-item');const simulations=data.simulations.filter(s=>s.proposal===row.id);
      card.append(node('h3',row.content.question),node('p',`${simulations.length?'已模拟':row.content.rule_idea&&!row.content.band_changes.length?'新规则待实现验证':'待决策'} · 未申请执行 · 未执行 · 效果尚未验证`, 'pill'),node('p',row.content.hypothesis),node('p',`复查：${row.content.review_plan}`));
      if(row.content.rule_idea)card.append(node('p',`新规则：${row.content.rule_idea.name}；${row.content.rule_idea.description}`));
      detail(card,'草案版本、依据与风险',{id:row.id,hash:row.content_hash,created_at:row.created_at,...row.content});
      for (const simulation of simulations) {
        const result=simulation.content;const table=node('table');const caption=node('caption','只读模拟 · 同一快照下的100K包价（USD）；包含本店赠送');table.append(caption);
        const head=node('thead'),tr=node('tr');for(const text of ['平台','基线包价','候选包价','候选采购毛利']){const th=node('th',text);th.scope='col';tr.append(th);}head.append(tr);table.append(head);
        const body=node('tbody');
        for(const candidate of result.candidate.rows){const base=result.baseline.rows.find(r=>r.platform===candidate.platform);const line=node('tr');const platform=node('th',candidate.platform);platform.scope='row';line.append(platform,node('td',`$${base.target_page_usd}`),node('td',`$${candidate.target_page_usd}`),node('td',`${candidate.gross_margin_pct}%`));body.append(line);}table.append(body);card.append(table);
        card.append(node('p','模拟完成仅表示计算完成；预检仍可能阻断，未获执行授权。','muted'));
        detail(card,'当次来源版本、差异及保护检查',{id:result.id,created_at:simulation.created_at,snapshot_id:result.snapshot_id,snapshot_sha256:result.snapshot_sha256,policy:result.baseline_policy,engine_sha256:result.engine_sha256,candidate_evaluator:result.candidate_evaluator,candidate_evaluator_sha256:result.candidate_evaluator_sha256,guard_hash:result.guard_hash,comparisons:result.comparisons,precheck:result.precheck.map(c=>({...c,status:label(c.status)})),fees_coverage:result.fees_coverage,limitations:result.limitations,write_performed:result.write_performed,execution_authorized:result.execution_authorized});
      }
      list.append(card);const option=node('option',row.content.question);option.value=row.id;review.append(option);
    }
    if(!data.drafts.length)list.append(node('p','尚无本范围策略草案。可在现有对话或调查中提出研究问题；草案不会直接应用。','empty'));
    const actions=new Map();for(const event of data.action_history)actions.set(`${event.report}:${event.action}`,event);
    const history=$('strategy-actions');history.replaceChildren();
    for(const [id,event] of actions){const option=node('option',`历史动作 · ${event.action_snapshot?.title || event.action}`);option.value=id;review.append(option);const card=node('article',undefined,'knowledge-item');card.append(node('p',`原账本：${event.status} · ${event.recorded_at}`),node('p','人工记录保留；实际执行、观察成熟度和效果仍须核证。'));detail(card,'原行动记录',event);history.append(card);}
    if(!actions.size)history.append(node('p','本范围行动账本暂无可读记录；这不代表从未做过运营。真实动作效果暂不评价。','empty'));
    $('strategy-review-submit').disabled=review.options.length===0;
    for(const name of ['start','end'])if(!$('strategy-'+name).value)$('strategy-'+name).value=$(name)?.value || '';
    const methods=$('method-candidates');methods.replaceChildren();
    for(const item of data.method_candidates){const card=node('article',undefined,'knowledge-item');card.append(node('p',`方法差异 · ${label(item.state)} · ${item.risk} · 未发布`),node('p',item.content.lesson_diff));detail(card,'方法基线与来源',{id:item.id,source:item.source,base_manifest:item.base_manifest,created_at:item.created_at});methods.append(card);}
    if(!data.method_candidates.length)methods.append(node('p','暂无方法差异候选。','muted'));
  }
  function renderLearning(data) {
    learning=data;const active=new Set(data.experiences.map(x=>x.id));const release=new Map();
    for(const item of data.publication_events || [])if(!release.has(item.experience))release.set(item.experience,item);
    message('learning-status',`正式经验 ${data.experiences.length} 条；候选 ${data.candidates.length} 条。自动发布关闭；新学习入队${data.paused?'已暂停':'可用'}。`);
    const list=$('learning-records');list.replaceChildren();const select=$('learning-version');select.replaceChildren();
    for(const item of data.candidates){const content=JSON.parse(item.content);const state=active.has(item.id)?'已发布':release.get(item.id)?.state==='revoked'?'已撤销':'待审候选';const card=node('article',undefined,'knowledge-item');card.append(node('h3',content.lesson),node('p',`${state} · ${item.risk} · 收益未验证`,'pill'),node('p',`适用：${content.applies_to}`),node('p',`反例或限制：${content.counterexample}`));detail(card,'版本、来源及发布记录',{id:item.id,hash:item.content_hash,event:item.event,expires_at:item.expires_at,evidence_refs:content.evidence_refs,publication:release.get(item.id) || null});list.append(card);const option=node('option',`${state} · ${content.lesson.slice(0,45)}`);option.value=item.id;select.append(option);}
    if(!data.candidates.length)list.append(node('p','暂无经验候选；已有教学方法继续按原版本使用。','empty'));
    $('learning-submit').disabled=!select.options.length;$('learning-pause').textContent=data.paused?'恢复新学习入队':'暂停新学习入队';$('learning-pause').disabled=false;
    const sources=$('learning-source'),selected=sources.value;sources.replaceChildren();
    for(const source of new Set(data.events.map(e=>e.source))){const option=node('option',`报告 ${source}`);option.value=source;sources.append(option);}
    if([...sources.options].some(o=>o.value===selected))sources.value=selected;
    $('learning-reflect-submit').disabled=data.paused || !sources.options.length;
    detail(list,'学习批次与失败记录',data.events.map(e=>({id:e.id,source:e.source,state:label(e.state),attempt:e.attempt,result:e.result?JSON.parse(e.result):null})));
  }
  async function loadStrategy(){message('strategy-status','正在读取策略与复查记录…');try{renderStrategy(await request({kind:'hermes_strategy',action:'list'}));}catch(e){error('strategy-status',e);}}
  async function loadLearning(){message('learning-status','正在读取经验与方法…');try{renderLearning(await request({kind:'hermes_learning',action:'list'}));}catch(e){error('learning-status',e);}}
  function refresh(id,load){$(id).addEventListener('click',async()=>{const button=$(id);button.disabled=true;try{await load();}finally{button.disabled=false;}});}
  refresh('strategy-refresh',loadStrategy);refresh('learning-refresh',loadLearning);
  $('strategy-enabled').addEventListener('click',async()=>{const button=$('strategy-enabled');button.disabled=true;try{await request({kind:'hermes_strategy',action:'set_enabled',enabled:!workspace.enabled});await loadStrategy();}catch(e){error('strategy-status',e);}finally{button.disabled=false;}});
  $('learning-pause').addEventListener('click',async()=>{const button=$('learning-pause');button.disabled=true;try{await request({kind:'hermes_learning',action:learning.paused?'resume':'pause'});await loadLearning();}catch(e){error('learning-status',e);}finally{button.disabled=false;}});
  $('learning-reflect').addEventListener('submit',async event=>{event.preventDefault();const button=$('learning-reflect-submit');button.disabled=true;try{
    const entry=await request({kind:'hermes_learning',action:'enqueue',source:$('learning-source').value,correction:$('learning-feedback').value});
    if(entry.state==='queued'){await request({kind:'hermes_learning',action:'review_model',event:entry.id});message('learning-reflect-status',`Hermes 正在独立复盘；批次 ${entry.id}。请刷新查看候选，迁移能力尚未验证。`);}
    else message('learning-reflect-status',`原批次状态：${label(entry.state)}。已保留原记录，未重复调用模型；经验保存不代表已经学会。`);
    await loadLearning();
  }catch(e){error('learning-reflect-status',e);}finally{button.disabled=!!learning?.paused || !$('learning-source').options.length;}});
  $('learning-publish').addEventListener('submit',async event=>{event.preventDefault();const button=$('learning-submit');button.disabled=true;try{await request({kind:'hermes_learning',action:new FormData(event.target).get('action'),id:$('learning-version').value,expected_manifest:learning.sha256,reason:$('learning-reason').value});message('learning-action-status','知识版本操作已记录；新任务按新版本检索，旧任务保留原引用。');await loadLearning();}catch(e){error('learning-action-status',e);}finally{button.disabled=!learning?.candidates.length;}});
  $('strategy-review-form').addEventListener('submit',async event=>{event.preventDefault();const button=$('strategy-review-submit');button.disabled=true;try{const result=await request({kind:'hermes_strategy',action:'read_review',decision_id:$('strategy-decision').value,start:$('strategy-start').value,end:$('strategy-end').value});message('strategy-review-status',`${label(result.execution_state)} · ${label(result.outcome_state)}`);$('strategy-review-result').textContent=JSON.stringify(result,null,2);}catch(e){error('strategy-review-status',e);}finally{button.disabled=!$('strategy-decision').options.length;}});
  loadStrategy();loadLearning();
})();
