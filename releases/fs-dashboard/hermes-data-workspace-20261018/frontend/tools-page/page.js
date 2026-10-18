import {protectedRead, sessionIdentity} from '/dashboard/workspace-assets/workspace-native-20261006-ba0a83afd594/runtime.js';

const status = document.getElementById('page-status');
const host = document.getElementById('workspace-host');
const theme = document.getElementById('theme');
const controller = new AbortController();
let identity = null;
let widget = null;
const insights = new Map();
const conversations = '/api/hermes/conversations';

function show(message, error = false) {
  status.textContent = message;
  status.dataset.state = error ? 'error' : 'available';
}

function deny(code) {
  controller.abort();
  widget?.dispose();
  widget = null;
  insights.clear();
  identity = null;
  host.hidden = true;
  show(code === 403 ? '当前账号未获此工具页授权。' : '登录已失效，请重新登录。', true);
}

function scopedSignal(signal) {
  return signal ? AbortSignal.any([controller.signal, signal]) : controller.signal;
}

function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('已取消', 'AbortError')); return; }
    const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve(); }, ms);
    function cancel() { clearTimeout(timer); reject(new DOMException('已取消', 'AbortError')); }
    signal.addEventListener('abort', cancel, {once:true});
  });
}

async function conversationPost(path, body, signal) {
  const response = await fetch(path, {
    method:'POST', credentials:'same-origin', redirect:'error', cache:'no-store',
    signal:AbortSignal.any([scopedSignal(signal), AbortSignal.timeout(20000)]),
    headers:{'Content-Type':'application/json','Accept':'application/json','X-FS-Advisor-Action':'submit'},
    body:JSON.stringify(body)
  });
  if (response.status === 401 || response.status === 403) deny(response.status);
  if (!response.ok) {
    const error = Error(response.status < 500 ? '本次提炼未获准，请核对权限或条件。' : '提交状态待核对，请勿重复提交。');
    error.rejected = response.status < 500;
    throw error;
  }
  return response.json();
}

async function summarizeEvidence({kind, data, selection}, {signal, progress}) {
  const tool = {product_orders:'fc.query_product_orders', discount:'fc.query_discount_analysis', cohort:'fc.query_cohort_observation'}[kind];
  const evidenceId = data?.evidence_id;
  const fallback = kind === 'discount' && !data?.query && selection &&
    ['discount_new_customer','discount_type','discount_day'].includes(selection.group_by) ?
    {profile:selection.profile,start:selection.start,end:selection.end,group_by:selection.group_by,status:selection.status || 'all'} : null;
  const archivedQuery = data?.query || fallback;
  if (!tool || !/^(?:ws|cohort)_[a-f0-9]{24}$/.test(evidenceId || '') || !archivedQuery || typeof archivedQuery !== 'object') throw Error('本次结果缺少有效归档，暂不能提炼。');
  const key = kind + ':' + evidenceId;
  let item = insights.get(key);
  if (item?.reply) return item.reply;
  if (!item) {
    const requestId = 'data_' + crypto.randomUUID().replaceAll('-','');
    const query = {...archivedQuery};
    if (kind === 'discount' && typeof query.group_by === 'string') query.group_by = query.group_by.replace(/^discount_/, '');
    const text = `请实际调用 ${tool}，使用以下精确参数读取已归档数据：${JSON.stringify({...query,evidence_id:evidenceId})}。可按需充分核对数据，但最终只用中文写 1–2 句、约 80–120 汉字：挑一个最关键的经营判断和一条可执行建议，把必要限制融入句内；不要逐项复述字段或展示证据编号，不生成报告，不把整单金额说成单品收入，不将缺失或部分覆盖解释为零。请求标识 ${requestId} 仅用于核对，勿当业务数据或写进回复。`;
    item = {requestId, text, state:'new'};
    insights.set(key,item);
  }
  if (item.state === 'create_unknown') throw Error('会话创建结果待核对，请勿重复提交。');
  if (item.state === 'new') {
    progress('正在建立独立提炼会话…');
    try {
      const created = await conversationPost(conversations, {}, signal);
      if (!/^[A-Za-z0-9_-]{8,80}$/.test(created.conversation_id || '')) throw Error('invalid_conversation_id');
      item.conversationId = created.conversation_id;
      item.state = 'created';
    } catch (error) {
      if (error.rejected) insights.delete(key);
      else item.state = 'create_unknown';
      throw error.rejected ? error : Error('会话创建结果待核对，请勿重复提交。');
    }
  }
  const path = conversations + '/' + encodeURIComponent(item.conversationId);
  if (item.state === 'created') {
    progress('Hermes 正在读取本次归档…');
    try {
      const submitted = await conversationPost(path + '/turns', {text:item.text,client_request_id:item.requestId}, signal);
      if (!/^[A-Za-z0-9_-]{8,80}$/.test(submitted.turn_id || '')) throw Error('invalid_turn_id');
      item.turnId = submitted.turn_id;
      item.state = 'running';
    } catch (error) {
      if (error.rejected) { insights.delete(key); throw error; }
      item.state = 'submit_unknown';
    }
  }
  const started = Date.now();
  for (;;) {
    const response = await protectedRead(path, {credentials:'same-origin',redirect:'error',cache:'no-store',signal:scopedSignal(signal)}, deny);
    if (!response.ok) throw Error('提炼结果读取失败，稍后点击可继续查看。');
    const detail = await response.json();
    const turn = detail.turns?.find(value => value.turn_id === item.turnId || value.text === item.text);
    if (turn) {
      item.turnId = turn.turn_id;
      item.state = turn.state;
      if (turn.state === 'completed') {
        if (!turn.reply?.trim()) { insights.delete(key); throw Error('提炼已结束，但没有可展示的文字结论。'); }
        item.reply = turn.reply.trim();
        return item.reply;
      }
      if (['failed','cancelled','interrupted'].includes(turn.state)) { insights.delete(key); throw Error('本次提炼未完成，请稍后重新发起。'); }
    } else if (item.state === 'submit_unknown') throw Error('提交状态仍待核对，请勿重复提交。');
    if (Date.now() - started > 600000) throw Error('Hermes 仍在处理；稍后点击可继续查看，不会重新提交。');
    progress('Hermes 正在分析已归档数据，完成后将在这里显示…');
    await pause(2500, scopedSignal(signal));
  }
}

function stylesheet(root, path) {
  return new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = path;
    link.onload = resolve;
    link.onerror = () => reject(Error('style_unavailable'));
    root.append(link);
  });
}

async function start() {
  try {
    identity = await sessionIdentity(controller.signal);
    if (controller.signal.aborted) return;
    const moduleURL = new URL(document.body.dataset.moduleUrl || '', location.href);
    if (moduleURL.origin !== location.origin || !/^\/dashboard\/workspace-assets\/workspace-native-20261006-[a-f0-9]{12}\/data-workspace\.js$/.test(moduleURL.pathname)) throw Error('invalid_data_module');
    const {mountDataWorkspace} = await import(moduleURL.href);
    if (controller.signal.aborted) return;
    const root = host.attachShadow({mode: 'open'});
    await Promise.all([
      stylesheet(root, '/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/fs-ui.css'),
      stylesheet(root, '/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/native-alias.css'),
      stylesheet(root, '/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/business.css')
    ]);
    if (controller.signal.aborted) return;
    const yesterday = new Date(Date.now() + 8 * 3600000 - 86400000).toISOString().slice(0, 10);
    const read = (url, options = {}) => protectedRead(url, {...options, signal: scopedSignal(options.signal)}, deny);
    const write = (url, options) => {
      if (url !== '/dashboard/fs-home/advisor.json' || options.method !== 'POST') throw Error('observation_endpoint_only');
      return fetch(url, {...options, credentials: 'same-origin', redirect: 'error', signal: scopedSignal(options.signal)}).then(response => {
        if (response.status === 401 || response.status === 403) deny(response.status);
        return response;
      });
    };
    widget = mountDataWorkspace(root, {
      fetch: read, writeFetch: write, start: yesterday, end: yesterday,
      onHermes: identity.role === 'admin' ? summarizeEvidence : undefined
    });
    host.dataset.theme = document.documentElement.dataset.fsTheme || 'light';
    host.hidden = false;
    show('按需选择一个工具和日期范围后查询。');
  } catch (error) {
    if (controller.signal.aborted) return;
    if (error.status === 401 || error.status === 403) deny(error.status);
    else show('工具页暂时无法加载，请刷新后重试。', true);
  }
}

theme.value = window.FSTheme?.get() || 'light';
theme.addEventListener('change', () => window.FSTheme?.set(theme.value));
document.addEventListener('fs-theme-change', event => { host.dataset.theme = event.detail.resolved; });
document.addEventListener('visibilitychange', async () => {
  if (document.hidden || !identity || controller.signal.aborted) return;
  try {
    const next = await sessionIdentity(controller.signal);
    if (next.name !== identity.name || next.role !== identity.role || JSON.stringify(next.groups) !== JSON.stringify(identity.groups)) deny(403);
  } catch (error) { if (error.status === 401 || error.status === 403) deny(error.status); }
});
window.addEventListener('pagehide', () => { controller.abort(); widget?.dispose(); insights.clear(); });
start();
