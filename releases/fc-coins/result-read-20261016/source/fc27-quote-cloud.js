// FC27 formal workbench: browser displays and confirms; all collection and writes run on the server.
(() => {
  'use strict';
  const API='/api/fc27/cloud';
  const PLATFORMS=['PS','XBOX','PC'];
  const $=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const fmt=value=>value==null?'—':esc(value);
  function decimal4(value,minDigits=4){
    if(value==null)return '—';
    const match=/^(\d+)(?:\.(\d+))?$/.exec(String(value).trim());
    if(!match)return '—';
    const digits=(match[2]||'').padEnd(5,'0');
    const scaled=BigInt(match[1])*10000n+BigInt(digits.slice(0,4))+(digits[4]>='5'?1n:0n);
    const whole=(scaled/10000n).toString();
    const fraction=(scaled%10000n).toString().padStart(4,'0');
    const shown=minDigits===4?fraction:fraction.replace(/0+$/,'').padEnd(minDigits,'0');
    return shown?`${whole}.${shown}`:whole;
  }
  let runId=null, quote=null, preview=null, restorePreview=null, busy=false, dirty=false, writerReady=false;
  let manualQuoteEpoch=0;
  let automation=null, automationDirty=false, displayedAutomaticJobId=null, automaticSyncing=false;
  let playerSync=null, playerSyncDirty=false;
  let discountDirty=false, discountBusy=false, discountBaseRevision=null, discountEpoch=0;
  const DISCOUNT_BANDS=['at_least_40','30_to_40','20_to_30','below_20'];
  const DEFAULT_DISCOUNT_RULES={schema_version:1,bands:{
    at_least_40:{min_discount_pct:'0.00',max_discount_pct:'10.00'},
    '30_to_40':{min_discount_pct:'7.50',max_discount_pct:'7.50'},
    '20_to_30':{min_discount_pct:'5.00',max_discount_pct:'5.00'},
    below_20:{min_discount_pct:'0.00',max_discount_pct:'0.00'}}};
  let writerBlockReason='安全通道尚未验收，仅可核对预览。';
  const REASONS={
    state_unavailable:'服务器状态读取暂时未完成，不代表采集或改价已经失败。只重试读取，不重复提交操作；持续失败请反馈诊断。',
    collection_incomplete:'本轮采集有缺项，请根据操作编号检查来源；没有使用旧数据。',
    collector_incomplete:'Lootbar 三平台采集未完成。',
    platform_coverage_incomplete:'竞品平台覆盖不完整。',
    cost_invalid:'P2PAH 真实成本缺失或校验失败。',
    source_incomplete:'成本、竞品或汇率有缺项。',
    quote_not_ready:'本轮报价未满足完整证据要求。',
    storefront_incomplete:'本轮 MMOEXP 前台 100K 页面售价未完整采集，已停止自动报价。',
    storefront_run_mismatch:'前台售价与竞品采集不属于同一轮，已停止自动报价。',
    storefront_contract_invalid:'本轮 MMOEXP 前台商品或平台对应关系校验失败。',
    quote_engine_changed_since_preview:'报价规则已更新，旧预览不能执行；请重新采集并预览。',
    manual_quote_required:'该平台没有满足毛利和降幅要求的自动价，请人工填写目标价后预览。',
    preview_unavailable:'后台预览读取失败，请核对 P2PAH 登录和页面筛选。',
    backend_login_expired:'服务器上的 P2PAH 后台登录已失效。',
    backend_validation_failed:'后台商品行、平台或同步选项与预期不一致。',
    browser_validation_failed:'服务器浏览器未能完成后台页面校验。',
    newer_run_exists:'已有更新的采集轮次，当前报价与预览已失效。请点击“开始采集最新价格”重新采集并审核；本次修改没有提交后台。',
    preview_expired:'预览已过期，请重新生成。',
    quote_changed_since_preview:'报价已修改，旧预览不能执行。',
    backend_before_changed:'后台现值已变化，请重新生成预览。',
    unresolved_execution_exists:'仍有未确认的改价操作，须先核对后台实际结果。',
    low_margin_confirmation_required:'低毛利平台需要在预览中逐项确认。',
    manual_margin_confirmation_required:'低毛利人工改价须逐项确认并填写原因。',
    automation_system_off:'系统总开关已关闭；可以继续手动采集和预览。',
    automation_policy_changed:'控制台配置已变化，需重新采集并预览。',
    automation_policy_changed_since_quote:'报价使用的是旧配置，需重新采集。',
    minimum_margin_invalid:'最低毛利率需在 0% 到 100% 之间，最多保留两位小数。',
    automation_discount_cycle_in_progress:'采集或改价任务正在执行；请等待该任务结束后再保存范围，避免中断本轮操作。',
    automation_discount_rules_invalid:'降幅配置格式无效，请重新读取范围。',
    automation_discount_pct_invalid:'每档降幅须为 0–10% 的数字，最多两位小数。',
    automation_discount_range_invalid:'每档下限不得大于上限。',
    automation_discount_margin_floor_invalid:'当前最低毛利低于10%，不能保存降幅范围；请先核对既有设置。',
    automation_discount_snapshot_unavailable:'没有可用的最新完整快照，或数据已超过60分钟。请等待原有采集周期后再预览。',
    automation_revision_changed:'其他人刚刚修改了控制台设置，请刷新后再保存。',
    automation_interval_invalid:'采集间隔须填写 1–9999 的整数分钟。',
    automation_platform_disabled:'该平台未在控制台启用。',
    automation_storage_unavailable:'服务器配置文件暂时无法写入，请联系维护人员检查权限。',
    player_sync_revision_changed:'其他人已修改球员同步开关，请刷新后再保存。',
    player_sync_request_invalid:'球员同步开关请求无效。',
    https_required_for_player_sync:'请通过 HTTPS 工作台保存球员同步开关。',
    activity_date_invalid:'请选择有效的历史日期。',
    activity_mark_invalid:'日志保留标记请求无效。',
    activity_event_not_found:'该条日志副本已过期或不存在，请刷新后重试。',
    activity_storage_unavailable:'团队日志副本暂时不可写，请联系维护人员检查服务器。',
    https_required_for_activity_mark:'请通过 HTTPS 工作台标记日志。',
    queue_unavailable:'服务器暂时无法接收任务，请联系维护人员检查服务状态。',
    automatic_margin_floor:'目标价低于自动改价最低毛利率，已拦截。',
    automation_writer_unavailable:'自动改价通道当前不可用，任务已停下。',
    writer_not_confirmed:'后台写入、同步或回读未全部确认，请核对审计。',
    job_timeout:'服务器任务尚未给出结果；保留操作编号，请勿直接重复提交。',
    not_found:'任务记录暂时未找到，请用操作编号反馈。',
    job_identity_mismatch:'返回的任务编号不匹配，已停止读取本轮报价。',
    FileNotFoundError:'本轮报价或预览文件不存在，请重新采集后再预览。',
    authentication_required:'当前没有通过工作台登录验证。',
    write_role_required:'当前账号没有提交采集或改价的权限。',
    https_required_for_price_write:'安全通道尚未验收；采集和预览可用，真实改价暂缓。',
    https_required_for_automation_config:'请通过 HTTPS 工作台保存自动化设置。',
    certificate_unhealthy:'HTTPS 证书续期或到期检查异常；真实改价已暂停。请反馈操作编号和证书状态。',
    restore_preview_unavailable:'无法确认原操作与当前后台一致；请核对原操作编号及后台现值。',
    restore_source_not_confirmed:'原操作尚未完成确认，不能按该记录自动恢复。',
    restore_backend_changed_since_execution:'后台现值与原操作完成时不一致，恢复已暂停。',
    restore_backend_changed_since_preview:'生成恢复预览后后台值又变化，恢复已暂停。',
    restore_preview_expired:'恢复预览已过期，请重新生成。',
    restore_not_confirmed:'恢复的保存、同步或回读未全部确认，请核对操作审计。',
    restore_source_mismatch:'恢复预览与原操作编号不一致。'
  };
  function clearProblem(){$('problem').classList.add('hidden')}
  function showProblem(stage,error,operationId=''){
    const code=String(error.code||error.message||'unknown').slice(0,700);
    const jobId=error.jobId||operationId||'未取得';
    const evidenceRunId=error.runId||runId;
    const costReason=code.startsWith('P2PAH:')?code.split(':')[1]:null;
    const costReasons={
      cost_delivery_type_unverified:'P2PAH \u6210\u672c\u4ea4\u8d27\u7c7b\u578b\u672a\u786e\u8ba4\uff0c\u53ea\u5141\u8bb8\u8ba2\u5355\u53d1\u8d27\uff0c\u91c7\u8d2d\u6253\u6b3e\u4e0d\u5f97\u7528\u4f5c\u6210\u672c\u3002\u672c\u8f6e\u672a\u62a5\u4ef7\u6216\u6539\u4ef7\uff0c\u81ea\u52a8\u4efb\u52a1\u4fdd\u62a4\u6682\u505c\uff0c\u9700\u6838\u5bf9\u4ea4\u8d27\u7c7b\u578b\u3002',
      filter_or_rows_unverified:'P2PAH 采购页的页码、FC27/Game Coins 筛选或表格未能确认；采购成本不足，本轮未报价或改价。自动任务已暂停，请维护人员核对采集诊断后恢复。',
      order_page_navigation_timeout:'P2PAH 采购页导航超时，未取得完整成本；本轮未报价或改价，自动任务已暂停。',
      order_page_read_timeout:'P2PAH 采购页读取超时，未取得完整成本；本轮未报价或改价，自动任务已暂停。',
      order_page_http_error:'P2PAH 采购页返回 HTTP 错误，未取得完整成本；本轮未报价或改价，自动任务已暂停。',
      login_expired:'P2PAH 采购页登录已失效，未取得完整成本；本轮未报价或改价，自动任务已暂停。',
      collector_failed:'P2PAH 采购成本采集失败，未取得三平台完整成本；本轮未报价或改价，自动任务已暂停。维护人员需核对原采集证据。',
      cost_records_incomplete:'P2PAH 未取得三平台有效采购记录；本轮未报价或改价，自动任务已暂停。'
    };
    const sourceErrors=code.split(';').map(part=>part.split(':')).filter(parts=>
      ['Lootbar','IGGM','U4GM','U7Buy','P2PAH','BOC'].includes(parts[0]));
    const collectionReasons={browser_connection_timeout:'浏览器连接超时',page_create_timeout:'浏览器新页面超时',
      page_navigation_timeout:'页面导航超时',page_read_timeout:'页面读取超时',platform_click_timeout:'平台点击超时',
      page_close_timeout:'页面关闭超时',collection_timeout:'采集超时（阶段未记录）',TimeoutError:'采集超时（旧证据未记录阶段）',
      cost_delivery_type_unverified:'\u6210\u672c\u4ea4\u8d27\u7c7b\u578b\u672a\u786e\u8ba4',platform_timeout:'平台切换或读取超时',platform_collection_failed:'平台采集失败',ps_restore_failed:'恢复 PS 页面失败'};
    const sourceSummary=sourceErrors.map(([source,reason,detail])=>`${source}：${collectionReasons[reason]||'采集失败'}${['PS','XBOX','PC'].includes(detail)?'（'+detail+'）':''}`).join('；');
    const reason=(sourceSummary&&!(sourceErrors.length===1&&costReason&&costReasons[costReason])?sourceSummary+'。采集不完整，本轮未报价或改价，自动任务已暂停；请维护人员核对采集证据后恢复。':null)||
      (costReason&&(costReasons[costReason]||costReasons.collector_failed))||REASONS[code]||REASONS[code.split(':',1)[0]];
    $('problem-summary').textContent=stage+'未完成：'+(reason||'服务器返回未分类错误，请将诊断信息反馈给维护人员。');
    $('problem-detail').textContent=`阶段：${stage}\n错误码：${code}\n操作编号：${jobId}\n采集轮次：${evidenceRunId||'未取得'}\n发生时间：${error.occurredAt?activityTime(error.occurredAt):'任务未记录'}`;
    if(error.readFailedAt)$('problem-detail').textContent+=`\n读取失败时间：${activityTime(error.readFailedAt)}\n请求：${error.requestPath||'未记录'}\nHTTP：${error.httpStatus??'未记录'}\n状态读取分类：${error.readFailure||'未记录'}`;
    if(error.costDiagnostic){
      const d=error.costDiagnostic;
      const observed=d.observed||{};
      $('problem-detail').textContent+=`\n采购页：${d.requested_page??'未记录'}\n采购页 HTTP：${d.http_status??'未记录'}\n实际页码/游戏/商品：${observed.page??'未记录'} / ${observed.game??'未记录'} / ${observed.product??'未记录'}`;
    }
    const retry=automation?.schedule?.collection_retry;
      if(sourceErrors.length&&retry&&jobId===automation.schedule.last_job_id){
        $('problem-summary').textContent=stage+'未完成：'+sourceSummary+'。本轮未报价或改价；'+
          (retry.blocked_reason?'重试等待安全门禁。':retry.fast_retries_exhausted?'快速重试已达3次，转为每60分钟恢复检查。':'系统将退避后重试完整采集。');
        $('problem-detail').textContent+=`\n采集重试：${retry.next_attempt}；下一次：${retry.next_at?activityTime(retry.next_at):'待定时检查'}`;
      }
      $('problem').classList.remove('hidden');
  }

  function eventId(){
    const bytes=new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
    const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  function setStatus(text,kind=''){
    $('status').textContent=text;
    $('status').className='notice'+(kind?' '+kind:'');
  }
  function modalStatus(text,kind=''){
    $('preview-status').textContent=text;
    $('preview-status').className='notice'+(kind?' '+kind:'');
  }
  function restoreStatus(text,kind=''){
    $('restore-status').textContent=text;
    $('restore-status').className='notice'+(kind?' '+kind:'');
  }
  function buttons(){
    $('collect').disabled=busy;
    $('preview').disabled=busy||!quote||!runId;
    $('update-preview').disabled=busy||!preview;
    $('execute').disabled=!writerReady||!automation?.system_enabled||busy||!preview||dirty||Date.now()>=Date.parse(preview.expires_at);
    $('automation-save').disabled=busy||discountBusy||!automation;
    discountButtons();
    $('player-sync-save').disabled=!playerSync;
    $('restore-preview-button').disabled=busy;
    $('restore-execute').disabled=!writerReady||busy||!restorePreview||Date.now()>=Date.parse(restorePreview.expires_at);
  }
  async function api(path,body){
    const readOnly=body===undefined,delays=[250,750];
    for(let attempt=0;;attempt++){
      const response=await fetch(API+path,{method:readOnly?'GET':'POST',
        headers:readOnly?undefined:{'Content-Type':'application/json'},
        body:readOnly?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store'});
      const data=await response.json().catch(()=>({error:'服务器没有返回有效数据'}));
      if(response.ok)return data;
      if(readOnly&&response.status===503&&data.error==='state_unavailable'&&
         data.retryable_read!==false&&attempt<delays.length){
        await new Promise(resolve=>setTimeout(resolve,delays[attempt]));
        continue;
      }
      const error=Error(data.error||`HTTP_${response.status}`);
      error.code=data.error||`HTTP_${response.status}`;error.httpStatus=response.status;
      error.requestPath=path;error.readFailure=data.read_failure;error.readFailedAt=new Date().toISOString();
      throw error;
    }
  }

  function clearOldQuote(){
    runId=null;quote=null;preview=null;dirty=false;
    $('shade').classList.add('hidden');
    $('cards').replaceChildren();$('costs').replaceChildren();buttons();
  }
  function renderAutomation(){
    if(!automation)return;
    $('automation-enabled').checked=automation.system_enabled;
    $('automation-auto').checked=automation.mode==='auto';
    $('automation-interval').value=String(automation.interval_minutes);
    $('automation-margin').value=automation.minimum_gross_margin_pct;
    $('automation-enabled-state').textContent=automation.system_enabled?'开启':'关闭';
    $('automation-auto-state').textContent=automation.mode==='auto'?'开启':'关闭';
    $('collect').textContent=automation.system_enabled&&automation.mode==='auto'
      ?'立即手动采集':'开始采集最新价格';
    for(const platform of PLATFORMS){
      document.querySelector(`.automation-platform[value="${platform}"]`).checked=automation.platforms.includes(platform);
    }
    $('automation-version').textContent=`配置版本 ${automation.revision} · ${automation.system_enabled?'运行中':'已关闭'} · ${automation.mode==='auto'?'自动改价':'人工改价'} · ${automation.updated_by||'尚未设置'} ${automation.updated_at?activityTime(automation.updated_at):''}`;
    const schedule=automation.schedule||{};
    const scheduleText={system_off:'系统总开关已关闭',manual_mode:'自动跟价已关闭；请用人工按钮采集并确认改价',
      platforms_off:'三个平台操作开关均关闭，定时任务已停用',due:'等待下一次定时检查',
      in_progress:'定时任务正在排队或执行',paused_after_failure:'上次故障需要核对，自动恢复保护未解除；请查看具体错误',
        retry_waiting:`采集暂态超时，退避重试 ${schedule.collection_retry?.next_attempt||1}；下一次：${schedule.next_at?activityTime(schedule.next_at):'待定时检查'}`,
        retry_due:'采集暂态超时，退避已到期；等待定时检查与安全门禁',
        retry_cooldown:`连续采集失败，快速重试已达3次；转为每60分钟恢复检查，下一次：${schedule.next_at?activityTime(schedule.next_at):'待定时检查'}`,
        retry_blocked:`采集重试等待安全门禁：${schedule.collection_retry?.blocked_reason||'请查看任务日志'}；不会重放未确认写入`,
      player_sync_in_progress:'球员同步仍在执行，下一轮金币自动改价暂缓',
      player_sync_needs_reconcile:'球员同步结果未确认，金币自动改价已暂停；请核对球员任务日志',
      waiting:schedule.next_at?`下次采集：${activityTime(schedule.next_at)}`:'等待下一次采集',
      unavailable:'定时任务记录读取异常，请检查服务器日志'};
    const resultText={confirmed:'后台改价已确认',no_price_change:'可自动改价的平台价格未变，本轮跳过改价',
      deferred_player_sync:'本轮采集已完成；当时因球员同步暂缓改价',
      previous_public_price_unconfirmed:'上轮前台售价未生效，本轮仅采集'};
    $('automation-schedule').textContent=`定时状态：${scheduleText[schedule.status]||'暂未取得'}；上次任务：${schedule.last_job_id||'无'}`+
      (schedule.last_result?`；结果：${resultText[schedule.last_result]||schedule.last_result}`:'')+
      (schedule.last_error?`；错误：${schedule.last_error}`:'');
    $('automation-status').textContent=automation.system_enabled&&automation.mode==='auto'
      ?'自动跟价运行中；建议价与前台售价将在监控区持续更新。'
      :'自动跟价关闭时，通过人工按钮采集和确认改价。';
    $('automation-status').className='muted';
    automationDirty=false;renderDiscountRules();buttons();
  }
  async function refreshAutomation(){
    if(automationDirty)return;
    try{
      const latest=await api('/automation');
      if(automation&&latest.revision!==automation.revision&&quote){
        clearOldQuote();setStatus('控制台配置已变化，旧报价和预览已清空。请重新采集。','warn');
      }
      automation=latest;renderAutomation();
      await syncAutomaticCycle();
    }catch(error){
      $('automation-status').textContent=`控制台设置读取失败：${error.code||error.message}`;
      $('automation-status').className='warning-text';
    }
  }
  function discountStatus(text,warn=false){
    $('discount-status').textContent=text;
    $('discount-status').className=warn?'warning-text':'muted';
  }
  function discountButtons(){
    const allowed=Boolean(automation?.can_edit_discount_rules);
    const unavailable=busy||discountBusy||!allowed;
    const stale=discountBaseRevision!==automation?.revision;
    document.querySelectorAll('.discount-input').forEach(input=>input.disabled=unavailable);
    $('discount-preview').disabled=unavailable||stale;
    $('discount-save').disabled=unavailable||stale||automationDirty;
    $('discount-defaults').disabled=unavailable;
    $('discount-reload').disabled=busy||discountBusy;
  }
  function setDiscountInputs(rules){
    for(const name of DISCOUNT_BANDS)for(const end of ['min','max'])
      $(`discount-${name}-${end}`).value=rules.bands[name][`${end}_discount_pct`];
  }
  function renderDiscountRules(){
    if(!automation)return;
    if(!discountDirty){
      setDiscountInputs(automation.pricing_rules||DEFAULT_DISCOUNT_RULES);
      discountBaseRevision=automation.revision;
      discountStatus(automation.can_edit_discount_rules
        ?'已读取保存范围；修改后可预览草稿，保存不会立即改价。'
        :'当前账号仅可查看已保存范围。');
    }else if(discountBaseRevision!==automation.revision){
      $('discount-impact').classList.add('hidden');
      discountStatus('配置版本已变化；本地草稿保留，需重新读取范围后再编辑保存。',true);
    }
    $('discount-version').textContent=`已保存版本 ${automation.revision}`+
      (discountDirty?` · 未保存草稿（基于版本 ${discountBaseRevision}）`:'');
    discountButtons();
  }
  function discountDraft(){
    const bands={};
    for(const name of DISCOUNT_BANDS){
      const row={};
      for(const end of ['min','max']){
        const text=$(`discount-${name}-${end}`).value;
        if(!/^[0-9]+(?:\.[0-9]{1,2})?$/.test(text)||!Number.isFinite(Number(text))||Number(text)>10)
          throw Error(REASONS.automation_discount_pct_invalid);
        row[`${end}_discount_pct`]=Number(text).toFixed(2);
      }
      if(Number(row.min_discount_pct)>Number(row.max_discount_pct))
        throw Error(REASONS.automation_discount_range_invalid);
      bands[name]=row;
    }
    return {schema_version:1,bands};
  }
  function markDiscountDirty(){
    discountDirty=true;discountEpoch++;
    $('discount-impact').classList.add('hidden');
    renderDiscountRules();discountStatus('范围草稿尚未保存；实际任务继续使用已保存版本。',true);
  }
  document.querySelectorAll('.discount-input').forEach(input=>input.addEventListener('input',markDiscountDirty));
  $('discount-defaults').onclick=()=>{
    if(!automation?.can_edit_discount_rules||discountBusy)return;
    setDiscountInputs(DEFAULT_DISCOUNT_RULES);markDiscountDirty();
  };
  $('discount-reload').onclick=async()=>{
    if(discountBusy||busy)return;
    discountBusy=true;buttons();
    try{
      const latest=await api('/automation');
      if(automation&&latest.revision!==automation.revision)clearOldQuote();
      automation=latest;discountDirty=false;discountEpoch++;
      $('discount-impact').classList.add('hidden');
      if(!automationDirty)renderAutomation();else renderDiscountRules();
    }catch(error){discountStatus(`读取未完成：${REASONS[error.code]||error.code||error.message}`,true)}
    finally{discountBusy=false;buttons()}
  };
  $('discount-preview').onclick=async()=>{
    if(discountBusy||busy||!automation?.can_edit_discount_rules)return;
    let rules;try{rules=discountDraft()}catch(error){discountStatus(error.message,true);return}
    const epoch=discountEpoch,revision=discountBaseRevision;
    discountBusy=true;buttons();discountStatus('正在按已有最新快照预览草稿…');
    try{
      const result=await api('/automation/discount-preview',{rules,expected_revision:revision});
      if(epoch!==discountEpoch||result.config_revision!==discountBaseRevision||
         automation.revision!==revision){discountStatus('草稿或配置已变化，预览结果已丢弃。',true);return}
      const original=new Map(result.original.rows.map(row=>[row.platform,row]));
      const current=new Map(result.current.rows.map(row=>[row.platform,row]));
      $('discount-impact').innerHTML=`<p class="footnote">未保存草稿预览 · 已保存配置版本 ${result.config_revision} · 快照 ${esc(result.run_id)} · ${esc(activityTime(result.collected_at))}</p><div class="discount-preview-cards">`+
        result.draft.rows.map(row=>{
          const before=current.get(row.platform),old=original.get(row.platform);
          return `<article class="discount-preview-card"><b>${esc(row.platform)}</b><p>改价前毛利：${fmt(row.pre_change_margin_pct)}%</p><p>原算法选值：${fmt(old?.requested_discount_pct)}% → 草稿目标降幅：${fmt(row.requested_discount_pct)}%</p><p>实际降幅：${fmt(row.lootbar_reduction_pct)}%</p><p>页面建议价：$${fmt(before?.target_page_usd)} → $${fmt(row.target_page_usd)}</p><p>成本保底：${row.profit_floor_applied?'已覆盖目标降幅':'未覆盖目标降幅'}${row.auto_price_source==='PS'?' · 跟随 PS':''}</p><p class="warning-text">${esc(row.warning||'')}</p></article>`;
        }).join('')+'</div>';
      $('discount-impact').classList.remove('hidden');
      discountStatus('草稿预览完成；未保存参数，未采集或改价。');
    }catch(error){discountStatus(`预览未完成：${REASONS[error.code]||error.code||error.message}`,true)}
    finally{discountBusy=false;buttons()}
  };
  $('discount-save').onclick=async()=>{
    if(discountBusy||busy||automationDirty||!automation?.can_edit_discount_rules)return;
    let rules;try{rules=discountDraft()}catch(error){discountStatus(error.message,true);return}
    if(Number(automation.minimum_gross_margin_pct)<10){discountStatus(REASONS.automation_discount_margin_floor_invalid,true);return}
    const oldRevision=discountBaseRevision;
    discountBusy=true;buttons();
    try{
      const updated=await api('/automation/discount-rules',{rules,expected_revision:oldRevision});
      automation=updated;discountDirty=false;discountEpoch++;
      $('discount-impact').classList.add('hidden');renderAutomation();
      if(updated.revision!==oldRevision){clearOldQuote();displayedAutomaticJobId=null}
      discountStatus(updated.revision===oldRevision?'范围与当前配置一致，无需重复保存；未触发改价。'
        :'范围已保存；旧预览已失效，将在下一原有自然周期使用，不立即改价。');
      void refreshActivity();
    }catch(error){
      try{
        const actual=await api('/automation');
        if(actual.revision!==automation.revision)clearOldQuote();
        automation=actual;renderDiscountRules();
        discountStatus(`保存未获确认：${REASONS[error.code]||error.code||error.message}；已读回线上版本 ${actual.revision}，请核对。`,true);
      }catch(_){discountStatus('保存响应异常且线上状态未读回；请保留草稿，勿重复提交，重新读取范围后核对。',true)}
    }finally{discountBusy=false;buttons()}
  };

  function renderPlayerSync(){
    if(!playerSync)return;
    $('player-sync-enabled').checked=playerSync.enabled;
    $('player-sync-state').textContent=playerSync.enabled?'开启':'关闭';
    const last=playerSync.last_job;
    if(playerSync.price_verification_waived===true){
      $('player-sync-status').textContent=`${playerSync.enabled?'已开启':'已关闭'} · 配置版本 ${playerSync.revision}；旧价格复验已豁免，不拦截自动改价。`;
      $('player-sync-status').className='muted';
      playerSyncDirty=false;buttons();return;
    }
    $('player-sync-status').textContent=`${playerSync.enabled?'已开启':'已关闭'} · 配置版本 ${playerSync.revision}`+
      (last?`；上次任务 ${last.job_id}：${last.result||last.status}`+
        (playerSync.price_verification==='disabled'?'；不复验球员价格':last.progress?.mode==='category_all'?`，类目 ${last.progress.model_count||'—'} 个模型；随机抽查 ${last.progress.sample_verified_count||0}/${last.progress.sample_count||5} 个`:
          last.progress?.model_count?`，已核验 ${last.progress.verified_count||0}/${last.progress.model_count} 个模型`:'')+
        (last.error?'，'+last.error:''):'；尚无联动任务');
    $('player-sync-status').className='muted';
    playerSyncDirty=false;buttons();
  }
  async function refreshPlayerSync(){
    if(playerSyncDirty)return;
    try{
      const latest=await api('/player-sync');
      const changed=!playerSync||latest.revision!==playerSync.revision;
      playerSync=latest;renderPlayerSync();
      if(changed){displayedAutomaticJobId=null;await syncAutomaticCycle()}
    }
    catch(error){$('player-sync-status').textContent=`球员同步状态读取失败：${error.code||error.message}`;
      $('player-sync-status').className='warning-text'}
  }
  $('player-sync-enabled').addEventListener('change',()=>{
    playerSyncDirty=true;
    $('player-sync-state').textContent=$('player-sync-enabled').checked?'开启':'关闭';
    $('player-sync-status').textContent='球员同步开关尚未保存。';
  });
  $('player-sync-save').onclick=async()=>{
    if(!playerSync)return;
    $('player-sync-save').disabled=true;
    try{
      playerSync=await api('/player-sync',{enabled:$('player-sync-enabled').checked,
        expected_revision:playerSync.revision});
      renderPlayerSync();
      $('player-sync-status').textContent=`球员同步开关已保存：${playerSync.enabled?'开启':'关闭'}。`;
      displayedAutomaticJobId=null;
      await refreshAutomation();
    }catch(error){
      playerSyncDirty=false;
      await refreshPlayerSync();
      $('player-sync-status').textContent=`未保存：${REASONS[error.code]||error.code||error.message}；已恢复服务器状态。`;
      $('player-sync-status').className='warning-text';
    }finally{$('player-sync-save').disabled=false}
  };
  document.querySelectorAll('#automation-enabled,#automation-auto,#automation-interval,#automation-margin,.automation-platform').forEach(input=>{
    for(const eventName of ['input','change'])input.addEventListener(eventName,()=>{
      automationDirty=true;discountButtons();$('automation-status').textContent='设置尚未保存。';
      $('automation-enabled-state').textContent=$('automation-enabled').checked?'开启':'关闭';
      $('automation-auto-state').textContent=$('automation-auto').checked?'开启':'关闭';
    });
  });
  $('automation-save').onclick=async()=>{
    if(!automation||busy||discountBusy)return;
    const interval=Number($('automation-interval').value);
    const margin=Number($('automation-margin').value);
    if(!Number.isInteger(interval)||interval<1||interval>9999){
      $('automation-status').textContent=REASONS.automation_interval_invalid;
      $('automation-status').className='warning-text';return;
    }
    if($('automation-margin').value.trim()===''||!Number.isFinite(margin)||margin<0||margin>=100||
       !/^\d+(?:\.\d{1,2})?$/.test($('automation-margin').value.trim())){
      $('automation-status').textContent=REASONS.minimum_margin_invalid;
      $('automation-status').className='warning-text';return;
    }
    const platforms=[...document.querySelectorAll('.automation-platform:checked')].map(input=>input.value);
    const settings={system_enabled:$('automation-enabled').checked,
      mode:$('automation-auto').checked?'auto':'manual',
      interval_minutes:interval,platforms,
      minimum_gross_margin_pct:$('automation-margin').value.trim()};
    try{
      const updated=await api('/automation',{expected_revision:automation.revision,settings});
      automation=updated;renderAutomation();clearOldQuote();
      displayedAutomaticJobId=null;
      $('automation-status').textContent=updated.mode==='auto'&&updated.system_enabled
        ?'设置已保存；旧报价已清空，等待定时任务生成新建议价。'
        :'设置已保存；旧报价已清空，请手动采集。';
      $('automation-status').className='muted';
      void refreshActivity();
    }catch(error){
      const oldRevision=automation.revision;
      automationDirty=false;
      renderAutomation();
      await refreshAutomation();
      $('automation-status').textContent=automation.revision!==oldRevision
        ?'保存响应异常；已重新读取线上配置，请核对开关与参数。'
        :`设置未保存，开关已恢复线上状态：${REASONS[error.code]||error.code||error.message}`;
      $('automation-status').className='warning-text';
    }
  };
  const ACTION_LABELS={collect:'采集与报价',auto_cycle:'定时采集与改价',automation_config:'控制台设置',player_sync:'球员售价同步',preview:'后台只读预览',recalculate:'修改报价',
    execute:'后台改价',restore_preview:'恢复只读预览',restore:'恢复原参数',
    price_change_start:'旧版改价开始',price_change_result:'旧版改价结果',
    restore_start:'旧版恢复开始',restore_result:'旧版恢复结果'};
  const STATE_LABELS={queued:'排队中',running:'执行中',ready:'已完成',failed:'失败',
    interrupted:'已中断',CONFIRMED:'已确认',RESTORED:'恢复已确认',CHECK_ONLY:'只读核对',
    PARTIAL:'部分完成，待核对',UNCERTAIN:'结果不明，待核对',FAILED_BEFORE_WRITE:'写入前失败',
    complete:'采集完成',partial:'采集有缺项',pending:'执行中',confirmed:'已确认',
    unconfirmed:'待核对',stopped:'已停止'};
  let activityLoading=false,activityModeDay=null,activityPending=false;
  function activityTime(value){
    if(!value)return '时间未取得';
    const date=new Date(value);
    return Number.isNaN(date.getTime())?'时间未取得':date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
  }
  let monitorData=null,monitorLoading=false;
  function renderMonitor(data,disconnected=false){
    const health=data.health||{},storefront=data.storefront||{},rows=storefront.rows||{};
    const publication=data.publication||{};
    const publicationRows=Object.fromEntries((publication.platforms||[]).map(row=>[row.platform,row]));
    const mismatched=(publication.platforms||[]).filter(row=>row.status==='mismatch');
    const automationStatus=data.automation?.schedule?.status||'unavailable';
    const sync=data.player_sync||{},syncJob=sync.last_job||{},syncProgress=syncJob.progress||{};
    const cache=data.cache_refresh||{};
    const syncCount=syncProgress.mode==='category_all'?
      (Number.isInteger(syncProgress.sample_verified_count)&&Number.isInteger(syncProgress.sample_count)?
        ` 抽查${syncProgress.sample_verified_count}/${syncProgress.sample_count}`:' 抽查待开始'):
      (Number.isInteger(syncProgress.verified_count)&&Number.isInteger(syncProgress.model_count)&&syncProgress.model_count>0?
        ` ${syncProgress.verified_count}/${syncProgress.model_count}`:'');
    let syncStatus='状态不可用',syncGood=false;
    if(sync.enabled===false)syncStatus='已关闭';
    else if(sync.enabled===true){
      syncGood=true;
      if(!sync.last_job||syncJob.config_revision!==sync.revision)syncStatus='开启·等待下轮';
      else if(syncJob.status==='queued')syncStatus='已排队';
      else if(syncJob.status==='running')syncStatus=`运行中${syncCount}`;
      else if(sync.price_verification_waived===true)syncStatus='旧价格复验已豁免';
      else if(syncJob.status==='ready'&&syncJob.result==='confirmed')syncStatus=sync.price_verification==='disabled'?'后台请求已确认 · 不复验价格':`已确认${syncCount}`;
      else{syncStatus=`待核对${syncCount}`;syncGood=false}
    }
    const states=[
      ['面板连接',disconnected?'连接中断':'已连接',!disconnected],
      ['自动跟价定时器',health.automation_timer==='active'?'运行中':health.automation_timer||'未取得',health.automation_timer==='active'],
      ['前台售价采集',health.storefront_collection==='linked'?'随竞品采集':health.storefront_collection||'未取得',health.storefront_collection==='linked'],
      ['写价后后台清缓存',cache.status==='cleared'?'已清理':cache.status==='unconfirmed'?'清理未确认':'尚无记录',cache.status==='cleared'],
      ['后台与前台售卖价',publication.status==='matched'?'三平台一致':
        publication.status==='mismatch'?`${mismatched.length} 个平台不一致`:
        publication.status==='not_checked_after_write'?'等待下轮前台采集':
        publication.status==='no_confirmed_write'?'尚无改价记录':'待核对',publication.status==='matched'],
      ['采集/改价任务',({waiting:'等待下轮',due:'等待定时检查',in_progress:'执行中',manual_mode:'人工模式',
        system_off:'系统已关闭',platforms_off:'平台已关闭',paused_after_failure:'故障需核对',unavailable:'状态不可用',
        retry_waiting:'采集退避重试',retry_due:'重试等待门禁',retry_cooldown:'连续故障 · 60分钟恢复检查',retry_blocked:'重试门禁阻止',
        player_sync_in_progress:'持续采集 · 自动改价暂缓',player_sync_needs_reconcile:'持续采集 · 自动改价暂停'})[automationStatus]||'状态未取得',
        !['unavailable','paused_after_failure','player_sync_needs_reconcile','retry_waiting','retry_due','retry_cooldown','retry_blocked'].includes(automationStatus)],
      ['球员售价同步',syncStatus,syncGood],
      ['工作进程',health.worker==='ok'?'正常':health.worker||'未取得',health.worker==='ok'],
      ['服务器浏览器',health.browser==='ok'?'正常':health.browser||'未取得',health.browser==='ok'],
      ['P2PAH 会话',health.p2pah_session==='ok'?'正常':health.p2pah_session||'未取得',health.p2pah_session==='ok'],
      ['改价通道',health.price_writer==='ready'?'就绪':health.price_writer||'未取得',health.price_writer==='ready'],
      ['任务队列',health.queue_depth==null?'未取得':`${health.queue_depth} 件`,health.queue_depth===0],
      ['未确认写入',health.incomplete_executions==null?'未取得':`${health.incomplete_executions} 件`,health.incomplete_executions===0]
    ];
    $('monitor-health').innerHTML=states.map(([label,value,good])=>
      `<div class="monitor-cell"><b>${esc(disconnected?'上次 '+label:label)}</b><span class="${label==='后台与前台售卖价'&&publication.status==='mismatch'&&!disconnected?'monitor-bad':good&&!disconnected?'monitor-good':'monitor-warn'}">${esc(value)}</span></div>`).join('');
    $('monitor-prices').innerHTML=PLATFORMS.map(platform=>{
      const row=rows[platform]||{},published=publicationRows[platform]||{},available=row.package_usd!=null;
      const state=disconnected?'页面连接中断；上次核实':
        published.status==='mismatch'?'与后台不一致':
        row.status==='last_collected'?'上轮核实':row.status==='stale'?'上次核实':
        row.status==='unavailable'?'采集不可用；上次核实':'尚无有效价格';
      const className=published.status==='mismatch'&&!disconnected?'monitor-bad':
        row.status==='last_collected'&&!disconnected?'monitor-good':'monitor-warn';
      const proposal=data.latest_collection?.proposals?.[platform];
      return `<article class="monitor-price-card ${platform.toLowerCase()} ${published.status==='mismatch'?'mismatch':''}">`+
        `<div class="monitor-card-head"><strong>${platform==='XBOX'?'Xbox':platform}</strong><span class="monitor-card-state ${className}">${esc(state)}</span></div>`+
        `<div class="monitor-card-value">${available?`$${decimal4(row.package_usd,2)} <small>100K 页面总价</small>`:'—'}</div>`+
        `<p class="monitor-card-detail">实际单价：<b>${available?`$${decimal4(row.usd_per_k)} / K`:'—'}</b> · 赠送 <b>${available?`${fmt(row.bonus_k)}K`:'—'}</b></p>`+
        `<p class="monitor-card-detail">上轮建议价：<b>${proposal==null?'—':`$${decimal4(proposal)} / K`}</b></p>`+
        (published.status==='mismatch'?`<p class="monitor-card-detail monitor-bad">后台商品价对应页面总价：<b>$${decimal4(published.backend_page_usd,2)}</b>；公开页尚未生效</p>`:'')+
        `<div class="monitor-card-time">前台核实：${row.checked_at?activityTime(row.checked_at):'—'}</div></article>`;
    }).join('');
    const collection=data.latest_collection,attempt=data.latest_attempt;
    $('monitor-collection-time').textContent=collection?
      `可用采集轮次：${collection.run_id}；开始时间：${activityTime(collection.created_at)}`+
      (collection.unavailable_sources?.length?`；应急运行：${collection.unavailable_sources.join('、')} 暂不可用；参考源 ${Object.entries(collection.reference_sources||{}).map(([p,sites])=>`${p}: ${sites.join('、')}`).join('；')}，异常来源恢复后重新纳入。`:'')+
      (attempt&&attempt.run_id!==collection.run_id?`；最新一轮 ${attempt.status||'未知'}，以下是上次可用记录，不是本轮报价。`:''):
      '尚无可用竞品采集记录。';
    const offers=collection?.competitors||[];
    const sites=['Lootbar','IGGM','U4GM','U7Buy'];
    // 每个区服固定四家来源（列＝竞品，行＝PS/XBOX/PC）。哪家本轮没采到，就补一张
    // 「暂未获取」占位卡 —— 缺项不再被后面的卡片顶上来，栅格不会错位。
    const gridSites=sites.concat(offers.map(row=>row.source).filter((source,index,list)=>
      sites.indexOf(source)<0&&list.indexOf(source)===index));
    const offerOf=(platform,source)=>offers.find(row=>row.platform===platform&&row.source===source);
    const slots=[];
    PLATFORMS.forEach(platform=>gridSites.forEach(source=>slots.push({platform,source,row:offerOf(platform,source)})));
    $('monitor-competitors').innerHTML=offers.length?slots.map(({platform,source,row})=>!row?
      `<article class="monitor-competitor-card missing"><div class="monitor-card-head"><strong>${esc(source)}</strong><span class="tag">${esc(platform)}</span></div>`+
      `<div class="monitor-card-value">暂未获取</div>`+
      `<p class="monitor-card-detail">本轮未采集到该来源</p>`+
      `<p class="monitor-card-detail">未纳入本轮比价</p>`+
      `<div class="monitor-card-time">采集：—</div></article>`:
      `<article class="monitor-competitor-card"><div class="monitor-card-head"><strong>${esc(row.source)}</strong><span class="tag">${esc(row.platform)}</span></div>`+
      `<div class="monitor-card-value">${row.gross_usd==null?'—':`$${decimal4(row.gross_usd,2)} <small>页面总价</small>`}</div>`+
      `<p class="monitor-card-detail">实际单价：<b>${row.effective_usd_per_k==null?'—':`$${decimal4(row.effective_usd_per_k)} / K`}</b></p>`+
      `<p class="monitor-card-detail">购买 ${fmt(row.purchase_k)}K · 赠送 ${fmt(row.bonus_k)}K · 参与比价：<b>${row.comparable===false?'否':'是'}</b></p>`+
      `<div class="monitor-card-time">采集：${row.captured_at?activityTime(row.captured_at):'—'}</div></article>`).join(''):
      '<div class="monitor-card-empty">尚无完整采集；没有用缺项或旧报价生成本轮建议价。</div>';
    $('monitor-updated').textContent=`监控接口：${activityTime(data.generated_at)}`;
    const available=PLATFORMS.every(platform=>rows[platform]?.status==='last_collected');
    const synchronized=storefront.collection_run_id&&storefront.collection_run_id===data.latest_attempt?.run_id;
    $('monitor-message').textContent=disconnected?'面板暂时无法连接服务器；以下均为上次读取结果，请按时间判断。':
      publication.status==='mismatch'?`严重：最近${publication.write_mode==='manual'?'人工临时':'已确认'}商品价与 MMOEXP 公开售价不一致（${mismatched.map(row=>row.platform).join('、')}）。后台“同步成功”不代表顾客已看到新价；继续核对真实前后台。${publication.write_mode==='manual'?'这次人工改价不改变自动开关；前后台核对通过后，下次自动周期按新鲜采集重新定价。':'自动写价等待前台核对。'}`:
      !available?'面板已连接；部分前台售价采集不可用，请查看各平台状态和上次核实时间。':
      synchronized?'面板已连接；前台售价与最近一轮竞品采集同步更新，请查看各卡片核实时间。':
      '面板已连接；前台售价将在下一轮竞品采集时同步更新，请查看各卡片当前核实时间。';
    $('monitor-message').className=publication.status==='mismatch'&&!disconnected?'notice error':
      disconnected||!available?'warning-text':'muted';
  }
  async function refreshMonitor(){
    if(monitorLoading)return;
    monitorLoading=true;$('monitor-refresh').disabled=true;
    try{
      monitorData=await api('/monitor');renderMonitor(monitorData);
    }catch(error){
      if(monitorData)renderMonitor(monitorData,true);
      else{
        $('monitor-health').innerHTML='<div class="monitor-cell"><b>面板连接</b><span class="monitor-bad">连接中断</span></div>';
        $('monitor-updated').textContent='监控尚未连接';
        $('monitor-message').textContent=`监控读取失败：${REASONS[error.code]||error.code||error.message}`;
        $('monitor-message').className='warning-text';
      }
    }finally{monitorLoading=false;$('monitor-refresh').disabled=false}
  }
  $('monitor-refresh').onclick=()=>{void refreshMonitor()};
  setInterval(()=>{if(!document.hidden)void refreshMonitor()},30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)void refreshMonitor()});
  function activityDetail(event){
    const changes=(event.changes||[]).map(row=>{
      const before=row.before_cost==null?'—':`¥${esc(row.before_cost)} / $${esc(row.before_b2c)}`;
      const target=row.target_cost==null?'未取得':`¥${esc(row.target_cost)} / $${esc(row.target_b2c)}`;
      const after=row.after_cost==null?'回读未确认':`¥${esc(row.after_cost)} / $${esc(row.after_b2c)}`;
      return `${esc(row.platform)}：原 ${before} → 目标 ${target} → ${after}`;
    });
    const edits=Object.entries(event.quote_edits||{}).map(([platform,price])=>
      `${esc(platform)} 人工目标 $${esc(price)}/K（待审核）`);
    const platformText=!changes.length&&(event.platforms||[]).length?
      `平台：${(event.platforms||[]).map(esc).join('、')}`:'';
    const numbers=`本轮：${esc(event.run_id||'—')}；操作：${esc(event.id||'—')}`;
    const attempt=event.attempt_id?`改价尝试：${esc(event.attempt_id)}`:'';
    const source=event.source_execution_id?`原操作：${esc(event.source_execution_id)}`:'';
    const error=event.error?`错误码：${esc(event.error)}`:'';
    const cycle=event.cycle_status?`定时结果：${esc(event.cycle_status)}`:'';
    const blocked=Object.entries(event.blocked_platforms||{}).map(([platform,reason])=>
      `${esc(platform)} 已拦截：${esc(reason)}`).join('；');
    const operatorReason=event.operator_reason?`人工操作原因：${esc(event.operator_reason)}`:'';
    const lowMargin=(event.low_margin_platforms||[]).length?`低毛利人工确认：${event.low_margin_platforms.map(esc).join('、')}`:'';
    const config=event.config_change?`配置版本 ${esc(event.config_change.revision)}：${event.config_change.before_enabled?'开':'关'} / ${esc(event.config_change.before_mode)} → ${event.config_change.after_enabled?'开':'关'} / ${esc(event.config_change.after_mode)}`:'';
    const change=event.config_change;
    const discountChange=change?.after_pricing_rules&&JSON.stringify(change.before_pricing_rules||DEFAULT_DISCOUNT_RULES)!==JSON.stringify(change.after_pricing_rules)
      ?'<br>降幅范围：'+DISCOUNT_BANDS.map(name=>{
        const before=(change.before_pricing_rules||DEFAULT_DISCOUNT_RULES).bands[name];
        const after=change.after_pricing_rules.bands[name];
        const label={at_least_40:'≥40%', '30_to_40':'30–40%', '20_to_30':'20–30%',below_20:'<20%'}[name];
        return `${esc(label)} ${esc(before.min_discount_pct)}–${esc(before.max_discount_pct)}% → ${esc(after.min_discount_pct)}–${esc(after.max_discount_pct)}%`;
      }).join('；'):'';
    return [...changes,...edits,platformText,source,attempt,cycle,blocked,lowMargin,operatorReason,config,discountChange,error,numbers].filter(Boolean).join('<br>');
  }
  async function refreshActivity(){
    if(activityLoading){activityPending=true;return}
    const requestedDay=activityModeDay;
    activityLoading=true;$('activity-refresh').disabled=true;
    try{
      const listing=await api('/activity?limit=200'+(requestedDay?'&date='+encodeURIComponent(requestedDay):''));
      $('activity-user').textContent='当前账号：'+listing.current_user;
      $('activity-rows').innerHTML=listing.events.length?listing.events.map(event=>
        `<tr><td>${activityTime(event.at)}</td><td>${esc(event.user||'未取得')}</td>`+
        `<td>${esc(ACTION_LABELS[event.kind]||event.kind||'未知操作')}<br><span class="muted">${event.source==='legacy'?'旧版共享日志':'云端任务'}</span></td>`+
        `<td>${esc(STATE_LABELS[event.status]||event.status||'未取得')}`+
        `${event.job_status&&event.job_status!==event.status?`<br><span class="muted">任务：${esc(STATE_LABELS[event.job_status]||event.job_status)}</span>`:''}`+
        `${event.stage?`<br><span class="muted">${esc(event.stage)}</span>`:''}</td>`+
        `<td>${activityDetail(event)}</td>`+
        `<td><button class="secondary activity-retain" type="button" data-source="${esc(event.source)}" data-id="${esc(event.id)}" data-retained="${event.retained?'1':'0'}">${event.retained?'取消保留':'标记保留'}</button></td></tr>`).join(''):
        '<tr><td colspan="6">此时段暂无团队操作日志。</td></tr>';
      const warnings=listing.warnings||[];
      const range=requestedDay?`${requestedDay}（北京时间）`:'近 24 小时';
      $('activity-status').textContent=warnings.length?
        `${range}日志副本已读取；部分来源未能同步。诊断：${warnings.join('、')}。请反馈此提示。`:
        `${range}共展示 ${listing.events.length} 条记录（最多 200 条）；${requestedDay?'历史由手动查询':'每 30 秒自动刷新'}。超过 14 天仅能查询已标记保留的副本。`;
      $('activity-status').className=warnings.length?'warning-text':'muted';
      $('activity-recent').classList.toggle('hidden',!requestedDay);
    }catch(error){
      $('activity-status').textContent=`团队日志读取失败；错误码：${error.code||error.message}；时间：${activityTime(new Date().toISOString())}。请反馈此提示。`;
      $('activity-status').className='warning-text';
      if($('problem').classList.contains('hidden'))showProblem('团队操作日志',error);
    }finally{
      activityLoading=false;$('activity-refresh').disabled=false;
      if(activityPending){activityPending=false;void refreshActivity()}
    }
  }
  $('activity-refresh').onclick=()=>{void refreshActivity()};
  const beijingParts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{
    timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(
      new Date(Date.now()-86400000)).map(part=>[part.type,part.value]));
  $('activity-date').value=`${beijingParts.year}-${beijingParts.month}-${beijingParts.day}`;
  $('activity-history').onclick=()=>{
    if(!$('activity-date').value){$('activity-status').textContent=REASONS.activity_date_invalid;return}
    activityModeDay=$('activity-date').value;void refreshActivity();
  };
  $('activity-recent').onclick=()=>{activityModeDay=null;void refreshActivity()};
  $('activity-rows').addEventListener('click',async event=>{
    const button=event.target.closest('button.activity-retain');
    if(!button)return;
    button.disabled=true;
    try{
      await api('/activity/retain',{source:button.dataset.source,id:button.dataset.id,
        retained:button.dataset.retained!=='1'});
      await refreshActivity();
    }catch(error){
      $('activity-status').textContent=REASONS[error.code]||`日志保留标记失败：${error.code||error.message}`;
      $('activity-status').className='warning-text';
      button.disabled=false;
    }
  });
  setInterval(()=>{if(!document.hidden&&!activityModeDay)void refreshActivity()},30000);
  async function jobUntilReady(id,seconds){
    const deadline=Date.now()+seconds*1000;
    while(Date.now()<deadline){
      let job;
      try{job=await api('/jobs/'+id)}catch(error){error.jobId=id;throw error}
      if(job.status==='ready'){void refreshActivity();return job}
      if(['failed','interrupted'].includes(job.status)){
        void refreshActivity();
        const code=job.error_detail||job.writer_result?.reason||job.quote?.reason||job.snapshot?.reason||job.error||'job_failed';
        const error=Error(code);error.code=code;error.jobId=id;error.runId=job.snapshot?.run_id||job.run_id;error.occurredAt=job.completed_at||job.started_at||job.created_at;throw error;
      }
      await new Promise(resolve=>setTimeout(resolve,2200));
    }
    const error=Error('job_timeout');error.code='job_timeout';error.jobId=id;throw error;
  }
  function showQuote(){
    const rows=quote.result.rows;
    const byPlatform=Object.fromEntries(rows.map(row=>[row.platform,row]));
    $('cards').innerHTML=PLATFORMS.map(platform=>{
      const row=byPlatform[platform];
      const pageBasis=row.pricing_basis==='page_total_100k';
      const blocked=Boolean(row.auto_blocked_reason&&!row.quote_manual);
      const basePricing=pageBasis&&row.pricing_quantity_basis==='own_base_competitor_delivered';
      const effective=pageBasis&&!blocked?Number(row.target_page_usd)/(100+Number(row.own_bonus_k)):null;
      return `<article class="card ${platform.toLowerCase()} ${row.margin_below_minimum||blocked?'warning':''}">
        <div class="head"><span class="platform">${platform}</span><span class="tag">${esc(row.quote_manual?'人工目标价 · 待确认':row.status)}</span></div>
        <div class="value">${blocked?'暂无自动建议价':pageBasis?`$${esc(row.target_page_usd)} <small>100K 页面总价</small>`:`$${esc(row.proposal)} / K`}</div>
        <dl><dt>${pageBasis?'Lootbar 含赠送实际单价':'Lootbar 基准'}</dt><dd>$${esc(row.lootbar_usd_per_1k)} / K</dd>${pageBasis?`<dt>Lootbar 100K 页面总价</dt><dd>$${esc(row.lootbar_page_usd)}</dd>`:''}<dt>${pageBasis?(basePricing?(row.pricing_mode==='ps_shared_market'?'基础量定价相对 Xbox Lootbar（售价跟随 PS）':'基础量定价相对 Lootbar 含赠送单价'):'实际到账单价相对 Lootbar（旧口径）'):'建议下调'}</dt><dd>${row.lootbar_reduction_pct==null?'—':esc(row.lootbar_reduction_pct)+'%'}</dd><dt>后台单价</dt><dd>${blocked?'—':'$'+esc(row.proposal)+' / K'}</dd>${pageBasis?`<dt>我站赠送后实际到账单价</dt><dd>${blocked?'—':'$'+decimal4(effective)+' / K'}</dd><dt>改价前毛利</dt><dd>${esc(row.pre_change_margin_pct)}%</dd><dt>选用档位</dt><dd>${row.pricing_tier==='at_least_40'?'40% 及以上':row.pricing_tier==='30_to_40'?'30%–40%':row.pricing_tier==='20_to_30'?'20%–30%':row.pricing_tier==='below_20'?'低于 20% · 不额外降价':'无自动档位'}</dd>`:''}<dt>有效采购成本</dt><dd>¥${esc(row.cost_cny)} / K</dd><dt>${esc(quote.result.minimum_gross_margin_pct)}% 毛利售价底线</dt><dd>$${fmt(row.floor_usd_per_1k)} / K</dd><dt>改价后毛利</dt><dd>${blocked?'—':esc(row.gross_margin_pct)+'%'}</dd></dl>
        ${row.warning?`<p class="warning-text">${esc(row.warning)}</p>`:''}
        ${row.auto_price_source==='PS'&&!row.quote_manual?'<p class="muted card-note" style="margin:12px 0 0">自动售价跟随 PS；按 Xbox 最新成本单独核对毛利。</p>':''}</article>`;
    }).join('');
    const evidence=quote.evidence;
    $('costs').innerHTML=PLATFORMS.map(platform=>{
      const raw=evidence.costs[platform],row=byPlatform[platform];
      return `<tr><td><b>${platform}</b></td><td>¥${fmt(raw.cny_per_1k)}</td>
        <td>${fmt(raw.record_id)}<br>${fmt(raw.trade_at)}</td><td>${row.auto_blocked_reason&&!row.quote_manual?'—':'$'+fmt(row.proposal)}</td>
        <td>${row.auto_blocked_reason&&!row.quote_manual?'—':fmt(row.gross_margin_pct)+'%'}</td><td class="${row.warning?'warning-text':''}">${fmt(row.warning||'无')}</td></tr>`;
    }).join('');
    buttons();
  }
  async function syncAutomaticCycle(){
    if(!automation||automationDirty||busy||automaticSyncing)return;
    if(!automation.system_enabled||automation.mode!=='auto'||!automation.platforms.length){
      if(!quote)setStatus('服务器服务已就绪。点击“开始采集最新价格”获取本轮数据。','success');
      return;
    }
    const schedule=automation.schedule||{};
    if(schedule.status==='due'||!schedule.last_job_id){
      if(schedule.last_result==='deferred_player_sync'&&playerSync?.enabled===false){
        clearProblem();
        setStatus('球员同步已关闭，金币自动采集与改价将在下一次定时检查恢复。','success');
      }else if(!quote)setStatus('自动跟价已开启，等待定时任务采集并生成建议价。','warn');
      return;
    }
    automaticSyncing=true;
    const epoch=manualQuoteEpoch,revision=automation.revision;
    let observedRunId=schedule.last_job_id,observedJobId=schedule.last_job_id;
    const superseded=()=>busy||automationDirty||epoch!==manualQuoteEpoch||revision!==automation?.revision;
    try{
      // A completed manual collection may be newer than the last automatic cycle.
      const current=await api('/monitor');
      if(current.latest_attempt?.run_id===schedule.last_job_id)observedRunId=current.latest_attempt.run_id;
      if(superseded())return;
      const job=await api('/jobs/'+schedule.last_job_id);
      if(superseded()||job.job_id!==automation.schedule?.last_job_id)return;
      const collection=current.latest_collection;
      if(collection&&collection.run_id!==job.job_id&&Date.parse(collection.created_at)>Date.parse(job.created_at)){
        // Never present an older complete run as the current attempt.
        if(current.latest_attempt?.run_id!==collection.run_id)return;
        observedRunId=collection.run_id;observedJobId=collection.run_id;
        const collectionJob=await api('/jobs/'+collection.run_id);
        if(superseded()||job.job_id!==automation.schedule?.last_job_id)return;
        if(collectionJob.job_id!==collection.run_id)throw Error('job_identity_mismatch');
        if(collectionJob.status==='failed'||!['ready_for_preview','margin_review_required'].includes(collectionJob.quote?.status)){
          clearOldQuote();
          if(['queued','running'].includes(collectionJob.status)){
            setStatus('最新采集任务仍在执行，等待本轮报价；当前未展示旧报价。','warn');
          }else{
            const code=collectionJob.error_detail||collectionJob.error||collectionJob.quote?.reason||'quote_not_ready';
            showProblem('采集与报价',{code,jobId:collectionJob.job_id,runId:collection.run_id,
              occurredAt:collectionJob.completed_at||collectionJob.started_at||collectionJob.created_at});
            setStatus('最新采集任务未生成可用报价，请查看“本轮问题”；当前未展示旧报价。','error');
          }
          return;
        }
        const latestQuote=await api('/quotes/'+collection.run_id);
        if(superseded()||job.job_id!==automation.schedule?.last_job_id)return;
        if(latestQuote.run_id!==collection.run_id||latestQuote.automation_policy_revision!==revision||
           !['ready_for_preview','margin_review_required'].includes(latestQuote.status))
          throw Error('quote_not_ready');
        if(quote&&Date.parse(quote.created_at)>Date.parse(latestQuote.created_at))return;
        if(runId!==collection.run_id){
          clearOldQuote();runId=collection.run_id;quote=latestQuote;showQuote();
          setStatus(`已加载最新采集建议价；采集轮次：${runId}；报价时间：${activityTime(quote.created_at)}。实际售价请查看监控区。`,'success');
        }
        return;
      }
      if(schedule.last_job_id===displayedAutomaticJobId)return;
      if(job.kind!=='auto_cycle'||job.request?.policy_revision!==automation.revision)return;
      if(['queued','running'].includes(job.status)){
        if(runId&&runId!==job.job_id)clearOldQuote();
        if(['ready_for_preview','margin_review_required'].includes(job.quote?.status)&&runId!==job.job_id){
          const latestQuote=await api('/quotes/'+job.job_id);
          if(job.job_id!==automation.schedule?.last_job_id||
             job.request.policy_revision!==automation.revision||superseded())return;
          if(!['ready_for_preview','margin_review_required'].includes(latestQuote.status))
            throw Error('quote_not_ready');
          runId=job.job_id;quote=latestQuote;showQuote();
        }
        setStatus(quote&&runId===job.job_id
          ?`本轮自动采集已生成建议价，后台自动改价仍在执行；任务编号：${job.job_id}。`
          :`自动采集与改价正在${job.status==='queued'?'排队':'执行'}；任务编号：${job.job_id}。`,'warn');
        return;
      }
      if(job.job_id!==automation.schedule?.last_job_id||
         job.request.policy_revision!==automation.revision||superseded())return;
      clearOldQuote();
      if(['ready_for_preview','margin_review_required'].includes(job.quote?.status)){
        const latestQuote=await api('/quotes/'+job.job_id);
        if(job.job_id!==automation.schedule?.last_job_id||
           job.request.policy_revision!==automation.revision||superseded())return;
        if(!['ready_for_preview','margin_review_required'].includes(latestQuote.status))
          throw Error('quote_not_ready');
        runId=job.job_id;quote=latestQuote;showQuote();
      }
      displayedAutomaticJobId=job.job_id;
      if(job.status==='ready'&&job.result?.status==='confirmed'){
        clearProblem();
        const publicPending=job.public_page_readback?.status==='unconfirmed';
        setStatus(publicPending
          ?`后台改价及回读已确认；MMOEXP 前台售价仍待核对。完成时间：${activityTime(job.completed_at)}。`
          :`自动采集已生成本轮建议价，后台改价及回读已确认。完成时间：${activityTime(job.completed_at)}。`,
          publicPending?'warn':'success');
      }else if(job.status==='ready'&&job.result?.status==='all_platforms_blocked'){
        setStatus('自动采集已生成本轮建议价；所有启用平台均被最低毛利率门禁拦截，未执行改价。','warn');
      }else if(job.status==='ready'&&job.result?.status==='no_price_change'){
        clearProblem();
        setStatus('自动采集已生成本轮建议价；可自动改价的平台目标价均未变化，本轮跳过改价和球员同步。','success');
      }else if(job.status==='ready'&&job.result?.status==='previous_public_price_unconfirmed'){
        clearProblem();
        setStatus(`上轮后台改价尚未显示在 MMOEXP 前台；本轮已完成采集，暂不重复写价。待下一轮前台核对通过后恢复自动改价。`,'warn');
      }else if(job.status==='ready'&&job.result?.status==='deferred_player_sync'){
        clearProblem();
        setStatus(playerSync?.enabled===false
          ?'球员同步已关闭；这是关闭前的采集结果，金币自动采集与改价正在恢复。'
          :'本轮竞品和金币前台售价采集已完成；球员同步尚待确认，本轮暂缓金币自动改价。',
          playerSync?.enabled===false?'success':'warn');
      }else{
        const code=job.error_detail||job.writer_result?.reason||job.quote?.reason||
          job.snapshot?.reason||job.error||job.result?.status||'job_failed';
        showProblem('自动采集与改价',{code,jobId:job.job_id,runId:job.snapshot?.run_id||job.run_id,occurredAt:job.completed_at||job.started_at||job.created_at,costDiagnostic:job.snapshot?.cost_failure?.diagnostic});
        setStatus(`自动任务未确认完成；${quote?'已展示本轮建议价，':''}请查看“本轮问题”及团队操作日志。`,'error');
      }
    }catch(error){
      if(superseded())return;
      clearOldQuote();
      // A later successful GET of this same job must hydrate the quote again.
      displayedAutomaticJobId=null;
      error.runId=error.runId||observedRunId;
      showProblem('自动任务结果读取',error,observedJobId);
      setStatus('自动任务结果读取失败，请查看“本轮问题”；没有展示旧报价。','error');
    }finally{automaticSyncing=false}
  }
  function selectedNow(){
    return new Set([...document.querySelectorAll('.platform-select:checked')].map(input=>input.dataset.platform));
  }
  function renderPreview(selected=new Set(PLATFORMS)){
    const before=Object.fromEntries(preview.backend_before.rows.map(row=>[row.platform,row]));
    const automatic=Object.fromEntries(quote.result.rows.map(row=>[row.platform,row.auto_proposal]));
    $('preview-rows').innerHTML=preview.targets.map(target=>{
      const row=before[target.platform];
      const floor=quote.result.rows.find(item=>item.platform===target.platform)?.floor_usd_per_1k;
      const disabled=!automation?.platforms?.includes(target.platform);
      return `<tr><td><input class="platform-select" type="checkbox" data-platform="${target.platform}" ${selected.has(target.platform)&&!disabled?'checked':''} ${disabled?'disabled':''}></td>
        <td><b>${target.platform}</b></td><td>$${esc(row.b2c)}</td><td>¥${esc(row.costPrice)}</td>
        <td>$${esc(automatic[target.platform])}</td><td><input class="price-input" type="number" min="0.0001" step="0.0001" data-platform="${target.platform}" value="${esc(target.quote)}" aria-label="${target.platform} 目标售价"></td>
        <td>${floor==null?'成本缺失':`$${esc(floor)}`}${target.marginBelowMinimum?'<br><span class="warning-text">低于底线，人工须确认</span>':''}</td>
        <td>¥${esc(target.targetCost)}</td><td>${esc(target.actualGrossMargin)}%${target.warning?`<br><span class="warning-text">${esc(target.warning)}</span>`:''}</td>
        <td>${target.marginBelowMinimum?`<label><input class="margin-ack" type="checkbox" data-platform="${target.platform}">已核对</label>`:'—'}</td></tr>`;
    }).join('');
    $('minimum-margin').value=quote.result.minimum_gross_margin_pct;
    $('edit-reason').value=quote.edits?.reason||'';
    dirty=false;
    modalStatus(`服务器预览已生成；有效至 ${new Date(preview.expires_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}。`+
      (writerReady&&automation?.system_enabled?'核对所选平台后可确认执行。临时人工价不改变自动开关；下次自动周期按新鲜采集重新定价。':
        !automation?.system_enabled?'系统总开关已关闭，当前只能查看预览。':writerBlockReason),
      writerReady&&automation?.system_enabled?'':'warn');
    buttons();
  }
  async function requestPreview(){
    const created=await api('/reprice/preview',{run_id:runId});
    const job=await jobUntilReady(created.job_id,100);
    preview=await api('/previews/'+job.result.preview_id);
    if(preview.run_id!==runId||preview.status!=='review_only')throw Error('预览与本轮数据不一致');
  }
  $('collect').onclick=async()=>{
    if(busy)return;
    manualQuoteEpoch++;busy=true;runId=null;quote=null;preview=null;buttons();
    clearProblem();
    $('shade').classList.add('hidden');
    $('cards').replaceChildren();$('costs').replaceChildren();
    setStatus('服务器正在采集四家竞品、三平台真实成本与汇率，请稍候…');
    try{
      const started=await api('/collect',{});
      $('audit').textContent='采集任务：'+started.run_id;
      const job=await jobUntilReady(started.run_id,480);
      runId=job.result.run_id;
      quote=await api('/quotes/'+runId);
      if(!['ready_for_preview','margin_review_required'].includes(quote.status))throw Error('服务器报价尚不可预览');
      showQuote();
      clearProblem();
      setStatus('新一轮服务器采集完成。请核对依据，随后进入提交修改预览。'+
        (quote.status==='margin_review_required'?'有平台触及利润率阈值，请在预览中重点核对。':''),
        quote.status==='margin_review_required'?'warn':'success');
    }catch(error){showProblem('服务器采集与报价',error);setStatus('本轮采集或报价未完成。请查看上方“本轮问题”并反馈操作编号。','error')}
    finally{busy=false;buttons();await refreshMonitor()}
  };
  $('preview').onclick=async()=>{
    if(busy||!quote)return;
    manualQuoteEpoch++;busy=true;buttons();setStatus('服务器正在读取后台现值并生成只读预览…');
    try{
      await requestPreview();
      $('shade').classList.remove('hidden');
      renderPreview();
      clearProblem();
      setStatus('只读预览已生成；尚未写入后台。','success');
    }catch(error){showProblem('后台只读预览',error);setStatus('预览未完成。请查看上方“本轮问题”。','error')}
    finally{busy=false;buttons()}
  };
  $('close').onclick=()=>{$('shade').classList.add('hidden');preview=null;buttons()};
  $('preview-rows').addEventListener('input',event=>{
    if(event.target.matches('.price-input')){dirty=true;modalStatus('目标价已修改，请先更新服务器预览。','warn');buttons()}
  });
  $('minimum-margin').addEventListener('input',()=>{dirty=true;modalStatus('提示阈值已修改，请先更新服务器预览。','warn');buttons()});
  $('edit-reason').addEventListener('input',()=>{dirty=true;modalStatus('说明已修改，请先更新服务器预览。','warn');buttons()});
  $('update-preview').onclick=async()=>{
    if(busy||!preview)return;
    const selected=selectedNow();
    const base=Object.fromEntries(quote.result.rows.map(row=>[row.platform,row.auto_proposal]));
    const overrides={};
    for(const input of document.querySelectorAll('.price-input')){
      const value=input.value.trim();
      if(!/^\d+(?:\.\d{1,4})?$/.test(value)||Number(value)<=0){modalStatus(input.dataset.platform+' 目标价格式无效','error');return}
      if(Number(value)!==Number(base[input.dataset.platform]))overrides[input.dataset.platform]=value;
    }
    const margin=$('minimum-margin').value.trim();
    if(!/^\d+(?:\.\d{1,2})?$/.test(margin)||Number(margin)>=100){modalStatus('提示阈值必须在 0 至 100% 之间','error');return}
    const reason=$('edit-reason').value.trim();
    if(Object.keys(overrides).length&&!reason){modalStatus('修改目标价时请填写说明','error');return}
    manualQuoteEpoch++;busy=true;buttons();modalStatus('服务器正在重新计算并重读后台现值…');
    try{
      const request=await api('/reprice/recalculate',{run_id:runId,
        edits:{quotes:overrides,minimum_gross_margin_pct:margin,reason}});
      await jobUntilReady(request.job_id,25);
      quote=await api('/quotes/'+runId);
      await requestPreview();
      showQuote();renderPreview(selected);
      clearProblem();
      modalStatus('修改后的目标值已在服务器重新计算并预览，请核对后明确执行。','success');
    }catch(error){
      showProblem('修改后重新预览',error);
      preview=null;dirty=true;
      if(error.code==='newer_run_exists'){
        runId=null;quote=null;dirty=false;
        $('shade').classList.add('hidden');
        $('cards').replaceChildren();$('costs').replaceChildren();
        setStatus('已有更新的采集轮次；旧报价和预览已清空。点击“开始采集最新价格”重新审核。','warn');
      }else{
        modalStatus(`修改预览失败；错误码：${error.code||error.message}；操作编号：${error.jobId||'未取得'}。关闭预览可复制上方诊断信息。`,'error');
      }
    }
    finally{busy=false;buttons()}
  };
  $('execute').onclick=async()=>{
    if(busy||!preview||dirty)return;
    const selected=[...selectedNow()];
    if(!selected.length){modalStatus('请至少选择一个平台','error');return}
    const confirmed=[...document.querySelectorAll('.margin-ack:checked')].map(input=>input.dataset.platform);
    const unconfirmed=preview.targets.filter(item=>selected.includes(item.platform)&&item.marginBelowMinimum&&!confirmed.includes(item.platform));
    if(unconfirmed.length){modalStatus('请核对并确认低毛利平台：'+unconfirmed.map(item=>item.platform).join('、'),'warn');return}
    const marginReason=$('edit-reason').value.trim();
    if(confirmed.length&&!marginReason){modalStatus('低毛利人工改价请填写原因。','warn');return}
    const id=eventId();
    manualQuoteEpoch++;busy=true;buttons();
    modalStatus('服务器正在保存、同步并回读；操作编号：'+id,'warn');
    $('audit').textContent='改价执行中。操作编号：'+id;
    try{
      const started=await api('/reprice/execute',{preview_id:preview.preview_id,
        selected_platforms:selected,margin_confirmed_platforms:confirmed,
        margin_exception_reason:marginReason,client_event_id:id});
      const job=await jobUntilReady(started.job_id,145);
      const audit=await api('/audits/'+id);
      $('audit').textContent=`操作编号：${id}；状态：${audit.status}；阶段：${audit.stage}；平台：${audit.selected.join('、')}；已保存：${audit.changed.join('、')||'无'}。`;
      $('restore-source').value=id;
      $('shade').classList.add('hidden');preview=null;quote=null;runId=null;
      setStatus('后台同步反馈与刷新回读均已确认。需要再次操作时请重新采集。','success');
      clearProblem();
      if(job.result.status!=='CONFIRMED')throw Error('执行状态未确认');
    }catch(error){
      let auditText='操作编号：'+id+'；执行未确认。';
      try{const audit=await api('/audits/'+id);auditText+=` 阶段：${audit.stage}；状态：${audit.status}；已保存：${audit.changed?.join('、')||'无'}。`}
      catch(_){auditText+=' 请在后台核对实际值。'}
      $('audit').textContent=auditText;
      showProblem('后台保存、同步与回读',error,id);
      modalStatus(`执行未确认；错误码：${error.code||error.message}；操作编号：${id}。先核对后台，不要直接重复提交。`,'error');
      setStatus('服务器改价未确认，请查看本轮操作与后台实际值。','error');
      preview=null;
    }finally{busy=false;buttons()}
  };
  $('restore-preview-button').onclick=async()=>{
    if(busy)return;
    const source=$('restore-source').value.trim();
    if(!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(source)){
      $('restore-summary').textContent='请填写有效的原改价操作编号。';return;
    }
    manualQuoteEpoch++;busy=true;restorePreview=null;buttons();clearProblem();
    $('restore-summary').textContent='服务器正在只读核对原操作记录与当前后台…';
    try{
      const started=await api('/reprice/'+source+'/restore/preview',{});
      const job=await jobUntilReady(started.job_id,145);
      restorePreview=await api('/restore-previews/'+job.result.restore_preview_id);
      if(restorePreview.source_execution_id!==source||restorePreview.status!=='restore_review_only')
        throw Error('restore_source_mismatch');
      const expiry=new Date(restorePreview.expires_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
      $('restore-summary').textContent=`原操作编号：${source}\n恢复预览编号：${restorePreview.restore_preview_id}\n有效至：${expiry}；当前后台已与原操作完成记录核对。`;
      $('restore-rows').innerHTML=restorePreview.rows.map(row=>{
        const changed=Number(row.current_cost)!==Number(row.restore_cost)||Number(row.current_b2c)!==Number(row.restore_b2c);
        const available=restorePreview.available_platforms.includes(row.platform);
        return `<tr><td><input class="restore-select" type="checkbox" data-platform="${row.platform}" ${changed&&available?'checked':''} ${available?'':'disabled'}></td><td><b>${row.platform}</b>${changed?'':'（数值相同）'}</td><td>$${esc(row.current_b2c)}</td><td>¥${esc(row.current_cost)}</td><td>$${esc(row.restore_b2c)}</td><td>¥${esc(row.restore_cost)}</td></tr>`;
      }).join('');
      restoreStatus(`只读恢复预览已生成，有效至 ${expiry}。请核对后明确执行。`+
        (writerReady?'':writerBlockReason),writerReady?'success':'warn');
      $('restore-shade').classList.remove('hidden');
      clearProblem();
    }catch(error){showProblem('只读恢复预览',error);$('restore-summary').textContent=`恢复预览失败；错误码：${error.code||error.message}；操作编号：${error.jobId||source}。`}
    finally{busy=false;buttons()}
  };
  $('restore-close').onclick=()=>{$('restore-shade').classList.add('hidden');restorePreview=null;buttons()};
  $('restore-execute').onclick=async()=>{
    if(busy||!restorePreview||!writerReady||Date.now()>=Date.parse(restorePreview.expires_at))return;
    const selected=[...document.querySelectorAll('.restore-select:checked')].map(input=>input.dataset.platform);
    if(!selected.length){restoreStatus('请至少选择一个平台。','warn');return}
    const id=eventId(),source=restorePreview.source_execution_id;
    manualQuoteEpoch++;busy=true;buttons();restoreStatus('服务器正在保存原参数、同步并回读；操作编号：'+id,'warn');
    $('audit').textContent=`恢复执行中。原操作：${source}；新操作：${id}`;
    try{
      const started=await api('/reprice/'+source+'/restore',{
        restore_preview_id:restorePreview.restore_preview_id,selected_platforms:selected,client_event_id:id});
      const job=await jobUntilReady(started.job_id,145);
      const audit=await api('/audits/'+id);
      if(job.result.status!=='RESTORED'||audit.status!=='RESTORED')throw Error('restore_not_confirmed');
      $('audit').textContent=`恢复操作编号：${id}；原操作：${source}；状态：${audit.status}；阶段：${audit.stage}；平台：${audit.selected.join('、')}。`;
      $('restore-summary').textContent=`原操作 ${source} 已按所选平台恢复；恢复操作编号 ${id}；后台同步与刷新回读已确认。`;
      $('restore-shade').classList.add('hidden');restorePreview=null;
      setStatus('所选平台原参数已恢复，后台同步与刷新回读均已确认。','success');clearProblem();
    }catch(error){
      let details=`恢复操作编号：${id}；原操作：${source}；执行未确认。`;
      try{const audit=await api('/audits/'+id);details+=` 阶段：${audit.stage}；状态：${audit.status}；已保存：${audit.changed?.join('、')||'无'}。`}
      catch(_){details+=' 请在后台核对实际值。'}
      $('audit').textContent=details;showProblem('恢复保存、同步与回读',error,id);
      restoreStatus(`恢复未确认；错误码：${error.code||error.message}；操作编号：${id}。先核对后台，不要直接重复提交。`,'error');
      setStatus('服务器恢复未确认，请查看本轮问题与后台实际值。','error');restorePreview=null;
    }finally{busy=false;buttons()}
  };
  (async()=>{
    void refreshActivity();
    void refreshMonitor();
    try{
      const health=await api('/health');
      if(['api','worker','browser','p2pah_session'].some(key=>health[key]!=='ok'))
        throw Error('服务器服务未全部就绪');
      writerReady=health.price_writer==='ready'&&health.https_certificate?.status==='ok'&&location.protocol==='https:';
      writerBlockReason=health.https_certificate?.status==='ok'?
        '改价安全限制尚未解除，仅可核对预览。':'HTTPS 证书状态异常，仅可核对预览。';
      const expires=health.https_certificate?.expires_at?
        new Date(health.https_certificate.expires_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'未取得';
      $('security-status').textContent=writerReady?`HTTPS 已验证；证书有效至 ${expires}；服务器自动续期已启用。`:
        `真实改价暂停：${writerBlockReason} 证书状态：${health.https_certificate?.status||'missing'}；有效至 ${expires}。`;
      $('security-status').className='notice '+(writerReady?'success':'warn');
      buttons();
      if(health.https_certificate?.status!=='ok'){
        showProblem('HTTPS 证书',{code:'certificate_unhealthy'});
        $('problem-detail').textContent+=`\n证书状态：${health.https_certificate?.status||'missing'}\n到期时间：${health.https_certificate?.expires_at||'未取得'}`;
      }
      setStatus(writerReady?'服务器服务已就绪。点击“开始采集最新价格”获取本轮数据。':
        health.https_certificate?.status==='ok'?'服务器采集与预览已就绪；真实改价安全限制尚未解除。':
        '服务器采集与预览已就绪；HTTPS 证书状态异常，真实改价暂停。',writerReady?'success':'warn');
    }catch(error){showProblem('服务器连接',error);setStatus('服务器当前不可用，请查看上方“本轮问题”。','error')}
    await refreshAutomation();
    await refreshPlayerSync();
    setInterval(()=>{if(!document.hidden){void refreshAutomation();void refreshPlayerSync()}},30000);
  })();
})();
