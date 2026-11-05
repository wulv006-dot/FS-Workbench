(() => {
  'use strict';
  const base='/api/fc27/cloud/pricing/v3';
  const names={smart:'智能决策',daily:'日常运营（备用）',revenue_sprint:'冲销售额'};
  const purposes={smart:'每小时重算冲额基准；每3小时选择基准、上调3%或上调6%，按当轮财务和竞品上限复核。48小时后按成熟数据评价；同价合并，不视为有效价差。',daily:'Lootbar有效时保留计划锚点与采购贡献目标；Lootbar缺价时按ItemD2R当轮实际交付价定价，低于双20合法底价则用底价并标未达到Item目标。两家均缺的平台按八日实际优惠后平均30%求最低价；Console共价按较低Item目标并披露各平台差价。',revenue_sprint:'两家有效取较低价，一家缺价用另一家；两家均缺则无竞争目标，按100K双20最低合法价。竞争锚低5–10%冲额，默认偏好7.5%；沙特额外比较Arab-UT普通发货。'};
  const $=id=>document.getElementById(id);
  let current,loading=false,acting=false,manualPreview=null,selectedPlanId=null,displayedMode='smart',canWrite=false,permissionKnown=false,playerRevision=null,playerDirty=false,collectPending=sessionStorage.getItem('fc-v3-collect-job'),automationRevision=null,lastAutomation=null,lastMonitor=null;
  const statuses={DRAFT:'待启用',SCHEDULED:'等待开始',ACTIVE:'执行中',SUSPENDED:'已暂停新写入',ENDING:'正在退出',ENDED:'已结束',
    READY:'已有可行方案',INFEASIBLE:'当前证据下无可行报价',DATA_PENDING:'数据待补齐',
    AUTHORIZED:'已授权待执行',DISPATCHED:'已发出请求',RUNNING:'执行中',CONFIRMED:'后台已确认',FAILED:'执行失败，保留原编号',CANCELLED:'已取消',CANCELLED_NOT_SENT:'已核实未发送并取消',SUPERSEDED:'已由更新计划接替',
    UNKNOWN:'结果未知，按原编号核对',PARTIALLY_APPLIED:'部分已应用，待原编号核对',KNOWN_PARTIAL_EXITED:'部分已应用，已退出新写入',PUBLIC_CONFIRMED:'公开已核实',
    BACKEND_CONFIRMED:'后台已确认，待后续核验',CACHE_CONFIRMED:'缓存已确认，待公开核验',PUBLIC_PENDING:'公开价格待核',
    COMPLETED:'公开核验完成',NO_CHANGE:'核算后无需改价',OPEN:'待处理',available:'数据可用',partial:'部分数据可用',
    legacy_replay_gap:'旧版证据不足',legacy_source_version_mismatch:'旧版源码版本不符',no_feasible_price:'无可行价格',
    queued:'已登记待处理',queued_or_missing:'排队中或结果尚未生成',scenario_projection:'需求情景预测',
    submitted:'已提交，等待原任务回执',completed:'已完成',failed:'执行失败，保留原编号',unknown:'结果未知，按原编号核对',
    review_prepared:'效果数据已准备',input_ready:'历史数据已准备',pending:'原任务处理中',
    causal_identification_unavailable:'缺少可识别的实验依据',identified_randomized_estimate:'实验估计可用',
    missing_at_historical_asof:'当时尚不可得',common_guard_contract_missing:'统一护栏证据缺失',
    baseline_pending_no_simulated_orders_fabricated:'缺少绝对需求基线，未虚构订单',
    historical_orders_missing:'缺少真实历史订单或成本证据，金额未核算',
    late_order_revision_not_repriced:'原订单后来修订；不以未来条款倒算旧窗口',
    NO_SAFE_COMMIT_PATH:'基础价与地区系数没有可证的当前写入顺序',
    pricing_regional_competitive_band:'地区价格舍入后未达到本轮竞争区间',
    'pricing_required_market_missing:ArabUT:PC':'Arab-UT 未提供可核的 PC 普通发货价',
    pricing_capacity_data_pending:'缺少可核供应能力或正常交付队列基数'};
  function statusText(raw){return raw==null?'待核':statuses[raw]||names[raw]||`待核（${raw}）`;}
  function errorText(error){
    const code=error.message||String(error);
    const known={pricing_snapshot_required:'缺少本轮真实快照，请先采集并核对来源',pricing_plan_scope_invalid:'计划范围不符合当前可修改资源',
      pricing_plan_required:'当前没有可执行的活动计划',pricing_resource_unresolved:'原操作尚未对账，此范围暂不可写',pricing_smart_scope_requires_all_owned_resources:'智能决策须同时接管Console、PC和现有Saudi范围，请刷新后重试',
      pricing_manual_preview_expired:'人工预览已过期，请重新核算',pricing_manual_infeasible:'当前明确价未通过新鲜财务或市场证明',
      pricing_operation_missing:'未找到该原操作编号',state_unavailable:'状态暂时无法读取',
      pricing_price_control_revision_changed:'配置已被更新，请刷新状态后再保存',pricing_manual_price_required:'开启人工干预时须填写 Console 和 PC 的后台单价',
      pricing_manual_unit_precision:'后台单价最多保留四位小数',pricing_price_control_conflicts_with_manual_preview:'请先关闭人工干预和临时涨价，再使用单次人工预览'};
    return known[code]||(/^pricing_[a-z_]+(?::.*)?$/.test(code)?`操作未完成；请核对当前状态和原编号。技术原因：${code}`:code);
  }
  const modeDefaults={smart:{allocation:['0.1','0.7','0.2'],undercut:'7.5'},daily:{offsets:'-8,-4,0,4,8',allocation:['0.2','0.6','0.2']},revenue_sprint:{allocation:['0.1','0.7','0.2'],undercut:'7.5'}};
  const modeDrafts={};
  let priceControlDirty=false,runtimeDirty=false;
  const pendingPriceKey='fc-v3-price-control-pending';
  function priceControlInputs(){
    const manual=$('v3-manual-enabled').checked;
    const pending=!!sessionStorage.getItem(pendingPriceKey),blocked=!canWrite||acting||pending;
    for(const id of ['v3-fixed-console','v3-fixed-pc']){$(id).disabled=blocked||!manual;$(id).required=manual;}
    $('v3-uplift-pct').disabled=blocked||!$('v3-uplift-enabled').checked||manual;
    $('v3-uplift-pct').required=$('v3-uplift-enabled').checked&&!manual;
    $('v3-price-control-draft').textContent=sessionStorage.getItem(pendingPriceKey)?'原保存请求待核对；再次保存沿用原编号':priceControlDirty?'有未保存修改，当前仍使用服务器配置':'已与服务器配置同步';
    $('v3-price-control-save').textContent=pending?'核对原保存请求':'保存价格控制';
  }
  function renderPriceControl(settings){
    if(!settings){$('v3-effective-control').textContent='价格控制配置待核';return;}
    if(!priceControlDirty){
      $('v3-manual-enabled').checked=settings.manual_enabled;
      $('v3-uplift-enabled').checked=settings.uplift_enabled;
      $('v3-fixed-console').value=settings.manual_prices.console??'';
      $('v3-fixed-pc').value=settings.manual_prices.pc??'';
      $('v3-uplift-pct').value=settings.uplift_pct;
    }
    $('v3-effective-control').textContent=settings.manual_enabled?`人工干预生效 · Console $${settings.manual_prices.console} / 1K · PC $${settings.manual_prices.pc} / 1K`:
      settings.uplift_enabled?`策略定价 + 临时上浮 ${settings.uplift_pct}%`:'原经营策略定价';
    priceControlInputs();
  }
  function requestKey(kind){const name='fc-v3-'+kind;let key=sessionStorage.getItem(name);if(!key){key=crypto.randomUUID();sessionStorage.setItem(name,key);}return key;}
  function clearKey(kind){sessionStorage.removeItem('fc-v3-'+kind);}
  function chosenPlan(){return (current?.plans||[]).find(p=>p.plan_id===selectedPlanId)||current?.plan;}
  function executeControls(){
    const disabled=acting||!canWrite||chosenPlan()?.state!=='ACTIVE'||lastAutomation?.system_enabled!==true;
    for(const id of ['v3-execute-now','v3-execute'])$(id).disabled=disabled;
  }
  function formParameters(){
    const mode=$('v3-mode').value;
    const allocation=Object.fromEntries(['control','exploit','explore'].map(k=>[k,$('v3-alloc-'+k).value]));
    if(Math.abs(Object.values(allocation).reduce((n,v)=>n+Number(v),0)-1)>1e-9)throw Error('对照、优选、探索分配之和必须为1');
    const parameters={allocation};
    if(mode==='revenue_sprint'||mode==='smart'){parameters.preferred_undercut_pct=$('v3-undercut').value;parameters.sprint_policy_version='sprint_5_10_lower_quote_floor20_v3';}
    else{parameters.offsets_pct=$('v3-offsets').value.split(',').map(v=>v.trim());if(parameters.offsets_pct.some(v=>v===''||!Number.isFinite(Number(v))))throw Error('候选偏移须为逗号分隔的数字');}
    return parameters;
  }
  function saveModeDraft(){modeDrafts[displayedMode]={offsets:$('v3-offsets').value,allocation:['control','exploit','explore'].map(k=>$('v3-alloc-'+k).value),undercut:$('v3-undercut').value};}
  function setMode(mode){const draft=modeDrafts[mode]||modeDefaults[mode],owner=(current?.active_plans||[]).find(p=>['revenue_sprint','smart'].includes(p.mode)&&p.resources?.includes('base:console')&&p.resources?.includes('base:pc')),baseline=owner?.mode==='smart'?owner.baseline_plan:owner,params=baseline?.parameters||{};$('v3-offsets').value=draft.offsets||'';['control','exploit','explore'].forEach((k,i)=>{$('v3-alloc-'+k).value=mode==='smart'?(params.allocation?.[k]??draft.allocation[i]):draft.allocation[i];$('v3-alloc-'+k).readOnly=mode==='smart';});for(const id of ['v3-console','v3-pc']){if(mode==='smart')$(id).checked=true;$(id).disabled=mode==='smart';}for(const input of $('v3-region-scopes').querySelectorAll('input')){if(mode==='smart')input.checked=true;input.disabled=mode==='smart';}$('v3-undercut').value=mode==='smart'?(baseline?(params.preferred_undercut_pct??'7.5'):''):(draft.undercut||'7.5');$('v3-undercut').readOnly=mode==='smart';$('v3-offsets-field').hidden=mode!=='daily';$('v3-undercut-field').hidden=mode==='daily';$('v3-target-section').hidden=mode!=='revenue_sprint';$('v3-allocation-legend').textContent=mode==='smart'?'继承当前冲额基准比例 · 不可在此修改':'试验分配 · 三项合计为 1';$('v3-mode-purpose').textContent=purposes[mode]+(mode==='smart'?(baseline?' 基准参数继承当前冲额计划，并一并接管全部Saudi范围。':' 当前冲额基准计划待核，不能创建。'):'');$('v3-end').required=false;$('v3-end-help').textContent='可选；留空持续运行，填写后按该时间结束。';if(current)renderDecision(current);}
  function node(tag,text){const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;}
  function value(v){return v==null?'待配置 / 待核':String(v);}
  function usd(v){return v==null?'待核':`$${Number(v).toFixed(2)}`;}
  function yuan(v){return v==null?'待核':`¥${Number(v).toFixed(2)}`;}
  function when(v){if(!v)return '待核';const d=new Date(v);return Number.isNaN(d.getTime())?String(v):new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d);}
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
    if(!result.records)return `任务 ${result.simulation_id} · ${statusText(result.status)}${result.paid_window?` · ${result.paid_window.start} 至 ${result.paid_window.end_exclusive}（结束日不含）`:''}。失败或结果未知时按此编号核对，勿重新登记。`;
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
    if(!response.ok){const error=Error(result.error||`请求失败 ${response.status}`);error.httpStatus=response.status;throw error;}
    return result;
  }
  async function cloud(path,body){
    const response=await fetch('/api/fc27/cloud/'+path,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(20000),
      ...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const result=await response.json();if(!response.ok)throw Error(result.error||`请求失败 ${response.status}`);return result;
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
    $('player-enabled').disabled=!canWrite;$('player-form').querySelector('button').disabled=!canWrite;
    $('v3-interval-save').disabled=!canWrite||automationRevision==null;
    for(const control of $('v3-price-control-form').querySelectorAll('input,button'))control.disabled=!canWrite||acting||current?.price_control==null||!!sessionStorage.getItem(pendingPriceKey)&&control.id!=='v3-price-control-save';
    for(const id of ['v3-system-enabled','v3-auto-enabled'])$(id).disabled=!canWrite||acting||automationRevision==null;
    priceControlInputs();
  }
  function table(id,rows){
    const body=$(id);body.replaceChildren();
    if(!rows.length){const tr=node('tr'),td=node('td','尚无记录');td.colSpan=8;tr.append(td);body.append(tr);return;}
    for(const cells of rows){const tr=node('tr');for(const cell of cells)tr.append(node('td',value(cell)));body.append(tr);}
  }
  function renderDecision(state){
    const mode=$('v3-mode').value,r=state.strategies?.[mode],cards=$('v3-strategies');cards.replaceChildren();
    const control=r?.selected?.price_control;
    const card=node('article');card.className='panel';card.append(node('h3',control?.manual_enabled?'人工干预':names[mode]),node('p',control?'最终价已通过双红线核算':Object.values(r?.selected?.daily_pricing||{}).some(t=>!t.item_target_met)?'双20可写，未达到ItemD2R目标':r?.selected?.decision_type==='floor_fallback'?'双20可写，未达到竞争目标':r?.status?statusText(r.status):'尚无本轮同策略决策'));
    if(mode==='smart'&&r?.smart_assignment){const a=r.smart_assignment,closed=Object.entries(a.no_space_by_group||{}).filter(([,v])=>v).map(([g])=>g==='pc'?'PC':'Console'),excluded=[...new Set([...(a.policy?.excluded||[]),...Object.entries(a.correction?.effective_blocks||{}).filter(([,n])=>n<=a.block).map(([k])=>k)])];card.append(node('p',a.no_uplift_space?'本轮缺少提价空间，候选合并；未形成有效价差。':`本轮计划档位 ${a.label}；实际价格及写后读回以执行记录为准。${closed.length?` ${closed.join('、')} 本轮缺少提价空间。`:''}`));card.append(node('p',a.policy?.winner?`观察性结果：${a.policy.winner} 档暂定领先；保留对照和探索。`:'效果数据尚未形成成熟赢家，继续按计划观察。'));if(excluded.length)card.append(node('p',`已撤回提价档：${excluded.join('、')}。`));}
    if(r?.selected){const s=r.selected;if(control)card.append(node('p',control.manual_enabled?'人工干预：本轮使用已保存固定价，策略和涨幅不参与。':`临时上浮 ${control.uplift_pct}%：原策略 Console ${usd(s.strategy_action?.base_prices.console)} / PC ${usd(s.strategy_action?.base_prices.pc)}。`));card.append(node('p',`本轮最终候选 100K：Console ${usd(s.action?.base_prices?.console)} · PC ${usd(s.action?.base_prices?.pc)}`),node('p',control?.manual_enabled?'人工指定价格，未运行策略收入预测。':s.score?.absolute_forecast_available?`同轮预测收入 ${usd(s.score.revenue)} · 采购贡献 ${usd(s.score.contribution)}`:'只有相对需求情景；绝对收入与新客效果待真实基线核证'));
      if(s.decision_type==='floor_fallback')card.append(node('p','财务底价兜底：竞争区间与双 20% 红线无交集；执行最低可写合法底价，不能视为已达到竞争降幅。'));
      for(const [group,target] of Object.entries(control?{}:s.daily_pricing||{})){
        card.append(node('p',`${group==='console'?'Console共价':'PC'}按ItemD2R ${target.driver_platform}当轮实际交付价定价：我方100K含赠套餐目标 ${usd(target.target_public_usd)}，执行基础价 ${usd(target.selected_base_total)}。${target.item_target_met?'达到Item目标（按公开分币舍入）':target.unmet_reason==='public_cent_not_reachable'?'舍入导致目标未命中，未达到Item目标':'财务底价抬高，未达到Item目标'}。`));
        for(const [platform,row] of Object.entries(target.platforms||{}))card.append(node('p',`${platform} · 每100K实际交付 ${usd(row.actual_unit_100k)} · 本平台参考 ${row.reference_source||'双源缺价'}${row.difference_pct!=null?` · 价差 ${Number(row.difference_pct)>0?'+':''}${Number(row.difference_pct).toFixed(2)}%`:''}`));
      }
      for(const [scope,platforms] of Object.entries(s.market_position||{}))for(const [platform,position] of Object.entries(platforms)){
        const differences=Object.entries(position.difference_pct||{}).map(([name,pct])=>`${name} ${Number(pct)>0?'+':''}${Number(pct).toFixed(2)}%`).join('；');
        card.append(node('p',`${scope} ${platform} · 每 100K 实际交付 ${usd(position.actual_unit_100k)} · 相对竞品 ${differences} · ${position.competitive_band_met?'达到 5–10% 区间':'未达到竞争区间'}`));
      }
    }
    else if(r?.failures?.length)card.append(node('p',`当前不可执行：${[...new Set(r.failures.map(f=>statusText(f.code)))].join('；')}`));
    if(r?.status==='INFEASIBLE')card.append(node('p','本次未写价；已启用计划按正常周期重新评估。最近公开价仍以上方实际读回为准。'));
    cards.append(card);
    $('v3-decision-basis').textContent=`本轮快照 ${state.snapshot_id||'尚无'} · ${names[mode]} · ${r?.selected?'已形成候选；执行前仍需新鲜财务与市场重证':'当前没有可执行的同策略候选'}。`;
  }
  function renderOverview(state,automation,monitor){
    const schedule=automation?.v3?.schedule||automation?.schedule||{},active=state.active_plans||[],plan=active.find(p=>p.plan_id===selectedPlanId)||active[0]||state.plan;
    const interval=schedule.cycle_interval_minutes??automation?.interval_minutes;
    $('v3-cycle').textContent=interval!=null?`自动改价间隔：${interval} 分钟`:'自动改价间隔待核（默认 60 分钟）';
    automationRevision=automation?.revision??null;
    for(const id of ['v3-system-enabled','v3-auto-enabled'])$(id).disabled=!canWrite||acting||automationRevision==null;
    if(!runtimeDirty){$('v3-interval-minutes').value=interval??'';$('v3-system-enabled').checked=automation?.system_enabled===true;$('v3-auto-enabled').checked=automation?.mode==='auto';}
    $('v3-runtime-status').textContent=automation?`服务器已保存：系统${automation.system_enabled?'开启':'关闭'} · ${automation.mode==='auto'?'自动运行':'仅手动执行'} · 每 ${interval} 分钟${runtimeDirty?'；有未保存修改':''}`:'服务器运行设置未读回';
    $('v3-interval-save').disabled=!canWrite||automationRevision==null;
    $('v3-current-plan').textContent=plan?`${active.length>1?`${active.length} 个受控计划 · 当前查看 `:''}${names[plan.mode]||plan.mode} · ${statusText(plan.state)}`:'无活动计划';
    $('v3-next-cycle').textContent=schedule.next_cycle_at?when(schedule.next_cycle_at):(schedule.active_plan_state==='SUSPENDED'||plan?.state==='SUSPENDED'?'已暂停，无下一自然写价轮':'暂无已排定自然轮');
    $('v3-source-time').textContent=schedule.last_source_checked_at?when(schedule.last_source_checked_at):'当前计划来源待核';
    const latest=state.operations?.[0],orderAdminLabel=latest?.status==='COMPLETED'&&latest?.order_close?.reason==='order_write_confirmed_admin_price_matched'?'Order与Admin已确认':null;
    const stageLabel=orderAdminLabel&&(!schedule.last_execution_stage||schedule.last_execution_stage==='COMPLETED')?orderAdminLabel:statusText(schedule.last_execution_stage||latest?.status);
    $('v3-stage').textContent=`${stageLabel}${schedule.last_cycle_at?` · ${when(schedule.last_cycle_at)}`:''}`;
    const rows=monitor?.storefront?.rows||{};
    for(const [platform,id] of [['PS','v3-price-ps'],['XBOX','v3-price-xbox'],['PC','v3-price-pc']]){
      const publicRow=rows[platform];$(id).textContent=publicRow?.package_usd!=null?usd(publicRow.package_usd):'公开价待核';
    }
    const publication=monitor?.publication?.status;
    $('v3-public-status').textContent=`公开读回：${publication==='matched'?'已核实':publication?statusText(publication):'待核'}。上述为最近公开采样，时点 ${when(rows.PS?.checked_at||rows.PC?.checked_at)}；不以候选报价代替。`;
    const receipt=latest?.bundle||{},source=receipt.decision_source;
    const reviewLabel=receipt.maintenance_purpose==='retire_uk_discount_v1'?'用户授权英国临时折扣退出；程序已核财务与地区规则':receipt.review_contract==='program_pricing_with_daily_hermes_review_v3'?'当前规则：程序逐轮定价，Hermes 每日效果复盘':(source==='v3_model_reviewed_this_cycle'||source==='v3_reviewed_assignment')&&receipt.review_approved===true?'本轮 Hermes 实际选择并审核':
      source==='v3_model_reviewed_this_cycle'?'模型选择回执与批准状态不一致，待核':
      source==='v3_inherited_reviewed_business_strategy'?'沿用先前已审经营策略，本轮程序重证':
      source==='v3_explicit_deterministic_feasible_assignment'||receipt.review_approved===false?'历史原操作当时使用程序路径，未获模型审核；当前规则无需逐轮审核':'审核来源待核';
    $('v3-review-source').textContent=latest?`最近原操作 ${latest.operation_id}：${orderAdminLabel||statusText(latest.status)}。${reviewLabel}；${orderAdminLabel?'公开读回状态单独列示':'真实生效以后台、缓存及公开读回为准'}。`:'尚无 V3 原操作。程序负责正常定价，Hermes 每日提供效果评估。';
    const daily=state.daily_review;
    $('v3-daily-status').textContent=daily?`${daily.local_date} · ${statusText(daily.phase)} · 专用定价通道；不会自动切换策略`:'尚无每日结果；每天 02:20 复盘前一日，保存的分时段输入不足会列为缺项。';
    const replies=(daily?.hermes?.evaluation?.turns||[]).map(t=>t.reply).filter(Boolean);
    const historyNote=daily&&current.plan?.financial_contract_version==='fc27_dual20_v1'&&daily.decision_basis?.financial_contract_version!=='fc27_dual20_v1'?'此为历史复盘，原文中的旧策略、预算、双10和赠品假设不代表当前规则；当前只保留日常运营与冲销售额、双20、无预算，ItemD2R按原100K核算。\n\n':'';
    $('v3-daily-result').textContent=historyNote+(replies.join('\n\n')|| (daily?`实际数据：${daily.actual?.status||'待核'}；影子：${daily.shadow?.status||'待运行'}；Hermes：${daily.hermes?.phase||'待提交'}`:''));

    $('collect').disabled=!canWrite||acting||!!collectPending;
  }
  async function renderMarketEvidence(){
    const output=$('v3-market-cards'),summary=$('v3-market-status');output.setAttribute('aria-busy','true');
    for(const platform of ['ps','xbox','pc'])$('v3-price-basis-'+platform).textContent='采购成本 / 双红线待核';
    try{
      const market=await request('market');
      output.replaceChildren();
      if(!market.snapshot_id){summary.textContent='尚无采集快照，等待下一次来源采集。';return;}
      if(market.snapshot_id!==current?.snapshot_id){summary.textContent='来源快照与本轮决策不一致，等待统一状态更新。';return;}
      for(const platform of ['PS','XBOX','PC']){
        const details=$('v3-price-basis-'+platform.toLowerCase()),basis=market.price_basis?.rows?.[platform];details.replaceChildren();
        if(!basis){details.textContent='采购成本 / 双红线待核';continue;}
        const publicPrice=lastMonitor?.storefront?.rows?.[platform]?.package_usd,cost=Number(basis.package_cost_usd),retained=Number(market.price_basis.historical_retained_ratio);
        const currentMargin=publicPrice>0&&Number.isFinite(cost)?((Number(publicPrice)-cost)/Number(publicPrice)*100).toFixed(1)+'%':'待核';
        const averageMargin=publicPrice>0&&retained>0&&Number.isFinite(cost)?((Number(publicPrice)*retained-cost)/(Number(publicPrice)*retained)*100).toFixed(1)+'%':'待核';
        const averageWindow=market.price_basis.history_window_contract==='d9_d2_eight_closed_days_v1'?'D-9至D-2八日平均红线':'历史七日平均红线';
        details.append(node('p',`采购成本 $${Number(basis.cost_usd_per_1k).toFixed(4)} / 1K（¥${Number(basis.cost_cny_per_1k).toFixed(4)}）`),
          node('p',`${basis.delivered_k}K 含赠套餐成本 ${usd(basis.package_cost_usd)}`),
          node('p',`未优惠红线 ${usd(basis.regular_floor_usd)} · 当前${currentMargin}`),node('p',`${averageWindow} ${usd(basis.average_floor_usd)} · 当前${averageMargin}`),
          node('p',`成本采集 ${when(basis.cost_checked_at)}；${market.price_basis.pricing_scope==='100k_package_only'?'双20只按购买100K、赠送5K这一档核算，地区实际售价另核。':'此为旧范围成本快照，等待100K新口径采集。'}`));
      }
      for(const platform of ['PS','XBOX','PC']){
        const column=node('article');column.className='market-platform';column.append(node('h3',platform==='XBOX'?'Xbox':platform));
        const loot=market.global_offers?.[platform]?.Lootbar;
        const item=(market.reference?.offers||[]).find(row=>row.platform===platform);
        const arab=(market.arab||[]).find(row=>row.platform===platform);
        for(const [name,row,price,purchase,bonus,stamp,verified,method] of [
          ['Lootbar',loot,loot?.usd_price,loot?.base_k,loot?.bonus_k,loot?.checked_at,loot?.comparable!==false,'无优惠券报价'],
          ['ItemD2R',item,item?.gross_usd,item?.purchase_k,item?.bonus_k,item?.captured_at,item?.status==='valid',item?.delivery_method||'交付方式待核'],
          ['Arab-UT',arab,arab?.total_usd,arab?.purchase_k,arab?.bonus_k,arab?.captured_at,arab?.selection_verified===true,'Saudi Arabia · 普通发货']]){
          const card=node('section');card.className='market-quote';
          const available=price!=null&&Number.isFinite(Number(price))&&Number(price)>0;
          const age=stamp?Date.now()-Date.parse(stamp):NaN;
          const stale=Number.isFinite(age)&&age>15*60000;
          card.dataset.state=!available?'missing':stale?'stale':'observed';
          const followGlobal=name==='Arab-UT'&&!available&&market.saudi_missing_price_policy==='follow_global';
          const missingReason=name==='ItemD2R'?(market.reference?.missing||[]).find(gap=>gap.platform===platform)?.reason||market.reference?.reason:name==='Lootbar'?(market.competitor_diagnostics||[]).find(reason=>reason.startsWith('Lootbar:')):null;
          const header=node('div');header.className='head';const badge=node('span',followGlobal?'缺价 · 跟随全球':!available&&missingReason==='itemd2r_cloudflare_403'?'Cloudflare 403 · 缺价':!available?'缺项':!verified?'规格待核':stale?'已过 15 分钟':!Number.isFinite(age)||age<0?'时点待核':'最近已采');badge.className='market-badge';header.append(node('h4',name),badge);card.append(header);
          const total=node('p',available?usd(price):'暂无报价');total.className='market-price';card.append(total);
          const delivered=purchase!=null&&bonus!=null?Number(purchase)+Number(bonus):NaN;
          const unit=node('p',available&&verified&&Number.isFinite(delivered)&&delivered>0?`${usd(Number(price)/delivered*100)} / 100K 实际交付`:'同口径单价待核');unit.className='market-unit';card.append(unit);
          card.append(node('p',row?`购买 ${purchase??'待核'}K + 赠送 ${bonus??'待核'}K${Number.isFinite(delivered)?` · 交付 ${delivered}K`:''}`:'本轮未取得可核报价'),node('p',method));
          if(!available&&name!=='Arab-UT')card.append(node('p',`冲额：另一家有效则用另一家；双缺取双20最低合法价，竞争目标未达。日常：Lootbar有效保留计划选价；缺价按ItemD2R实际交付价；双缺的平台按八日平均30%最低价。原因：${missingReason||'本轮无有效报价'}`));
          const time=node('p',`采集 ${when(stamp)} · USD`);time.className='footnote';card.append(time);column.append(card);
        }
        output.append(column);
      }
      summary.textContent=`快照 ${market.snapshot_id} · 采集时间均为北京时间。卡片展示保存的来源证据，不表示当前可直接执行。`;
    }catch(error){output.replaceChildren();summary.textContent=`竞品价格暂无法读取：${errorText(error)}；下次更新重试。`;}
    finally{output.removeAttribute('aria-busy');}
  }
  function render(state){
    const firstRender=!current;
    current=state;
    renderPriceControl(state.price_control);
    const plans=state.plans||[],list=$('v3-plan-select');
    list.replaceChildren();for(const p of plans){const option=node('option',`${names[p.mode]} · ${p.plan_id} · ${p.state}`);option.value=p.plan_id;list.append(option);}
    if(!plans.some(p=>p.plan_id===selectedPlanId))selectedPlanId=state.active_plans?.[0]?.plan_id||plans[0]?.plan_id||null;
    list.value=selectedPlanId||'';
    const plan=chosenPlan(),active=(state.active_plans||[]).find(p=>p.plan_id===selectedPlanId)||state.active_plans?.[0]||state.plan;
    if(firstRender&&active?.mode&&names[active.mode]){$('v3-mode').value=active.mode;displayedMode=active.mode;setMode(active.mode);}
    $('v3-state').textContent=(active?`${names[active.mode]} · ${statusText(active.state)} · 数据 ${state.captured_at||'尚未取得'} · ${state.generation?'统一控制权已登记':'尚未切换'}`:'无活动计划；历史价格与原操作保留')+
      (permissionKnown?(canWrite?' · 当前账户可操作':' · 当前账户仅可查看'):' · 操作权限待核');
    $('v3-target').textContent=targetText(state.target||{});
    if(document.activeElement!==$('v3-target-amount'))$('v3-target-amount').value=state.target?.amount??'';
    const scopes=$('v3-region-scopes'),checked=new Set([...scopes.querySelectorAll('input:checked')].map(input=>input.value));scopes.replaceChildren();for(const control of state.regional_controls||[]){if(control.region_id!==21||!control.resource)continue;const label=node('label'),input=node('input');input.type='checkbox';input.value=control.resource;input.dataset.regionScope='1';input.checked=$('v3-mode').value==='smart'||checked.has(control.resource);input.disabled=$('v3-mode').value==='smart';label.append(input,node('span',`Saudi Arabia ${control.platforms.join('/')}`));scopes.append(label);}
    renderDecision(state);
    const latest=state.operations?.[0],proof=latest?.bundle?.financial_proof?.prices||{};
    const matrix=[];
    for(const [key,p] of Object.entries(proof))matrix.push([key,usd(p.price.regular_usd),p.price.delivered_k,p.coefficient||'1',p.rule_id||'默认',p.catalog.minimum_estimated_average_margin_pct,p.catalog.worst_published_margin_pct,latest.status]);
    for(const rule of state.region_rules||[])if(!matrix.some(r=>r[0].startsWith(String(rule.region_id)+':')))for(const platform of rule.platforms)matrix.push([`${rule.region_id}:${platform}`,'待联合证明','待核',rule.factor,rule.id,'待核','待核',rule.verification_status||'待核']);
    table('v3-regions',matrix);
    table('v3-operations',(state.operations||[]).map(o=>[o.created_at,names[o.bundle?.mode]||(o.bundle?.maintenance_purpose==='retire_uk_discount_v1'?'英国临时折扣退出':'待核'),statusText(o.status),o.operation_id,statusText(o.readback?.public?.status),statusText(o.cache_receipt?.status)]));
    table('v3-incidents',(state.incidents||[]).map(i=>[i.code,i.dependency,statusText(i.state),i.first_seen,i.last_seen,i.attempt]));
    $('v3-proof-notes').textContent=`双红线：购买100K、赠送5K档未优惠及D-9至D-2八个完整日真实优惠金额结构估算平均采购毛利都至少 20%。成本、竞品及汇率取本轮。小额与其他档位不作为自动定价硬门槛。全球核心参考 Lootbar 与 ItemD2R；Saudi Arabia 另核 Arab 普通报价，破线时系数归1；英国系数1。${latest?.bundle?.financial_proof?.pricing_scope!=='100k_package_only'&&latest?'下表最近原操作为旧口径历史证明，不代表100K新口径验收。':''}${matrix.length?'下表展示已获得的地区证明；缺项保持待核。':'本轮地区证明尚未取得。'}`;
    writeControls();
    list.disabled=!plans.length;
    $('v3-plan-stop').disabled=!canWrite||!plan||['ENDED','ENDING'].includes(plan.state);
    $('v3-plan-pause').disabled=!canWrite||!plan||!['ACTIVE','SUSPENDED'].includes(plan.state);
    $('v3-plan-pause').textContent=plan?.state==='SUSPENDED'?'恢复当前计划':'暂停新写入';
    executeControls();
    $('v3-manual-execute').disabled=!canWrite||!manualPreview||!plan||plan.plan_id!==manualPreview.plan_id||Date.now()>=Date.parse(manualPreview.valid_until);
    $('v3-history-read').disabled=!$('v3-history-id').value.trim();
    $('v3-error').hidden=!$('v3-error').textContent;
  }
  async function refresh(){
    if(loading)return;loading=true;$('v3-panel').setAttribute('aria-busy','true');$('v3-refresh').disabled=true;$('v3-refresh').textContent='正在读取…';
    try{const [state,permission,automation,monitor,player]=await Promise.all([
      request('state'),writePermission().then(value=>({known:true,value})).catch(()=>({known:false,value:false})),
      cloud('automation').catch(()=>null),cloud('monitor').catch(()=>null),cloud('player-sync').catch(()=>null)]);
      permissionKnown=permission.known;canWrite=permission.value;lastAutomation=automation;lastMonitor=monitor;render(state);renderOverview(state,automation,monitor);await renderMarketEvidence();
      if(player){playerRevision=player.revision;if(!playerDirty)$('player-enabled').checked=Boolean(player.enabled);}
      $('v3-error').textContent=permissionKnown?'':'操作权限暂时无法核对，写入入口已停用；只读状态仍可查看。';
      $('v3-error').hidden=permissionKnown;
      $('version').textContent=`V3 状态读取 ${when(new Date())} · 快照 ${state.snapshot_id||'尚无'} · 下轮时间以统一调度实际回执为准`;
      if(collectPending){const job=await cloud('jobs/'+collectPending).catch(()=>null);if(job&&['ready','failed'].includes(job.status)){$('v3-result').textContent=job.result?.status==='INFEASIBLE'?`只读采集任务 ${collectPending}：采集已完成；当前策略无可执行报价，未写价。`:job.status==='failed'?`只读采集任务 ${collectPending}：采集失败（${errorText({message:job.error_detail||job.error||'原因待核'})}）；竞品卡片保留原采集时间，不是已刷新。`:`只读采集任务 ${collectPending}：${statusText(job.status)}；本轮报价需另经 V3 证明。`;collectPending=null;sessionStorage.removeItem('fc-v3-collect-job');clearKey('collect');}}}
    catch(error){$('v3-error').textContent=`未完成：${errorText(error)}。旧值保留其原时点。`;$('v3-error').hidden=false;}
    finally{loading=false;$('v3-refresh').disabled=false;$('v3-refresh').textContent='更新统一状态';$('v3-panel').removeAttribute('aria-busy');}
  }
  async function action(fn){
    if(acting)return;acting=true;executeControls();$('collect').disabled=true;$('v3-panel').setAttribute('aria-busy','true');$('v3-result').textContent='请求处理中，请等待原请求回执。';
    writeControls();
    try{await fn();if($('v3-result').textContent==='请求处理中，请等待原请求回执。')$('v3-result').textContent='请求已登记；实际状态以后台、缓存与公开读回为准。';await refresh();}
    catch(error){if($('v3-result').textContent==='请求处理中，请等待原请求回执。')$('v3-result').textContent='请求未完成；请核对下方原因和原请求回执。';$('v3-error').textContent=`未完成：${errorText(error)}`;$('v3-error').hidden=false;$('v3-error').focus();}
    finally{acting=false;writeControls();executeControls();$('collect').disabled=!canWrite||!!collectPending;$('v3-panel').removeAttribute('aria-busy');}
  }
  $('v3-mode').addEventListener('change',()=>{saveModeDraft();displayedMode=$('v3-mode').value;setMode(displayedMode);});setMode(displayedMode);
  $('v3-plan-select').addEventListener('change',()=>{selectedPlanId=$('v3-plan-select').value;manualPreview=null;render(current);renderOverview(current,lastAutomation,lastMonitor);});
  $('player-form').addEventListener('input',()=>{playerDirty=true;});
  $('player-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{if(playerRevision==null)throw Error('联动配置尚未读取');const saved=await cloud('player-sync',{enabled:$('player-enabled').checked,expected_revision:playerRevision});playerRevision=saved.revision;playerDirty=false;$('player-state').textContent='联动配置已保存并读回。';});});
  $('v3-interval-form').addEventListener('input',()=>{runtimeDirty=true;$('v3-runtime-status').textContent='运行设置有未保存修改，当前仍使用服务器配置。';});
  $('v3-price-control-form').addEventListener('input',()=>{priceControlDirty=true;priceControlInputs();});
  $('v3-price-control-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
    if(current?.price_control==null)throw Error('价格控制配置尚未读回');
    const pending=sessionStorage.getItem(pendingPriceKey);
    const data=pending?JSON.parse(pending):{request_key:requestKey('price-control'),expected_revision:current.price_control.revision,
      manual_enabled:$('v3-manual-enabled').checked,manual_prices:{console:$('v3-fixed-console').value||null,pc:$('v3-fixed-pc').value||null},
      uplift_enabled:$('v3-uplift-enabled').checked,uplift_pct:$('v3-uplift-pct').value||'0'};
    sessionStorage.setItem(pendingPriceKey,JSON.stringify(data));
    try{
      const result=await request('price-control',data);current.price_control=result.settings;priceControlDirty=false;
      sessionStorage.removeItem(pendingPriceKey);clearKey('price-control');
      $('v3-price-control-result').textContent=`价格控制已保存并读回（版本 ${result.settings.revision}）。保存没有立即写价；下个自然轮或点击立即执行时使用。`;
    }catch(error){
      if(!pending&&error.httpStatus>=400&&error.httpStatus<500&&error.httpStatus!==408){sessionStorage.removeItem(pendingPriceKey);clearKey('price-control');}
      $('v3-price-control-result').textContent=sessionStorage.getItem(pendingPriceKey)?'保存结果尚未确认；再次保存会沿用原请求核对，避免重复写入。':'配置未保存，请根据提示修正后重试。';
      throw error;
    }
  });});
  $('v3-interval-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
    if(automationRevision==null)throw Error('自动化配置版本尚未读回');
    const interval=Number($('v3-interval-minutes').value);
    if(!Number.isInteger(interval)||interval<=0)throw Error('自动改价间隔须为正整数分钟');
    const settings={system_enabled:$('v3-system-enabled').checked,mode:$('v3-auto-enabled').checked?'auto':'manual',interval_minutes:interval,
      platforms:lastAutomation.platforms,minimum_gross_margin_pct:lastAutomation.minimum_gross_margin_pct};
    const result=await cloud('automation',{settings,expected_revision:automationRevision});runtimeDirty=false;
    $('v3-interval-result').textContent=`运行设置已保存并读回。${result.revision!=null?`配置版本 ${result.revision}。`:''}原计划与期限保持。`;
  });});
  $('collect').addEventListener('click',()=>action(async()=>{const result=await cloud('pricing/collect',{client_event_id:requestKey('collect')});collectPending=result.job_id;sessionStorage.setItem('fc-v3-collect-job',collectPending);$('v3-result').textContent=`只读采集已登记，任务 ${collectPending}；不写价。`; }));
  $('v3-manual-form').addEventListener('input',()=>{if(manualPreview){manualPreview=null;$('v3-manual-execute').disabled=true;$('v3-manual-result').textContent='输入已改变，请重新进行只读预览。';}});
  $('v3-history-id').addEventListener('input',()=>{$('v3-history-read').disabled=!$('v3-history-id').value.trim();});
  $('v3-target-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{await request('monthly-target',{request_key:requestKey('target'),amount:$('v3-target-amount').value||null});clearKey('target');});});
  $('v3-plan-form').addEventListener('submit',event=>{
    event.preventDefault();action(async()=>{
      const data={request_key:requestKey('plan'),mode:$('v3-mode').value,resources:[],parameters:formParameters()};
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
  function executeCurrentPlan(){
    return action(async()=>{
      const plan=chosenPlan();
      if(!canWrite||!plan||plan.state!=='ACTIVE')throw Error('当前没有可执行的活动计划或操作权限');
      const kind='execute-'+plan.plan_id,key=requestKey(kind),unknownKey='fc-v3-execute-unknown-'+plan.plan_id;
      try{
        const result=await request('execute',{request_key:key,plan_id:plan.plan_id});
        if(!result.job_key)throw Error('改价任务回执缺少编号，请按原请求核对');
        if(!['queued','running','done','failed'].includes(result.status))throw Error('原改价任务状态尚未确认，请按原请求核对');
        clearKey(kind);sessionStorage.removeItem(unknownKey);
        $('v3-result').textContent=`改价任务已登记，编号 ${result.job_key}（${statusText(result.status)}）。按当前计划重新采集、核算并按规则改价；实际结果以执行状态和读回为准。`;
      }catch(error){
        if(sessionStorage.getItem(unknownKey)!==key&&error.httpStatus>=400&&error.httpStatus<500&&error.httpStatus!==408&&error.message!=='pricing_execute_payload_conflict'){
          clearKey(kind);
          $('v3-result').textContent=`本次改价请求被拒绝：${errorText(error)}。未登记新任务，修正后可重新执行。`;
        }else{
          sessionStorage.setItem(unknownKey,key);
          $('v3-result').textContent=`改价请求 ${key} 尚未确认；请先更新统一状态核对。再次点击将沿用该请求编号，不重复登记。`;
        }
        throw error;
      }
    });
  }
  for(const id of ['v3-execute-now','v3-execute'])$(id).addEventListener('click',executeCurrentPlan);
  $('v3-preview').addEventListener('click',()=>action(async()=>{
    const result=await request('preview',{mode:$('v3-mode').value});
    const owner=(current?.active_plans||[]).find(p=>['revenue_sprint','smart'].includes(p.mode)&&p.resources?.includes('base:console')&&p.resources?.includes('base:pc')),baseline=owner?.mode==='smart'?owner.baseline_plan:owner,pct=baseline?.parameters?.preferred_undercut_pct;
    const note=$('v3-mode').value==='smart'?`默认7.5%基准候选排序的只读情景，未使用当前${pct!=null?pct+'%':'计划参数'}及真实6小时分配；不是本计划报价，不作为切换或审批依据。实际结果以启用后同轮采集和决策回执为准。\n`:'';
    $('v3-preview-output').textContent=note+Object.entries(result.results).map(([m,r])=>`${names[m]}：${statusText(r.status)}；${r.selected?`Console ${usd(r.selected.action.base_prices.console)} / PC ${usd(r.selected.action.base_prices.pc)}`:`当前不可执行 ${[...new Set((r.failures||[]).map(f=>statusText(f.code)))].join('；')}`}`).join('\n');
  }));
  $('v3-manual-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
    const restore=$('v3-restore-id').value.trim();
    const data={request_key:requestKey('manual-preview'),reason:$('v3-manual-reason').value,plan_id:chosenPlan()?.plan_id};
    if(restore)data.restore_source_execution_id=restore;
    else{data.explicit_prices={};if($('v3-manual-console').value)data.explicit_prices.console=$('v3-manual-console').value;if($('v3-manual-pc').value)data.explicit_prices.pc=$('v3-manual-pc').value;}
    manualPreview=await request('manual-previews',data);clearKey('manual-preview');
    const action=manualPreview.selected?.action?.base_prices||manualPreview.explicit_prices;
    const regions=Object.entries(manualPreview.selected?.action?.region_coefficients||{}).map(([key,factor])=>`${key} 系数 ${factor}`).join('；');
    const averageWindow=manualPreview.selected?.financial_proof?.financial_contract_version==='fc27_dual20_d9_d2_v2'?'八日金额结构':'历史七日结构';
    const proof=Object.entries(manualPreview.selected?.financial_proof?.prices||{}).map(([key,row])=>`${key}：未优惠 ${value(row.catalog?.worst_published_margin_pct)}% / ${averageWindow} ${value(row.catalog?.minimum_estimated_average_margin_pct)}%`).join('；');
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
    const window=$('v3-history-days').value;
    const result=await request('simulations',{request_key:requestKey('history'),kind:$('v3-history-kind').value,closed_days:window==='month'?'month':Number(window)});
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
