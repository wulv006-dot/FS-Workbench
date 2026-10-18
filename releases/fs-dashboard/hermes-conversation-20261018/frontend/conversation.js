(() => {
  'use strict';
  const api = '/api/hermes/conversations';
  const $ = id => document.getElementById(id);
  const activeStates = new Set(['preparing', 'dispatch_unknown', 'queued', 'running', 'stopping']);
  let current = null, snapshot = null, stream = null, epoch = 0, sending = false, creating = false, stopping = false, pending = null, ready = false, accessDenied = false;
  let reconnectTimer = null, announcementTimer = null;

  function announce(message) {
    clearTimeout(announcementTimer);
    announcementTimer = setTimeout(() => { $('status').textContent = message; }, 350);
  }
  function errorMessage(error) {
    const known = {
      conversation_busy: '当前会话仍有任务在进行，请等结果或补充当前任务。',
      conversation_unavailable: '会话服务暂时不可用。',
      invalid_input: '消息内容不符合要求，请检查后重试。',
      admin_required: '当前账号没有持续对话权限。',
      same_origin_required: '页面会话校验失败，请从 FS 重新打开。'
    };
    return known[error?.message] || error?.message || '连接暂时失败，请刷新后核对原会话。';
  }
  async function request(path = '', body, method = 'GET') {
    const response = await fetch(api + path, {
      method, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      signal: AbortSignal.timeout(20000),
      headers: body === undefined ? {} : {'Content-Type': 'application/json', 'X-FS-Advisor-Action': 'submit'},
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const value = await response.json().catch(() => ({}));
    if (!response.ok) { const error = Error(value.error || value.message || 'HTTP ' + response.status); error.status = response.status; throw error; }
    return value;
  }
  function el(tag, text, parent, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    parent.append(item);
    return item;
  }
  function selectedRun() {
    return [...(snapshot?.turns || [])].reverse().find(turn => activeStates.has(turn.state) && turn.run_id);
  }
  function syncControls() {
    const running = selectedRun();
    const unknown = (snapshot?.turns || []).some(turn => turn.state === 'dispatch_unknown');
    $('new-conversation').disabled = accessDenied || creating || sending || !!pending;
    $('message-input').disabled = accessDenied;
    $('send-message').disabled = accessDenied || !ready || sending || creating || (!pending && (unknown || running?.state === 'stopping'));
    $('send-message').textContent = pending ? '核对上次发送' : running ? '补充当前任务' : '发送';
    $('stop-run').hidden = accessDenied || !running;
    $('stop-run').disabled = stopping || running?.state === 'stopping';
  }
  function pendingKey(id) { return 'hermes_pending_' + id; }
  function restorePending(id) {
    try { pending = JSON.parse(sessionStorage.getItem(pendingKey(id)) || 'null'); }
    catch { pending = null; }
    if (pending) {
      $('message-input').value = pending.text;
      $('message-input').readOnly = true;
      announce('上次发送结果待核对。可用同一请求编号重试，避免重复任务。');
    } else { $('message-input').value = ''; $('message-input').readOnly = false; }
  }
  function progressText(progress) {
    if (!progress) return '';
    if (typeof progress === 'string') return progress;
    if (progress.type?.startsWith('tool.')) return (progress.tool || '数据工具') + ' · ' + (progress.type === 'tool.started' ? '正在查询' : progress.type === 'tool.failed' ? '查询失败' : '已完成');
    return progress.status || '正在处理';
  }
  function terminalMessage(state) {
    return {completed: 'Hermes 已完成。', cancelled: '任务已停止。', interrupted: '任务已中断。', failed: '任务失败。'}[state] || '';
  }
  function scrollIfAtBottom(render) {
    const box = $('messages');
    const follows = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    render();
    if (follows) box.scrollTop = box.scrollHeight;
  }
  function renderList(items) {
    const list = $('conversation-list');
    list.replaceChildren();
    if (!items.length) el('li', '还没有会话。', list, 'muted');
    for (const item of items) {
      const li = el('li', undefined, list);
      const button = el('button', item.title || '新对话', li);
      button.type = 'button';
      button.setAttribute('aria-current', String(item.conversation_id === current));
      if (item.updated_at) el('small', new Date(item.updated_at).toLocaleString('zh-CN'), button);
      button.onclick = () => openConversation(item.conversation_id);
    }
  }
  function denyAccess() {
    accessDenied = true; ready = false; epoch++;
    closeStream();
    $('connection-indicator').textContent = '无对话权限';
    syncControls();
    $('conversation-list').replaceChildren();
    $('messages').replaceChildren();
    const box = el('div', undefined, $('messages'), 'empty');
    el('p', '当前账号没有持续对话权限。', box);
    const link = el('a', '返回获准的快捷报告', box);
    link.href = '/dashboard/fs-home/brain/index.html';
    announce('持续对话仅向管理员开放。');
  }
  async function loadList() {
    const value = await request();
    if (!accessDenied) renderList(value.items || []);
    return value.items || [];
  }
  function renderMessages() {
    const box = $('messages');
    box.replaceChildren();
    const turns = snapshot?.turns || [];
    if (!turns.length) el('p', '可以直接提问，也可以布置调查。', box, 'empty');
    for (const turn of turns) {
      const user = el('article', undefined, box, 'message user');
      el('h2', '你', user);
      el('p', turn.text || '', user);
      const answer = el('article', undefined, box, 'message assistant');
      el('h2', 'Hermes', answer);
      const hasHtml = turn.artifacts?.some(artifact => artifact.mime?.split(';')[0].toLowerCase() === 'text/html');
      const hasText = turn.artifacts?.some(artifact => artifact.mime?.split(';')[0].toLowerCase() === 'text/plain');
      const htmlReply = hasHtml || /<(!doctype\s+html|html(?:\s|>))/i.test((turn.reply || '').slice(0, 1024));
      if (htmlReply) {
        const label = hasHtml ? '已生成 HTML，可打开原稿查看。'
          : ['preparing', 'queued', 'running', 'stopping'].includes(turn.state) ? 'HTML 原稿正在归档，稍后可打开。'
          : hasText ? '回复已归档为文本，可打开原稿查看。'
          : '暂无可打开的 HTML 原稿，可展开原始回复查看。';
        el('p', label, answer);
        if (turn.reply) {
          const details = el('details', undefined, answer);
          el('summary', '展开 Hermes 原始回复', details);
          details.ontoggle = () => {
            if (details.open && !details.querySelector('pre')) el('pre', turn.reply, details, 'raw-reply');
          };
        }
      } else el('p', turn.reply || (activeStates.has(turn.state) ? '正在处理…' : turn.state === 'cancelled' ? '已停止；本轮未产生回复。' : turn.state === 'interrupted' ? '已中断；本轮未产生回复。' : ''), answer);
      if (turn.state === 'cancelled' && turn.reply) el('p', '已停止；上方保留停止前的回复。', answer, 'progress');
      if (turn.progress && activeStates.has(turn.state)) el('p', progressText(turn.progress), answer, 'progress');
      if (turn.state === 'failed' || turn.state === 'interrupted' || turn.state === 'dispatch_unknown') {
        el('p', turn.state === 'dispatch_unknown' ? '提交状态待核对，请勿重复发起新任务。' : turn.state === 'interrupted' ? '任务已中断：' + (turn.error || '可在此会话继续说明需求。') : '任务未完成：' + (turn.error || '可在此会话继续说明需求。'), answer, 'error');
      }
      if (turn.artifacts?.length) {
        const files = el('div', undefined, answer, 'artifact-list');
        for (const artifact of turn.artifacts) {
          const path = api + '/' + encodeURIComponent(current) + '/artifacts/' + encodeURIComponent(artifact.artifact_id);
          const open = el('a', '打开原稿 · ' + artifact.filename, files);
          open.href = path + '?view=1'; open.target = '_blank'; open.rel = 'noopener noreferrer';
          const download = el('a', '下载原文件', files);
          download.href = path; download.download = artifact.filename;
        }
      }
    }
    syncControls();
    $('conversation-title').textContent = snapshot?.title || '与 Hermes 对话';
  }
  function closeStream() {
    clearTimeout(reconnectTimer);
    if (stream) stream.close();
    stream = null;
  }
  function connect(id, seq, generation) {
    closeStream();
    const eventsUrl = api + '/' + encodeURIComponent(id) + '/events?after=' + encodeURIComponent(seq);
    stream = new EventSource(eventsUrl, {withCredentials: true});
    stream.onopen = () => { if (generation === epoch) $('connection-indicator').textContent = '实时连接'; };
    stream.onmessage = event => {
      if (generation !== epoch || id !== current) return;
      let update;
      try { update = JSON.parse(event.data); } catch { return; }
      if (!Number.isSafeInteger(update.seq) || update.seq <= (snapshot?.last_seq || 0)) return;
      snapshot.last_seq = update.seq;
      const turn = snapshot.turns.find(item => item.turn_id === update.turn_id);
      if (!turn) { refreshCurrent(generation); return; }
      if (update.type === 'message.delta') turn.reply = (turn.reply || '') + (update.payload?.delta || '');
      else if (update.type === 'message.interim') turn.progress = {type: update.type, ...update.payload};
      else if (update.type.startsWith('tool.')) turn.progress = {type: update.type, ...update.payload};
      else if (update.type.startsWith('run.')) {
        if (update.type === 'run.completed') { turn.state = 'completed'; turn.reply = update.payload?.output || turn.reply || ''; }
        else if (update.type === 'run.failed') { turn.state = 'failed'; turn.error = update.payload?.error || ''; }
        else if (update.type === 'run.cancelled') turn.state = 'cancelled';
        else if (update.type === 'run.interrupted') turn.state = 'interrupted';
        else if (update.type === 'run.stopping') turn.state = 'stopping';
        if (['run.completed', 'run.failed', 'run.cancelled', 'run.interrupted'].includes(update.type)) refreshCurrent(generation);
      }
      scrollIfAtBottom(renderMessages);
      if (update.type !== 'message.delta') announce(terminalMessage(turn.state) || progressText(turn.progress) || '任务状态已更新。');
    };
    stream.onerror = () => {
      if (generation !== epoch) return;
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => refreshCurrent(generation), 2500);
    };
  }
  async function refreshCurrent(generation = epoch) {
    if (!current || generation !== epoch) return;
    try {
      const detail = await request('/' + encodeURIComponent(current));
      if (generation !== epoch) return;
      if (snapshot && (detail.last_seq || 0) < (snapshot.last_seq || 0)) return;
      snapshot = detail;
      ready = true;
      scrollIfAtBottom(renderMessages);
      connect(current, detail.last_seq || 0, generation);
      $('connection-indicator').textContent = '已连接';
    } catch (error) {
      if (generation !== epoch) return;
      if (error.status === 403) { denyAccess(); return; }
      $('connection-indicator').textContent = '连接失败';
      announce('会话读取失败：' + errorMessage(error));
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => refreshCurrent(generation), 5000);
    }
  }
  async function openConversation(id) {
    if (accessDenied || !/^[a-f0-9]{32}$/.test(id || '')) return;
    current = id; epoch++; snapshot = null; ready = false; closeStream(); restorePending(id); syncControls();
    history.replaceState(null, '', '?conversation=' + encodeURIComponent(id));
    $('connection-indicator').textContent = '正在读取';
    await refreshCurrent(epoch);
    loadList().catch(() => {});
  }
  async function newConversation() {
    if (creating || accessDenied) return;
    creating = true; syncControls();
    try {
      const value = await request('', {}, 'POST');
      await openConversation(value.conversation_id);
      $('message-input').focus();
    } catch (error) {
      if (error.status === 403) { denyAccess(); return; }
      announce('新会话结果未确认：' + errorMessage(error) + '。请先核对会话列表。');
      loadList().catch(() => {});
    } finally { creating = false; syncControls(); }
  }
  async function send(event) {
    event.preventDefault();
    if (sending || !ready || accessDenied || $('send-message').disabled) return;
    const text = $('message-input').value.trim();
    if (!text) return;
    sending = true; syncControls();
    try {
      if (!current) await newConversation();
      if (!current) return;
      const running = selectedRun();
      const target = running ? '/' + encodeURIComponent(current) + '/runs/' + encodeURIComponent(running.run_id) + '/steer' : '/' + encodeURIComponent(current) + '/turns';
      if (!pending) {
        pending = {target, text, client_request_id: 'web_' + crypto.randomUUID().replaceAll('-', '')};
        sessionStorage.setItem(pendingKey(current), JSON.stringify(pending));
      }
      const wasSteer = pending.target.endsWith('/steer');
      const result = await request(pending.target, {text: pending.text, client_request_id: pending.client_request_id}, 'POST');
      const state = result.state;
      const accepted = wasSteer ? state === 'accepted' : ['preparing', 'queued', 'running', 'stopping', 'completed'].includes(state);
      const rejected = ['rejected', 'failed', 'cancelled', 'interrupted'].includes(state);
      if (accepted || rejected) {
        sessionStorage.removeItem(pendingKey(current)); pending = null; $('message-input').readOnly = false;
      }
      if (accepted) $('message-input').value = '';
      else if (!rejected) $('message-input').readOnly = true;
      await refreshCurrent();
      loadList().catch(() => {});
      if (accepted) announce(wasSteer ? '补充请求已接受；是否被模型处理请以回复为准。' : '消息已送达 Hermes。');
      else if (rejected) announce('本次提交未被接受，内容已保留，可调整后重新发送。');
      else announce('提交状态待核对，请勿换请求编号或重复发起新任务。');
    } catch (error) {
      if (error.status === 403) { denyAccess(); return; }
      $('message-input').readOnly = !!pending;
      announce('发送结果需核对：' + errorMessage(error) + '。再次发送会使用同一请求编号。');
      await refreshCurrent();
    } finally { sending = false; syncControls(); }
  }
  async function stop() {
    const run = selectedRun();
    if (!run || !current) return;
    stopping = true; syncControls();
    try {
      const key = 'hermes_stop_' + current + '_' + run.run_id;
      const requestId = sessionStorage.getItem(key) || 'stop_' + crypto.randomUUID().replaceAll('-', '');
      sessionStorage.setItem(key, requestId);
      const result = await request('/' + encodeURIComponent(current) + '/runs/' + encodeURIComponent(run.run_id) + '/stop', {client_request_id: requestId}, 'POST');
      if (result.state === 'accepted' || ['completed', 'failed', 'cancelled', 'interrupted'].includes(result.state)) {
        sessionStorage.removeItem(key);
        if (result.state !== 'accepted') announce(terminalMessage(result.state) || '任务已结束，无需停止。');
      } else if (result.state === 'rejected') {
        sessionStorage.removeItem(key);
        announce('停止请求未被接受，请核对任务状态后重试。');
      } else {
        announce('停止状态待核对；重试会使用原请求编号。');
      }
      await refreshCurrent();
      const latest = snapshot?.turns.find(turn => turn.run_id === run.run_id);
      if (latest && terminalMessage(latest.state)) announce(terminalMessage(latest.state));
      else if (result.state === 'accepted') announce('停止请求已接受，正在等待服务确认。');
    } catch (error) {
      if (error.status === 403) { denyAccess(); return; }
      announce('停止结果需核对：' + errorMessage(error));
      await refreshCurrent();
    } finally { stopping = false; syncControls(); }
  }
  $('new-conversation').onclick = newConversation;
  $('composer').onsubmit = send;
  $('stop-run').onclick = stop;
  $('message-input').onkeydown = event => { if (event.key === 'Enter' && event.ctrlKey) { event.preventDefault(); $('composer').requestSubmit(); } };
  (async () => {
    try {
      const items = await loadList();
      const requested = new URL(location.href).searchParams.get('conversation');
      const first = items.find(item => item.conversation_id === requested) || items[0];
      if (first) await openConversation(first.conversation_id);
      else { ready = true; syncControls(); $('connection-indicator').textContent = '可以开始'; }
    } catch (error) {
      if (error.status === 403) { denyAccess(); return; }
      $('connection-indicator').textContent = '连接失败';
      announce('会话列表读取失败：' + errorMessage(error));
    }
  })();
})();
