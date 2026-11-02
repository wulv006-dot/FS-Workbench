(() => {
  'use strict';
  const api = '/api/hermes/conversations';
  const $ = id => document.getElementById(id);
  const activeStates = new Set(['preparing', 'dispatch_unknown', 'queued', 'running', 'stopping']);
  let current = null, snapshot = null, stream = null, epoch = 0, sending = false, creating = false, stopping = false, pending = null, ready = false, accessDenied = false;
  let reconnectTimer = null, announcementTimer = null;
  let uploads = [], fileItems = [], selectedFiles = new Set(), filesReady = false;
  const uploadBytes = new Map(), uploadFlights = new Set();
  const fileStates = {available: '可用', expired: '已过期', damaged: '文件损坏', missing: '文件不可用',
    unavailable: '暂不可用', unknown: '上传结果待核对', uploading: '正在上传', failed: '上传失败'};
  function fileStatus(file) {
    return typeof file.expires_at === 'number' && file.expires_at * 1000 <= Date.now() ? 'expired' : file.status;
  }
  function bindingAvailable(file) {
    return fileStatus(file) === 'available' && !uploads.some(u => ['unknown', 'uploading'].includes(u.status) &&
      (u.file_id === file.file_id || (!u.file_id && u.sha256 === file.sha256 && u.name === file.filename && u.size === file.size)));
  }

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
    const active = (snapshot?.turns || []).some(turn => activeStates.has(turn.state));
    const unresolved = uploads.some(u => ['unknown', 'uploading', 'failed'].includes(u.status));
    const invalidFiles = unresolved || selectedFiles.size > 10 || (selectedFiles.size && (!filesReady || [...selectedFiles].some(id => !fileItems.some(f => f.file_id === id && bindingAvailable(f)))));
    $('send-message').disabled = accessDenied || !ready || sending || creating || (!pending && (unknown || running?.state === 'stopping' || (active && !running) || (invalidFiles || (running && selectedFiles.size > 0))));
    $('send-message').textContent = pending ? '核对上次发送' : running ? '补充当前任务' : '发送';
    $('stop-run').hidden = accessDenied || !running;
    $('stop-run').disabled = stopping || running?.state === 'stopping';
    if ($('file-input')) $('file-input').disabled = accessDenied || !ready || active || sending || !!pending;
    if ($('attach-file')) $('attach-file').disabled = $('file-input').disabled;
    $('file-help').textContent = running ? '可继续发送文字补充；本轮回复结束后可添加新附件。' : '添加文件或拖到这里，和消息一起发送。支持情况由服务端确认。';
    renderFileChoices();
  }
  function pendingKey(id) { return 'hermes_pending_' + id; }
  function filesKey(id) { return 'hermes_files_' + id; }
  function storedFiles(id) {
    try { return JSON.parse(sessionStorage.getItem(filesKey(id)) || '{}'); } catch { return {}; }
  }
  function saveFiles(id, record) {
    const value = storedFiles(id);
    if (record) value.uploads = [...(value.uploads || []).filter(u => u.request_id !== record.request_id), record];
    if (id === current) { value.selected = [...selectedFiles]; if (!record) value.uploads = uploads; }
    sessionStorage.setItem(filesKey(id), JSON.stringify(value));
  }
  function lockedFiles() {
    return accessDenied || !ready || sending || !!pending || (snapshot?.turns || []).some(t => activeStates.has(t.state));
  }
  function renderFileChoices() {
    if (!$('file-choices')) return;
    const focusId = document.activeElement?.id;
    $('file-choices').replaceChildren(); $('upload-list').replaceChildren();
    if (!ready || accessDenied) return;
    for (const upload of uploads) {
      if (upload.status === 'available') continue;
      const row = el('li', undefined, $('upload-list'), 'attachment-chip');
      el('span', upload.name + ' · ' + (fileStates[upload.status] || '待核对'), row);
      if (['unknown', 'failed'].includes(upload.status)) {
        const check = el('button', '核对原上传', row, 'fs-btn'); check.type = 'button';
        check.disabled = uploadFlights.has(current + ':' + upload.request_id);
        check.onclick = () => checkUpload(current, epoch, upload);
        const retry = el('button', '重试原文件', row, 'fs-btn'); retry.type = 'button';
        retry.disabled = lockedFiles() || uploadFlights.has(current + ':' + upload.request_id);
        retry.onclick = () => {
          const bytes = uploadBytes.get(current + ':' + upload.request_id);
          if (bytes) return uploadFile(current, epoch, upload, bytes);
          announce('请重新选择内容相同的原文件，将沿原上传核对。'); $('file-input').click();
        };
        if (upload.status === 'failed') {
          const remove = el('button', '移除附件', row, 'fs-btn'); remove.type = 'button';
          remove.disabled = lockedFiles();
          remove.onclick = () => { uploads = uploads.filter(u => u.request_id !== upload.request_id); saveFiles(current); syncControls(); };
        }
      }
    }
    for (const id of selectedFiles) {
      const file = fileItems.find(f => f.file_id === id) || {filename:'附件',status:'unavailable'};
      const row = el('li', undefined, $('file-choices'), 'attachment-chip');
      el('span', file.filename + ' · ' + (bindingAvailable(file) ? '已上传' : fileStates[fileStatus(file)] || '待核对'), row);
      const remove = el('button', '移除附件', row, 'fs-btn'); remove.type = 'button';
      remove.id = 'remove-file-' + id; remove.setAttribute('aria-label', '移除附件：' + file.filename);
      remove.disabled = lockedFiles();
      remove.onclick = () => {
        selectedFiles.delete(id); uploads = uploads.filter(u => u.file_id !== id);
        saveFiles(current); syncControls(); $('message-input').focus();
      };
    }
    if (focusId?.startsWith('remove-file-')) document.getElementById(focusId)?.focus();
  }
  function fileCards(parent, files, generated) {
    for (const file of files || []) {
      if (!/^[a-f0-9]{32}$/.test(file.file_id || '')) continue;
      const card = el('div', undefined, parent, 'file-card');
      el('p', (file.filename || '文件') + ' · v' + (file.version || '?') + ' · ' + (fileStates[fileStatus(file)] || '暂不可用'), card);
      if (file.expires_at) el('p', '到期：' + new Date(file.expires_at * 1000).toLocaleString('zh-CN'), card, 'file-state');
      if (fileStatus(file) === 'available') {
        const download = el('a', '下载文件', card);
        download.href = api + '/' + encodeURIComponent(current) + '/files/' + file.file_id;
        download.download = file.filename || 'file';

      }
    }
  }
  async function refreshFiles(id, generation) {
    const result = await request('/' + encodeURIComponent(id) + '/files');
    if (id !== current || generation !== epoch || accessDenied) return;
    fileItems = result.items || []; filesReady = true;
    for (const upload of uploads) {
      const item = fileItems.find(f => f.file_id === upload.file_id);
      if (item) upload.status = item.status;
    }
    saveFiles(id); syncControls();
  }
  function updateUpload(id, generation, record) {
    saveFiles(id, record);
    if (id !== current || generation !== epoch || accessDenied) return;
    uploads = [...uploads.filter(u => u.request_id !== record.request_id), record];
    renderFileChoices();
  }
  async function checkUpload(id, generation, record) {
    try {
      const item = await request('/' + id + '/files?request_id=' + encodeURIComponent(record.request_id));
      if (item.sha256 !== record.sha256 || item.size !== record.size || item.filename !== record.name) throw Error('上传内容核对不一致，请保留原文件并检查。');
      updateUpload(id, generation, {...record, file_id: item.file_id, status: item.status});
      if (id === current && generation === epoch && !accessDenied && item.status === 'available') selectedFiles.add(item.file_id);
      await refreshFiles(id, generation);
    } catch (error) {
      if (id !== current || generation !== epoch) return;
      if ([401, 403].includes(error.status)) { denyAccess(); return; }
      updateUpload(id, generation, {...record, status: 'unknown'});
      announce(error.status === 404 ? '尚未查到上传结果；请选回同一原文件，沿原上传重试。' : '上传结果尚未确认，请稍后核对原上传。');
    }
  }
  async function uploadFile(id, generation, record, file) {
    const key = id + ':' + record.request_id;
    if (uploadFlights.has(key)) return;
    uploadFlights.add(key); updateUpload(id, generation, {...record, status: 'uploading'});
    try {
      const response = await fetch(api + '/' + id + '/files', {method: 'POST', credentials: 'same-origin',
        cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(60000),
        headers: {'Content-Type': 'application/octet-stream', 'X-FS-Advisor-Action': 'submit',
          'X-FS-Filename': encodeURIComponent(record.name), 'X-FS-Request-ID': record.request_id}, body: file});
      if (!response.ok) { const error = Error('upload'); error.status = response.status; throw error; }
      // Success bytes are reconciled against server metadata, including SHA256.
      await checkUpload(id, generation, record);
    } catch (error) {
      const failed = error.status >= 400 && error.status < 500;
      updateUpload(id, generation, {...record, status: failed ? 'failed' : 'unknown'});
      if (id === current && generation === epoch) {
        if ([401, 403].includes(error.status)) denyAccess();
        else announce(failed ? '上传未被接受，请检查文件后重试原上传。' : '上传结果待核对，请勿重复新建上传。');
      }
    } finally { uploadFlights.delete(key); if (id === current && generation === epoch) syncControls(); }
  }
  async function chooseFiles(dropped) {
    if (lockedFiles()) return;
    const chosen = [...(dropped || $('file-input').files)]; $('file-input').value = '';
    if (chosen.length + selectedFiles.size > 10) { announce('每次最多上传 10 个文件。'); return; }
    if (!current) await newConversation();
    const id = current, generation = epoch;
    if (!id || lockedFiles()) return;
    for (const file of chosen) {
      if (id !== current || generation !== epoch) break;
      if (!file.size) { announce('文件为空，请检查后重新选择。'); continue; }
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer()))].map(b => b.toString(16).padStart(2, '0')).join('');
      if (id !== current || generation !== epoch) break;
      const previous = uploads.find(u => ['unknown', 'failed', 'uploading'].includes(u.status) && u.name === file.name);
      if (previous && (previous.sha256 !== hash || previous.size !== file.size)) { announce('所选文件内容与待核对的原上传不同，请选回原文件。'); continue; }
      const record = previous || {name: file.name, size: file.size, sha256: hash,
        request_id: 'upload_' + crypto.randomUUID().replaceAll('-', ''), status: 'unknown'};
      uploadBytes.set(id + ':' + record.request_id, file);
      await uploadFile(id, generation, record, file);
    }
  }
  function restorePending(id) {
    try { pending = JSON.parse(sessionStorage.getItem(pendingKey(id)) || 'null'); }
    catch { pending = null; }
    if (pending) {
      if (!pending.target?.endsWith('/steer')) selectedFiles = new Set(pending.file_ids || []);
      $('message-input').value = pending.text;
      $('message-input').readOnly = true;
      announce('上次发送结果待核对。可用同一请求编号重试，避免重复任务。');
    } else { $('message-input').value = ''; $('message-input').readOnly = false; }
  }
  function progressText(progress) {
    if (!progress) return '';
    if (typeof progress === 'string') return progress;
    if (progress.type?.startsWith('tool.')) {
      const labels = {mcp__fcro__fc_list_conversation_files: '查看附件目录',
        mcp__fcro__fc_read_conversation_file: '读取附件', mcp__fcro__fc_revise_conversation_file: '生成修订文件'};
      return (labels[progress.tool] || progress.tool || '数据工具') + ' · ' +
        (progress.type === 'tool.started' ? '正在处理' : progress.type === 'tool.failed' ? '处理失败' : '已完成');
    }
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
    fileItems = []; uploads = []; selectedFiles.clear(); uploadBytes.clear(); filesReady = false; renderFileChoices();
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
  function safeLink(value) {
    try { const url = new URL(value, location.href); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; }
    catch { return null; }
  }
  function inline(parent, text) {
    // Build DOM nodes only. Raw HTML and unrecognized syntax remain readable text.
    const tokens = /(`[^`]+`|\*\*[^*]+\*\*|!?\[[^\]]*\]\([^\s)]+\))/g;
    let offset = 0;
    for (const match of text.matchAll(tokens)) {
      if (match.index > offset) el('span', text.slice(offset, match.index), parent);
      const token = match[0];
      if (token.startsWith('`')) el('code', token.slice(1, -1), parent);
      else if (token.startsWith('**')) el('strong', token.slice(2, -2), parent);
      else {
        const parts = /^(!?)\[([^\]]*)\]\(([^)]+)\)$/.exec(token), href = safeLink(parts[3]);
        if (href) {
          // Authenticated server metadata supplies real file/image previews below.
          // An arbitrary model URL is a normal link, never a download artifact.
          const link = el('a', parts[2] || parts[3], parent); link.href = href; link.rel = 'noopener noreferrer';
        } else el('span', token, parent);
      }
      offset = match.index + token.length;
    }
    if (offset < text.length) el('span', text.slice(offset), parent);
  }
  function renderReply(parent, value) {
    const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    const body = el('div', undefined, parent, 'reply-body');
    const lines = (text || '').split('\n');
    const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(v => v.trim());
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.startsWith('```')) {
        const language = line.slice(3), code = [];
        while (++i < lines.length && !lines[i].startsWith('```')) code.push(lines[i]);
        const pre = el('pre', undefined, body); pre.setAttribute('aria-label', language || '代码');
        el('code', code.join('\n'), pre); continue;
      }
      if (i + 1 < lines.length && line.includes('|') && /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(lines[i+1].trim())) {
        const frame = el('div', undefined, body, 'table-scroll'); frame.tabIndex = 0; frame.setAttribute('aria-label', '回答表格');
        const table = el('table', undefined, frame), header = el('tr', undefined, el('thead', undefined, table));
        for (const cell of cells(line)) inline(el('th', undefined, header), cell);
        const rows = el('tbody', undefined, table); i++;
        while (i + 1 < lines.length && lines[i+1].includes('|')) {
          const row = el('tr', undefined, rows); for (const cell of cells(lines[++i])) inline(el('td', undefined, row), cell);
        }
        continue;
      }
      const heading = /^(#{1,6})\s+(.+)$/.exec(line), list = /^\s*(?:[-*]|\d+\.)\s+(.+)$/.exec(line);
      if (heading) inline(el('h' + Math.min(heading[1].length + 2, 6), undefined, body), heading[2]);
      else if (list) { const row = el('p', undefined, body, 'reply-list'); inline(row, line); }
      else inline(el('p', undefined, body), line || '\u00a0');
    }
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
      fileCards(user, turn.files?.inputs, false);
      const answer = el('article', undefined, box, 'message assistant');
      el('h2', 'Hermes', answer);
      renderReply(answer, turn.reply || (activeStates.has(turn.state) ? '正在处理…' : turn.state === 'cancelled' ? '已停止；本轮未产生回复。' : turn.state === 'interrupted' ? '已中断；本轮未产生回复。' : ''));
      if (turn.state === 'cancelled' && turn.reply) el('p', '已停止；上方保留停止前的回复。', answer, 'progress');
      if (turn.progress && activeStates.has(turn.state)) {
        const progress = el('details', undefined, answer, 'progress');
        el('summary', '处理进度', progress); el('p', progressText(turn.progress), progress);
      }
      if (turn.state === 'failed' || turn.state === 'interrupted' || turn.state === 'dispatch_unknown') {
        el('p', turn.state === 'dispatch_unknown' ? '提交状态待核对，请勿重复发起新任务。' : turn.state === 'interrupted' ? '任务已中断：' + (turn.error || '可在此会话继续说明需求。') : '任务未完成：' + (turn.error || '可在此会话继续说明需求。'), answer, 'error');
      }
      if (turn.artifacts?.length) {
        const files = el('div', undefined, answer, 'artifact-list');
        for (const artifact of turn.artifacts) {
          if (!/^[a-f0-9]{32}$/.test(artifact.artifact_id || '')) continue;
          const path = api + '/' + encodeURIComponent(current) + '/artifacts/' + encodeURIComponent(artifact.artifact_id);
          if (artifact.mime?.startsWith('image/')) { const image = el('img', undefined, files, 'reply-image'); image.src = path; image.alt = artifact.filename || 'Hermes 生成的图片'; image.loading = 'lazy'; }
          const open = el('a', '打开原稿 · ' + artifact.filename, files);
          open.href = path + '?view=1'; open.target = '_blank'; open.rel = 'noopener noreferrer';
          const download = el('a', '下载原文件', files);
          download.href = path; download.download = artifact.filename;
        }
      }
      fileCards(answer, turn.files?.generated, true);
    }
    syncControls();
    $('conversation-title').textContent = snapshot?.title || '与 Hermes 对话';
    $('conversation-title').title = snapshot?.title || '与 Hermes 对话';
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
      if (pending && !pending.target?.endsWith('/steer')) {
        const accepted = detail.turns?.find(t => t.client_request_id === pending.client_request_id && t.text === pending.text &&
          JSON.stringify([...(t.file_bindings?.inputs || [])].sort()) === JSON.stringify([...(pending.file_ids || [])].sort()));
        if (accepted && accepted.state !== 'dispatch_unknown') {
          sessionStorage.removeItem(pendingKey(current)); pending = null; uploads = uploads.filter(u => !selectedFiles.has(u.file_id)); selectedFiles.clear();
          $('message-input').value = ''; $('message-input').readOnly = false; saveFiles(current);
        }
      }
      try { await refreshFiles(current, generation); }
      catch (error) {
        if (generation !== epoch) return;
        filesReady = false; fileItems = fileItems.map(f => ({...f, status: 'unavailable'}));
        if ([401, 403].includes(error.status)) { denyAccess(); return; }
        if ($('file-help')) $('file-help').textContent = '附件状态暂未确认，请稍后刷新核对；已选附件确认前不会用于新一轮。';
      }
      if (generation !== epoch || accessDenied) return;
      scrollIfAtBottom(renderMessages);
      connect(current, detail.last_seq || 0, generation);
      $('connection-indicator').textContent = '已连接';
    } catch (error) {
      if (generation !== epoch) return;
      if ([401, 403].includes(error.status)) { denyAccess(); return; }
      $('connection-indicator').textContent = '连接失败';
      announce('会话读取失败：' + errorMessage(error));
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(() => refreshCurrent(generation), 5000);
    }
  }
  async function openConversation(id) {
    if (accessDenied || !/^[a-f0-9]{32}$/.test(id || '')) return;
    current = id; epoch++; snapshot = null; ready = false; filesReady = false; fileItems = [];
    const saved = storedFiles(id);
    uploads = (saved.uploads || []).map(u => ({...u, status: u.status === 'failed' ? 'failed' : 'unknown'}));
    selectedFiles = new Set(saved.selected || []);
    closeStream(); restorePending(id); syncControls();
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
      if ([401, 403].includes(error.status)) { denyAccess(); return; }
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
    let origin = null, sendEpoch = null;
    try {
      if (!current) await newConversation();
      if (!current) return;
      const id = current, generation = epoch;
      origin = id; sendEpoch = generation;
      const running = selectedRun();
      if (!pending && !running && selectedFiles.size) {
        await refreshFiles(id, generation);
        if (id !== current || generation !== epoch || accessDenied) return;
        if ([...selectedFiles].some(fid => !fileItems.some(f => f.file_id === fid && bindingAvailable(f)))) {
          announce('已选附件已过期或不可用，请取消选择后再发送。'); return;
        }
      }
      const target = running ? '/' + encodeURIComponent(current) + '/runs/' + encodeURIComponent(running.run_id) + '/steer' : '/' + encodeURIComponent(current) + '/turns';
      if (!pending) {
        pending = {target, text, client_request_id: 'web_' + crypto.randomUUID().replaceAll('-', ''),
          ...(!running ? {file_ids: [...selectedFiles].sort()} : {})};
        sessionStorage.setItem(pendingKey(current), JSON.stringify(pending));
      }
      const wasSteer = pending.target.endsWith('/steer');
      const result = await request(pending.target, {text: pending.text, client_request_id: pending.client_request_id,
        ...(!wasSteer && pending.file_ids?.length ? {file_ids: pending.file_ids} : {})}, 'POST');
      if (id !== current || generation !== epoch) return;
      const state = result.state;
      const accepted = wasSteer ? state === 'accepted' : ['preparing', 'queued', 'running', 'stopping', 'completed'].includes(state);
      const rejected = ['rejected', 'failed', 'cancelled', 'interrupted'].includes(state);
      if (accepted || rejected) {
        sessionStorage.removeItem(pendingKey(current)); pending = null; $('message-input').readOnly = false;
      }
      if (accepted) {
        $('message-input').value = '';
        if (!wasSteer) {
          uploads = uploads.filter(u => !selectedFiles.has(u.file_id)); selectedFiles.clear(); saveFiles(current);
          if ($('attachments')) $('attachments').open = false;
        }
      }
      else if (!rejected) $('message-input').readOnly = true;
      await refreshCurrent();
      loadList().catch(() => {});
      if (accepted) announce(wasSteer ? '补充请求已接受；是否被模型处理请以回复为准。' : '消息已送达 Hermes。');
      else if (rejected) announce('本次提交未被接受，内容已保留，可调整后重新发送。');
      else announce('提交状态待核对，请勿换请求编号或重复发起新任务。');
    } catch (error) {
      if (origin && (origin !== current || sendEpoch !== epoch)) return;
      if ([401, 403].includes(error.status)) { denyAccess(); return; }
      $('message-input').readOnly = !!pending;
      announce('发送结果需核对：' + errorMessage(error) + '。再次发送会使用同一请求编号。');
      await refreshCurrent();
    } finally { sending = false; syncControls(); }
  }
  async function stop() {
    const run = selectedRun();
    if (!run || !current) return;
    stopping = true; syncControls();
    const id = current, generation = epoch;
    try {
      const key = 'hermes_stop_' + current + '_' + run.run_id;
      const requestId = sessionStorage.getItem(key) || 'stop_' + crypto.randomUUID().replaceAll('-', '');
      sessionStorage.setItem(key, requestId);
      const result = await request('/' + encodeURIComponent(current) + '/runs/' + encodeURIComponent(run.run_id) + '/stop', {client_request_id: requestId}, 'POST');
      if (id !== current || generation !== epoch) return;
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
      if (id !== current || generation !== epoch) return;
      if ([401, 403].includes(error.status)) { denyAccess(); return; }
      announce('停止结果需核对：' + errorMessage(error));
      await refreshCurrent();
    } finally { stopping = false; syncControls(); }
  }
  $('new-conversation').onclick = newConversation;
  $('composer').onsubmit = send;
  $('stop-run').onclick = stop;
  $('message-input').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); $('composer').requestSubmit(); } };
  $('attach-file').onclick = () => $('file-input').click();
  $('composer').ondragover = event => { event.preventDefault(); };
  $('composer').ondrop = event => {
    event.preventDefault();
    if (lockedFiles()) { announce('本轮回复结束后可添加附件，文件尚未上传。'); return; }
    chooseFiles(event.dataTransfer?.files || []).catch(() => announce('文件读取失败，请检查原文件。'));
  };
  if ($('file-input')) $('file-input').onchange = () => chooseFiles().catch(() => announce('文件读取失败，请检查原文件后重试。'));
  (async () => {
    try {
      const items = await loadList();
      const requested = new URL(location.href).searchParams.get('conversation');
      const first = items.find(item => item.conversation_id === requested) || items[0];
      if (first) await openConversation(first.conversation_id);
      else { ready = true; syncControls(); $('connection-indicator').textContent = '可以开始'; }
    } catch (error) {
      if ([401, 403].includes(error.status)) { denyAccess(); return; }
      $('connection-indicator').textContent = '连接失败';
      announce('会话列表读取失败：' + errorMessage(error));
    }
  })();
})();
