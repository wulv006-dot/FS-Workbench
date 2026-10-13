(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const gameSelect = byId('fsGame'), eventSelect = byId('fsEvent');
  const button = byId('fsInsightButton'), status = byId('fsInsightStatus');
  const output = byId('fsInsightText'), receipt = byId('fsInsightReceipt');
  const games = window.GAME_TIMELINE_DATA?.games || [];
  let identity = null, request = null, checking = null, revoked = false, pending = null, storageError = false;
  const recordKey = (user, data) => 'fs-game-insight-v1:' + encodeURIComponent(user) + ':' + encodeURIComponent(data);
  function saveRecord(record) {
    sessionStorage.setItem(recordKey(record.user, record.context), JSON.stringify(record));
  }
  function restoreRecord() {
    pending = null; storageError = false;
    if (!identity || !context()) return;
    try {
      const data = JSON.stringify(context()), raw = sessionStorage.getItem(recordKey(identity.user, data));
      if (!raw) return;
      const record = JSON.parse(raw);
      if (record.user !== identity.user || record.context !== data || typeof record.request_id !== 'string' || !/^[A-Za-z0-9_-]{8,80}$/.test(record.request_id) || !['unknown', 'pending'].includes(record.state) || !(record.job_id === null || typeof record.job_id === 'string' && record.job_id.length > 0 && record.job_id.length <= 200)) throw Error('invalid_record');
      pending = record;
    } catch { storageError = true; }
  }

  function context() {
    const game = games[Number(gameSelect.value)];
    const event = game?.events?.[Number(eventSelect.value)];
    if (!event || !/^\d{4}-\d{2}-\d{2}$/.test(event.date || '')) return null;
    const date = new Date(event.date + 'T00:00:00Z');
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== event.date) return null;
    let url;
    try { url = new URL(event.source); } catch { return null; }
    if (url.protocol !== 'https:' || url.username || url.password) return null;
    url.search = ''; url.hash = '';
    return {events: [{game: game.name_en || game.name_cn, title: event.title, date: event.date, source_url: url.href}]};
  }

  function updateButton() {
    button.disabled = revoked || !identity || identity.role !== 'admin' || !!request || !context() || storageError || !!(pending && !pending.job_id);
    button.textContent = pending ? pending.job_id ? '查询已有解读任务' : '原请求待核对' : '根据导入情报解读';
  }
  function clearResult() { output.textContent = ''; receipt.textContent = ''; }
  function selected() {
    request?.abort(); restoreRecord();
    clearResult();
    status.textContent = !context() ? '该事件缺少有效日期或 HTTPS 来源，暂不可调用。'
      : identity?.role === 'admin' ? '点击后仅发送所选游戏名、事件名、日期与来源链接。'
      : '需要 FS 管理员权限才可调用 AI 解读。';
    if (storageError) status.textContent = '无法安全读取本页请求记录，已暂停新提交；请先核对已有请求。';
    if (pending) {
      receipt.textContent = `请求编号：${pending.request_id}` + (pending.job_id ? ` · 任务编号：${pending.job_id}` : '');
      status.textContent = pending.job_id ? '已有任务记录；点击后仅查询原任务，不重新提交。' : '原请求结果未确认，未自动重试；暂无任务编号，已禁止重新提交，请凭原请求编号核对。';
    }
    updateButton();
  }
  function events() {
    eventSelect.replaceChildren();
    (games[Number(gameSelect.value)]?.events || []).forEach((event, index) => {
      const option = document.createElement('option');
      option.value = String(index); option.textContent = `${event.date || '待确认'} · ${event.title}`;
      eventSelect.append(option);
    });
    selected();
  }
  games.forEach((game, index) => {
    const option = document.createElement('option');
    option.value = String(index); option.textContent = game.name_cn || game.name_en;
    gameSelect.append(option);
  });
  gameSelect.addEventListener('change', events);
  eventSelect.addEventListener('change', selected);
  events();

  function unavailable(message, denied = false) {
    identity = null;
    pending = null;
    request?.abort(); clearResult();
    document.body.removeAttribute('data-fs-session');
    const notice = byId('fsSessionStatus');
    notice.textContent = message;
    if (denied) {
      revoked = true;
      for (const timer of window.FS_GAME_TIMERS || []) clearInterval(timer);
      // A denied session must discard rendered content before navigation or a new login.
      for (const child of [...document.body.children]) if (child !== notice) child.remove();
      window.GAME_TIMELINE_DATA = null;
      window.GAME_GUIDE = null;
      window.REGION_RELEASES = null;
      games.length = 0;
      const link = document.createElement('a');
      link.href = '/__auth/login?next=%2Fdashboard%2Fgame-monitor%2F';
      link.textContent = '重新登录 FS';
      notice.append(document.createElement('br'), link);
    }
    updateButton();
  }
  async function checkSession() {
    if (revoked) return false;
    if (checking) return checking;
    checking = (async () => {
      try {
        const response = await fetch('/__auth/verify', {credentials: 'same-origin', cache: 'no-store', redirect: 'manual', signal: AbortSignal.timeout(15000)});
        if ([401, 403].includes(response.status) || response.redirected || response.type === 'opaqueredirect' || (response.status >= 300 && response.status < 400)) {
          unavailable('登录已失效或无访问权限，页面内容已清空。', true); return false;
        }
        if (!response.ok) throw Error('session_unavailable');
        if (!(response.headers.get('X-Auth-Groups') || '').split(',').includes('dashboard')) {
          unavailable('当前账号无 FS 工作区权限，页面内容已清空。', true); return false;
        }
        const previousRole = identity?.role, previousUser = identity?.user;
        identity = {role: response.headers.get('X-Auth-Role') || '', user: response.headers.get('X-Auth-User') || ''};
        const changed = previousRole !== identity.role || previousUser !== identity.user;
        if (changed && previousRole) { request?.abort(); pending = null; clearResult(); }
        document.body.setAttribute('data-fs-session', 'ready');
        if (!request && changed) selected();
        updateButton();
        return true;
      } catch {
        unavailable('暂时无法核验 FS 登录状态，内容已隐藏。恢复连接后可刷新页面。'); return false;
      } finally { checking = null; }
    })();
    return checking;
  }

  button.addEventListener('click', async () => {
    if (button.disabled || request) return;
    button.disabled = true;
    if (!await checkSession() || identity?.role !== 'admin' || request) return;
    const data = context();
    if (!data) { selected(); return; }
    if (storageError || pending && !pending.job_id) { selected(); return; }
    const submittedUser = identity.user, submittedContext = JSON.stringify(data);
    const current = () => !revoked && identity?.role === 'admin' && identity.user === submittedUser && JSON.stringify(context()) === submittedContext;
    const controller = new AbortController();
    request = controller;
    gameSelect.disabled = eventSelect.disabled = true;
    updateButton(); clearResult();
    status.textContent = '正在根据导入快照生成解读，请勿重复提交…';
    const record = pending || {request_id: crypto.randomUUID(), job_id: null, state: 'unknown', user: submittedUser, context: submittedContext};
    const requestId = record.request_id;
    receipt.textContent = `请求编号：${requestId}` + (record.job_id ? ` · 任务编号：${record.job_id}` : '');
    const timeout = setTimeout(() => controller.abort(), 180000);
    const reasons = {
      configuration_missing: '服务器尚未配置模型。', provider_unavailable: '模型服务暂不可用。',
      model_unavailable: '模型服务暂不可用。', rate_limited: '模型调用频率已达限制，请稍后查询。',
      daily_model_limit: '今日模型调用额度已用完，请明日再试；已有任务仍可查询。',
      invalid_context: '事件信息不满足解读要求。', invalid_request: '提交内容未通过校验。',
      permission_denied: '当前账号无此解读权限。', forbidden: '当前账号无此解读权限。',
      source_permission_denied: '当前账号无权读取该任务来源。',
      job_not_found: '该任务不存在或不属于当前账号，请核对任务编号。',
      unknown: '模型请求结果尚未确认，请先核对任务编号。',
      unavailable: 'AI 暂不可用；导入情报仍可查阅。'
    };
    const reasonText = code => Object.hasOwn(reasons, code) ? reasons[code] : '';
    async function read(url, options = {}) {
      const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', redirect: 'manual', signal: controller.signal, ...options});
      if ([401, 403].includes(response.status) || response.redirected || response.type === 'opaqueredirect' || (response.status >= 300 && response.status < 400)) {
        await checkSession(); throw Object.assign(Error('permission_denied'), {rejected: options.method === 'POST' && [401, 403].includes(response.status)});
      }
      if (response.status === 404 && url.startsWith('/dashboard/fs-home/advisor.json?')) throw Error('job_not_found');
      if (!(response.headers.get('content-type') || '').includes('application/json')) throw Error('unavailable');
      const result = await response.json();
      if (!response.ok) throw Object.assign(Error(Object.hasOwn(reasons, result.reason) ? result.reason : 'unavailable'), {rejected: options.method === 'POST' && [400, 404, 413, 422, 429].includes(response.status)});
      return result;
    }
    async function pause(seconds) {
      await new Promise((resolve, reject) => {
        const abort = () => { clearTimeout(timer); reject(Error('poll_timeout')); };
        const timer = setTimeout(() => { controller.signal.removeEventListener('abort', abort); resolve(); }, seconds * 1000);
        controller.signal.addEventListener('abort', abort, {once: true});
        if (controller.signal.aborted) abort();
      });
    }
    try {
      // Persist intent before POST so a lost reply or refresh cannot submit a new request.
      try { saveRecord(record); } catch { storageError = true; throw Error('storage_unavailable'); }
      pending = record;
      let result = record.job_id
        ? {status: 'pending', job_id: record.job_id, retryAfter: 0}
        : await read('/dashboard/boss-api/insight', {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-FS-Advisor-Action': 'submit'},
          body: JSON.stringify({scope: 'game-monitor', request_id: requestId, context: data})
        });
      if (result.status === 'pending') {
        if (typeof result.job_id !== 'string' || !result.job_id || result.job_id.length > 200) throw Error('unavailable');
        record.job_id = result.job_id; record.state = 'pending';
        saveRecord(record);
        if (!current()) return;
        receipt.textContent = `请求编号：${requestId} · 任务编号：${record.job_id}`;
        status.textContent = '任务已受理，正在查询处理进度；不会重复提交。';
        let wait = Math.min(10, Math.max(0, Number(result.retryAfter) || 0));
        while (current() && !controller.signal.aborted) {
          await pause(wait);
          const reply = await read('/dashboard/fs-home/advisor.json?id=' + encodeURIComponent(record.job_id));
          const job = reply.job;
          if (!job || typeof job.state !== 'string') throw Error('unavailable');
          if (['pending', 'running'].includes(job.state)) { wait = 3; continue; }
          if (!['completed', 'failed'].includes(job.state)) throw Error('unavailable');
          result = job.state === 'completed' ? job.result || {status: 'unavailable'} : {status: 'unavailable', reason: job.error};
          break;
        }
      }
      if (!await checkSession() || !current()) return;
      if (controller.signal.aborted) throw Error('poll_timeout');
      const jobId = record.job_id;
      if (result.status !== 'unknown') {
        sessionStorage.removeItem(recordKey(record.user, record.context));
        pending = null;
      }
      if (result.status === 'succeeded' && typeof result.text === 'string') {
        output.textContent = result.text;
        receipt.textContent = `${jobId ? `任务编号：${jobId} · ` : ''}模型：${result.model || 'DeepSeek'} · 回执：${result.receipt || '未提供'} · tokens：${result.tokens ?? '未提供'}`;
        status.textContent = '解读已生成，仅依据导入快照；请核实来源后再决策。';
      } else {
        status.textContent = reasonText(result.reason) || reasonText(result.status) || reasons.unavailable;
      }
    } catch (error) {
      if (error.rejected) {
        try { sessionStorage.removeItem(recordKey(record.user, record.context)); if (current()) pending = null; } catch { storageError = true; }
      }
      if (current()) status.textContent = reasonText(error.message) || (pending
        ? record.job_id ? '查询超时或中断，仍可凭编号查询，不自动重提。点击“查询已有解读任务”继续只读查询。' : '请求结果未确认，未自动重试；暂无任务编号，已禁止重新提交，请凭原请求编号核对。'
        : storageError ? '无法安全保存请求记录，未提交新请求；请先核对已有请求。' : '请求超时或网络中断，结果未确认，未自动重试。');
    } finally {
      clearTimeout(timeout); request = null;
      gameSelect.disabled = eventSelect.disabled = false;
      updateButton();
    }
  });
  window.addEventListener('focus', checkSession);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) checkSession(); });
  window.addEventListener('pagehide', () => { request?.abort(); clearResult(); document.body.removeAttribute('data-fs-session'); });
  window.addEventListener('pageshow', checkSession);
  setInterval(checkSession, 30000);
  checkSession();
})();
