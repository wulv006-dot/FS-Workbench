(() => {
  'use strict';
  const base='/api/fc27/cloud/pricing/v3';
  const platforms=['PS','XBOX','PC'];
  function discountWindow(average){
    const labels={fc_v6_d8_d2_amount_weighted_discount_v1:'D-8 至 D-2',fc_v6_d3_d1_amount_weighted_discount_v1:'D-3 至 D-1'};
    const label=labels[average?.contract]||'回执所列窗口';
    if(!average?.start||!average?.end_exclusive)return label;
    const last=new Date(Date.parse(`${average.end_exclusive.slice(0,10)}T00:00:00Z`)-86400000);
    return Number.isFinite(+last)?`${label}（${average.start.slice(0,10)} 至 ${last.toISOString().slice(0,10)}）`:label;
  }
  const curveProtocol='fc27_curve_v6',curveRequest='curve-collect',curvePendingKey='fc-v3-curve-collect-job';
  const curveActivationKey='fc-v3-curve-activation';
  const collectedMarketKey='fc-v3-collected-market';
  const pricesText=prices=>prices&&Object.keys(prices).some(p=>platforms.includes(p))?platforms.map(p=>`${p==='XBOX'?'Xbox':p} ${usd(prices?.[p])}`).join(' · '):`历史Console ${usd(prices?.console)} · PC ${usd(prices?.pc)}`;
  const names={smart:'智能决策',daily:'日常运营（备用）',revenue_sprint:'冲销售额'};
  const purposes={smart:'三平台独立双向试验：每小时重算各平台基准，每3小时独立选择A基准、B合法降3%、C合法涨3%，受各自双20与竞品上界约束。同价合并；按同钟点累计有效对照复盘，低量不强判赢家。',daily:'PS、Xbox、PC分别按真实八日优惠核算财务底线；Lootbar为主锚、Arab-UT为次锚，双源缺失按本平台八日平均30%求最低合法价。',revenue_sprint:'三平台独立报价，Lootbar为主锚、Arab-UT为次锚，ItemD2R仅辅助。按本平台100K实交100K双20及5–10%竞争目标选价，地区继承全球。'};
  const primaryPolicy=plan=>plan?.parameters?.competitor_policy==='lootbar_primary_arabut_secondary_v1';
  function modePurpose(mode,plan){
    if(plan?.write_protocol===curveProtocol)return 'PS、Xbox、PC 各自核价。按最近三个已归档完整自然日（D-3 至 D-1）的金额加权优惠估算，检查各档保本及平台组合采购毛利至少 18%，以 25% 为经营目标。';
    if(mode==='smart'&&plan?.smart_strategy_version==='smart-three-platform-v3')return purposes.smart;
    if(mode==='smart'&&plan?.smart_strategy_version==='smart-bidirectional-v2')return '历史双向试验v2：每小时重算冲额基准；Console与PC独立选择A基准、B合法降3%、C合法涨3%，同价候选合并；48小时为检查点，成熟度按有效对照判断。程序每小时执行，Hermes每日只读复盘；月目标仅为经营背景，不接入选价。';
    if(primaryPolicy(plan)&&mode==='daily')return 'Lootbar有效时保留原计划锚点；缺价按同平台ArabUT当轮实际交付价，低于双20则用合法底价。两源均缺的平台按八日平均30%求最低价；ItemD2R仅辅助观察。';
    if(primaryPolicy(plan)&&mode==='revenue_sprint')return 'Lootbar为主锚；缺有效价时用同平台ArabUT，ItemD2R仅辅助观察。两源均缺按100K双20最低合法价；保留原5–10%冲额目标和计划偏好，地区继承全球。';
    if(mode==='smart'&&plan&&!plan.smart_strategy_version)return '历史智能策略：每小时重算基准，B上调3%、C上调6%；仅按原回执解释，不能当作当前三平台策略。';
    return purposes[mode];
  }
  const $=id=>document.getElementById(id);
  const marketTag=$('v3-market-title').parentElement.querySelector('.tag'),legacyMarketTag=marketTag.textContent;
  let current,loading=false,acting=false,manualPreview=null,selectedPlanId=null,displayedMode='smart',canWrite=false,permissionKnown=false,playerRevision=null,playerDirty=false,collectPending=sessionStorage.getItem('fc-v3-collect-job'),automationRevision=null,lastAutomation=null,lastMonitor=null;
  let curvePending=sessionStorage.getItem(curvePendingKey),curveChecking=false,curveRetry='',curveSubmitError='',curveTimer,curveReadOnly=false;
  let curveReady=null,curveActivationRetry=false;
  let executeReceipt=null,executionTimer,executionRead=null,executionPageLeft=false;
  let collectedMarketId=sessionStorage.getItem(collectedMarketKey),marketRead=0,collectTimer;
  const statuses={DRAFT:'待启用',SCHEDULED:'等待开始',ACTIVE:'执行中',SUSPENDED:'已暂停新写入',ENDING:'正在退出',ENDED:'已结束',
    READY:'已有可行方案',INFEASIBLE:'当前证据下无可行报价',DATA_PENDING:'数据待补齐',
    AUTHORIZED:'已授权待执行',DISPATCHED:'已发出请求',RUNNING:'执行中',CONFIRMED:'后台已确认',FAILED:'执行失败，保留原编号',CANCELLED:'已取消',CANCELLED_NOT_SENT:'已核实未发送并取消',SUPERSEDED:'已由更新计划接替',
    UNKNOWN:'结果未知，按原编号核对',PARTIALLY_APPLIED:'部分已应用，待原编号核对',KNOWN_PARTIAL_EXITED:'部分已应用，已退出新写入',PUBLIC_CONFIRMED:'公开已核实',
    BACKEND_CONFIRMED:'后台已确认，待后续核验',CACHE_CONFIRMED:'缓存已确认，待公开核验',PUBLIC_PENDING:'公开价格待核',
    KEEP:'保持现价', NO_PRICE_CHANGE:'本轮保持现价', PROOF_INCOMPLETE:'核算待补',
    HARD_CONSTRAINT_FAILED:'当前价表未通过财务约束', PREFERRED_HARD_CONSTRAINT_FAILED:'候选未通过财务约束',
    NO_FEASIBLE_CURVE:'本轮未找到可保存的价表',
    REJECTED_NO_CHANGE:'后台已拒绝，实际价格未变',COMPLETED:'公开核验完成',NO_CHANGE:'核算后无需改价',OPEN:'待处理',available:'数据可用',partial:'部分数据可用',
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
    'pricing_required_market_missing:ArabUT:PC':'Arab-UT 本轮未取得可核的 PC 独立报价',
    pricing_capacity_data_pending:'缺少可核供应能力或正常交付队列基数'};
  function statusText(raw){return raw==null?'待核':statuses[raw]||names[raw]||`待核（${raw}）`;}
  function errorText(error){
    const code=error.message||String(error);
    const known={weekly_plan_owner_required:'请由计划创建者确认这次周调整',weekly_four_manual_weeks_required:'前四周须逐周确认，到期后可明确开启自动调整',weekly_proposal_expired_or_parameters_changed:'提议已过期或定位参数已变化，请刷新核对',weekly_proposal_not_pending:'这条提议已处理，请刷新核对',pricing_snapshot_required:'缺少本轮真实快照，请先采集并核对来源',pricing_plan_scope_invalid:'计划范围不符合当前可修改资源',
      pricing_plan_required:'当前没有可执行的活动计划',pricing_resource_unresolved:'原操作尚未对账，此范围暂不可写',pricing_smart_scope_requires_all_owned_resources:'智能决策须同时接管PS、Xbox、PC和现有Saudi范围，请刷新后重试',
      pricing_manual_preview_expired:'人工预览已过期，请重新核算',pricing_manual_infeasible:'当前明确价未通过新鲜财务或市场证明',
      pricing_operation_missing:'未找到该原操作编号',state_unavailable:'状态暂时无法读取',
      queue_mutation_busy:'采集队列暂忙，本次未入队',queue_unavailable:'采集队列暂不可用',
      pricing_curve_activation_snapshot_unverified:'预览已过期或来源未核验，请重新采集',
      pricing_curve_activation_proof_incomplete:'本轮财务或原后台核验尚未通过',
      pricing_migration_cycle_running:'原自动轮正在执行，请待其完成后核对原请求',
      pricing_price_control_revision_changed:'配置已被更新，请刷新状态后再保存',pricing_manual_price_required:'开启人工干预时须填写PS、Xbox和PC的后台单价',
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
    for(const id of ['v3-fixed-ps','v3-fixed-xbox','v3-fixed-pc']){$(id).disabled=blocked||!manual;$(id).required=manual;}
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
      for(const p of platforms)$('v3-fixed-'+p.toLowerCase()).value=settings.manual_prices[p]??'';
      $('v3-uplift-pct').value=settings.uplift_pct;
    }
    $('v3-effective-control').textContent=settings.manual_enabled?`人工干预生效 · ${platforms.map(p=>`${p} $${settings.manual_prices[p]} / 1K`).join(' · ')}`:
      settings.uplift_enabled?`策略定价 + 临时上浮 ${settings.uplift_pct}%`:'原经营策略定价';
    priceControlInputs();
  }
  function requestKey(kind){const name='fc-v3-'+kind;let key=sessionStorage.getItem(name);if(!key){key=crypto.randomUUID();sessionStorage.setItem(name,key);}return key;}
  function clearKey(kind){sessionStorage.removeItem('fc-v3-'+kind);}
  function chosenPlan(){return (current?.plans||[]).find(p=>p.plan_id===selectedPlanId)||current?.plan;}
  function executionReceipt(state){
    const progress=state?.manual_execution;
    return executeReceipt&&progress?.job_key!==executeReceipt.job_key?executeReceipt:progress;
  }
  function renderExecutionProgress(state){
    const receipt=executionReceipt(state);
    if(!receipt)return;
    if(receipt.job_key===executeReceipt?.job_key)executeReceipt=receipt;
    if(receipt.phase==='collecting')marketActivity('pending','正在采集竞品 100K 报价；卡片为最近保存的快照。');
    else if(receipt.phase==='failed')marketActivity('failed','本轮执行未完成；卡片保留原采价时点。');
    else if(!curvePending)marketActivity(null);
    const labels={rejected_no_change:'后台已拒绝，实际价格未变',queued:'已排队，等待采价',running:'执行中，等待当前任务进度',collecting:'正在采价',
      pricing:'采价完成，正在核算',checked:'核算完成，等待写入',writing:'正在写价',
      readback:'写价结果待核对',completed:'已完成读回',no_change:'本轮无需改价',
      failed:'本轮未完成',done:'本轮已结束，实际改价见操作回执',
      no_price_change:'原价已在使用',proof_incomplete:'恢复条件待核，未写价',
      hard_constraint_failed:'恢复价未通过财务复核，未写价',
      original_operation_reconciliation_pending:'等待原操作对账，尚未开始新采价'};
    $('v3-execution-progress').textContent=`${labels[receipt.phase||receipt.status]||'已登记，等待当前任务进度'} · 任务 ${receipt.job_key.replace(/^manual:/,'').slice(0,8)}${receipt.source_checked_at?` · 本轮采价 ${when(receipt.source_checked_at)}`:''}`;
    if(receipt.rows?.some(row=>row.gaps?.includes('pricing_restore_quantity_or_offer_changed'))){
      $('v3-execution-progress').textContent+=' · 当前商品规格或优惠与原表不一致';
    }
    $('v3-execution-job').textContent=receipt.job_key;
    $('v3-execution-reference').hidden=false;
  }
  function scheduleExecutionProgress(){
    clearTimeout(executionTimer);
    if(document.hidden||executionPageLeft||loading||executionRead||!['queued','running'].includes(executeReceipt?.status))return;
    executionTimer=setTimeout(readExecutionProgress,7000);
  }
  async function readExecutionProgress(){
    if(document.hidden||executionPageLeft||loading||executionRead)return;
    executionRead=request('state');
    try{
      const state=await executionRead;
      if(!executionPageLeft&&!document.hidden&&state.manual_execution?.job_key===executeReceipt?.job_key){
        executeReceipt=state.manual_execution;
        renderExecutionProgress(state);
        executeControls();
      }
    }catch(error){
      if(error.httpStatus===401||error.httpStatus===403)executeReceipt=null;
    }finally{
      executionRead=null;
      scheduleExecutionProgress();
    }
  }
  function executeControls(){
    const receipt=executionReceipt(current);
    const inFlight=receipt?.plan_id===chosenPlan()?.plan_id&&['queued','running'].includes(receipt?.status);
    const disabled=acting||inFlight||!canWrite||chosenPlan()?.state!=='ACTIVE'||lastAutomation?.system_enabled!==true;
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
  function setMode(mode){const draft=modeDrafts[mode]||modeDefaults[mode],owner=(current?.active_plans||[]).find(p=>['revenue_sprint','smart'].includes(p.mode)&&platforms.every(g=>p.resources?.includes('base:'+g))),baseline=owner?.mode==='smart'?owner.baseline_plan:owner,params=baseline?.parameters||{};$('v3-offsets').value=draft.offsets||'';['control','exploit','explore'].forEach((k,i)=>{$('v3-alloc-'+k).value=mode==='smart'?(params.allocation?.[k]??draft.allocation[i]):draft.allocation[i];$('v3-alloc-'+k).readOnly=mode==='smart';});for(const id of ['v3-ps','v3-xbox','v3-pc']){if(mode==='smart')$(id).checked=true;$(id).disabled=mode==='smart';}for(const input of $('v3-region-scopes').querySelectorAll('input')){if(mode==='smart')input.checked=true;input.disabled=mode==='smart';}$('v3-undercut').value=mode==='smart'?(baseline?(params.preferred_undercut_pct??'7.5'):''):(draft.undercut||'7.5');$('v3-undercut').readOnly=mode==='smart';$('v3-offsets-field').hidden=mode!=='daily';$('v3-undercut-field').hidden=mode==='daily';$('v3-target-section').hidden=mode!=='revenue_sprint';$('v3-allocation-legend').textContent=mode==='smart'?'继承当前冲额基准比例 · 不可在此修改':'试验分配 · 三项合计为 1';$('v3-mode-purpose').textContent=purposes[mode]+(mode==='smart'?(baseline?' 基准参数继承当前冲额计划，并一并接管全部Saudi范围。':' 当前冲额基准计划待核，不能创建。'):'');$('v3-end').required=false;$('v3-end-help').textContent='可选；留空持续运行，填写后按该时间结束。';if(current)renderDecision(current);}
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
    const result=await response.json();
    if(!response.ok){const error=Error(result.error||`请求失败 ${response.status}`);error.httpStatus=response.status;throw error;}
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
    $('player-enabled').disabled=!canWrite;$('player-form').querySelector('button').disabled=!canWrite;
    $('v3-interval-save').disabled=!canWrite||automationRevision==null;
    for(const control of $('v3-price-control-form').querySelectorAll('input,button'))control.disabled=!canWrite||acting||current?.price_control==null||!!sessionStorage.getItem(pendingPriceKey)&&control.id!=='v3-price-control-save';
    for(const id of ['v3-system-enabled','v3-auto-enabled'])$(id).disabled=!canWrite||acting||automationRevision==null;
    priceControlInputs();
    curveActivationControls();
    renderWeekly(current);
  }
  function renderWeekly(state){
    const weekly=state?.weekly_ladder,plan=state?.plan,control=weekly?.control||{};
    const panel=$('v3-weekly-panel'),output=$('v3-weekly-proposals'),automatic=$('v3-weekly-auto');
    output.replaceChildren();automatic.disabled=true;
    panel.hidden=!weekly||plan?.smart_strategy_version!=='market-anchor-v1';
    if(panel.hidden)return;
    $('v3-weekly-mode').textContent=control.automatic?'自动调整已开启':'由创建者逐周确认';
    const marginBand=!!plan.parameters?.margin_band;
    $('v3-weekly-help').textContent=(marginBand?'按两个完整自然周的订单和实际采购毛利调整目标利润率。确认后按新目标在决策轮核价。':'按两个完整自然周比较订单和实际采购毛利。确认后下一自然轮按新定位核价。')+
      (control.eligible_after?`前四周逐周确认，可开启自动的日期：${when(control.eligible_after)}。`:'首次周一评估后开始计算四周确认期。');
    const rows=weekly.proposals||[],week=rows[0]?.week_start;
    const rules={retain_raise:'保留上次定位',rollback_raise:'上次上调未达到保留条件，退回并冻结两周',recover_orders:'先改善订单量',raise_position:'小步提高定位',protect_orders:'订单低于底线，下调目标利润率',repair_margin:'实际毛利率低于 28%，上调目标利润率',continue_direction:'沿上周方向继续调整',revert_direction:'回退上周调整并冻结两周',probe:'试探调整目标利润率',hold:'保持目标利润率'};
    for(const proposal of rows.filter(row=>row.week_start===week)){
      const card=node('div');card.className='market-quote';
      const target=proposal.before_t!=null;
      const percent=value=>`${(Number(value)*100).toFixed(target?1:0)}%`;
      const platform=proposal.platform==='XBOX'?'Xbox':proposal.platform;
      card.append(node('h3',target?platform:`${platform} · ${proposal.band==='small'?'小额':'大额'}`));
      if(target){
        card.append(node('p',`目标利润率 ${percent(proposal.before_t)} → ${percent(proposal.after_t)}`),
          node('p',proposal.t_bound_reached?'目标利润率已到边界，保持当前目标':rules[proposal.rule]),
          node('p',`平台订单 ${proposal.previous_orders} → ${proposal.orders}；采购毛利 ¥${proposal.previous_procurement_gross_cny} → ¥${proposal.procurement_gross_cny}`));
      }else{
        card.append(node('p',`Lootbar 定位溢价 ${percent(proposal.before_p)} → ${percent(proposal.after_p)}`),
          node('p',Number(proposal.delta_p)===0&&proposal.rule==='raise_position'?'当前无可上调量段，保持定位':rules[proposal.rule]||'保持当前定位'));
        const before=proposal.prior?.[proposal.band],after=proposal.current?.[proposal.band];
        if(before&&after)card.append(node('p',`该段订单 ${before.orders} → ${after.orders}；采购毛利 ¥${before.procurement_gross_cny} → ¥${after.procurement_gross_cny}`));
      }
      if(proposal.market_ratio)card.append(node('p',`其余两平台订单系数 ${Number(proposal.market_ratio).toFixed(2)}；优先评估采购毛利率较低的平台。`));
      const labels={PROPOSED:'待确认',CONFIRMED:'已确认',REJECTED:'已拒绝',EXPIRED:'已过期'};
      card.append(node('p',`${labels[proposal.status]||'待核'} · 确认截止 ${when(proposal.expires_at)}`));
      const actions=node('div');actions.className='actions';
      for(const [operation,label] of [['confirm','确认本周调整'],['reject','本周不调整']]){
        const button=node('button',label);button.type='button';button.className='secondary';
        button.disabled=!canWrite||acting||proposal.status!=='PROPOSED'||Date.parse(proposal.expires_at)<=Date.now()||operation==='confirm'&&target!==marginBand;
        button.addEventListener('click',()=>{if(!canWrite||acting)return;return action(async()=>{
          await request(`weekly-ladder/${proposal.proposal_id}/${operation}`,operation==='confirm'?{expected_revision:current.plan.revision}:{});
          $('v3-result').textContent=target?(operation==='confirm'?'本周目标利润率已确认，下一个决策轮按新目标核价。':'本周提议已拒绝，目标利润率保持。'):
            (operation==='confirm'?'本周定位已确认；下一自然轮重新核价后执行。':'本周提议已拒绝，定位参数保持。');
        });});actions.append(button);
      }
      card.append(actions);output.append(card);
    }
    if(!rows.length)output.append(node('p','首个自然周结束后，周一等待归档齐全再评估；缺项会保留原因。'));
    automatic.textContent=control.automatic?'改为每周确认':'开启自动周调整';
    automatic.disabled=!canWrite||acting||!control.eligible_after||!control.automatic&&Date.parse(control.eligible_after)>Date.now();
  }
  function table(id,rows){
    const body=$(id);body.replaceChildren();
    if(!rows.length){const tr=node('tr'),td=node('td','尚无记录');td.colSpan=8;tr.append(td);body.append(tr);return;}
    for(const cells of rows){const tr=node('tr');for(const cell of cells)tr.append(node('td',value(cell)));body.append(tr);}
  }
  const isCurvePlan=state=>state?.plan?.write_protocol===curveProtocol;
  const curveSnapshot=state=>isCurvePlan(state)&&state.write_protocol===curveProtocol&&state.snapshot_id;
  function currentCurveOperation(state){
    const snapshotId=curveSnapshot(state);
    return snapshotId?(state.operations||[]).find(operation=>operation.bundle?.write_protocol===curveProtocol
      &&operation.bundle.snapshot_id===snapshotId&&operation.plan_id===state.plan.plan_id):undefined;
  }
  function curveOperationStatus(operation){
    if(operation.status!=='COMPLETED')return statusText(operation.status);
    const readback=operation.readback;
    return readback?.write_protocol===curveProtocol&&readback.execution_id===operation.operation_id
      &&readback.status==='CONFIRMED'?'该操作的 Admin 主站价表已核对':'原操作已完成，主站价表回执待核';
  }
  function renderCurveDecision(state,cards){
    const snapshotId=curveSnapshot(state),decision=snapshotId&&state.curve_decision;
    const card=node('article');card.className='panel';
    card.append(node('h3',names[state.plan.mode]||'当前定价'));
    card.append(node('p',decision?statusText(decision.status):'等待当前 V6 计划的核算结果。'));
    for(const row of decision?.rows||[]){
      const platform=row.platform==='XBOX'?'Xbox':row.platform;
      const segment={small:'小额段',large:'大额段'}[row.selection?.segment];
      const label=row.selection?.actual_label||row.selection?.label;
      const assignment=segment?' · '+segment+(['A','B','C'].includes(label)?' '+label+' 档':''):'';
      const gaps=(row.gaps||[]).map(statusText);
      card.append(node('p',platform+' · '+statusText(row.status)+assignment+(gaps.length?' · '+gaps.join('、'):'')));
    }
    const operation=currentCurveOperation(state);
    if(operation){
      card.append(node('p','本轮原操作 · '+curveOperationStatus(operation)+' · '+operation.operation_id));
    }else if(decision?.status==='READY'){
      card.append(node('p','已形成候选，等待本轮原操作回执。'));
    }
    cards.append(card);
    $('v3-decision-basis').textContent=decision?'本轮快照 '+snapshotId+' · V6'
      :snapshotId?'V6 采集快照 '+snapshotId+' · 等待本轮核算。':'等待当前 V6 快照。';
  }
  function renderDecision(state){
    const mode=$('v3-mode').value,r=state.strategies?.[mode],cards=$('v3-strategies');cards.replaceChildren();
    $('v3-mode-purpose').textContent=modePurpose(mode,isCurvePlan(state)?state.plan:chosenPlan());
    if(isCurvePlan(state)){renderCurveDecision(state,cards);return;}
    const control=r?.selected?.price_control;
    const unmet=Object.values(r?.selected?.daily_pricing||{}).filter(t=>!t.item_target_met),unmetSources=[...new Set(unmet.map(t=>t.driver_source||'ItemD2R'))];
    const card=node('article');card.className='panel';card.append(node('h3',control?.manual_enabled?'人工干预':names[mode]),node('p',control?'最终价已通过双红线核算':unmet.length?`双20可写，未达到${unmetSources.join('/')}目标`:r?.selected?.decision_type==='floor_fallback'?'双20可写，未达到竞争目标':r?.status?statusText(r.status):'尚无本轮同策略决策'));
    if(mode==='smart'&&r?.smart_assignment){
      const a=r.smart_assignment;
      if(a.strategy_version==='smart-three-platform-v3'){
        card.append(node('p',`三平台双向试验 · 本轮计划档位 ${platforms.map(p=>`${p} ${a.group_labels?.[p]||'待核'}`).join(' / ')}；实际开窗以写后确认回执为准。`));
        for(const [group,title] of platforms.map(p=>[p,p==='XBOX'?'Xbox':p])){
          const closed=a.no_space_by_group?.[group],winner=a.policy?.group_results?.[group]?.winner;
          const excluded=[...new Set([...(a.policy?.group_results?.[group]?.excluded||[]),...Object.entries(a.correction?.groups?.[group]?.effective_blocks||{}).filter(([,n])=>n<=a.block).map(([label])=>label)])];
          card.append(node('p',`${title} · ${closed?'候选同价合并，未形成有效价差':a.merged_with_A_by_group?.[group]?'本轮候选与A合并':'保留独立价格试验'} · ${winner?`${winner}档暂定领先，保留对照和探索`:'尚无成熟赢家'}${excluded.length?` · 已撤回档位 ${excluded.join('、')}`:''}。`));
        }
      }else if(a.strategy_version==='smart-bidirectional-v2'){
        card.append(node('p',`历史双向试验v2 · Console ${a.group_labels?.console||'待核'} / PC ${a.group_labels?.pc||'待核'}；按原回执解释。`));
        for(const [group,title] of [['console','Console'],['pc','PC']])card.append(node('p',`${title} · ${a.no_space_by_group?.[group]?'候选同价合并':'独立历史试验'} · ${a.policy?.group_results?.[group]?.winner||'尚无成熟赢家'}`));
      }else{
        const closed=Object.entries(a.no_space_by_group||{}).filter(([,v])=>v).map(([g])=>g==='pc'?'PC':'Console'),excluded=[...new Set([...(a.policy?.excluded||[]),...Object.entries(a.correction?.effective_blocks||{}).filter(([,n])=>n<=a.block).map(([k])=>k)])];card.append(node('p',a.no_uplift_space?'本轮缺少提价空间，候选合并；未形成有效价差。':`本轮计划档位 ${a.label}；实际价格及写后读回以执行记录为准。${closed.length?` ${closed.join('、')} 本轮缺少提价空间。`:''}`));card.append(node('p',a.policy?.winner?`观察性结果：${a.policy.winner} 档暂定领先；保留对照和探索。`:'效果数据尚未形成成熟赢家，继续按计划观察。'));if(excluded.length)card.append(node('p',`已撤回提价档：${excluded.join('、')}。`));
      }
    }
    if(r?.selected){const s=r.selected;if(control)card.append(node('p',control.manual_enabled?'人工干预：本轮使用已保存固定价，策略和涨幅不参与。':`临时上浮 ${control.uplift_pct}%：原策略 ${pricesText(s.strategy_action?.base_prices)}。`));card.append(node('p',`本轮最终候选 100K：${pricesText(s.action?.base_prices)}`),node('p',control?.manual_enabled?'人工指定价格，未运行策略收入预测。':s.score?.absolute_forecast_available?`同轮预测收入 ${usd(s.score.revenue)} · 采购贡献 ${usd(s.score.contribution)}`:'只有相对需求情景；绝对收入与新客效果待真实基线核证'));
      if(s.decision_type==='floor_fallback')card.append(node('p','财务底价兜底：竞争区间与双 20% 红线无交集；执行最低可写合法底价，不能视为已达到竞争降幅。'));
      for(const [group,target] of Object.entries(control?{}:s.daily_pricing||{})){
        const source=target.driver_source||'ItemD2R',label=source==='ItemD2R'?'Item':source;
        card.append(node('p',`${group==='XBOX'?'Xbox':group}按${source} ${target.driver_platform}当轮实际交付价定价：我方100K套餐目标 ${usd(target.target_public_usd)}，执行基础价 ${usd(target.selected_base_total)}。${target.item_target_met?`达到${label}目标（按公开分币舍入）`:target.unmet_reason==='public_cent_not_reachable'?`舍入导致目标未命中，未达到${label}目标`:`财务底价抬高，未达到${label}目标`}。`));
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
  function priceDifference(after,before){
    if(after==null||before==null)return null;
    const difference=Math.round(Number(after)*100)-Math.round(Number(before)*100);
    return Number.isFinite(difference)?difference:null;
  }
  function priceChange(target,difference,caption){
    target.hidden=difference===null;
    target.dataset.trend=difference>0?'up':difference<0?'down':'same';
    target.textContent=difference===null?'':`${caption} ${difference>0?'+':difference<0?'−':''}${usd(Math.abs(difference)/100)}`;
  }
  function platformCard(platform){
    const card=node('article');
    card.className='market-platform';
    card.dataset.platform=platform.toLowerCase();
    const title=node('h3',platform==='XBOX'?'Xbox':platform);
    title.className='platform-name';
    card.append(title);
    return card;
  }
  function renderCatalogue(samples={}){
    const rows=lastMonitor?.storefront?.rows||{};
    const verified=current?.catalogue_readbacks||{};
    const unresolved=(current?.operations||[]).some(operation=>['UNKNOWN','PARTIALLY_APPLIED'].includes(operation.status));
    $('v3-catalogue-status').textContent=unresolved?'保存未确认，以下为最后读到的价格。':'';
    const completed=(current?.operations||[]).find(operation=>operation.status==='COMPLETED'
      &&operation.readback?.write_protocol===curveProtocol&&operation.readback.execution_id===operation.operation_id
      &&operation.readback.status==='CONFIRMED');
    for(const platform of platforms){
      const slug=platform.toLowerCase(),readback=verified[platform],sample=samples[platform];
      const catalogue=sample&&(!readback||Date.parse(sample.observed_at)>Date.parse(readback.observed_at))?sample:readback;
      const small=catalogue?.tiers.find(tier=>tier.purchase_k==='100');
      const large=catalogue?.tiers.find(tier=>tier.purchase_k==='1000');
      const publicRow=rows[platform],usePublic=!isCurvePlan(current)&&publicRow?.package_usd!=null&&(!small||
        Date.parse(publicRow.checked_at)>Date.parse(catalogue.observed_at));
      const smallPrice=usePublic?publicRow.package_usd:small?.native_price_usd;
      const priceSmall=$('v3-price-'+slug),priceLarge=$('v3-price-large-'+slug);
      priceSmall.textContent=smallPrice==null?'现价待核':usd(smallPrice);
      priceLarge.textContent=large?usd(large.native_price_usd):'现价待核';
      priceSmall.dataset.missing=String(smallPrice==null);
      priceLarge.dataset.missing=String(!large);
      const delivery=tier=>tier?`赠 ${tier.promised_bonus_k}K · 实交 ${Number(tier.purchase_k)+Number(tier.promised_bonus_k)}K`:'';
      $('v3-price-small-delivery-'+slug).textContent=usePublic?'公开套餐':delivery(small);
      $('v3-price-delivery-'+slug).textContent=delivery(large);
      const sampleLabel=catalogue?.basis==='confirmed_readback'?'后台已确认':'后台采样';
      $('v3-price-source-'+slug).textContent=catalogue?`${sampleLabel} · ${when(catalogue.observed_at)}`
        :usePublic?`公开采样 · ${when(publicRow.checked_at)}`:'来源待核';
      const receipt=completed?.readback.curve_results?.[platform];
      const sameReadback=catalogue?.basis==='confirmed_readback'&&receipt&&receipt.operation_id===completed.operation_id
        &&receipt?.propagation?.status==='confirmed'&&receipt.propagation.confirmed_at===catalogue.observed_at;
      const before=sameReadback?receipt?.recipients_before?.['266']?.more:null;
      const previous=quantity=>before?.price?.[before?.gold?.findIndex(value=>Number(value)===quantity)];
      priceChange($('v3-price-change-'+slug),usePublic?null:priceDifference(smallPrice,previous(100)),'最近确认');
      priceChange($('v3-price-change-large-'+slug),priceDifference(large?.native_price_usd,previous(1000)),'最近确认');
    }
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
    $('v3-next-cycle').textContent=schedule.status==='waiting_for_yesterday_es'?'等待昨日 ES 发布，完成后顺延执行':schedule.next_cycle_at?when(schedule.next_cycle_at):(schedule.active_plan_state==='SUSPENDED'||plan?.state==='SUSPENDED'?'已暂停，无下一自然写价轮':'暂无已排定自然轮');
    const curve=isCurvePlan(state),snapshotId=curveSnapshot(state);
    const sourceTime=curve?(snapshotId&&state.source_checked_at):schedule.last_source_checked_at;
    $('v3-source-time').textContent=sourceTime?when(sourceTime):'当前计划来源待核';
    const latest=state.operations?.[0],curveConfirmed=latest?.status==='COMPLETED'&&latest?.readback?.write_protocol===curveProtocol
      &&latest.readback.execution_id===latest.operation_id&&latest.readback.status==='CONFIRMED';
    const orderAdminLabel=curveConfirmed?'Admin 主站完整价表已确认':
      latest?.status==='COMPLETED'&&latest?.order_close?.reason==='order_write_confirmed_admin_price_matched'?'Order与Admin已确认':null;
    const stageLabel=orderAdminLabel&&(!schedule.last_execution_stage||schedule.last_execution_stage==='COMPLETED')?orderAdminLabel:statusText(schedule.last_execution_stage||latest?.status);
    const curveOperation=currentCurveOperation(state);
    $('v3-stage').textContent=curve
      ?(curveOperation?curveOperationStatus(curveOperation):snapshotId&&state.curve_decision?statusText(state.curve_decision.status):'当前 V6 进度待核')
      :`${stageLabel}${schedule.last_cycle_at?` · ${when(schedule.last_cycle_at)}`:''}`;
    renderExecutionProgress(state);
    const rows=monitor?.storefront?.rows||{};
    renderCatalogue();
    const publication=monitor?.publication?.status;
    $('v3-public-status').textContent=`公开网页独立核验：${publication==='matched'?'已核实':publication?statusText(publication):'待核'} · 最近公开采样 ${when(rows.PS?.checked_at||rows.PC?.checked_at)}`;
    const receipt=latest?.bundle||{},source=receipt.decision_source;
    const operationScope=curve?(receipt.write_protocol===curveProtocol?'V6 · ':'旧标量历史 · '):'';
    const reviewLabel=receipt.maintenance_purpose==='retire_uk_discount_v1'?'用户授权英国临时折扣退出；程序已核财务与地区规则':receipt.review_contract==='program_pricing_with_daily_hermes_review_v3'?'当前规则：程序逐轮定价，Hermes 每日效果复盘':(source==='v3_model_reviewed_this_cycle'||source==='v3_reviewed_assignment')&&receipt.review_approved===true?'本轮 Hermes 实际选择并审核':
      source==='v3_model_reviewed_this_cycle'?'模型选择回执与批准状态不一致，待核':
      source==='v3_inherited_reviewed_business_strategy'?'沿用先前已审经营策略，本轮程序重证':
      source==='v3_explicit_deterministic_feasible_assignment'||receipt.review_approved===false?'历史原操作当时使用程序路径，未获模型审核；当前规则无需逐轮审核':'审核来源待核';
    $('v3-review-source').textContent=latest?`最近原操作 ${operationScope}${latest.operation_id}：${orderAdminLabel||statusText(latest.status)}。${reviewLabel}；${orderAdminLabel?'公开网页核验单独列示':'以原操作回执核对实际结果'}。`:'尚无 V3 原操作。程序负责正常定价，Hermes 每日提供效果评估。';
    const daily=state.daily_review;
    $('v3-daily-status').textContent=daily?`${daily.local_date} · ${statusText(daily.phase)} · 专用定价通道；不会自动切换策略`:'尚无每日结果；每天 02:20 复盘前一日，保存的分时段输入不足会列为缺项。';
    const replies=(daily?.hermes?.evaluation?.turns||[]).map(t=>t.reply).filter(Boolean);
    const historyNote=daily&&current.plan?.financial_contract_version==='fc27_dual20_v1'&&daily.decision_basis?.financial_contract_version!=='fc27_dual20_v1'?'此为历史复盘，原文中的旧策略、预算、双10和赠品假设不代表当前规则；当前只保留日常运营与冲销售额、双20、无预算，ItemD2R按原100K核算。\n\n':'';
    $('v3-daily-result').textContent=historyNote+(replies.join('\n\n')|| (daily?`实际数据：${daily.actual?.status||'待核'}；影子：${daily.shadow?.status||'待运行'}；Hermes：${daily.hermes?.phase||'待提交'}`:''));

    $('collect').disabled=!canWrite||acting||!!collectPending;
    curveControls();
  }

  function curveControls(){
    const button=$('v3-curve-collect');
    button.disabled=!canWrite||curveChecking||Boolean(curvePending&&!curveRetry);
    button.textContent=curveRetry==='submit'?'续办原采集':curveRetry==='preview'?'重读原预览':'采集并预览新定价';
    curveActivationControls();
  }

  function pendingCurveActivation(){
    const stored=sessionStorage.getItem(curveActivationKey);
    return stored?JSON.parse(stored):null;
  }

  function curveReadyFor(plan){
    return curveReady&&Date.now()<curveReady.expiresAt&&plan?.state==='ACTIVE'&&!plan.write_protocol
      &&Number.isInteger(plan.revision)&&plan.resources?.some(resource=>resource.startsWith('base:'));
  }

  function curveActivationControls(){
    const button=$('v3-curve-activate'),pending=pendingCurveActivation();
    button.disabled=!canWrite||acting||curveChecking||!(pending||curveReadyFor(chosenPlan()));
    button.textContent=pending?(curveActivationRetry?'续办原启用':'核对原启用'):'启用新定价';
    $('v3-curve-read').disabled=!canWrite||acting||curveChecking||!!curvePending;
  }

  function readCurveActivation(state,pending){
    const plan=(state?.plans||[]).find(value=>value.plan_id===pending.planId);
    const status=$('v3-curve-activation-status');
    if(plan?.write_protocol===curveProtocol&&plan.curve_activation_snapshot_id===pending.snapshotId
        &&plan.revision>=pending.revision+1){
      sessionStorage.removeItem(curveActivationKey);
      curveReady=null;curveActivationRetry=false;
      status.textContent=`新定价已启用，计划 ${plan.plan_id} · 版本 ${plan.revision}。实际改价以原自动轮回执为准。`;
      return true;
    }
    if(plan?.state==='ACTIVE'&&plan.revision===pending.revision&&!plan.write_protocol){
      curveActivationRetry=Date.now()<pending.expiresAt;
      if(!curveActivationRetry){sessionStorage.removeItem(curveActivationKey);curveReady=null;}
      status.textContent=`原计划仍是版本 ${plan.revision}，尚未读到启用回执。${curveActivationRetry?'可按原预览续办。':'原预览已过期，请重新采集。'}`;
      return false;
    }
    curveActivationRetry=false;
    status.textContent=`启用回执待核，计划 ${pending.planId} · 原预览 ${pending.snapshotId}。`;
    return false;
  }

  async function activateCurve(){
    if(!canWrite||acting||curveChecking)return;
    return action(async()=>{
      const status=$('v3-curve-activation-status');
      let pending=pendingCurveActivation();
      if(pending&&!curveActivationRetry){
        readCurveActivation(await request('state'),pending);
        return;
      }
      if(!pending){
        const plan=chosenPlan();
        if(!curveReadyFor(plan)){
          status.textContent='预览已过期或所选计划当前不可启用，请刷新核对。';
          return;
        }
        pending={planId:plan.plan_id,revision:plan.revision,snapshotId:curveReady.snapshotId,expiresAt:curveReady.expiresAt};
        sessionStorage.setItem(curveActivationKey,JSON.stringify(pending));
      }
      curveActivationRetry=false;
      status.textContent=`正在启用计划 ${pending.planId} · 原预览 ${pending.snapshotId}。`;
      try{
        await request(`plans/${pending.planId}/activate-curve`,{expected_revision:pending.revision,snapshot_id:pending.snapshotId});
      }catch(error){
        if(error.httpStatus>=400&&error.httpStatus<500&&![408,409,429].includes(error.httpStatus)){
          sessionStorage.removeItem(curveActivationKey);
          if(error.message==='pricing_curve_activation_snapshot_unverified')curveReady=null;
          status.textContent=`启用请求未完成。${errorText(error)}。`;
          return;
        }
      }
      status.textContent=`启用回执待核，计划 ${pending.planId} · 原预览 ${pending.snapshotId}。`;
      const state=await request('state').catch(()=>null);
      if(state)readCurveActivation(state,pending);
    });
  }

  function marketActivity(state,label=''){
    const status=$('v3-market-activity');
    status.hidden=!state;
    status.dataset.state=state||'';
    if(status.textContent!==label)status.textContent=label;
  }
  function curveStatus(text,id,marketState){
    if(marketState)marketActivity(marketState,marketState==='pending'?`${text}；卡片为最近保存的快照。`:text);
    const status=$('v3-curve-status'),reference=$('v3-curve-reference');
    const label=id?`${text} · 任务 ${id.slice(0,8)}`:text;
    if(status.textContent!==label)status.textContent=label;
    if(id){reference.textContent=`原采集任务 ${id}`;reference.hidden=false;}
  }

  function finishCurve(){
    curvePending=null;
    curveRetry='';
    curveSubmitError='';
    curveReadOnly=false;
    sessionStorage.removeItem(curvePendingKey);
    clearKey(curveRequest);
  }

  function rememberCollectedMarket(id){
    collectedMarketId=id;
    sessionStorage.setItem(collectedMarketKey,id);
    return renderMarketEvidence();
  }

  async function readCollectionStatus(){
    if(!collectPending||executionPageLeft)return;
    clearTimeout(collectTimer);
    const id=collectPending;
    const job=await cloud('jobs/'+id).catch(()=>null);
    if(collectPending!==id||executionPageLeft)return;
    if(!job||!['ready','failed'].includes(job.status)){
      collectTimer=setTimeout(readCollectionStatus,10000);
      return;
    }
    let result;
    if(job.status==='failed'){
      result=`采集失败（${errorText({message:job.error_detail||job.error||'原因待核'})}）。竞品卡片保留原采集时间，本次未改价。`;
    }else if(job.result?.status==='INFEASIBLE'){
      result='采集已完成；当前策略无可执行报价，未写价。';
    }else if(current?.plan?.write_protocol===curveProtocol){
      const shown=job.job_id===id&&job.kind==='collect'&&job.result?.run_id===id&&await rememberCollectedMarket(id);
      if(collectPending!==id||executionPageLeft)return;
      result=shown?'采集已完成，已显示本次竞品报价。本次未改价。':'采集已完成，竞品快照暂未显示，可更新状态重读。本次未改价。';
    }else{
      result='采集已完成，本轮报价需另经 V3 证明。本次未改价。';
    }
    $('v3-result').textContent=`只读采集任务 ${id}：${result}`;
    collectPending=null;sessionStorage.removeItem('fc-v3-collect-job');clearKey('collect');
    $('collect').disabled=!canWrite||acting;
  }

  function renderCurvePreviews(previews){
    const output=$('v3-curve-results');
    const proofLabels={PROVEN:'核算通过',HARD_CONSTRAINT_FAILED:'未达到财务底线',PROOF_INCOMPLETE:'证据待补',NOT_EVALUABLE:'暂无法核算'};
    output.replaceChildren(...previews.map((item,index)=>{
      const card=platformCard(platforms[index]);
      const caption=node('p',item?`候选预览 · ${when(item.snapshot_captured_at)}`:'预览暂不可读');
      caption.className='candidate-caption';
      card.append(caption);
      const catalogue=item?.current_catalogue,currentQuote=catalogue?.quote_100k;
      const candidates=[...(item?.small?.decision?.candidates||[]),...(item?.decision?.candidates||[])];
      if(item&&!candidates.length){
        const gap=item.decision?.gaps?.at(-1);
        card.append(node('p',`暂无候选报价${gap?` · ${errorText({message:gap})}`:''}`));
      }
      const proofDetails=node('details');
      proofDetails.className='candidate-basis';
      proofDetails.append(node('summary','核算依据'));
      for(const candidate of candidates){
        const proof=candidate.financial_proof,quote=candidate.quote;
        const labels={CURRENT:'当前方案',COST_REPAIR:'成本底线修复'};
        const label=candidate.labels?.map(value=>labels[value]||value).join(' / ')||'候选';
        const row=node('div');row.className='curve-quote';
        const heading=node('div');heading.className='quote-heading';
        heading.append(node('span',label),node('strong',quote?.regular_usd==null?'待核':`${quote.purchase_k}K ${usd(quote.regular_usd)}`));
        const quantity=Number(quote?.purchase_k);
        const currentPrice=quantity===100?currentQuote?.regular_usd
          :catalogue?.tiers?.find(tier=>Number(tier.purchase_k)===quantity)?.native_price_usd;
        const result=node('p',proofLabels[proof?.status]||'证据待补');result.className='quote-meta';
        const change=node('p');change.className='price-change';
        priceChange(change,priceDifference(quote?.regular_usd,currentPrice),'同档较现价');
        row.append(heading,result,change);
        if(quote?.promised_bonus_k!=null&&quote?.promised_delivered_k!=null){
          const delivery=node('p',`赠 ${quote.promised_bonus_k}K · 实交 ${quote.promised_delivered_k}K`);
          delivery.className='quote-meta';
          row.append(delivery);
        }
        card.append(row);
        const average=proof?.average_discount;
        if(average?.contract){
          const retained=average.retained_ratio,margin=proof.minimum_safe_procurement_margin;
          const rate=retained==null?'待补':`${((1-Number(retained))*100).toFixed(2)}%`;
          const marginText=margin==null?'待核':`${(Number(margin)*100).toFixed(2)}%`;
          proofDetails.append(node('p',`${quote?.purchase_k??'待核'}K · ${label} · ${discountWindow(average)} 平均优惠 ${rate} · 已核 ${average.matched_orders}/${average.eligible_orders} 单`),
            node('p',`组合采购毛利 ${marginText}（底线 18%，目标 25%）`));
        }
      }
      if(proofDetails.children.length>1)card.append(proofDetails);
      return card;
    }));
    output.hidden=false;
  }

  async function checkCurveCollection(){
    if(!curvePending||curveChecking||!canWrite)return;
    clearTimeout(curveTimer);
    curveChecking=true;
    curveRetry='';
    curveControls();
    const id=curvePending;
    let retry=false;
    try{
      let job;
      try{job=await cloud('jobs/'+id);}
      catch(error){
        if(error.httpStatus!==404)throw error;
        if(curveReadOnly){
          curveStatus('未找到原采集。请核对编号。',id);
          finishCurve();
          return;
        }
        curveRetry='submit';
        curveStatus(curveSubmitError?`${curveSubmitError}。可用原编号续办。`:'暂未找到采集。可用原编号续办。',id);
        return;
      }
      curveSubmitError='';
      if(job.job_id!==id||job.kind!=='collect'||job.request?.write_protocol!==curveProtocol){
        curveStatus('回执与新定价请求不符。',id);
        if(curveReadOnly)finishCurve();
        return;
      }
      if(job.status==='failed'||job.result?.status==='INFEASIBLE'){
        curveStatus(`未能生成预览。${errorText({message:job.error_detail||job.result?.reason||job.error||'原因待核'})}`,id,job.status==='failed'&&!curveReadOnly?'failed':null);
        finishCurve();
        return;
      }
      if(job.status!=='ready'){
        curveStatus(job.status==='queued'?'已排队，等待采价':job.status==='running'?'正在采集三平台报价':'等待原任务进度',id,curveReadOnly?null:'pending');
        retry=true;
        return;
      }
      if(job.result?.run_id!==id){
        curveRetry='preview';
        curveStatus('预览快照待核，可重读原任务。',id);
        return;
      }
      curveStatus('采价完成，正在读取核算结果',id,curveReadOnly?null:'success');
      if(!curveReadOnly&&current?.plan?.write_protocol===curveProtocol)await rememberCollectedMarket(id);
      const results=await Promise.allSettled(platforms.map(async platform=>{
        const preview=await request('preview',{write_protocol:curveProtocol,platform,snapshot_id:id});
        if(preview.snapshot_id!==id||preview.platform!==platform||preview.write_protocol!==curveProtocol
          ||preview.execution_authorized!==false||preview.write_performed!==false)throw Error('pricing_preview_scope_mismatch');
        const small=await request('preview',{write_protocol:curveProtocol,platform,snapshot_id:id,segment:'small'}).catch(()=>null);
        if(small?.snapshot_id===id&&small.platform===platform&&small.write_protocol===curveProtocol&&
          small.execution_authorized===false&&small.write_performed===false)preview.small=small;
        return preview;
      }));
      const previews=results.map(result=>result.status==='fulfilled'?result.value:null);
      renderCurvePreviews(previews);
      if(previews.some(item=>!item)){
        curveRetry='preview';
        curveStatus('采价完成。部分平台预览暂不可读，可重读原预览。',id);
      }else{
        const captured=Date.parse(previews[0].snapshot_captured_at);
        const proven=previews.every(item=>Date.parse(item.snapshot_captured_at)===captured&&
          item.decision?.candidates?.some(candidate=>candidate.financial_proof?.status==='PROVEN'&&
            candidate.labels?.some(label=>label==='CURRENT'||label==='COST_REPAIR')));
        if(proven)curveReady={snapshotId:id,expiresAt:captured+15*60*1000};
        curveStatus(`三平台预览已读回 · 本次未改价${Number.isFinite(captured)?` · 本轮采价 ${when(captured)}`:''}`,id);
        finishCurve();
      }
    }catch(error){
      curveStatus('状态暂不可读，正在核对原任务。',id);
      retry=true;
    }finally{
      curveChecking=false;
      curveControls();
      if(retry)curveTimer=setTimeout(checkCurveCollection,10000);
    }
  }

  async function startCurveCollection(){
    if(!canWrite||curveChecking)return;
    if(curvePending&&curveRetry!=='submit')return checkCurveCollection();
    const id=curvePending||requestKey(curveRequest);
    curveReady=null;
    curvePending=id;
    sessionStorage.setItem(curvePendingKey,id);
    curveChecking=true;
    curveRetry='';
    curveSubmitError='';
    curveControls();
    $('v3-curve-results').hidden=true;
    curveStatus('正在登记只读采集',id);
    try{
      const receipt=await cloud('pricing/collect',{client_event_id:id,write_protocol:curveProtocol});
      if(receipt.job_id!==id)curveStatus('提交回执待核。',id);
    }catch(error){
      if(error.httpStatus>=400&&error.httpStatus<500&&![408,409,429].includes(error.httpStatus)){
        curveStatus(`未登记。${errorText(error)}`,id);
        finishCurve();
      }else{
        if(error.httpStatus)curveSubmitError=errorText(error);
        curveStatus('提交回执待核。',id);
      }
    }finally{
      curveChecking=false;
      curveControls();
    }
    return checkCurveCollection();
  }

  function readExistingCurve(){
    if($('v3-curve-read').disabled)return;
    const id=$('v3-curve-read-id').value.trim();
    if(!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(id)){
      curveStatus('请输入有效的原采集任务编号。');
      return;
    }
    curveReady=null;
    curvePending=id;
    curveReadOnly=true;
    $('v3-curve-results').hidden=true;
    return checkCurveCollection();
  }
  async function renderMarketEvidence(){
    const reading=++marketRead;
    const output=$('v3-market-cards'),summary=$('v3-market-status');output.setAttribute('aria-busy','true');
    summary.dataset.state='pending';
    $('v3-market-reference').hidden=true;
    const curveActive=(current?.plan?.write_protocol===curveProtocol);
    for(const platform of ['ps','xbox','pc'])$('v3-price-basis-'+platform).textContent=curveActive?'新定价核算待核':'采购成本 / 双红线待核';
    const originalId=curveActive?collectedMarketId:null;
    try{
      const [planMarket,collected]=await Promise.all([
        request('market'),originalId?request('market/'+originalId).catch(()=>null):null
      ]);
      if(reading!==marketRead)return false;
      const fromCollection=collected?.snapshot_id===originalId&&collected?.basis==='readonly_collection'
        &&collected.write_protocol===curveProtocol&&collected.execution_authorized===false&&collected.write_performed===false
        &&(!planMarket.snapshot_id||Date.parse(collected.captured_at)>=Date.parse(planMarket.captured_at));
      const market=fromCollection?collected:planMarket;
      output.replaceChildren();
      renderCatalogue(planMarket.catalogue_samples);
      if(!market.snapshot_id){summary.textContent='尚无采集快照，等待下一次来源采集。';return;}
      if(curveActive){
        if(market.write_protocol!==curveProtocol){summary.textContent='正在等待当前新定价的市场与财务证据。';return;}
        for(const platform of platforms){
          const column=platformCard(platform);
          const details=$('v3-price-basis-'+platform.toLowerCase()),basis=planMarket.price_basis?.rows?.[platform];
          const retained=basis?.average_discount?.retained_ratio,margin=basis?.minimum_safe_procurement_margin;
          if(retained!=null)details.replaceChildren(node('p',`${discountWindow(basis?.average_discount)} 平均优惠 ${((1-Number(retained))*100).toFixed(2)}%`),
            node('p',`采集时估算组合采购毛利 ${margin==null?'待核':(Number(margin)*100).toFixed(2)+'%'}`));
          if(basis?.normal_anchors?.large != null && basis?.final_anchors?.large != null){
            const protectedLarge=Boolean(basis.cost_protection?.segments?.large);
            details.append(node('p',`1000K · 基准 ${usd(basis.reference_anchors?.large)} · 候选 ${usd(basis.normal_anchors.large)} · 目标 ${usd(basis.final_anchors.large)}${protectedLarge?' · 含临时成本保护':''}`));
            const references=basis.large_market_reference||[];
            if(!references.length)details.append(node('p','1000K 参考暂无同地区、同币种及同发货方式样本。'));
            const percent=value=>`${Number(value)>0?'+':''}${Number(value).toFixed(1)}%`;
            for(const reference of references){
              const source=reference.source==='ArabUT'?'Arab-UT':reference.source;
              details.append(node('p',`${source} · 由 100K 线性折算 ${usd(reference.price_usd)} / 1000K，赠 ${reference.bonus_k}K · ${when(reference.captured_at)}`),
                node('p',`每实交 100K ${usd(reference.usd_per_delivered_100k)} · 候选价差 ${percent(reference.normal_difference_pct)} · 目标价差 ${percent(reference.final_difference_pct)}`));
            }
          }
          for(const source of ['Lootbar','U7Buy','ArabUT']){
            const card=node('section');card.className='market-quote';card.append(node('h4',source==='ArabUT'?'Arab-UT':source));
            const offers=(market.competitor_offers||[]).filter(row=>row.source===source&&row.platform===platform&&Number(row.purchase_k)===100);
            if(!offers.length){
              card.dataset.state='failed';
              const empty=node('p','该快照未取得 100K 报价');empty.className='quote-state';card.append(empty);
            }
            for(const offer of offers){
              const amount=offer.regular_price??offer.eligible_net_price??offer.display_price;
              const price=node('p',amount==null?'价格待核':offer.currency==='USD'?usd(amount):offer.currency+' '+amount);
              price.className='market-amount';
              const age=Date.now()-Date.parse(offer.captured_at);
              const knownTime=Number.isFinite(age)&&age>=0;
              const status=amount==null?'failed':!knownTime||!offer.comparable||age>15*60000?'pending':'success';
              const label=amount==null?'报价未取得':!knownTime?'采价时间待核':age>15*60000?'历史报价 · 已过 15 分钟':
                !offer.comparable?'口径待核':'已采 · 15 分钟内';
              const evidence=node('p',label);evidence.className='quote-state';evidence.dataset.state=status;
              const timestamp=node('p',`采价 ${when(offer.captured_at)}`);timestamp.className='quote-meta';
              const detail=node('details');detail.className='market-details';
              const gift=offer.bonus_k==null?'赠送待核':`赠 ${offer.bonus_k}K`;
              const method=offer.delivery_tier||offer.delivery_method;
              detail.append(node('summary','报价详情'),node('p',`购买 100K · ${gift}${method?` · ${method}`:''}`));
              card.append(price,evidence,timestamp,detail);
            }
            column.append(card);
          }
          output.append(column);
        }
        summary.dataset.state='success';
        summary.textContent=fromCollection?`只读采集快照 · ${when(market.captured_at)} · 本次未改价`:
          `新定价采集快照 · ${when(market.captured_at)}`;
        $('v3-market-reference').hidden=false;
        $('v3-market-snapshot').textContent=market.snapshot_id;
        return fromCollection;
      }
      if(market.snapshot_id!==current?.snapshot_id){summary.textContent='来源快照与本轮决策不一致，等待统一状态更新。';return;}
      const newPolicy=primaryPolicy(chosenPlan());
      for(const platform of ['PS','XBOX','PC']){
        const details=$('v3-price-basis-'+platform.toLowerCase()),basis=market.price_basis?.rows?.[platform];details.replaceChildren();
        if(!basis){details.textContent='采购成本 / 双红线待核';continue;}
        const publicPrice=lastMonitor?.storefront?.rows?.[platform]?.package_usd,cost=Number(basis.package_cost_usd),retained=Number(basis.historical_retained_ratio);
        const currentMargin=publicPrice>0&&Number.isFinite(cost)?((Number(publicPrice)-cost)/Number(publicPrice)*100).toFixed(1)+'%':'待核';
        const averageMargin=publicPrice>0&&retained>0&&Number.isFinite(cost)?((Number(publicPrice)*retained-cost)/(Number(publicPrice)*retained)*100).toFixed(1)+'%':'待核';
        const averageDiscount=retained>0&&retained<=1?(Math.floor((1-retained)*1000+1e-9)/10).toFixed(1)+'%':'待核';
        const averageWindow=market.price_basis.history_window_contract==='d9_d2_eight_closed_days_v1'?'D-9至D-2八日平均优惠':'历史七日平均优惠';
        details.append(node('p',`采购成本 $${Number(basis.cost_usd_per_1k).toFixed(4)} / 1K（¥${Number(basis.cost_cny_per_1k).toFixed(4)}）`),
          node('p',`${basis.delivered_k}K 套餐成本 ${usd(basis.package_cost_usd)}`),
          node('p',`未优惠红线 ${usd(basis.regular_floor_usd)} · 当前${currentMargin}`),node('p',`${averageWindow}${averageDiscount} 红线 ${usd(basis.average_floor_usd)} · 当前${averageMargin}`),
          node('p',`成本采集 ${when(basis.cost_checked_at)}；${market.price_basis.pricing_scope==='100k_package_only'?'双20只按购买100K、实交100K这一档核算，地区实际售价另核。':'此为旧范围成本快照，等待100K新口径采集。'}`));
      }
      for(const platform of ['PS','XBOX','PC']){
        const column=platformCard(platform);
        const loot=market.global_offers?.[platform]?.Lootbar;
        const item=(market.reference?.offers||[]).find(row=>row.platform===platform);
        const arab=(market.arab||[]).find(row=>row.platform===platform&&(!newPolicy||row.delivery===(platform==='PC'?'standard':'normal')));
        for(const [name,row,price,purchase,bonus,stamp,verified,method] of [
          ['Lootbar',loot,loot?.usd_price,loot?.base_k,loot?.bonus_k,loot?.checked_at,loot?.comparable!==false,'无优惠券报价'],
          ['ItemD2R',item,item?.gross_usd,item?.purchase_k,item?.bonus_k,item?.captured_at,item?.status==='valid',item?.delivery_method||'交付方式待核'],
          ['Arab-UT',arab,arab?.total_usd,arab?.purchase_k,arab?.bonus_k,arab?.captured_at,arab?.selection_verified===true,platform==='PC'?'Saudi Arabia来源 · PC独立标准报价 · 全球参考':'Saudi Arabia来源 · 主机普通发货报价'+(newPolicy?' · 全球参考':'')]]){
          const card=node('section');card.className='market-quote';
          const available=price!=null&&Number.isFinite(Number(price))&&Number(price)>0;
          const age=stamp?Date.now()-Date.parse(stamp):NaN;
          const stale=Number.isFinite(age)&&age>15*60000;
          card.dataset.state=!available?'missing':stale?'stale':'observed';
          const followGlobal=!newPolicy&&name==='Arab-UT'&&!available&&market.saudi_missing_price_policy==='follow_global';
          const missingReason=name==='ItemD2R'?(market.reference?.missing||[]).find(gap=>gap.platform===platform)?.reason||market.reference?.reason:name==='Lootbar'?(market.competitor_diagnostics||[]).find(reason=>reason.startsWith('Lootbar:')):null;
          const header=node('div');header.className='head';const badge=node('span',followGlobal?'缺价 · 跟随全球':!available&&missingReason==='itemd2r_cloudflare_403'?'Cloudflare 403 · 缺价':!available?'缺项':!verified?'规格待核':stale?'已过 15 分钟':!Number.isFinite(age)||age<0?'时点待核':'最近已采');badge.className='market-badge';header.append(node('h4',name),badge);card.append(header);
          if(newPolicy)card.append(node('p',name==='Lootbar'?'主锚 · 同平台有效价优先':name==='Arab-UT'?'次锚 · Lootbar缺有效价时采用':'辅助观察 · 不参与定价锚和写价阻断'));
          const total=node('p',available?usd(price):'暂无报价');total.className='market-price';card.append(total);
          const delivered=purchase!=null&&bonus!=null?Number(purchase)+Number(bonus):NaN;
          const unit=node('p',available&&verified&&Number.isFinite(delivered)&&delivered>0?`${usd(Number(price)/delivered*100)} / 100K 实际交付`:'同口径单价待核');unit.className='market-unit';card.append(unit);
          card.append(node('p',row?`购买 ${purchase??'待核'}K + 赠送 ${bonus??'待核'}K${Number.isFinite(delivered)?` · 交付 ${delivered}K`:''}`:'本轮未取得可核报价'),node('p',method));
          if(!available&&newPolicy)card.append(node('p',name==='ItemD2R'?`辅助来源缺价，不阻断核心定价。原因：${missingReason||'本轮无有效报价'}`:`Lootbar有效时优先；缺价用同平台ArabUT，两源均缺沿双20最低合法价（日常八日平均30%）；地区按计划继承全球。原因：${missingReason||'本轮无有效报价'}`));
          else if(!available&&name!=='Arab-UT')card.append(node('p',`冲额：另一家有效则用另一家；双缺取双20最低合法价，竞争目标未达。日常：Lootbar有效保留计划选价；缺价按ItemD2R实际交付价；双缺的平台按八日平均30%最低价。原因：${missingReason||'本轮无有效报价'}`));
          const time=node('p',`采集 ${when(stamp)} · USD`);time.className='footnote';card.append(time);column.append(card);
        }
        output.append(column);
      }
      summary.dataset.state='success';
      summary.textContent=`快照 ${market.snapshot_id} · 采集时间均为北京时间。卡片展示保存的来源证据，不表示当前可直接执行。`;
    }catch(error){if(reading===marketRead){output.replaceChildren();summary.dataset.state='failed';summary.textContent=`竞品价格暂无法读取：${errorText(error)}；下次更新重试。`;}}
    finally{if(reading===marketRead)output.removeAttribute('aria-busy');}
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
    marketTag.textContent=state.plan?.write_protocol===curveProtocol?'Lootbar · U7Buy · Arab-UT · 100K':primaryPolicy(plan)?'Lootbar 主锚 · Arab-UT 次锚（主机Normal / PC标准）· ItemD2R 辅助':legacyMarketTag;
    if(firstRender&&active?.mode&&names[active.mode]){$('v3-mode').value=active.mode;displayedMode=active.mode;setMode(active.mode);}
    const curve=isCurvePlan(state),activeState=curve?state.plan:active;
    const capturedAt=curve?(curveSnapshot(state)&&state.captured_at):state.captured_at;
    $('v3-state').textContent=(activeState?`${names[activeState.mode]} · ${statusText(activeState.state)}${curve?' · V6':''} · 数据 ${capturedAt||'尚未取得'} · ${state.generation?'统一控制权已登记':'尚未切换'}`:'无活动计划；历史价格与原操作保留')+
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
    table('v3-operations',(state.operations||[]).map(o=>{
      const mode=names[o.bundle?.mode]||(o.bundle?.maintenance_purpose==='retire_uk_discount_v1'?'英国临时折扣退出':'待核');
      const label=o.bundle?.write_protocol===curveProtocol?'V6':curve?'旧标量历史 · '+mode:mode;
      return [o.created_at,label,statusText(o.status),o.operation_id,statusText(o.readback?.public?.status),statusText(o.cache_receipt?.status)];
    }));
    table('v3-incidents',(state.incidents||[]).map(i=>[i.code,i.dependency,statusText(i.state),i.first_seen,i.last_seen,i.attempt]));
    const sourcePolicy=primaryPolicy(plan)?'计划规则：Lootbar主锚，ArabUT次锚，ItemD2R仅辅助；PS、Xbox和PC分别独立核价。'+(plan.parameters.region_pricing==='global'?'全球统一：地区继承全球，系数1；实际生效以已核地区证明为准。':'地区按原配置核算。'):'全球核心参考 Lootbar 与 ItemD2R；Saudi Arabia 另核 Arab 普通报价，破线时系数归1；英国系数1。';
    $('v3-legacy-proof-table').hidden=curve;
    $('v3-proof-notes').textContent=curve
      ?'按最近三个已归档完整自然日（D-3 至 D-1）的实际优惠金额加权核算。各档检查保本，平台组合采购毛利至少 18%，经营重点是全天累计利润和利润率。'
      :`双红线：购买100K、实交100K档未优惠及D-9至D-2八个完整日真实优惠金额结构估算平均采购毛利都至少 20%。成本、竞品及汇率取本轮。小额与其他档位不作为自动定价硬门槛。${sourcePolicy}${latest?.bundle?.financial_proof?.pricing_scope!=='100k_package_only'&&latest?'下表最近原操作为旧口径历史证明，不代表100K新口径验收。':''}${matrix.length?'下表展示已获得的地区证明；缺项保持待核。':'本轮地区证明尚未取得。'}`;
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
    if(loading||executionPageLeft)return;loading=true;clearTimeout(executionTimer);$('v3-panel').setAttribute('aria-busy','true');$('v3-refresh').disabled=true;$('v3-refresh').textContent='正在读取…';
    try{
      if(executionRead)await executionRead.catch(()=>{});
      const [state,permission,automation,monitor,player]=await Promise.all([
      request('state'),writePermission().then(value=>({known:true,value})).catch(()=>({known:false,value:false})),
      cloud('automation').catch(()=>null),cloud('monitor').catch(()=>null),cloud('player-sync').catch(()=>null)]);
      permissionKnown=permission.known;canWrite=permission.value;lastAutomation=automation;lastMonitor=monitor;render(state);renderOverview(state,automation,monitor);await renderMarketEvidence();
      if(curvePending)await checkCurveCollection();
      const activation=pendingCurveActivation();
      if(activation&&!acting)readCurveActivation(state,activation);
      if(player){playerRevision=player.revision;if(!playerDirty)$('player-enabled').checked=Boolean(player.enabled);}
      $('v3-error').textContent=permissionKnown?'':'操作权限暂时无法核对，写入入口已停用；只读状态仍可查看。';
      $('v3-error').hidden=permissionKnown;
      const curve=isCurvePlan(state),snapshotId=curve?curveSnapshot(state):state.snapshot_id;
      $('version').textContent=`${curve?'V6':'V3'} 状态读取 ${when(new Date())} · 快照 ${snapshotId||'尚无'} · 下轮时间以统一调度实际回执为准`;
      if(collectPending)await readCollectionStatus();
    }
    catch(error){$('v3-error').textContent=`未完成：${errorText(error)}。旧值保留其原时点。`;$('v3-error').hidden=false;}
    finally{loading=false;scheduleExecutionProgress();$('v3-refresh').disabled=false;$('v3-refresh').textContent='更新统一状态';$('v3-panel').removeAttribute('aria-busy');}
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
      manual_enabled:$('v3-manual-enabled').checked,manual_prices:Object.fromEntries(platforms.map(p=>[p,$('v3-fixed-'+p.toLowerCase()).value||null])),
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
  $('v3-curve-collect').addEventListener('click',startCurveCollection);
  $('v3-curve-activate').addEventListener('click',activateCurve);
  $('v3-curve-read').addEventListener('click',readExistingCurve);
  $('v3-manual-form').addEventListener('input',()=>{if(manualPreview){manualPreview=null;$('v3-manual-execute').disabled=true;$('v3-manual-result').textContent='输入已改变，请重新进行只读预览。';}});
  $('v3-history-id').addEventListener('input',()=>{$('v3-history-read').disabled=!$('v3-history-id').value.trim();});
  $('v3-target-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{await request('monthly-target',{request_key:requestKey('target'),amount:$('v3-target-amount').value||null});clearKey('target');});});
  $('v3-plan-form').addEventListener('submit',event=>{
    event.preventDefault();action(async()=>{
      const data={request_key:requestKey('plan'),mode:$('v3-mode').value,resources:[],parameters:formParameters()};
      for(const p of platforms)if($('v3-'+p.toLowerCase()).checked)data.resources.push('base:'+p);
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
    if($('v3-execute-now').disabled)return;
    return action(async()=>{
      const plan=chosenPlan();
      if(!canWrite||!plan||plan.state!=='ACTIVE')throw Error('当前没有可执行的活动计划或操作权限');
      const kind='execute-'+plan.plan_id,key=requestKey(kind),unknownKey='fc-v3-execute-unknown-'+plan.plan_id;
      try{
        const result=await request('execute',{request_key:key,plan_id:plan.plan_id});
        if(!result.job_key)throw Error('改价任务回执缺少编号，请按原请求核对');
        if(!['queued','running','done','failed'].includes(result.status))throw Error('原改价任务状态尚未确认，请按原请求核对');
        clearKey(kind);sessionStorage.removeItem(unknownKey);
        executeReceipt={...result,plan_id:plan.plan_id};
        renderExecutionProgress();
        scheduleExecutionProgress();
        $('v3-result').textContent='改价任务已登记。';
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
    const owner=(current?.active_plans||[]).find(p=>['revenue_sprint','smart'].includes(p.mode)&&platforms.every(g=>p.resources?.includes('base:'+g))),baseline=owner?.mode==='smart'?owner.baseline_plan:owner,pct=baseline?.parameters?.preferred_undercut_pct;
    const note=$('v3-mode').value==='smart'?`默认7.5%基准候选排序的只读情景，未使用当前${pct!=null?pct+'%':'计划参数'}及真实6小时分配；不是本计划报价，不作为切换或审批依据。实际结果以启用后同轮采集和决策回执为准。\n`:'';
    $('v3-preview-output').textContent=note+Object.entries(result.results).map(([m,r])=>`${names[m]}：${statusText(r.status)}；${r.selected?pricesText(r.selected.action.base_prices):`当前不可执行 ${[...new Set((r.failures||[]).map(f=>statusText(f.code)))].join('；')}`}`).join('\n');
  }));
  $('v3-manual-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
    const restore=$('v3-restore-id').value.trim();
    const data={request_key:requestKey('manual-preview'),reason:$('v3-manual-reason').value,plan_id:chosenPlan()?.plan_id};
    if(restore)data.restore_source_execution_id=restore;
    else{data.explicit_prices=Object.fromEntries(platforms.filter(p=>$('v3-manual-'+p.toLowerCase()).value).map(p=>[p,$('v3-manual-'+p.toLowerCase()).value]));}
    manualPreview=await request('manual-previews',data);clearKey('manual-preview');
    if(manualPreview.restore_tiers){
      const tiers=Object.entries(manualPreview.restore_tiers).map(([platform,rows])=>
        `${platform==='XBOX'?'Xbox':platform}：${rows.map(row=>`${row.purchase_k}K ${usd(row.native_price_usd)}`).join(' · ')}`);
      $('v3-manual-result').textContent=tiers.concat(
        `原操作 ${manualPreview.restore_source_execution_id}。有效至 ${manualPreview.valid_until}。执行时按当前规格、成本和优惠复核 0% / 18%。`).join('\n');
      return;
    }
    const action=manualPreview.selected?.action?.base_prices||manualPreview.explicit_prices;
    const regions=Object.entries(manualPreview.selected?.action?.region_coefficients||{}).map(([key,factor])=>`${key} 系数 ${factor}`).join('；');
    const averageWindow=['fc27_dual20_d9_d2_v2','fc27_dual20_d9_d2_platform_100k_v4'].includes(manualPreview.selected?.financial_proof?.financial_contract_version)?'八日金额结构':'历史七日结构';
    const proof=Object.entries(manualPreview.selected?.financial_proof?.prices||{}).map(([key,row])=>`${key}：未优惠 ${value(row.catalog?.worst_published_margin_pct)}% / ${averageWindow} ${value(row.catalog?.minimum_estimated_average_margin_pct)}%`).join('；');
    $('v3-manual-result').textContent=`只读财务与市场重证已完成：${pricesText(action)}。${regions}。${proof}。预览 ${manualPreview.manual_preview_id}；有效至 ${manualPreview.valid_until}。确认后由同一新鲜采集链再次核准。`;
  });});
  $('v3-manual-execute').addEventListener('click',()=>action(async()=>{
    if(!manualPreview||Date.now()>=Date.parse(manualPreview.valid_until))throw Error('人工预览已过期，请重新核算');
    const result=await request('execute',{request_key:'manual-'+manualPreview.manual_preview_id,manual_preview_id:manualPreview.manual_preview_id,plan_id:manualPreview.plan_id});
    if(manualPreview.restore_tiers){
      executeReceipt={...result,plan_id:manualPreview.plan_id};
      renderExecutionProgress();
    }
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
  $('v3-weekly-auto').addEventListener('click',()=>{if(!canWrite||acting)return;return action(async()=>{
    const enabled=!current.weekly_ladder?.control?.automatic;
    await request(`weekly-ladder/${current.plan.plan_id}/automatic`,{enabled,expected_revision:current.plan.revision});
    $('v3-result').textContent=enabled?'已明确开启自动周调整，仍保留每次提议与计划修订。':'已恢复每周确认。';
  });});
  writeControls();$('v3-history-read').disabled=true;$('v3-plan-select').disabled=true;
  document.addEventListener('visibilitychange',scheduleExecutionProgress);
  window.addEventListener('pagehide',()=>{executionPageLeft=true;clearTimeout(executionTimer);clearTimeout(collectTimer);});
  window.addEventListener('pageshow',()=>{executionPageLeft=false;scheduleExecutionProgress();});
  setInterval(()=>{if(!document.hidden)refresh();},300000);refresh();
})();
