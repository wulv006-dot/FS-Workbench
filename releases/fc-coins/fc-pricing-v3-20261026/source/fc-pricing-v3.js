(() => {
  'use strict';
  const base='/api/fc27/cloud/pricing/v3';
  const names={daily:'日常经营',acquisition:'拉新增长',backlog:'交付积压（已支付新单 / 验证通过 / 发货中）',flash_sale:'限时促销',revenue_sprint:'冲销售额'};
  const $=id=>document.getElementById(id);
  let current,loading=false,acting=false,manualPreview=null,selectedPlanId=null,displayedMode='revenue_sprint',canWrite=false,permissionKnown=false;
  const statuses={DRAFT:'待启用',SCHEDULED:'等待开始',ACTIVE:'执行中',SUSPENDED:'已暂停新写入',ENDING:'正在退出',ENDED:'已结束',
    READY:'已有可行方案',INFEASIBLE:'当前证据下无可行报价',DATA_PENDING:'数据待补齐',BUDGET_EXHAUSTED:'预算已用尽',
    AUTHORIZED:'已授权待执行',DISPATCHED:'已发出请求',UNKNOWN:'结果未知，按原编号核对',PARTIALLY_APPLIED:'部分已应用，待原编号核对',
    BACKEND_CONFIRMED:'后台已确认，待后续核验',CACHE_CONFIRMED:'缓存已确认，待公开核验',PUBLIC_PENDING:'公开价格待核',
    COMPLETED:'公开核验完成',NO_CHANGE:'核算后无需改价',OPEN:'待处理',available:'数据可用',partial:'部分数据可用',
    legacy_replay_gap:'旧版证据不足',legacy_source_version_mismatch:'旧版源码版本不符',no_feasible_price:'无可行价格',
    queued:'已登记待处理',queued_or_missing:'排队中或结果尚未生成',scenario_projection:'需求情景预测',
    causal_identification_unavailable:'缺少可识别的实验依据',identified_randomized_estimate:'实验估计可用',
    missing_at_historical_asof:'当时尚不可得',common_guard_contract_missing:'统一护栏证据缺失',
    baseline_pending_no_simulated_orders_fabricated:'缺少绝对需求基线，未虚构订单',
    historical_orders_missing:'缺少真实历史订单或成本证据，金额未核算',
    late_order_revision_not_repriced:'原订单后来修订；不以未来条款倒算旧窗口'};
  function statusText(raw){return raw==null?'待核':statuses[raw]||names[raw]||`待核（${raw}）`;}
  function errorText(error){
    const code=error.message||String(error);
    const known={pricing_snapshot_required:'缺少本轮真实快照，请先采集并核对来源',pricing_plan_scope_invalid:'计划范围不符合当前可修改资源',
      pricing_plan_required:'当前没有可执行的活动计划',pricing_resource_unresolved:'原操作尚未对账，此范围暂不可写',
      pricing_manual_preview_expired:'人工预览已过期，请重新核算',pricing_manual_infeasible:'当前明确价未通过新鲜财务或市场证明',
      pricing_operation_missing:'未找到该原操作编号',state_unavailable:'状态暂时无法读取'};
    return known[code]||(/^pricing_[a-z_]+(?::.*)?$/.test(code)?`操作未完成；请核对当前状态和原编号。技术原因：${code}`:code);
  }
  const modeDefaults={daily:{offsets:'-8,-4,0,4,8',allocation:['0.2','0.6','0.2']},acquisition:{offsets:'-20,-15,-10,-5,0,5',allocation:['0.2','0.4','0.4']},backlog:{offsets:'0,5,10,15,20',allocation:['0','1','0'],reserve:'0.1'},flash_sale:{offsets:'-25,-20,-15,-10,-5,0',allocation:['0.1','0.6','0.3']},revenue_sprint:{allocation:['0.1','0.7','0.2'],undercut:'1'}};
  const modeDrafts={};
  function requestKey(kind){const name='fc-v3-'+kind;let key=sessionStorage.getItem(name);if(!key){key=crypto.randomUUID();sessionStorage.setItem(name,key);}return key;}
  function clearKey(kind){sessionStorage.removeItem('fc-v3-'+kind);}
  function chosenPlan(){return (current?.plans||[]).find(p=>p.plan_id===selectedPlanId)||current?.plan;}
  function formParameters(){
    const mode=$('v3-mode').value;
    const allocation=Object.fromEntries(['control','exploit','explore'].map(k=>[k,$('v3-alloc-'+k).value]));
    if(Math.abs(Object.values(allocation).reduce((n,v)=>n+Number(v),0)-1)>1e-9)throw Error('对照、优选、探索分配之和必须为1');
    const parameters={allocation};
    if(mode==='revenue_sprint')parameters.preferred_undercut_pct=$('v3-undercut').value;
    else{parameters.offsets_pct=$('v3-offsets').value.split(',').map(v=>v.trim());if(parameters.offsets_pct.some(v=>v===''||!Number.isFinite(Number(v))))throw Error('候选偏移须为逗号分隔的数字');}
    if(mode==='backlog')parameters.capacity_reserve_ratio=$('v3-reserve').value;
    return parameters;
  }
  function saveModeDraft(){modeDrafts[displayedMode]={offsets:$('v3-offsets').value,allocation:['control','exploit','explore'].map(k=>$('v3-alloc-'+k).value),reserve:$('v3-reserve').value,undercut:$('v3-undercut').value};}
  function setMode(mode){const draft=modeDrafts[mode]||modeDefaults[mode];$('v3-offsets').value=draft.offsets||'';['control','exploit','explore'].forEach((k,i)=>$('v3-alloc-'+k).value=draft.allocation[i]);$('v3-reserve').value=draft.reserve||'0.1';$('v3-undercut').value=draft.undercut||'1';for(const [id,visible] of [['v3-offsets',mode!=='revenue_sprint'],['v3-reserve',mode==='backlog'],['v3-undercut',mode==='revenue_sprint']]){$(id).hidden=!visible;$(id).previousElementSibling.hidden=!visible;}}
  function node(tag,text){const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;}
  function value(v){return v==null?'待配置 / 待核':String(v);}
  function usd(v){return v==null?'待核':`$${Number(v).toFixed(2)}`;}
  function yuan(v){return v==null?'待核':`¥${Number(v).toFixed(2)}`;}
  function targetText(target={}){
    const goal=target.amount==null?'月目标待配置':`月目标 ${usd(target.amount)}`;
    const through=target.through_date?`截至 ${target.through_date}`:'截至已核时点';
    const exact=target.mtd_exact;
    const lower=target.mtd_lower_bound??target.mtd;
    let progress=exact!=null?`${through}净实付已完成 ${usd(exact)}`:
      lower!=null?`${through}已核净实付至少 ${usd(lower)}${target.mtd_upper_bound!=null?`，当前可核区间上界 ${usd(target.mtd_upper_bound)}`:''}`:'已完成金额待核';
    if(target.today?.status==='unavailable')progress+='；今日订单待补';
    return `${goal} · ${progress} · ${target.target_scope||'site266 FC27 Coins'}`;
  }
  function historySummary(result){
    if(!result.records)return `任务 ${result.simulation_id} 仍在处理或来源缺失。`;
    const rows=result.records.map(r=>{
      if(r.status==='historical_orders_missing')return `${r.snapshot_id} · ${statusText(r.status)} · ${(r.gaps||[]).join('；')}`;
      if(r.status==='late_order_revision_not_repriced')return `${r.snapshot_id} · ${statusText(r.status)} · 修订原单 ${r.revised_order_count} 个`;
      if(r.actual)return `${r.snapshot_id} · 当时新增${r.actual.order_count}单、净实付 ${usd(r.actual.net_revenue_usd)} · ${r.revised_order_count?`原单后来修订${r.revised_order_count}条；截至此时去重累计 ${usd(r.cumulative_actual?.net_revenue_usd)}、USD采购贡献 ${usd(r.cumulative_actual?.procurement_contribution_usd)}、同单CNY覆盖毛利 ${yuan(r.cumulative_actual?.covered_procurement_gross_cny)}`:`USD采购贡献 ${usd(r.actual.procurement_contribution_usd)}；同单CNY覆盖${r.actual.cny_covered_orders||0}单、Admin快照采购毛利 ${yuan(r.actual.covered_procurement_gross_cny)}`} · ${statusText(r.status)}`;
      if(r.alternatives)return `${r.snapshot_id} · 固定${r.fixed_order_count}单 · ${Object.entries(r.alternatives).map(([name,value])=>`${names[name]||name}:${statusText(value.status)}/${usd(value.totals?.net_revenue_usd)}${value.source_sha256?` (源码 ${value.source_sha256.slice(0,12)})`:''}`).join('；')}`;
      if(r.path)return `${names[r.path.policy]} · 情景收入 ${usd(r.path.revenue)} · ${statusText(r.status)}`;
      return `${statusText(r.status)} · 效果 ${r.effect_usd==null?'不可识别':usd(r.effect_usd)} · ${(r.gaps||[]).join('；')}`;
    });
    const reconciled=result.reconciled_actual;
    const latest=reconciled?`截至 ${reconciled.as_of} 按原订单去重及后到修订：${reconciled.actual.order_count}单、净实付 ${usd(reconciled.actual.net_revenue_usd)}、USD采购贡献 ${usd(reconciled.actual.procurement_contribution_usd)}、CNY同单覆盖毛利 ${yuan(reconciled.actual.covered_procurement_gross_cny)}；修订原单 ${reconciled.revised_order_count} 个。\n`:'';
    return `${result.simulation_kind} · ${result.rule_mode} · ${latest}${rows.join('\n')}\nCNY采购毛利仅用同单Admin人民币收入快照减Order历史实际成本；Admin快照按取数时汇率展示，不与USD实结互换。历史实绩、金额重算、需求情景与因果估计口径分开。`;
  }
  async function request(path,body){
    const response=await fetch(base+'/'+path,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(20000),
      ...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||`请求失败 ${response.status}`);
    return result;
  }
  async function writePermission(){
    const response=await fetch('/api/fc27/cloud/automation',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(20000)});
    if(!response.ok)throw Error('操作权限读取失败');
    return (await response.json()).can_manage_v3===true;
  }
  function writeControls(){
    for(const id of ['v3-target-form','v3-plan-form','v3-manual-form','v3-reconcile-form'])
      for(const control of $(id).querySelectorAll('input,select,button'))control.disabled=!canWrite;
    $('v3-history-run').disabled=!canWrite;
  }
  function table(id,rows){
    const body=$(id);body.replaceChildren();
    if(!rows.length){const tr=node('tr'),td=node('td','尚无记录');td.colSpan=8;tr.append(td);body.append(tr);return;}
    for(const cells of rows){const tr=node('tr');for(const cell of cells)tr.append(node('td',value(cell)));body.append(tr);}
  }
  function render(state){
    current=state;
    const plans=state.plans||[],list=$('v3-plan-select');
    list.replaceChildren();for(const p of plans){const option=node('option',`${names[p.mode]} · ${p.plan_id} · ${p.state}`);option.value=p.plan_id;list.append(option);}
    if(!plans.some(p=>p.plan_id===selectedPlanId))selectedPlanId=state.active_plans?.[0]?.plan_id||plans[0]?.plan_id||null;
    list.value=selectedPlanId||'';
    const plan=chosenPlan();
    $('v3-state').textContent=(plan?`${names[plan.mode]} · ${statusText(plan.state)} · 数据 ${state.captured_at||'尚未取得'} · ${state.generation?'统一控制权已登记':'尚未切换'}`:'尚无活动计划；历史价格保留，等待统一控制权切换')+
      (permissionKnown?(canWrite?' · 当前账户可操作':' · 当前账户仅可查看'):' · 操作权限待核');
    $('v3-target').textContent=targetText(state.target||{});
    if(document.activeElement!==$('v3-target-amount'))$('v3-target-amount').value=state.target?.amount??'';
    const observation=(state.latest_market_observations||[])[0],eld=observation?.eldorado;
    const eldState=observation?.status==='started'?'采样中':eld?.status==='observed'?'三平台已观察':eld?.status==='partial'?'部分平台已观察':eld?.status==='failed'?'采样失败':'尚无真实采样';
    $('v3-eld-status').textContent=observation?`${eldState} · ${observation.completed_at||observation.started_at||'时点待核'} · 关联本轮 ${observation.run_id}；仅为已观察卖家报价，不代表全站最低，也不参与当前定价。`:'尚无 ELD 真实采样；仅观察，不参与当前定价。';
    const eldRows=new Map((eld?.platforms||[]).map(row=>[row.platform,row]));
    table('v3-eld-platforms',observation?['PS','XBOX','PC'].map(platform=>{const row=eldRows.get(platform);return [platform,row?.status==='observed'?'已观察':row?.status?'未取得（'+row.status+'）':'未取得',row?.status==='observed'&&row.lowest_observed_100k_usd!=null?usd(row.lowest_observed_100k_usd):'待核',row?.eligible_100k_sellers??'待核'];}):[]);
    const scopes=$('v3-region-scopes'),checked=new Set([...scopes.querySelectorAll('input:checked')].map(input=>input.value));scopes.replaceChildren();for(const control of state.regional_controls||[]){if(control.region_id!==21||!control.resource)continue;const label=node('label'),input=node('input');input.type='checkbox';input.value=control.resource;input.dataset.regionScope='1';input.checked=checked.has(control.resource);label.append(input,node('span',`Saudi Arabia ${control.platforms.join('/')}`));scopes.append(label);}
    const cards=$('v3-strategies');cards.replaceChildren();
    for(const [mode,name] of Object.entries(names)){
      const r=state.strategies?.[mode],card=node('article');card.className='panel';
      card.append(node('h3',name),node('p',r?.status?statusText(r.status):'等待同一快照'));
      if(r?.selected){const s=r.selected;card.append(node('p',`Console ${usd(s.action.base_prices.console)} · PC ${usd(s.action.base_prices.pc)}`),node('p',s.score.absolute_forecast_available?`预测收入 ${usd(s.score.revenue)} · 采购贡献 ${usd(s.score.contribution)}`:'先验相对场景；绝对收入 / 新客预测待核'));
      }else if(r?.failures?.length)card.append(node('p',`当前无法形成可执行报价；技术原因：${r.failures.map(f=>f.code).join('；')}`));
      cards.append(card);
    }
    const latest=state.operations?.[0],proof=latest?.bundle?.financial_proof?.prices||{};
    const matrix=[];
    for(const [key,p] of Object.entries(proof))matrix.push([key,usd(p.price.regular_usd),p.price.delivered_k,p.coefficient||'1',p.rule_id||'默认',p.catalog.minimum_estimated_average_margin_pct,p.catalog.worst_published_margin_pct,latest.status]);
    for(const rule of state.region_rules||[])if(!matrix.some(r=>r[0].startsWith(String(rule.region_id)+':')))for(const platform of rule.platforms)matrix.push([`${rule.region_id}:${platform}`,'待联合证明','待核',rule.factor,rule.id,'待核','待核',rule.verification_status||'待核']);
    table('v3-regions',matrix);
    table('v3-operations',(state.operations||[]).map(o=>[o.created_at,names[o.bundle?.mode]||'待核',statusText(o.status),o.operation_id,statusText(o.readback?.public?.status),statusText(o.cache_receipt?.status)]));
    table('v3-incidents',(state.incidents||[]).map(i=>[i.code,i.dependency,statusText(i.state),i.first_seen,i.last_seen,i.attempt]));
    writeControls();
    list.disabled=!plans.length;
    $('v3-plan-stop').disabled=!canWrite||!plan||['ENDED','ENDING'].includes(plan.state);
    $('v3-plan-pause').disabled=!canWrite||!plan||!['ACTIVE','SUSPENDED'].includes(plan.state);
    $('v3-plan-pause').textContent=plan?.state==='SUSPENDED'?'恢复当前计划':'暂停新写入';
    $('v3-execute').disabled=!canWrite||!plan||plan.state!=='ACTIVE';
    $('v3-manual-execute').disabled=!canWrite||!manualPreview||!plan||plan.plan_id!==manualPreview.plan_id||Date.now()>=Date.parse(manualPreview.valid_until);
    $('v3-history-read').disabled=!$('v3-history-id').value.trim();
    for(const id of ['candidate-form','restore-form','preview','execute','hermes-restore','hermes-review'])if($(id))$(id).hidden=true;
  }
  async function refresh(){
    if(loading)return;loading=true;$('v3-panel').setAttribute('aria-busy','true');$('v3-refresh').disabled=true;$('v3-refresh').textContent='正在读取…';
    try{const [state,permission]=await Promise.all([request('state'),writePermission().then(value=>({known:true,value})).catch(()=>({known:false,value:false}))]);
      permissionKnown=permission.known;canWrite=permission.value;render(state);
      $('v3-error').textContent=permissionKnown?'':'操作权限暂时无法核对，写入入口已停用；只读状态仍可查看。';}
    catch(error){$('v3-error').textContent=`未完成：${errorText(error)}。旧值保留其原时点。`;}
    finally{loading=false;$('v3-refresh').disabled=false;$('v3-refresh').textContent='更新统一状态';$('v3-panel').removeAttribute('aria-busy');}
  }
  async function action(fn){
    if(acting)return;acting=true;$('v3-panel').setAttribute('aria-busy','true');$('v3-result').textContent='请求处理中，请等待原请求回执。';
    try{await fn();$('v3-result').textContent='请求已登记；实际状态以后台、缓存与公开读回为准。';await refresh();}
    catch(error){$('v3-error').textContent=`未完成：${errorText(error)}`;$('v3-error').focus();}
    finally{acting=false;$('v3-panel').removeAttribute('aria-busy');}
  }
  $('v3-mode').addEventListener('change',()=>{saveModeDraft();displayedMode=$('v3-mode').value;setMode(displayedMode);});setMode(displayedMode);
  $('v3-plan-select').addEventListener('change',()=>{selectedPlanId=$('v3-plan-select').value;manualPreview=null;render(current);});
  $('v3-manual-form').addEventListener('input',()=>{if(manualPreview){manualPreview=null;$('v3-manual-execute').disabled=true;$('v3-manual-result').textContent='输入已改变，请重新进行只读预览。';}});
  $('v3-history-id').addEventListener('input',()=>{$('v3-history-read').disabled=!$('v3-history-id').value.trim();});
  $('v3-target-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{await request('monthly-target',{request_key:requestKey('target'),amount:$('v3-target-amount').value||null});clearKey('target');});});
  $('v3-plan-form').addEventListener('submit',event=>{
    event.preventDefault();action(async()=>{
      const data={request_key:requestKey('plan'),mode:$('v3-mode').value,daily_budget:$('v3-budget').value,resources:[],parameters:formParameters()};
      if($('v3-console').checked)data.resources.push('base:console');if($('v3-pc').checked)data.resources.push('base:pc');
      for(const input of $('v3-region-scopes').querySelectorAll('input:checked'))data.resources.push(input.value);
      if(!data.resources.length)throw Error('至少选择一个基础价或Saudi Arabia范围');
      if($('v3-start').value)data.starts_at=new Date($('v3-start').value).toISOString();
      if($('v3-end').value)data.ends_at=new Date($('v3-end').value).toISOString();
      const plan=await request('plans',data);selectedPlanId=plan.plan_id;await request(`plans/${plan.plan_id}/activate`,{});clearKey('plan');
    });
  });
  $('v3-plan-stop').addEventListener('click',()=>action(()=>request(`plans/${chosenPlan().plan_id}/stop`,{})));
  $('v3-plan-pause').addEventListener('click',()=>action(()=>request(`plans/${chosenPlan().plan_id}/${chosenPlan().state==='SUSPENDED'?'resume':'pause'}`,{})));
  $('v3-execute').addEventListener('click',()=>action(()=>request('execute',{request_key:'cycle-'+current.snapshot_id+'-'+chosenPlan().plan_id,plan_id:chosenPlan().plan_id})));
  $('v3-preview').addEventListener('click',()=>action(async()=>{
    const result=await request('preview',{mode:$('v3-mode').value});
    $('v3-preview-output').textContent=Object.entries(result.results).map(([m,r])=>`${names[m]}：${statusText(r.status)}；${r.selected?`Console ${usd(r.selected.action.base_prices.console)} / PC ${usd(r.selected.action.base_prices.pc)}`:`技术原因 ${(r.failures||[]).map(f=>f.code).join('；')}`}`).join('\n');
  }));
  $('v3-manual-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
    const restore=$('v3-restore-id').value.trim();
    const data={request_key:requestKey('manual-preview'),reason:$('v3-manual-reason').value,plan_id:chosenPlan()?.plan_id};
    if(restore)data.restore_source_execution_id=restore;
    else{data.explicit_prices={};if($('v3-manual-console').value)data.explicit_prices.console=$('v3-manual-console').value;if($('v3-manual-pc').value)data.explicit_prices.pc=$('v3-manual-pc').value;}
    manualPreview=await request('manual-previews',data);clearKey('manual-preview');
    const action=manualPreview.selected?.action?.base_prices||manualPreview.explicit_prices;
    const regions=Object.entries(manualPreview.selected?.action?.region_coefficients||{}).map(([key,factor])=>`${key} 系数 ${factor}`).join('；');
    const proof=Object.entries(manualPreview.selected?.financial_proof?.prices||{}).map(([key,row])=>`${key}：未优惠 ${value(row.catalog?.worst_published_margin_pct)}% / 七日结构 ${value(row.catalog?.minimum_estimated_average_margin_pct)}%`).join('；');
    $('v3-manual-result').textContent=`只读财务与市场重证已完成：Console ${usd(action.console)} / PC ${usd(action.pc)}。${regions}。${proof}。预览 ${manualPreview.manual_preview_id}；有效至 ${manualPreview.valid_until}。确认后由同一新鲜采集链再次核准。`;
  });});
  $('v3-manual-execute').addEventListener('click',()=>action(async()=>{
    if(!manualPreview||Date.now()>=Date.parse(manualPreview.valid_until))throw Error('人工预览已过期，请重新核算');
    const result=await request('execute',{request_key:'manual-'+manualPreview.manual_preview_id,manual_preview_id:manualPreview.manual_preview_id,plan_id:manualPreview.plan_id});
    $('v3-manual-result').textContent=`已登记原请求 ${result.job_key}；等待同一新鲜来源重证与原操作读回。`;
    manualPreview=null;
  }));
  $('v3-reconcile-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
    const operation=$('v3-reconcile-id').value.trim();
    await request('reconcile/'+operation,{request_key:requestKey('reconcile-'+operation)});
    clearKey('reconcile-'+operation);
    $('v3-result').textContent=`已请求核对原操作 ${operation}；不重复保存价格。`;
  });});
  $('v3-shadow-read').addEventListener('click',()=>action(async()=>{
    const [result,summaries]=await Promise.all([request('shadow'),request('shadow/summary')]);
    table('v3-shadow',(result.paths||[]).map(p=>[names[p.policy],p.sequence,p.last_as_of,usd(p.revenue),usd(p.contribution),statusText(p.absolute_rollforward_status||p.effective_mode)]));
    $('v3-history-result').textContent=`最近影子汇总 ${summaries.summaries?.length||0} 条；路径金额仅为情景模拟。`;
  }));
  $('v3-history-run').addEventListener('click',()=>action(async()=>{
    const result=await request('simulations',{request_key:requestKey('history'),kind:$('v3-history-kind').value,closed_days:Number($('v3-history-days').value)});
    clearKey('history');
    $('v3-history-id').value=result.simulation_id;
    $('v3-history-result').textContent=`历史任务 ${result.simulation_id} 已登记；读取中。`;
    const latest=await request('simulations/'+result.simulation_id);
    $('v3-history-result').textContent=historySummary(latest);
  }));
  $('v3-history-read').addEventListener('click',()=>action(async()=>{
    if(!$('v3-history-id').value)throw Error('请先登记历史任务');
    $('v3-history-result').textContent=historySummary(await request('simulations/'+$('v3-history-id').value));
  }));
  $('v3-refresh').addEventListener('click',refresh);
  writeControls();$('v3-history-read').disabled=true;$('v3-plan-select').disabled=true;
  setInterval(()=>{if(!document.hidden)refresh();},60000);refresh();
})();
