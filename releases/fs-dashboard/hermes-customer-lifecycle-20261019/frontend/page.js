(() => {
  'use strict';
  const api = '/dashboard/fs-home/advisor.json';
  const $ = id => document.getElementById(id);
  const idPattern = /^[a-f0-9]{32}$/;
  const states = new Set(['available', 'partial', 'pending', 'unavailable']);
  let config = null, chosen = null, candidateEpoch = 0, detailEpoch = 0;
  let candidateAbort = null, detailAbort = null, pendingWrite = null, disposed = false, detailTimer = null, detailPollStarted = 0, detailLoading = false;
  const node = (tag, text, parent, cls) => { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; if (cls) item.className = cls; parent.append(item); return item; };
  const asText = value => value === null || value === undefined || value === '' ? '未取得' : String(value);
  const uidText = uid => uid === 0 || uid === '0' ? '游客（UID 0）' : uid === null || uid === undefined || uid === '' ? 'UID 未取得' : 'UID ' + uid;
  const money = value => value === null || value === undefined || value === '' ? '未取得' : '$' + value;
  const timeText = value => { const date = new Date(value); if (!value || Number.isNaN(date.getTime())) return '时间待核对'; const parts = new Intl.DateTimeFormat('en-US', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date); const get = type => parts.find(part => part.type === type)?.value; return get('year') + '-' + get('month') + '-' + get('day') + ' ' + get('hour') + ':' + get('minute'); };
  const identityReason = value => ({email_missing_or_invalid:'客户邮箱缺失或格式异常，不能加入观察。',customer_email_conflict:'同一订单的客户邮箱不一致，请先核对。',buyer_email_conflict:'同一 Buyer ID 对应不同邮箱，请先核对。',order_no_unmatched:'订单未在 Admin 中核对，不能加入观察。',admin_scope_mismatch:'订单游戏、站点或支付状态未通过核对。'})[value] || '客户身份尚未核实，不能加入观察。';
  const trackingStatus = value => ({active:'观察中',paused:'已停止追踪',closed:'已结束'})[value] || asText(value);
  const orderStatus = value => ({paid:'已付款',completed:'已完成',pending:'待处理',processing:'处理中',refunded:'已退款',cancelled:'已取消'})[value] || asText(value);
  const requestId = () => crypto.randomUUID().replaceAll('-', '');
  const setStatus = (text, error = false) => { $('status').hidden = !text; $('status').textContent = text; $('status').dataset.state = error ? 'error' : 'normal'; $('reconcile-write').hidden = !pendingWrite; };
  const params = (view, extra = {}) => { const query = new URLSearchParams({mode:'hermes',structure:'customer_tracking',view,...extra}); return api + '?' + query; };
  async function fetchJson(url, body, signal) {
    const local = new AbortController();
    const timer = setTimeout(() => local.abort(), 20000);
    const abort = () => local.abort();
    signal?.addEventListener('abort', abort, {once:true});
    try {
      const response = await fetch(url, {method:body ? 'POST' : 'GET',credentials:'same-origin',cache:'no-store',redirect:'error',signal:local.signal,headers:body ? {'Content-Type':'application/json','X-FS-Advisor-Action':'submit'} : {},body:body ? JSON.stringify(body) : undefined});
      if (!response.headers.get('content-type')?.includes('application/json')) throw Error('登录状态或返回内容异常，请重新登录 FS。');
      const value = await response.json();
      if (!response.ok) { const error = Error(value.error || '请求失败（' + response.status + '）'); error.status = response.status; throw error; }
      return value;
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  }
  const get = (view, extra, signal) => fetchJson(params(view, extra), null, signal);
  const post = (action, fields) => fetchJson(api, {kind:'hermes_customer_tracking',action,...fields});
  const clearPrivate = () => { clearVip(true); candidateAbort?.abort(); detailAbort?.abort(); clearTimeout(detailTimer); $('candidate-list').replaceChildren(); $('tracked-list').replaceChildren(); $('detail').replaceChildren(); $('detail-section').hidden = true; $('pool-reports').replaceChildren(); $('app').hidden = true; };
  const denied = () => { clearPrivate(); config = null; setStatus('当前账号没有智体客单追踪权限。请返回智体决策报告查看获准内容。', true); };
  function renderConfig(value) {
    if (!Number.isInteger(value?.version) || !Array.isArray(value?.product_types) || !Array.isArray(value?.customer_flags)) throw Error('配置格式异常。');
    if (config && config.version !== value.version) { candidateAbort?.abort(); $('candidate-list').replaceChildren(); node('p', '筛选条件已更新，请重新查看或扫描该日期名单。', $('candidate-list'), 'empty'); $('candidate-meta').textContent = ''; }
    config = value;
    const form = $('config-form');
    form.elements.profile.value = value.profile;
    form.elements.min_order_usd_exclusive.value = value.min_order_usd_exclusive;
    form.elements.max_discount_usd_exclusive.value = value.max_discount_usd_exclusive;
    for (const box of form.querySelectorAll('input[type=checkbox]')) box.checked = (value[box.name] || []).includes(box.value);
    $('config-version').textContent = '配置版本 ' + value.version;
    $('enabled-state').textContent = value.enabled ? '每日筛选已启用；符合条件的订单仍需人工加入持续观察。' : '每日自动筛选已停用；可人工查看已归档名单。';
  }
  function readForm() {
    const form = $('config-form');
    const value = {profile:form.elements.profile.value,site_id:config.site_id,product_types:[],min_order_usd_exclusive:form.elements.min_order_usd_exclusive.value,max_discount_usd_exclusive:form.elements.max_discount_usd_exclusive.value,customer_flags:[],enabled:config.enabled};
    for (const box of form.querySelectorAll('input[type=checkbox]:checked')) value[box.name].push(box.value);
    if (!value.product_types.length || !value.customer_flags.length) throw Error('至少选择一个商品品类和一个客户标记。');
    return value;
  }
  async function reconcile() {
    const pending = pendingWrite;
    if (!pending) return;
    try {
      const value = await get('request', {request_id:pending.request_id});
      if (pendingWrite !== pending) return;
      if (value.status === 'unknown') { setStatus('上次操作仍需服务端核对。请勿重复提交。', true); return; }
      if (value.status !== 'available' || value.action !== pendingWrite.action ||
          (pendingWrite.action === 'vip_feedback' && !validVipReceipt(value.result, pendingWrite))) {
        throw Error('操作回执不匹配，请人工核对。');
      }
      const action = pendingWrite.action;
      pendingWrite = null;
      $('save-config').disabled = false;
      setStatus('上次' + ({save_config:'配置保存',scan:'名单扫描',track:'加入观察'}[action] || '操作') + '已核实。');
      if (action === 'save_config') await loadConfig();
      if (action === 'track' || action === 'stop') await loadTracked();
      if (action !== 'vip_feedback') loadPoolReports();
      if (action === 'generate_pool') await loadPoolReports();
      if (action === 'scan') await loadCandidates($('candidate-date').value);
      if (action === 'vip_feedback') await loadVip($('vip-week-date').value, value.result?.case_id);
      $('scan-day').disabled = false;
    } catch (error) { if (error.status === 403) { denied(); return; } setStatus('上次操作仍需核对：' + error.message, true); }
  }
  let writeInFlight = false;
  async function write(action, fields, button) {
    if (writeInFlight) return null;
    if (pendingWrite) { await reconcile(); return null; }
    const body = {...fields,request_id:requestId()};
    const receipt = {action,request_id:body.request_id};
    if (action === 'vip_feedback') Object.assign(receipt, {case_id:body.case_id,event:body.event});
    button.disabled = writeInFlight = true;
    try {
      const result = await post(action, body);
      if (result.state === 'unknown' || result.status === 'unknown' ||
          (action === 'vip_feedback' && !validVipReceipt(result, receipt))) {
        pendingWrite = receipt;
        setStatus('操作结果待核对，请勿重新发起。', true);
        return null;
      }
      return result;
    } catch (error) {
      if (action === 'vip_feedback' && error.message === 'vip_owner_required') {
        setStatus('维护记录由其他同事负责，请重新查看名单。', true);
        return null;
      }
      if (error.status === 403) { denied(); return null; }
      if (!error.status || error.status >= 500) { pendingWrite = receipt; setStatus('连接中断，操作结果待核对。请勿重复提交。', true); }
      else setStatus('操作未接受：' + error.message, true);
      return null;
    } finally { writeInFlight = false; button.disabled = !!pendingWrite; }
  }
  async function loadConfig() {
    try {
      const value = await get('config');
      renderConfig(value);
      $('app').hidden = false;
      setStatus(pendingWrite ? '上次操作待核对。' : '');
    } catch (error) { if (error.status === 403) denied(); else { clearPrivate(); config = null; setStatus('配置读取失败：' + error.message, true); } }
  }
  function detailRow(list, label, value) { const box = node('div', undefined, list); node('dt', label, box); node('dd', asText(value), box); }
  function candidateCard(item) {
    const card = node('article', undefined, $('candidate-list'), 'record');
    node('h3', '订单 ' + asText(item.order_no), card);
    const dl = node('dl', undefined, card);
    detailRow(dl, '客户邮箱', item.email);
    detailRow(dl, '客户身份', uidText(item.uid));
    detailRow(dl, '订单金额（USD）', money(item.order_usd));
    detailRow(dl, '金额来源', item.order_usd_source === 'ES_candidate_export' ? 'ES 导出（候选筛选）' : item.order_usd_source === 'Admin' ? 'Admin' : item.order_usd_source === 'Admin_ES_export' ? 'Admin 缺项，由 ES 订单补充' : item.order_usd_source);
    if (item.buyer_group_order_count > 1) detailRow(dl, '同一 Buyer ID 合格订单', item.buyer_group_order_count + ' 笔（本日）');
    detailRow(dl, '折扣（USD）', money(item.discount_usd));
    detailRow(dl, '品类', item.product_type);
    detailRow(dl, '新老客', ({new:'新客',old:'老客',unknown:'未识别'})[item.customer_flag] || '未识别');
    detailRow(dl, '支付时间（北京时间）', timeText(item.paid_at));
    if (item.amount_conflict) node('p', item.order_usd_source === 'ES_candidate_export' ? 'Admin 与 ES 金额不一致，本次按 ES 金额筛选；请复核差异。' : 'Admin 与 ES 金额不一致，列表按 Admin 优先；请复核差异。', card, 'error');
    const actions = node('div', undefined, card, 'actions');
    const add = node('button', '加入持续观察', actions, 'fs-btn fs-btn--primary'); add.type = 'button';
    const verified = item.identity_status === 'verified' && typeof item.email === 'string' && item.email.includes('@');
    add.disabled = !verified || !idPattern.test(item.candidate_id || '');
    if (!verified) node('span', identityReason(item.identity_reason), actions, 'error');
    add.onclick = async () => { const result = await write('track', {candidate_id:item.candidate_id}, add); if (result?.state === 'tracked') { setStatus('已加入持续观察；首次付款日为第1天，每天更新状态；报告需手动生成。'); await loadTracked();loadPoolReports(); } };
  }
  function rangeDays(start, end) {
    const valid = value => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value+'T00:00:00Z')) && new Date(value+'T00:00:00Z').toISOString().slice(0,10) === value;
    if (!valid(start) || !valid(end)) throw Error('请选择有效的开始和结束日期。');
    const first=Date.parse(start+'T00:00:00Z'), last=Date.parse(end+'T00:00:00Z');
    if (last < first) throw Error('结束日期不能早于开始日期。');
    if ((last-first)/86400000 >= 93) throw Error('每次最多查看 93 天，请缩小日期区间。');
    const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(Date.now());
    const field=type=>today.find(part=>part.type===type).value;
    if(end>field('year')+'-'+field('month')+'-'+field('day')) throw Error('不能查询未来日期。');
    const days=[];for(let day=first;day<=last;day+=86400000)days.push(new Date(day).toISOString().slice(0,10));return days;
  }
  function selectedDays() { return rangeDays($('candidate-date').value,$('candidate-end').value); }
  function renderRange(results, days) {
    const host=$('candidate-list'), items=new Map();host.replaceChildren();
    const ready=[], pending=[], missing=[], partial=[];
    for(const day of days){
      const value=results.get(day);
      if(!value){pending.push(day);continue;}
      if(value.status==='available')ready.push(day);
      else if(value.status==='pending')pending.push(day);
      else if(value.status==='partial')partial.push(day);
      else missing.push(day);
      if(['available','partial'].includes(value.status))for(const item of value.items||[]){
        const buyer=item.identity_status==='verified' && item.es_identity?.status==='verified' && item.es_identity.buyer_id;
        const key=buyer ? 'buyer:'+item.site_id+':'+buyer+':'+item.email : 'order:'+(item.order_no||item.candidate_id);
        if(key&&!items.has(key))items.set(key,item);
      }
    }
    const captured=[...results.values()].map(v=>v.captured_at).filter(Boolean).sort();
    $('candidate-meta').textContent=days[0]+' 至 '+days[days.length-1]+'（北京时间，含首尾） · 已取得 '+ready.length+'/'+days.length+' 天 · 去重后 '+items.size+' 位候选客户'+(captured.length?' · 归档时间 '+timeText(captured[0])+' ～ '+timeText(captured[captured.length-1]):'');
    if(pending.length)node('p','正在读取或整理：'+pending.join('、')+'。已取得的名单先展示，完成后自动更新。',host,'empty');
    if(missing.length)node('p','以下日期未取得，不能当作零订单：'+missing.join('、')+'。可点击“扫描所选区间”补充读取。',host,'error');
    if(partial.length)node('p','以下日期覆盖不完整：'+partial.join('、')+'；当前名单不代表完整区间。',host,'error');
    if(!items.size&&ready.length===days.length)node('p','该区间没有符合当前条件的客户。',host,'empty');
    for(const item of [...items.values()].sort((a,b)=>String(b.paid_at||'').localeCompare(String(a.paid_at||''))))candidateCard(item);
  }
  async function loadCandidates(date, end=$('candidate-end').value) {
    let days;try{days=rangeDays(date,end);}catch(error){setStatus(error.message,true);return;}
    setStatus('正在读取所选日期区间；未取得的日期会单独提示。');
    const epoch=++candidateEpoch;candidateAbort?.abort();candidateAbort=new AbortController();
    const signal=candidateAbort.signal, results=new Map(), version=config?.version;
    const host=$('candidate-list');host.replaceChildren();node('p','正在读取所选区间名单…',host,'empty');
    $('candidate-meta').textContent=date+' 至 '+end+' · 正在读取 0/'+days.length+' 天';
    const deadline=Date.now()+10*60*1000;
    try {
      let todo=days;
      while(todo.length&&!signal.aborted&&!disposed){
        for(const day of todo){
          const value=await get('candidates',{day},signal);
          if(epoch!==candidateEpoch||signal.aborted||disposed)return;
          if(value.config_version!==undefined&&value.config_version!==version)throw Error('筛选条件已更新，请重新读取区间。');
          if(!states.has(value.status)&&value.status!=='failed')throw Error('名单状态异常。');
          results.set(day,value);renderRange(results,days);
        }
        todo=days.filter(day=>results.get(day)?.status==='pending');
        if(!todo.length)break;
        if(Date.now()>=deadline){node('p','后台仍在整理，稍后查看同一区间即可继续读取。',host,'empty');break;}
        await new Promise((resolve,reject)=>{const done=()=>{signal.removeEventListener('abort',abort);resolve();};const timer=setTimeout(done,5000);const abort=()=>{clearTimeout(timer);reject(Error('aborted'));};signal.addEventListener('abort',abort,{once:true});});
      }
    }catch(error){if(signal.aborted||epoch!==candidateEpoch)return;if(error.status===403){denied();return;}node('p','区间读取未完成：'+error.message+'；以上仅为已取得的部分。',host,'error');}
  }
  async function scanRange() {
    if(pendingWrite){await reconcile();return;}
    let days;try{days=selectedDays();}catch(error){setStatus(error.message,true);return;}
    candidateAbort?.abort();++candidateEpoch;
    const button=$('scan-day');button.disabled=true;
    const controls=[...$('date-form').elements];controls.forEach(control=>control.disabled=true);
    let completed=0;
    try {
      for(const day of days){
        setStatus('正在补充区间名单 '+(completed+1)+'/'+days.length+'：'+day+'；已完成的归档会复用。');
        const existing=await get('candidates',{day});
        if(existing.status!=='available'&&existing.status!=='pending'){
          const result=await write('scan',{day},button);
          button.disabled=true;
          if(!result){setStatus('区间扫描停在 '+day+'，后续日期尚未提交；请先核对操作状态。',true);return;}
        }
        completed++;
      }
      setStatus('区间扫描已提交或复用 '+completed+' 天，名单整理完成后自动显示。');
      void loadCandidates(days[0],days[days.length-1]);
    }catch(error){if(error.status===403){denied();return;}setStatus('扫描未完成：'+error.message+'；已提交的日期不会自动重放。',true);}
    finally{controls.forEach(control=>control.disabled=false);button.disabled=!!pendingWrite;}
  }
  async function loadTracked() {
    const host = $('tracked-list'); host.replaceChildren(); node('p', '正在读取观察名单…', host, 'empty');
    try {
      const value = await get('tracked');
      host.replaceChildren();
      if (!Array.isArray(value.items) || !value.items.length) { node('p', '尚无人工加入的持续观察对象。', host, 'empty'); return; }
      for (const item of value.items) {
        const card = node('article', undefined, host, 'record');
        node('h3', asText(item.email), card);
        const dl = node('dl', undefined, card);
        detailRow(dl, '客户身份', uidText(item.uid)); detailRow(dl, '加入时间（北京时间）', timeText(item.tracked_at)); detailRow(dl, '状态', trackingStatus(item.status));
        detailRow(dl, '首次付款（北京时间）', item.first_paid_status === 'verified' ? timeText(item.first_paid_at) : '待核实完整历史');
        detailRow(dl, '生命周期', item.lifecycle_day ? '第 '+item.lifecycle_day+' 天 · '+item.phase : '首付日期待核实');
        detailRow(dl, '最近数据更新', timeText(item.history_observed_at));
        detailRow(dl, '客户编号（报告对应）', item.tracking_id);
        if (item.status === 'active') {
          const stop = node('button','停止追踪',card,'fs-btn'); stop.type='button';
          stop.onclick=()=>{
            stop.disabled=true;const box=node('div',undefined,card,'actions');node('span','停止后不再每日更新，也不进入之后生成的追踪池报告；历史保留。',box);
            const confirm=node('button','确认停止',box,'fs-btn');confirm.type='button';
            const cancel=node('button','取消',box,'fs-btn');cancel.type='button';cancel.onclick=()=>{box.remove();stop.disabled=false;};
            confirm.onclick=async()=>{cancel.disabled=true;const result=await write('stop',{tracking_id:item.tracking_id},confirm);if(result?.state==='stopped'){setStatus('已停止追踪，历史记录保留。');await loadTracked();loadPoolReports();if(chosen===item.tracking_id)await loadDetail(chosen,{interactive:true});}else cancel.disabled=false;};
          };
        }
        const button = node('button', '查看订单与节点', card, 'fs-btn'); button.type = 'button';
        button.disabled = !idPattern.test(item.tracking_id || '');
        button.dataset.detailId = item.tracking_id;
        button.setAttribute('aria-controls', 'detail-section');
        button.onclick = () => loadDetail(item.tracking_id, {interactive:true});
      }
    } catch (error) { if (error.status === 403) { denied(); return; } host.replaceChildren(); node('p', '观察名单读取失败：' + error.message, host, 'error'); }
  }
  function detailFeedback(id, state, message) {
    const section = $('detail-section');
    section.dataset.state = state;
    section.setAttribute('aria-busy', String(state === 'loading'));
    let status = $('detail-feedback');
    if (!status) {
      status = document.createElement('p'); status.id = 'detail-feedback';
      status.className = 'detail-feedback'; status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite'); section.insertBefore(status, $('detail'));
    }
    status.textContent = message;
    $('tracked-list').querySelectorAll('[data-detail-id]').forEach(button => {
      const selected = button.dataset.detailId === id;
      button.setAttribute('aria-expanded', String(selected));
      button.setAttribute('aria-busy', String(selected && state === 'loading'));
      button.closest('.record')?.classList.toggle('detail-selected', selected);
      button.disabled = selected && state === 'loading';
      button.textContent = selected ? state === 'loading' ? '正在加载订单与节点…' : state === 'error' ? '重试查看订单与节点' : '正在查看 · 订单与节点' : '查看订单与节点';
    });
    $('refresh-detail').disabled = state === 'loading';
  }
  function focusDetail() {
    const section = $('detail-section'); section.tabIndex = -1;
    section.focus({preventScroll:true});
    section.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',block:'start'});
  }
  async function loadDetail(id, {interactive = false} = {}) {
    if (!idPattern.test(id || '')) return;
    const sameDetail = chosen === id;
    if (interactive && sameDetail && detailLoading) { focusDetail(); return; }
    if (!sameDetail) detailPollStarted = Date.now();
    chosen = id;
    clearTimeout(detailTimer);
    const epoch = ++detailEpoch;
    detailAbort?.abort(); detailAbort = new AbortController();
    const controller = detailAbort; detailLoading = true;
    $('detail-section').hidden = false;
    const host = $('detail'); if (!sameDetail || !host.childElementCount) { host.replaceChildren(); node('p', '正在读取观察详情…', host, 'empty'); }
    if (interactive) { detailFeedback(id, 'loading', '正在读取该客户的订单与观察节点，请稍候…'); focusDetail(); }
    try {
      const value = await get('detail', {id}, controller.signal);
      if (epoch !== detailEpoch || chosen !== id) return;
      host.replaceChildren();
      const summary = node('div', undefined, host, 'record');
      node('h3', asText(value.email), summary);
      const dl = node('dl', undefined, summary);
      detailRow(dl, '客户身份', uidText(value.uid)); detailRow(dl, '加入时间（北京时间）', timeText(value.tracked_at));
      detailRow(dl,'首次付款（北京时间）',value.first_paid_status==='verified'?timeText(value.first_paid_at):'待核实完整历史');
      detailRow(dl,'生命周期',value.lifecycle_day?'第 '+value.lifecycle_day+' 天 · '+value.phase:'首付日期待核实');
      detailRow(dl,'追踪状态',trackingStatus(value.status));
      node('p',value.clock_rule || '首次付款日为第1天；阶段到达不会自动生成单人报告。',summary,'muted');
      const stages=node('div',undefined,host,'record');node('h3','7／14／30天阶段',stages);
      for(const marker of value.stage_markers||[])node('p','第 '+marker.days+' 天：'+(marker.reached===null?'待核实':marker.reached?'已达到':'未达到')+(marker.date?' · '+marker.date:''),stages);
      if (value.history_status === 'stopped') node('p','已停止每日更新，以下为保留的历史快照。',summary,'muted');
      if (value.history_status === 'pending') node('p', '历史订单正在整理，页面会自动复查；当前明细可能不完整。', summary, 'muted');
      else if (value.history_coverage && value.history_coverage.complete !== true) node('p', '历史订单覆盖尚未完整，请勿将下列订单当作客户全部记录。', summary, 'error');
      const orders = node('section', undefined, host); node('h3', '订单状态变化', orders);
      if (!Array.isArray(value.orders) || !value.orders.length) node('p', '暂无可核实订单。', orders, 'empty');
      else { const wrap = node('div', undefined, orders, 'table-wrap'), table = node('table', undefined, wrap), head = node('thead', undefined, table), row = node('tr', undefined, head); for (const text of ['订单号','支付时间（北京时间）','订单金额','折扣','状态']) node('th', text, row); const body = node('tbody', undefined, table); for (const order of value.orders) { const r = node('tr', undefined, body); for (const text of [asText(order.order_no),timeText(order.paid_at),money(order.order_usd),money(order.discount_usd),orderStatus(order.status)]) node('td', text, r); } }
      const milestoneHost = node('section', undefined, host); node('h3', '历史单人报告（已退役，不再自动生成）', milestoneHost);
      for (const milestone of (value.milestones || []).filter(item=>item.state!=='cancelled')) {
        const card = node('article', undefined, milestoneHost, 'record');
        const originalReady = milestone.state === 'completed' && idPattern.test(milestone.conversation_id || '') && idPattern.test(milestone.artifact_id || '');
        const stateLabel = milestone.state === 'completed' ? originalReady ? '完整 HTML 原稿已就绪' : '已完成，原稿待核对' : milestone.state === 'needs_review' ? milestone.turn_id ? '需复核：已有模型输出，但完整 HTML 原稿未就绪' : '任务结果需人工核对，报告未完成' : milestone.days === 0 && milestone.state === 'scheduled' ? '首次建议待派发' : ({scheduled:'待到期',claimed:'已领取分析任务',creating:'正在建立会话',dispatch_unknown:'派发结果待核对',pending:'正在生成建议',preparing:'正在准备证据',running:'Hermes 正在分析',failed:'生成失败'})[milestone.state] || asText(milestone.state);
        node('h3', (milestone.days === 0 ? '首次维护建议' : '旧规则：加入后第 ' + milestone.days + ' 天') + ' · ' + stateLabel, card);
        node('p', '到期时间（北京时间）：' + timeText(milestone.due_at), card, 'muted');
        if (milestone.summary || milestone.advice) node('p', milestone.summary || milestone.advice, card);
        if (originalReady) {
          const link = node('a', '打开 Hermes 报告原稿 ↗', card);
          link.href = '/api/hermes/conversations/' + encodeURIComponent(milestone.conversation_id) + '/artifacts/' + encodeURIComponent(milestone.artifact_id) + '?view=1';
          link.target = '_blank'; link.rel = 'noopener noreferrer';
        } else if (idPattern.test(milestone.conversation_id || '')) {
          const link = node('a', '查看 Hermes 建议 ↗', card);
          link.href = '/dashboard/fs-home/hermes/conversation/?conversation=' + encodeURIComponent(milestone.conversation_id);
          link.target = '_blank'; link.rel = 'noopener noreferrer';
        }
      }
      detailFeedback(id, 'ready', value.history_status === 'pending' ? '详情已打开，历史订单仍在整理，稍后自动更新。' : '订单与观察节点已加载；下方保留各节点的实际状态。');
      if (interactive) focusDetail();
      if (value.history_status === 'pending' && value.status === 'active' && !document.hidden && Date.now()-detailPollStarted<10*60*1000) detailTimer=setTimeout(()=>{if(chosen===id)loadDetail(id);},5000);
    } catch (error) { if (controller.signal.aborted || epoch !== detailEpoch) return; if (error.status === 403) { denied(); return; } host.replaceChildren(); node('p', '详情读取失败：' + error.message, host, 'error'); detailFeedback(id, 'error', '读取失败，请点击“刷新观察”重试。'); }
    finally { if (epoch === detailEpoch) { detailLoading = false; if (controller.signal.aborted) detailFeedback(id, 'idle', '读取已中断，可重新查看。'); } }
  }
  let poolTimer=null;
  async function loadPoolReports(){
    clearTimeout(poolTimer);const host=$('pool-reports');
    try{
      const result=await get('pool_reports');host.replaceChildren();
      if(!result.items?.length)node('p','尚无全局追踪报告。需要分析时点击“生成追踪报告”。',host,'empty');
      let pending=false;
      for(const item of result.items||[]){
        const card=node('article',undefined,host,'record');const labels={creating:'正在创建',dispatch_unknown:'派发待核对',queued:'排队中',pending:'生成中',running:'分析中',completed:'已完成',failed:'失败',needs_review:'待复核',cancelled:'已取消',interrupted:'已中断'};
        node('h3',timeText(item.created_at)+' · '+(labels[item.state]||item.state),card);node('p','生成时活跃追踪池：'+item.customer_count+' 位客户',card,'muted');
        if(idPattern.test(item.conversation_id||'')){
          const link=node('a',item.state==='completed'&&idPattern.test(item.artifact_id||'')?'打开／下载完整追踪报告 ↗':'查看生成进度 ↗',card);
          link.href=item.state==='completed'&&idPattern.test(item.artifact_id||'')?'/api/hermes/conversations/'+item.conversation_id+'/artifacts/'+item.artifact_id+'?view=1':'/dashboard/fs-home/hermes/conversation/?conversation='+item.conversation_id;
          link.target='_blank';link.rel='noopener noreferrer';
        }
        if(['creating','dispatch_unknown','queued','pending','running'].includes(item.state))pending=true;
      }
      $('generate-pool').disabled=pending||!!pendingWrite;
      if(pending&&!document.hidden&&!disposed)poolTimer=setTimeout(loadPoolReports,5000);
    }catch(error){if(error.status===403){denied();return;}host.replaceChildren();node('p','追踪报告列表读取失败：'+error.message,host,'error');}
  }
  $('generate-pool').onclick=async()=>{const button=$('generate-pool');button.textContent='正在提交追踪池分析…';const result=await write('generate_pool',{},button);button.textContent='生成追踪报告';if(result){setStatus('已提交全局追踪池分析，可在下方查看进度。');await loadPoolReports();}};
  $('refresh-pool').onclick=loadPoolReports;
  function shanghaiDay(at = Date.now()) { const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(at); const field = type => parts.find(part => part.type === type)?.value; return field('year') + '-' + field('month') + '-' + field('day'); }

  let vipAbort = null, vipEditor = null, vipItems = [];
  const vipStatuses = {queued:'待领取',assigned:'已领取',contacted:'已联系',closed:'已结案',returned:'已回购'};
  const vipPriorities = {after_sales:'售后优先',due:'到期复核',review:'优先维护'};
  const vipEvents = {claim:'领取',contacted:'联系',feedback:'反馈',close:'结案'};
  const vipReasons = {early_stock:'已提前备货',game_demand:'游戏需求变化',platform_change:'更换平台',price:'价格',
    payment:'支付',fulfillment:'交付或售后',no_reply:'未回复',resolved:'维护完成',no_contact:'无需联系',other:'其他'};
  const dayOffset = (day, offset) => new Date(Date.parse(day + 'T00:00:00Z') + offset * 86400000).toISOString().slice(0,10);
  function weekMonday(day) {
    const date = new Date(day + 'T00:00:00Z');
    return dayOffset(day, -((date.getUTCDay() + 6) % 7));
  }
  const currentWeek = () => weekMonday(shanghaiDay());
  function clearVip(resetFilters = false) {
    vipAbort?.abort();
    vipEditor = null;
    vipItems = [];
    $('vip-tools').hidden = true;
    $('vip-list-count').textContent = '';
    $('vip-performance-link').hidden = true;
    if (resetFilters) {
      $('vip-search').value = '';
      $('vip-filter').value = 'all';
    }
    $('vip-list').replaceChildren();
    $('vip-metrics').replaceChildren();
    $('vip-performance').hidden = true;
  }
  function updateVipState(text, state) {
    $('vip-state').textContent = text;
    $('vip-state').dataset.state = state;
    $('vip-list').setAttribute('aria-busy', String(state === 'loading'));
  }
  function vipRowValue(host, text, small = false) {
    return node('p', text, host, small ? 'vip-line vip-small' : 'vip-line');
  }
  function vipPill(host, text, tone) {
    const pill = node('span', text, host, 'vip-pill');
    pill.dataset.tone = tone;
  }
  function vipOutcome(item) {
    const outcome = item.outcome;
    if (outcome?.kind === 'natural') return '联系前回购 · ' + money(outcome.paid_usd);
    if (outcome?.kind === 'post_contact') return '联系后回购 · ' + money(outcome.paid_usd);
    if (outcome?.status === 'immature') return '仍在复购观察期';
    if (outcome?.kind === 'no_return' && outcome.status === 'mature') return '观察期内未回购';
    return '回购待核实';
  }
  function recordVipEvents(row, item) {
    if (!item.events?.length) return;
    const details = node('details', undefined, row, 'vip-row-details');
    node('summary', '跟进记录（' + item.events.length + '）', details);
    const list = node('ol', undefined, details);
    for (const event of item.events) {
      const li = node('li', undefined, list);
      vipRowValue(li, (vipEvents[event.event] || '维护记录') + ' · ' + asText(event.actor) + ' · ' + timeText(event.contacted_at || event.at), true);
      if (event.reason) vipRowValue(li, vipReasons[event.reason] || event.reason);
      if (event.notes) vipRowValue(li, event.notes);
      if (event.next_review_day) vipRowValue(li, '下次复核 ' + event.next_review_day, true);
    }
  }
  function vipButton(host, text, accept, primary = false) {
    const button = node('button', text, host, primary ? 'fs-btn fs-btn--primary' : 'fs-btn');
    button.type = 'button';
    button.onclick = accept;
    return button;
  }
  function validVipReceipt(result, request) {
    return result?.status === 'recorded' && result.case_id === request.case_id &&
      result.event === request.event && result.request_id === request.request_id;
  }
  async function saveVipFeedback(item, fields, button, message) {
    if (pendingWrite) {
      await reconcile();
      return;
    }
    const result = await write('vip_feedback', {case_id:item.case_id,...fields}, button);
    if (!result) {
      message.textContent = $('status').textContent;
      if (pendingWrite?.action === 'vip_feedback') {
        const verify = vipButton(message.parentNode, '核对上次操作', reconcile);
        verify.focus();
      }
      return;
    }
    setStatus('已记录' + vipEvents[fields.event] + '。');
    await loadVip($('vip-week-date').value, item.case_id);
  }
  function editVip(row, item, event, origin) {
    if (writeInFlight) return;
    vipEditor?.remove();
    const form = node('form', undefined, row, 'vip-editor');
    vipEditor = form;
    node('h4', '记录' + vipEvents[event], form);
    const fields = node('div', undefined, form, 'vip-editor-fields');
    let contact, reason, review, notes;
    if (event === 'contacted') {
      contact = node('input', undefined, node('label', '实际联系时间（北京时间）', fields));
      contact.type = 'datetime-local';
      contact.required = true;
    }
    const isClose = event === 'close';
    reason = node('select', undefined, node('label', isClose ? '结案原因' : '反馈原因（可选）', fields));
    if (!isClose) node('option', '选择原因', reason).value = '';
    const keys = isClose ? ['resolved','no_contact','other'] : Object.keys(vipReasons).filter(key => key !== 'no_contact');
    for (const value of keys) node('option', vipReasons[value], reason).value = value;
    if (!isClose) {
      review = node('input', undefined, node('label', '下次复核（可选）', fields));
      review.type = 'date';
      review.value = item.next_review_day || '';
    }
    notes = node('textarea', undefined, node('label', '维护反馈（可选）', fields));
    notes.rows = 2;
    notes.maxLength = 1000;
    const actions = node('div', undefined, form, 'vip-ops');
    const save = vipButton(actions, '保存' + vipEvents[event], null, true);
    save.type = 'submit';
    const cancel = vipButton(actions, '取消', () => {
      form.remove();
      vipEditor = null;
      origin.focus();
    });
    const message = node('p', '', form, 'vip-state');
    message.setAttribute('role', 'status');
    form.onsubmit = async action => {
      action.preventDefault();
      if (writeInFlight) return;
      const text = notes.value.trim();
      if (event === 'feedback' && !reason.value && !text && (!review.value || review.value === item.next_review_day)) {
        message.textContent = '请选择原因、填写反馈或修改下次复核日期。';
        return;
      }
      const update = {event};
      if (contact) update.contacted_at = contact.value + ':00+08:00';
      if (reason.value) update.reason = reason.value;
      if (review?.value) update.next_review_day = review.value;
      if (text) update.notes = text;
      cancel.disabled = true;
      message.textContent = '正在保存…';
      try { await saveVipFeedback(item, update, save, message); }
      finally { cancel.disabled = false; }
    };
    (contact || reason).focus();
  }
  function renderVipRow(list, item) {
    const row = node('li', undefined, list, 'vip-row');
    if (idPattern.test(item.case_id || '')) row.dataset.caseId = item.case_id;
    const main = node('div', undefined, row, 'vip-row-main');
    const person = node('div', undefined, main, 'vip-person');
    node('h3', item.email || '邮箱待核验', person);
    vipRowValue(person, uidText(item.uid), true);
    if (item.country) vipRowValue(person, item.country, true);
    if (item.last_paid_at) vipRowValue(person, '最近付款 ' + timeText(item.last_paid_at), true);

    const guidance = node('div', undefined, main);
    const priority = item.guidance?.priority;
    if (priority && vipPriorities[priority]) vipPill(guidance, vipPriorities[priority], priority === 'after_sales' ? 'warn' : 'info');
    vipRowValue(guidance, item.guidance?.reason || '优先理由待核实。');
    if (item.carried_over) vipRowValue(guidance, '上周延续', true);

    const progress = node('div', undefined, main, 'vip-progress');
    vipPill(progress, vipStatuses[item.status] || '状态待核实', item.status === 'returned' ? 'ok' : item.status === 'contacted' ? 'info' : '');
    vipRowValue(progress, vipOutcome(item));
    if (item.owner) vipRowValue(progress, '领取人 ' + item.owner, true);
    if (item.next_review_day) vipRowValue(progress, '下次复核 ' + item.next_review_day, true);

    const canAct = item.can_update && (item.status === 'queued' || (item.owner && item.status !== 'closed'));
    if (row.dataset.caseId && canAct) {
      const actions = node('div', undefined, row, 'vip-row-actions');
      if (item.status === 'queued') {
        const message = node('p', '', row, 'vip-state');
        message.setAttribute('role','status');
        const claim = vipButton(actions, '领取跟进', () => saveVipFeedback(item, {event:'claim'}, claim, message), true);
      } else {
        if (item.status === 'assigned') {
          const contact = vipButton(actions, '记录联系', () => editVip(row, item, 'contacted', contact), true);
        }
        const feedback = vipButton(actions, '填写反馈', () => editVip(row, item, 'feedback', feedback), item.status !== 'assigned');
        const close = vipButton(actions, '结案', () => editVip(row, item, 'close', close));
      }
    }
    recordVipEvents(row, item);
  }
  function renderVipPerformance(summary) {
    const host = $('vip-metrics');
    $('vip-performance').hidden = !summary;
    $('vip-performance-link').hidden = !summary;
    if (!summary) return;
    $('vip-performance-note').textContent = '按当周名单统计。自然回购包含联系前或从未联系的回购，联系后回购按已付款订单时间核对。';
    const metrics = node('dl', undefined, host, 'vip-metric-grid');
    for (const [label,count,amount] of [
      ['本周名单', summary.people], ['已联系', summary.contacted_people],
      ['联系前回购', summary.natural_people, summary.natural_usd],
      ['联系后回购', summary.post_contact_people, summary.post_contact_usd],
    ]) {
      const metric = node('div', undefined, metrics, 'vip-metric');
      node('dt', label, metric);
      node('dd', Number.isInteger(count) ? count + ' 人' : '待核实', metric, 'vip-metric-number');
      if (amount !== undefined) node('dd', amount === null ? '金额待核实' : money(amount), metric, 'vip-small');
    }
    if (Number.isInteger(summary.people) && summary.people > 0) {
      const chart = node('div', undefined, host, 'vip-bars');
      node('h3', '本周名单中的已确认占比', chart);
      for (const [label,count] of [['已联系',summary.contacted_people],['联系前回购',summary.natural_people],['联系后回购',summary.post_contact_people]]) {
        if (!Number.isInteger(count) || count < 0 || count > summary.people) continue;
        const bar = node('label', undefined, chart, 'vip-bar');
        node('span', label, bar);
        const meter = node('meter', undefined, bar);
        meter.max = summary.people;
        meter.value = count;
        node('span', count + ' / ' + summary.people, bar);
      }
    }
    const pending = [Number.isInteger(summary.immature_people) ? summary.immature_people + ' 人观察期未满' : '',
      Number.isInteger(summary.unknown_people) ? summary.unknown_people + ' 人结果待核实' : ''].filter(Boolean);
    if (pending.length) node('p', pending.join(' · '), host, 'vip-small');
    const cohort = [Number.isInteger(summary.new_people) ? summary.new_people + ' 人本周新增' : '',
      Number.isInteger(summary.carried_people) ? summary.carried_people + ' 人上周延续' : '',
      Number.isInteger(summary.closed_people) ? summary.closed_people + ' 人已结案' : ''].filter(Boolean);
    if (cohort.length) node('p', cohort.join(' · '), host, 'vip-small');
  }
  function vipHistory(item) {
    return ['returned','closed'].includes(item.status) || ['natural','post_contact'].includes(item.outcome?.kind);
  }
  function vipNeedsFeedback(item) {
    return item.status === 'contacted' &&
      item.events?.findLast(event => ['contacted','feedback'].includes(event.event))?.event === 'contacted';
  }
  function paginateVipRows(host, rows, focusCase) {
    const list = node('ol', undefined, host, 'vip-rows');
    let shown = 0;
    const append = count => {
      for (const item of rows.slice(shown, shown + count)) renderVipRow(list, item);
      shown = Math.min(shown + count, rows.length);
    };
    const activeIndex = rows.findIndex(item => item.case_id === focusCase);
    append(Math.max(8, activeIndex + 1));
    if (shown >= rows.length) return;
    const more = vipButton(host, '显示更多（剩 ' + (rows.length - shown) + ' 人）', () => {
      const firstNew = shown;
      append(8);
      const row = list.children[firstNew];
      row.tabIndex = -1;
      row.focus();
      if (shown >= rows.length) more.remove();
      else more.textContent = '显示更多（剩 ' + (rows.length - shown) + ' 人）';
    });
    more.classList.add('vip-more');
  }
  function renderVipList(focusCase) {
    const host = $('vip-list');
    vipEditor = null;
    host.replaceChildren();
    const search = $('vip-search').value.trim().toLowerCase();
    const filter = $('vip-filter').value;
    const active = [], regular = [], history = [];
    for (const item of vipItems) {
      if (vipHistory(item)) history.push(item);
      else if (item.guidance?.priority === 'review' && item.status === 'queued') regular.push(item);
      else active.push(item);
    }
    const count = active.filter(item => ['after_sales','due'].includes(item.guidance?.priority) &&
      (item.status !== 'contacted' || vipNeedsFeedback(item))).length;
    const visible = vipItems.filter(item => {
      if (search && !String(item.email || '').toLowerCase().includes(search) &&
          (item.uid == null || !String(item.uid).includes(search))) return false;
      if (filter === 'queued') return item.status === 'queued' && !vipHistory(item);
      if (filter === 'mine') return !!item.owner && item.can_update && !vipHistory(item);
      if (filter === 'needs_feedback') return vipNeedsFeedback(item) && !vipHistory(item);
      return true;
    });
    const filtered = search || filter !== 'all';
    $('vip-list-count').textContent = '优先待跟进 ' + count + ' 人 · 本周名单 ' + vipItems.length +
      ' 人' + (filtered ? ' · 找到 ' + visible.length + ' 人' : '');
    if (!visible.length) {
      node('p', '没有符合当前搜索和筛选的客户。', host, 'empty');
      return;
    }
    if (filtered || active.length || regular.length) {
      const columns = node('div', undefined, host, 'vip-row-main vip-columns');
      columns.setAttribute('aria-hidden','true');
      for (const label of ['客户','优先依据','跟进与回购']) node('span', label, columns);
    }
    if (filtered) {
      paginateVipRows(host, visible, focusCase);
      return;
    }
    function foldRows(label, rows) {
      if (!rows.length) return;
      const fold = node('details', undefined, host, 'vip-group');
      fold.open = rows.some(item => item.case_id === focusCase);
      node('summary', label + '（' + rows.length + '）', fold);
      paginateVipRows(fold, rows, focusCase);
    }
    if (active.length) {
      paginateVipRows(host, active, focusCase);
      foldRows('常规维护', regular);
    } else if (regular.length) paginateVipRows(host, regular, focusCase);
    else node('p', '当周待跟进事项已处理。', host, 'empty');
    foldRows('已回购与已结案', history);
  }
  async function loadVip(week = currentWeek(), focusCase = null) {
    if (!config || disposed || document.hidden) return;
    const form = $('vip-week-form');
    const date = $('vip-week-date');
    date.max = currentWeek();
    week = weekMonday(week);
    date.value = week;
    $('vip-week-next').disabled = week >= currentWeek();
    $('vip-title').textContent = week === currentWeek() ? '本周优先跟进' : '当周优先跟进';
    $('vip-week-label').textContent = week + ' 至 ' + dayOffset(week, 6) + '（北京时间）';
    clearVip();
    updateVipState('正在读取维护名单…', 'loading');
    const controller = new AbortController();
    vipAbort = controller;
    try {
      const result = await get('vip_week', {week}, controller.signal);
      if (controller.signal.aborted || !config) return;
      const host = $('vip-list');
      if (result.week !== week || !Array.isArray(result.items)) throw Error('名单日期或格式异常。');
      const partial = result.status !== 'ready';
      const updated = result.as_of || result.coverage?.as_of;
      const freshness = updated ? '最近更新 ' + timeText(updated) + '（北京时间）' : result.frozen_at ? '名单生成 ' + timeText(result.frozen_at) + '（北京时间）' : '';
      const notes = [];
      if (partial) notes.push(result.status === 'pending' ? '本周名单尚在准备。' : '本周数据部分可用，名单或回购结果可能不完整。');
      if (freshness) notes.push(freshness);
      updateVipState(notes.join(' '), partial ? 'partial' : 'ready');
      if (result.items.length) {
        vipItems = result.items;
        $('vip-tools').hidden = false;
        renderVipList(focusCase);
      } else {
        node('p', partial ? '暂无可确认的维护客户，可稍后点击“查看”刷新。' : '本周暂无需要维护的客户。', host, 'empty');
      }
      renderVipPerformance(result.summary);
      if (focusCase && idPattern.test(focusCase)) {
        const row = host.querySelector('[data-case-id="' + focusCase + '"]');
        if (row) { row.tabIndex = -1; row.focus(); } else ($('vip-tools').hidden ? form.querySelector('[type="submit"]') : $('vip-search')).focus();
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error.status === 403) { denied(); return; }
      updateVipState('维护名单读取失败，请点击“查看”重试。', 'error');
    }
  }
  function loadLegacy() {
    if (!config || !$('legacy-tools').open) return;
    loadCandidates($('candidate-date').value);
    loadTracked();
    loadPoolReports();
  }
  function onPrivateVisible() {
    loadConfig().then(() => {
      if (!config || document.hidden || disposed) return;
      if (pendingWrite) reconcile();
      loadVip($('vip-week-date').value || currentWeek());
      loadLegacy();
    });
  }
  $('vip-week-form').onsubmit = event => { event.preventDefault(); loadVip($('vip-week-date').value); };
  $('vip-week-prev').onclick = () => loadVip(dayOffset($('vip-week-date').value || currentWeek(), -7));
  $('vip-week-next').onclick = () => loadVip(dayOffset($('vip-week-date').value || currentWeek(), 7));
  $('vip-search').oninput = () => renderVipList();
  $('vip-filter').onchange = () => renderVipList();
  $('legacy-tools').ontoggle = loadLegacy;
  $('theme').value = window.FSTheme?.get() || 'system';
  $('theme').onchange = () => window.FSTheme?.set($('theme').value);
  $('candidate-date').value = shanghaiDay(Date.now() - 86400000);
  $('candidate-end').value = $('candidate-date').value;
  $('config-form').onsubmit = async event => { event.preventDefault(); if (!config || pendingWrite) { await reconcile(); return; } let next; try { next = readForm(); } catch (error) { $('config-state').textContent = error.message; return; } $('config-state').textContent = '正在保存…'; const result = await write('save_config', {config:next,expected_version:config.version}, $('save-config')); if (result) { await loadConfig(); $('config-state').textContent = '条件已保存。'; } };
  $('date-form').onsubmit = async event => { event.preventDefault(); await loadCandidates($('candidate-date').value); };
  $('scan-day').onclick = scanRange;
  $('refresh-tracked').onclick = loadTracked;
  $('reconcile-write').onclick = reconcile;
  $('refresh-detail').onclick = () => { if (chosen) loadDetail(chosen, {interactive:true}); };
  function clearVisibleData() {
    clearVip(true);
    clearTimeout(poolTimer);
    candidateAbort?.abort();
    detailAbort?.abort();
    clearTimeout(detailTimer);
    $('candidate-list').replaceChildren();
    $('tracked-list').replaceChildren();
    $('detail').replaceChildren();
    $('detail-section').hidden = true;
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) clearVisibleData(); else onPrivateVisible();
  });
  window.addEventListener('pageshow', event => { if (event.persisted) { disposed = false; onPrivateVisible(); } });
  window.addEventListener('pagehide', () => { disposed = true; clearVisibleData(); });
  onPrivateVisible();
})();
