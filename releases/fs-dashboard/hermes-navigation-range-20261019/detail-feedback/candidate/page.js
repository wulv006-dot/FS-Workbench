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
  const identityReason = value => ({email_missing_or_invalid:'客户邮箱缺失或格式异常，不能加入观察。',customer_email_conflict:'同一订单的客户邮箱不一致，请先核对。',order_no_unmatched:'订单未在 Admin 中核对，不能加入观察。',admin_scope_mismatch:'订单游戏、站点或支付状态未通过核对。'})[value] || '客户身份尚未核实，不能加入观察。';
  const trackingStatus = value => ({active:'观察中',paused:'已暂停',closed:'已结束'})[value] || asText(value);
  const orderStatus = value => ({paid:'已付款',completed:'已完成',pending:'待处理',processing:'处理中',refunded:'已退款',cancelled:'已取消'})[value] || asText(value);
  const requestId = () => crypto.randomUUID().replaceAll('-', '');
  const setStatus = (text, error = false) => { $('status').textContent = text; $('status').dataset.state = error ? 'error' : 'normal'; $('reconcile-write').hidden = !pendingWrite; };
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
  const clearPrivate = () => { candidateAbort?.abort(); detailAbort?.abort(); clearTimeout(detailTimer); $('candidate-list').replaceChildren(); $('tracked-list').replaceChildren(); $('detail').replaceChildren(); $('detail-section').hidden = true; $('app').hidden = true; };
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
    if (!pendingWrite) return;
    try {
      const value = await get('request', {request_id:pendingWrite.request_id});
      if (value.status === 'unknown') { setStatus('上次操作仍需服务端核对。请勿重复提交。', true); return; }
      if (value.status !== 'available' || value.action !== pendingWrite.action) throw Error('操作回执不匹配，请人工核对。');
      const action = pendingWrite.action;
      pendingWrite = null;
      $('save-config').disabled = false;
      setStatus('上次' + ({save_config:'配置保存',scan:'名单扫描',track:'加入观察'}[action] || '操作') + '已核实。');
      if (action === 'save_config') await loadConfig();
      if (action === 'track') await loadTracked();
      if (action === 'scan') await loadCandidates($('candidate-date').value);
      $('scan-day').disabled = false;
    } catch (error) { if (error.status === 403) { denied(); return; } setStatus('上次操作仍需核对：' + error.message, true); }
  }
  async function write(action, fields, button) {
    if (pendingWrite) { await reconcile(); return null; }
    const body = {...fields,request_id:requestId()};
    button.disabled = true;
    try {
      const result = await post(action, body);
      if (result.state === 'unknown' || result.status === 'unknown') { pendingWrite = {action,request_id:body.request_id}; setStatus('操作结果待核对，请勿重新发起。', true); return null; }
      return result;
    } catch (error) {
      if (error.status === 403) { denied(); return null; }
      if (!error.status || error.status >= 500) { pendingWrite = {action,request_id:body.request_id}; setStatus('连接中断，操作结果待核对。请勿重复提交。', true); }
      else setStatus('操作未接受：' + error.message, true);
      return null;
    } finally { button.disabled = !!pendingWrite; }
  }
  async function loadConfig() {
    try {
      const value = await get('config');
      renderConfig(value);
      $('app').hidden = false;
      setStatus('仅管理员可查看客户明细；名单与报告只供内部判断，不会联系客户或发券。');
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
    detailRow(dl, '金额来源', item.order_usd_source === 'Admin' ? 'Admin' : item.order_usd_source === 'Admin_ES_export' ? 'Admin 缺项，由 ES 订单补充' : item.order_usd_source);
    detailRow(dl, '折扣（USD）', money(item.discount_usd));
    detailRow(dl, '品类', item.product_type);
    detailRow(dl, '新老客', ({new:'新客',old:'老客',unknown:'未识别'})[item.customer_flag] || '未识别');
    detailRow(dl, '支付时间（北京时间）', timeText(item.paid_at));
    if (item.amount_conflict) node('p', 'Admin 与 ES 金额不一致，列表按 Admin 优先；请复核差异。', card, 'error');
    const actions = node('div', undefined, card, 'actions');
    const add = node('button', '加入持续观察', actions, 'fs-btn fs-btn--primary'); add.type = 'button';
    const verified = item.identity_status === 'verified' && typeof item.email === 'string' && item.email.includes('@');
    add.disabled = !verified || !idPattern.test(item.candidate_id || '');
    if (!verified) node('span', identityReason(item.identity_reason), actions, 'error');
    add.onclick = async () => { const result = await write('track', {candidate_id:item.candidate_id}, add); if (result?.state === 'tracked') { setStatus('已加入持续观察；7、14、30天节点从加入时间起算。'); await loadTracked(); } };
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
        const key=item.order_no||item.candidate_id;
        if(key&&!items.has(key))items.set(key,item);
      }
    }
    const captured=[...results.values()].map(v=>v.captured_at).filter(Boolean).sort();
    $('candidate-meta').textContent=days[0]+' 至 '+days[days.length-1]+'（北京时间，含首尾） · 已取得 '+ready.length+'/'+days.length+' 天 · 去重后 '+items.size+' 笔候选订单'+(captured.length?' · 归档时间 '+timeText(captured[0])+' ～ '+timeText(captured[captured.length-1]):'');
    if(pending.length)node('p','正在读取或整理：'+pending.join('、')+'。已取得的名单先展示，完成后自动更新。',host,'empty');
    if(missing.length)node('p','以下日期未取得，不能当作零订单：'+missing.join('、')+'。可点击“扫描所选区间”补充读取。',host,'error');
    if(partial.length)node('p','以下日期覆盖不完整：'+partial.join('、')+'；当前名单不代表完整区间。',host,'error');
    if(!items.size&&ready.length===days.length)node('p','该区间没有符合当前条件的订单。',host,'empty');
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
      if (value.history_status === 'pending') node('p', '历史订单正在整理，页面会自动复查；当前明细可能不完整。', summary, 'muted');
      else if (value.history_coverage && value.history_coverage.complete !== true) node('p', '历史订单覆盖尚未完整，请勿将下列订单当作客户全部记录。', summary, 'error');
      const orders = node('section', undefined, host); node('h3', '订单状态变化', orders);
      if (!Array.isArray(value.orders) || !value.orders.length) node('p', '暂无可核实订单。', orders, 'empty');
      else { const wrap = node('div', undefined, orders, 'table-wrap'), table = node('table', undefined, wrap), head = node('thead', undefined, table), row = node('tr', undefined, head); for (const text of ['订单号','支付时间（北京时间）','订单金额','折扣','状态']) node('th', text, row); const body = node('tbody', undefined, table); for (const order of value.orders) { const r = node('tr', undefined, body); for (const text of [asText(order.order_no),timeText(order.paid_at),money(order.order_usd),money(order.discount_usd),orderStatus(order.status)]) node('td', text, r); } }
      const milestoneHost = node('section', undefined, host); node('h3', '初始建议与7／14／30天观察节点', milestoneHost);
      for (const milestone of value.milestones || []) {
        const card = node('article', undefined, milestoneHost, 'record');
        const originalReady = milestone.state === 'completed' && idPattern.test(milestone.conversation_id || '') && idPattern.test(milestone.artifact_id || '');
        const stateLabel = milestone.state === 'completed' ? originalReady ? '完整 HTML 原稿已就绪' : '已完成，原稿待核对' : milestone.state === 'needs_review' ? milestone.turn_id ? '需复核：已有模型输出，但完整 HTML 原稿未就绪' : '任务结果需人工核对，报告未完成' : milestone.days === 0 && milestone.state === 'scheduled' ? '首次建议待派发' : ({scheduled:'待到期',claimed:'已领取分析任务',creating:'正在建立会话',dispatch_unknown:'派发结果待核对',pending:'正在生成建议',preparing:'正在准备证据',running:'Hermes 正在分析',failed:'生成失败'})[milestone.state] || asText(milestone.state);
        node('h3', (milestone.days === 0 ? '首次维护建议' : '加入后第 ' + milestone.days + ' 天') + ' · ' + stateLabel, card);
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
      const reportPending = (value.milestones || []).some(item => item.days === 0 && ['scheduled','claimed','creating','dispatch_unknown','pending','preparing','running'].includes(item.state));
      if ((value.history_status === 'pending' || reportPending) && !document.hidden && Date.now() - detailPollStarted < 10 * 60 * 1000) detailTimer = setTimeout(() => { if (chosen === id) loadDetail(id); }, 5000);
    } catch (error) { if (controller.signal.aborted || epoch !== detailEpoch) return; if (error.status === 403) { denied(); return; } host.replaceChildren(); node('p', '详情读取失败：' + error.message, host, 'error'); detailFeedback(id, 'error', '读取失败，请点击“刷新观察”重试。'); }
    finally { if (epoch === detailEpoch) { detailLoading = false; if (controller.signal.aborted) detailFeedback(id, 'idle', '读取已中断，可重新查看。'); } }
  }
  function shanghaiYesterday() { const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(Date.now() - 86400000); const field = type => parts.find(part => part.type === type)?.value; return field('year') + '-' + field('month') + '-' + field('day'); }
  $('theme').value = window.FSTheme?.get() || 'system';
  $('theme').onchange = () => window.FSTheme?.set($('theme').value);
  $('candidate-date').value = shanghaiYesterday();
  $('candidate-end').value = $('candidate-date').value;
  $('config-form').onsubmit = async event => { event.preventDefault(); if (!config || pendingWrite) { await reconcile(); return; } let next; try { next = readForm(); } catch (error) { $('config-state').textContent = error.message; return; } $('config-state').textContent = '正在保存…'; const result = await write('save_config', {config:next,expected_version:config.version}, $('save-config')); if (result) { await loadConfig(); $('config-state').textContent = '条件已保存。'; } };
  $('date-form').onsubmit = async event => { event.preventDefault(); await loadCandidates($('candidate-date').value); };
  $('scan-day').onclick = scanRange;
  $('refresh-tracked').onclick = loadTracked;
  $('reconcile-write').onclick = reconcile;
  $('refresh-detail').onclick = () => { if (chosen) loadDetail(chosen, {interactive:true}); };
  document.addEventListener('visibilitychange', () => { if (document.hidden) { candidateAbort?.abort(); detailAbort?.abort(); clearTimeout(detailTimer); $('candidate-list').replaceChildren(); $('tracked-list').replaceChildren(); $('detail').replaceChildren(); $('detail-section').hidden = true; } else { loadConfig().then(() => { if (config) { if (pendingWrite) reconcile(); loadCandidates($('candidate-date').value); loadTracked(); } }); } });
  window.addEventListener('pageshow', event => { if(event.persisted) { disposed=false; loadConfig().then(() => { if(config) { loadCandidates($('candidate-date').value); loadTracked(); } }); } });
  window.addEventListener('pagehide', () => { disposed = true; candidateAbort?.abort(); detailAbort?.abort(); clearTimeout(detailTimer); $('candidate-list').replaceChildren(); $('tracked-list').replaceChildren(); $('detail').replaceChildren(); });
  loadConfig().then(() => { if (config) { loadCandidates($('candidate-date').value); loadTracked(); } });
})();
