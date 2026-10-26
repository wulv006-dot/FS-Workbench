(() => {
  'use strict';
  function pageToUnit(value) {
    if(!/^[0-9]{1,10}(?:\.[0-9]{1,2})?$/.test(value))throw Error('请填写最多两位小数的美元标价');
    const [whole,fraction='']=value.split('.');
    const cents=BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));
    if(cents<=0n)throw Error('标价须大于0');
    return `${cents/10000n}.${String(cents%10000n).padStart(4,'0')}`;
  }
  function money(value) {return value==null?'待核':`$${Number(value).toFixed(2)}`;}
  function time(value) {return value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'待核';}
  const $=id=>document.getElementById(id),BASE='/api/fc27/cloud';
  let policy,player,state,preview,restore,busy=false,dirty=false,playerDirty=false,refreshing=false;
  const pendingKey='fc-pricing-v2-pending';
  const names={temporary_itemd2r_parity:'临时按ItemD2R同量含赠送单价一致',owner_position_ceiling:'按品牌定位限制到Lootbar与ItemD2R可比上限',weighted_market_reference:'按80/15/5同量竞价形成双向候选',cost_or_promotion_floor:'成本或优惠挤压利润，先修复红线',public_anchor_parity:'只调整到本轮公开可比位置',already_competitive_hold:'已在竞争位置，主策略保持',unify_common_console_base:'旧价不同，统一PS / Xbox共同基价',operator_or_hermes_candidate:'人工或Hermes明确候选'};
  const endingNames={temporary_reference_no_ending:'临时同价不叠加尾价偏移',accepted:'小幅调整为.99，预算和红线均通过',already_99:'已是.99，无额外调整',no_positive_99:'金额过小，保持主策略',hard_floor:'红线限制，保持主策略',ending_budget:'让利预算限制，保持主策略',ending_margin_budget:'毛利率预算限制，保持主策略',catalog_hard_floor:'套餐红线限制，保持主策略',explicit_candidate_no_hidden_adjustment:'明确指定价，不另加尾价调整'};
  const labels={auto_cycle:'自然自动周期',collect:'价格采集',execute:'确认执行',restore:'恢复',recalculate:'候选核算',preview:'后台只读预览',hermes_review:'Hermes审核',ready:'处理完成',queued:'排队中',running:'进行中',failed:'失败',confirmed:'已确认',CONFIRMED:'已确认',verified:'已核实',pending:'待处理',no_price_change:'价格无需变化',unknown:'原请求待核',completed:'已完成',submitted:'已提交，等待模型',timeout:'本轮等待超时，不追补执行'};
  const label=value=>labels[value]||value;
  function historyCells(item){
    const reconciled=item.reconciliation?.status==='confirmed';
    return [time(item.completed_at||item.created_at),label(item.kind),`${label(item.result?.status||item.status)}${reconciled?'；原ID对账已确认':''}`,label(item.reconciliation?.public_readback||item.public_page_readback?.status)||'未取得',`${item.job_id} ${item.error_detail||item.error||''}${reconciled?'；原失败保留，补核已完成':''}${reconciled&&item.reconciliation.mmoexp_replayed===false?'，Order未重放':''}`];
  }
  function estimatedMarginText(average){
    const value=average?.procurement_margin_pct;
    return value!=null&&Number.isFinite(Number(value))?`${Number(value).toFixed(2)}%`:average?.estimated_net_usd==='0'?'无正实收，预计亏损':'待历史优惠数据';
  }
  function marketOffers(quote,row,now=Date.now()){
    const offers=(row.offers||[]).filter(o=>o.site!=='ItemD2R');
    const reference=quote.evidence?.reference_market;
    const offer=reference?.status==='available'&&reference.run_id===quote.run_id
      ? reference.offers?.find(o=>o.platform===row.platform&&o.run_id===quote.run_id&&o.source==='ItemD2R'&&o.status==='valid'&&o.currency==='USD'):null;
    const age=offer?now-Date.parse(offer.captured_at):NaN;
    const comparable=Boolean(offer&&offer.comparable===true&&offer.conditional===false&&Number.isFinite(age)&&age>=0&&age<=900000);
    offers.push({site:'ItemD2R',usd_price:offer?.gross_usd,base_k:offer?.purchase_k,bonus_k:offer?.bonus_k,usd_per_1k:offer?.effective_usd_per_k,checked_at:offer?.captured_at,comparable,
      evidence_status:offer?(comparable?'公开规格可比':'历史采价或条件不可比'):`缺项 · ${reference?.reason||'本轮未取得'}`});
    return offers;
  }
  function referenceLines(row,decision){
    const reference=row.reference_adjustment;
    if(!reference)return [['竞价依据','旧回执 · 未使用80/15/5权重']];
    const percent=value=>`${Number(value)>=0?'+':''}${(Number(value)*100).toFixed(3)}%`;
    return [
      ['竞价权重',row.temporary_itemd2r_parity?'临时ItemD2R同量同价；80/15/5仅保留观察':'Lootbar 80% · ItemD2R 15% · U7Buy 5%'],
      ...(row.temporary_itemd2r_parity?[["临时对标规则",'ItemD2R每实际交付K同价，向下取整分；受原Lootbar上限及共同池约束，直到你解除']]:[]),
      ...(row.position_policy_version?[["品牌定位上限",money(row.position_ceiling_usd)+' · 同量含赠送不高于Lootbar及ItemD2R'],["平均毛利复核",({normal:'正常',warning:'40%预警：须比较毛利额与量价取舍',urgent:'50%紧急复核：不得机械跟随高价'})[row.margin_review?.level]||'待核']]:[]),
      ['同量Lootbar锚',money(reference.anchor_usd)],
      ...Object.entries(reference.sources).map(([site,source])=>[`${site}本轮贡献`,source.status==='available'?`${percent(source.contribution)} · 同量指数${money(source.normalized_usd)} · 采价${time(source.checked_at)}`:`0% · 缺项或不合格（${source.reason}）；权重不转移`]),
      ['本平台锚价修正',`${percent(reference.raw_offset)} · 原始同量指数${money(reference.raw_weighted_usd)}`],
      ['共同市场候选 / 红线后',`${money(decision?.raw_weighted_usd)} / ${money(decision?.after_floor_usd)}`],
      ['分币 / 尾价或明确候选',`${money(decision?.after_cent_usd)} / ${money(decision?.selected_usd)}${decision?.explicit_candidate?' · 人工或Hermes明确候选':''}`],
      ['第三梯队','IGGM / U4GM直接权重0，保留趋势与反证分析']
    ];
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={pageToUnit,historyCells,estimatedMarginText,marketOffers,referenceLines};return;}
  const errors={pricing_temporary_itemd2r_parity:'临时规则要求本轮ItemD2R同量同价，不能选其他保持/涨跌幅度；如需解除请明确调整临时规则。',pricing_position_ceiling:'候选价高于Lootbar或ItemD2R的同量可比上限，未写入。',pricing_position_floor_conflict:'竞品上限低于成本双红线，没有合格新价；请处理成本或定位冲突。',pricing_position_peer_missing:'缺少本轮ItemD2R，无法核准品牌定位上限，未写入。',pricing_average_history_required:'缺少完整七日优惠金额样本，不能放行新价；原自动化继续核验。',pricing_average_history_coverage:'已识别Coins历史样本有优惠金额缺失，不能放行新价。',pricing_average_history_period:'优惠历史窗口不符最近七个完整日，请更新来源。',pricing_average_catalog_margin_floor:'候选套餐或自定义量的估算平均毛利低于红线，未写入。',pricing_hard_margin_floor:'候选价低于10%采购毛利硬红线，未写入。',pricing_catalog_hard_margin_floor:'套餐或小额自定义订单未达到硬红线，未写入。',pricing_hard_margin_minimum_10:'最低采购毛利率不能低于10%。',pricing_promotions_changed_since_quote:'优惠配置已变化，请重新采集核算。',pricing_source_stale:'来源已过期，请重新采集。',pricing_custom_formula_changed:'公开数量公式已更新，正在等待核实新边界。',pricing_legacy_quote_requires_recollection:'这是旧版报价，请采集新的V2报价。',pricing_common_console_scope_required:'PS与Xbox必须共同选择。',automation_revision_changed:'运行设置已被其他人更新，草稿保留，请先更新状态。',queue_mutation_busy:'原任务队列正忙，未接受本次请求。',authentication_required:'请重新登录FS。'};
  function error(value) {
    const code=value?.code||value?.message||String(value);
    $('error').textContent=errors[code]||`未完成：${code}。请查看原任务编号和核验记录。`;
    $('error').classList.remove('hidden');$('error').focus();
  }
  function status(text){$('status').textContent=text;}
  function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
  async function api(path,body){
    const response=await fetch(BASE+path,{credentials:'same-origin',cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    let data;try{data=await response.json();}catch{throw Error('服务器未返回可读回执');}
    if(!response.ok){const e=Error(data.error||`HTTP ${response.status}`);e.code=data.error;e.httpStatus=response.status;throw e;}
    return data;
  }
  function chosen(){return policy?.platforms||[];}
  function buttons(){
    const pending=Boolean(sessionStorage.getItem(pendingKey));
    $('collect').disabled=busy||pending;
    $('preview').disabled=busy||pending||!state?.quote_usable;
    $('execute').disabled=busy||pending||!preview||!state?.execution_ready||Date.now()>=Date.parse(preview.expires_at)||!policy?.system_enabled;
    $('restore-execute').disabled=busy||pending||!restore||!state?.execution_ready||Date.now()>=Date.parse(restore.expires_at);
    $('hermes-review').disabled=busy||pending||!state?.quote_usable;
    $('hermes-restore').disabled=busy||pending||!state?.quote_usable;
  }
  function renderSettings(){
    if(!dirty&&policy){$('enabled').checked=policy.system_enabled;$('auto').checked=policy.mode==='auto';$('interval').value=policy.interval_minutes;$('margin').value=policy.minimum_gross_margin_pct;$('console-enabled').checked=policy.platforms.includes('PS')&&policy.platforms.includes('XBOX');$('pc-enabled').checked=policy.platforms.includes('PC');}
    if(player&&!playerDirty)$('player-enabled').checked=player.enabled;
  }
  function card(group,title){
    const box=node('section',null,'panel');box.append(node('h2',title));
    const quote=state?.quote,rows=quote?.result?.rows||[],row=rows.find(r=>r.platform===group[0]);
    if(!row||quote.result.strategy_version!=='fc-coins-decision-v2'||row.margin_basis!=='undiscounted_and_historical_average_v2'){box.append(node('p','等待按未优惠售价红线重新核算。旧规则报价保留为历史，不用于新执行。'));return box;}
    box.append(node('div',money(row.target_page_usd),'amount'),node('p',`${state.quote_usable?'本轮候选':'历史候选 · 过期'} · 金币100K标价`,'muted'));
    const dl=node('dl'),decision=quote.result.decision_receipt?.decisions?.find(d=>d.platforms.includes(group[0]));
    for(const [label,value] of [
      ['最近公开100K',group.map(p=>`${p} ${money(state.current_storefront?.rows?.[p]?.package_usd)} · ${time(state.current_storefront?.rows?.[p]?.checked_at)}`).join(' / ')],
      ['候选相对采集价变化',group.map(p=>{const r=rows.find(v=>v.platform===p);return `${p} ${Number(r.change_pct)>=0?'+':''}${Number(r.change_pct).toFixed(2)}%`;}).join(' / ')],
      ['估算平均采购毛利率（100K）',estimatedMarginText(row.estimated_average_margin)],
      ...referenceLines(row,decision),
      ['有效采购成本',`¥${row.cost_cny} / K`],[`双红线 · ${row.minimum_gross_margin_pct}%最低100K`,money(Number(row.floor_usd_per_1k)*100)],
      ['未用优惠采购毛利率',row.proof?`${Number(row.proof.procurement_margin_pct).toFixed(2)}%`:'待核'],
      ['主策略标价',money(row.main_page_usd)],['尾价处理',endingNames[row.ending_reason]||row.ending_reason],
      ['保采购毛利所需订单倍数',row.break_even_order_multiplier?`${Number(row.break_even_order_multiplier).toFixed(3)}倍（条件计算）`:'不适用'],
      ['套餐 / 自定义核算',`${row.proof?.catalog?.published_packages??'?'}档 · 最小${row.proof?.catalog?.minimum_custom_k??'?'}K`]]){
        dl.append(node('dt',label),node('dd',value));
    }
    const avg=row.estimated_average_margin;
    box.append(dl,node('p',avg?.period?`估算来源：${avg.period.start}–${avg.period.end}全Coins历史折扣结构，${avg.observed_orders}/${avg.eligible_orders}笔有折扣金额；${avg.status==='partial'?'来源部分覆盖；':''}当前100K数量与成本情景，非分平台历史或未来全盘利润。`:'估算缺项保持未知，不用最差优惠或零折扣代替平均值。','footnote'),node('p',names[row.decision_reason]||row.decision_reason),node('p','未用优惠和近七日结构估算平均采购毛利都须≥10%；单笔合法优惠可亏损。广告后贡献另核。','footnote'));
    return box;
  }
  function render(){
    $('run-state').textContent=policy?`${policy.system_enabled?'允许改价':'停止新改价'} · ${policy.mode==='auto'?'自动':'人工'}`:'状态缺失';
    $('next-cycle').textContent=time(policy?.schedule?.next_at);
    $('decisions').replaceChildren(card(['PS','XBOX'],'PS / Xbox 共同市场'),card(['PC'],'PC 独立市场'));
    const q=state?.quote,receipt=q?.result?.decision_receipt;
    $('version').textContent=`流程 ${state?.version||'未知'} · 配置 ${policy?.revision??'未知'} · 状态读取 ${time(state?.observed_at)} · ${state?.quote_status||''} ${state?.execution_block_reason||''}`;
    $('basis').textContent=receipt?`主机共同成本依据：${receipt.common_console_cost.selected_platform}的最近有效交货记录 ${receipt.common_console_cost.record_id}，交易 ${receipt.common_console_cost.trade_at}；保留两个原始观察。${receipt.margin_basis==='undiscounted_and_historical_average_v2'?'双红线：未用优惠及七日历史优惠结构估算平均毛利均≥10%；单笔优惠可亏损，不是销量预测。':'旧规则回执，仅供历史追溯；等待新规则核算。'}`:'等待新鲜成本、公开价格及优惠/套餐配置的核算回执。';
    $('sources').textContent=q?`操作 ${q.run_id} · 采集 ${time(q.evidence.checked_at)} · 优惠/套餐核对 ${time(q.evidence.promotion_envelope?.checked_at)} · 回执 ${receipt?.sha256||'旧版无V2回执'}`:'';
    const tbody=$('competitors');tbody.replaceChildren();
    for(const row of q?.result?.rows||[])for(const offer of marketOffers(q,row)){const tr=node('tr');for(const value of [row.platform,offer.site,money(offer.usd_price),offer.base_k?`${offer.base_k} / ${offer.bonus_k}`:'待核',offer.usd_per_1k?`$${offer.usd_per_1k}`:'待核',`${time(offer.checked_at)} · ${offer.evidence_status||(offer.comparable?'公开规格可比':'缺项或不可比')}`])tr.append(node('td',value));tbody.append(tr);}
    const history=$('history');history.replaceChildren();
    for(const item of state?.recent||[]){const tr=node('tr');for(const value of historyCells(item))tr.append(node('td',value));history.append(tr);}
    if(!state?.recent?.length){const tr=node('tr'),td=node('td','尚无可显示的操作记录；等待原任务账本读回。');td.colSpan=5;tr.append(td);history.append(tr);}
    renderSettings();buttons();
  }
  async function refresh(){
    if(refreshing)return;refreshing=true;
    try{const values=await Promise.all([api('/automation'),api('/pricing/state'),api('/monitor'),api('/player-sync')]);[policy,state,,player]=values;
      const monitor=values[2];state.current_storefront=monitor.storefront;$('public-state').textContent=monitor.publication?.status==='matched'?'已核实':monitor.publication?.status||monitor.page_readback?.status||'待真实读回';
      $('health').textContent=`定时器：${monitor.health?.automation_timer||'未知'}；未确认写入：${monitor.health?.incomplete_executions??'未知'}；清缓存：${monitor.cache_refresh?.status||'待核'}`;
      if(preview&&(preview.run_id!==state.quote?.run_id||preview.automation_policy_revision!==policy.revision))preview=null;
      const review=state.hermes_review;
      $('hermes-status').textContent=review?`Hermes ${label(review.phase)} · 会话 ${review.conversation_id||'待核'} · 任务 ${review.task_id||'准备中'} · 模型运行 ${review.turn?.run_id||'待回执'}${review.recommendation?' · 已完成程序候选选择':' · 选择结果详见会话及操作账本'}；已采用与实际写价另查原操作。`:'尚无本轮Hermes任务；发起后会显示真实会话和模型回执。';
      render();await checkPending();if(!busy&&!sessionStorage.getItem(pendingKey))status(state.quote_status);
    }catch(e){preview=null;restore=null;if(state)state={...state,quote_usable:false,execution_ready:false,quote_status:'状态读取失败，保留原记录等待核对'};render();error(e);}finally{refreshing=false;}
  }
  async function waitJob(id){
    status(`等待原操作 ${id}`);
    const value=await api('/jobs/'+id);
    if(['queued','running'].includes(value.status))return null;
    if(value.status!=='ready'){const e=Error(value.error_detail||value.error||value.result?.reason||value.status);e.job=id;e.terminal=true;throw e;}
    return value;
  }
  async function checkPending(){
    const saved=sessionStorage.getItem(pendingKey);if(!saved)return;
    const pending=JSON.parse(saved);
    try{const job=await waitJob(pending.id);if(!job)return;
      if(pending.kind==='preview'){
        const id=job.result?.preview_id;if(!id)throw Error('预览回执缺失');preview=await api('/previews/'+id);
        $('preview-state').textContent=`后台预览已核，操作 ${pending.id}；有效至 ${time(preview.expires_at)}。执行平台 ${chosen().join(' / ')}，同一红线再次核算。`;
      }else if(pending.kind==='restore_preview'){
        restore=await api('/restore-previews/'+job.result.restore_preview_id);restore.source=pending.source;
        $('restore-state').textContent=`原操作 ${pending.source} 的恢复已按当前成本核算，有效至 ${time(restore.expires_at)}`;
      }else if(pending.kind==='hermes_review'){
        if(job.result?.do_not_replay||job.result?.phase==='unknown'){
          const actual=state?.hermes_review;
          if(actual?.job_id!==pending.id||actual.live_receipt!=='original_owned_turn_identified'){
            $('hermes-status').textContent=`Hermes原请求 ${pending.id} 回执未知，保留编号核对；不会再派发模型。`;
            return;
          }
        }
        $('hermes-status').textContent=`Hermes原操作 ${pending.id} 已派发，会话 ${job.result?.conversation_id||'待核'}；等待真实模型任务终态。`;
      }else{preview=null;restore=null;status(`原操作 ${pending.id} 已结束：${job.result?.status||job.status}。继续核对前台真实暴露。`);}
      sessionStorage.removeItem(pendingKey);
    }catch(e){if(e.terminal){sessionStorage.removeItem(pendingKey);error(e);}else{status(`原请求 ${pending.id} 回执待核，保留编号；不会重新派发。`);error(e);}}
    buttons();
  }
  async function submit(path,body,kind,extra={}){
    if(busy||sessionStorage.getItem(pendingKey))return;
    busy=true;$('error').classList.add('hidden');buttons();
    const id=crypto.randomUUID();sessionStorage.setItem(pendingKey,JSON.stringify({id,kind,...extra}));
    try{const answer=await api(path,{...body,client_event_id:id});
      if(answer.job_id&&answer.job_id!==id){const saved=JSON.parse(sessionStorage.getItem(pendingKey));saved.id=answer.job_id;sessionStorage.setItem(pendingKey,JSON.stringify(saved));}
      await checkPending();
    }catch(e){if(e.httpStatus>=400&&e.httpStatus<500){sessionStorage.removeItem(pendingKey);}else{status(`请求回执未知，保留原编号 ${id}；不会自动重新派发。`);}error(e);
    }finally{busy=false;buttons();}
  }
  $('refresh').onclick=refresh;
  $('collect').onclick=()=>submit('/pricing/collect',{},'collect');
  $('preview').onclick=()=>submit('/pricing/preview',{run_id:state.quote.run_id},'preview');
  $('execute').onclick=()=>submit('/reprice/execute',{preview_id:preview.preview_id,selected_platforms:chosen(),margin_confirmed_platforms:[],margin_exception_reason:''},'execute');
  $('settings-form').addEventListener('input',()=>{dirty=true;$('settings-state').textContent='未保存草稿';});
  $('settings-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;
    try{policy=await api('/automation',{expected_revision:policy.revision,settings:{system_enabled:$('enabled').checked,mode:$('auto').checked?'auto':'manual',interval_minutes:Number($('interval').value),platforms:[...($('console-enabled').checked?['PS','XBOX']:[]),...($('pc-enabled').checked?['PC']:[])],minimum_gross_margin_pct:$('margin').value}});dirty=false;preview=null;$('settings-state').textContent='已保存并读回服务器配置';await refresh();}catch(e){error(e);}finally{button.disabled=false;}
  });
  $('player-form').addEventListener('input',()=>{playerDirty=true;});
  $('player-form').addEventListener('submit',async event=>{event.preventDefault();event.submitter.disabled=true;try{player=await api('/player-sync',{enabled:$('player-enabled').checked,expected_revision:player.revision});playerDirty=false;status('商品公式联动开关已读回');}catch(e){error(e);}finally{event.submitter.disabled=false;}});
  $('candidate-form').addEventListener('submit',event=>{event.preventDefault();if(!state?.quote_usable){error(Error('请先采集新鲜数据'));return;}try{const unit=pageToUnit($('console-price').value),pc=pageToUnit($('pc-price').value);preview=null;submit('/pricing/recalculate',{run_id:state.quote.run_id,edits:{quotes:{PS:unit,XBOX:unit,PC:pc},reason:$('candidate-reason').value,minimum_gross_margin_pct:policy.minimum_gross_margin_pct}},'recalculate');}catch(e){error(e);}});
  $('restore-form').addEventListener('submit',event=>{event.preventDefault();const source=$('restore-id').value;submit('/pricing/restore-preview',{source_execution_id:source},'restore_preview',{source});});
  $('restore-execute').onclick=()=>submit('/reprice/'+restore.source+'/restore',{restore_preview_id:restore.restore_preview_id,selected_platforms:restore.available_platforms},'restore');
  $('hermes-review').onclick=()=>submit('/pricing/hermes-review',{run_id:state.quote.run_id},'hermes_review');
  $('hermes-restore').onclick=()=>{if($('restore-form').reportValidity())submit('/pricing/hermes-review',{run_id:state.quote.run_id,restore_source_execution_id:$('restore-id').value},'hermes_review');};
  setInterval(refresh,10000);refresh();
})();

