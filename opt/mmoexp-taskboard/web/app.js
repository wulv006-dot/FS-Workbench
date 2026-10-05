/* ==========================================================================
   MMOEXP 站内项目工作任务台 · 前端逻辑
   数据源：/dashboard/tasks/api/*  （身份由 nginx 注入 X-Auth-User）
   权限：viewer 只读 / editor 只能改自己名下任务的进展与自检 / admin 全权
   ========================================================================== */
'use strict';

const API = '/dashboard/tasks/api';
const $ = id => document.getElementById(id);

const STATUS = {
  todo:    { label: '未开始', cls: 's-todo' },
  doing:   { label: '进行中', cls: 's-doing' },
  blocked: { label: '受阻',   cls: 's-blocked' },
  review:  { label: '待确认', cls: 's-review' },
  done:    { label: '已完成', cls: 's-done' }
};
const HORIZON = { short: '短期', long: '长期' };
const ROLE_LABEL = { admin: '管理员', editor: '执行', viewer: '只读' };

/* ---------------------------------------------------------------- 全局状态 */
let BOARD = { viewer: null, structure: { groups: [], depts: [] }, members: [], tasks: [] };
let TASKS = [];
let MEMBERS = [];
let GROUPS = [], DEPTS = [], PROJECTS = [];
let view = 'overview';
let scope = 'all';
let me = '';
let editingId = null;
let busy = false;
let pollTimer = null;
let filters = { project: '', dept: '', horizon: '', status: '', assignee: '', q: '' };

const auth = () => BOARD.viewer || { user: '', role: 'anonymous', isAdmin: false, canEditOwn: false };
const isAdmin = () => !!auth().isAdmin;
const canEditOwn = () => !!auth().canEditOwn;

/* ---------------------------------------------------------------- 基础工具 */
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const pad = n => String(n).padStart(2, '0');

function beijingToday() {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' })
    .format(new Date());
  return p;
}
function fmtTime(iso, withDate = true) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return '—';
  const p = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', hour12: false,
    ...(withDate ? { year: 'numeric', month: '2-digit', day: '2-digit' } : {}),
    hour: '2-digit', minute: '2-digit'
  }).format(d);
  return p.replace(/\//g, '-');
}
function daysLeft(due) {
  if (!due) return 9999;
  const d = new Date(due + 'T00:00:00+08:00');
  const t = new Date(beijingToday() + 'T00:00:00+08:00');
  return Math.round((d - t) / 86400000);
}
const byId = id => TASKS.find(t => t.id === Number(id));
const assigneeName = u => {
  if (!u) return '';
  const m = MEMBERS.find(x => x.username === u);
  return m && m.displayName && m.displayName !== u ? `${m.displayName}（${u}）` : u;
};

function stat(list) {
  const n = list.length;
  const done = list.filter(t => t.status === 'done').length;
  const doing = list.filter(t => t.status === 'doing').length;
  const blocked = list.filter(t => t.status === 'blocked').length;
  const unassigned = list.filter(t => !t.assignee).length;
  const unacked = list.filter(t => t.assignee && !t.ack).length;
  // 完成度按任务推进程度加权；自检清单是放行闸门，不参与折算（口径与看板说明一致）
  const progress = n ? Math.round(list.reduce((s, t) => s + (t.status === 'done' ? 1 : t.progress / 100), 0) / n * 100) : 0;
  return { n, done, doing, blocked, unassigned, unacked, progress };
}

/* ---------------------------------------------------------------- 提示条 */
let alertTimer = null;
function notify(kind, text) {
  const host = $('alert-host');
  const icon = kind === 'ok' ? 'i-check' : kind === 'err' ? 'i-warn' : 'i-info';
  host.innerHTML = `<div class="alert ${kind === 'ok' ? 'ok' : 'err'}" role="status">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><use href="#${icon}"/></svg>
    <span>${esc(text)}</span><button type="button" id="alert-x">关闭</button></div>`;
  const close = () => { host.innerHTML = ''; clearTimeout(alertTimer); };
  const x = $('alert-x');
  if (x) x.onclick = close;
  clearTimeout(alertTimer);
  alertTimer = setTimeout(close, kind === 'err' ? 9000 : 4000);
}

/* ---------------------------------------------------------------- API */
async function api(method, path, body) {
  const opt = { method, credentials: 'same-origin', cache: 'no-store', headers: {} };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(API + path, opt);
  } catch (e) {
    throw new Error('网络不可达，请检查登录状态后重试');
  }
  if (res.status === 401) {
    location.assign('/__auth/login?next=' + encodeURIComponent('/dashboard/tasks/'));
    throw new Error('会话已过期');
  }
  let data = null;
  const text = await res.text();
  if (text) { try { data = JSON.parse(text); } catch (e) { data = null; } }
  if (!res.ok) {
    const msg = (data && data.error) || `请求失败（HTTP ${res.status}）`;
    const detail = data && data.detail;
    const err = new Error(detail && detail.length ? `${msg}：${detail.join('；')}` : msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

async function loadBoard(quiet) {
  const data = await api('GET', '/board');
  BOARD = {
    viewer: data.viewer,
    structure: data.structure,
    members: data.members || [],
    serverTime: data.serverTime
  };
  TASKS = data.tasks || [];
  MEMBERS = BOARD.members;
  GROUPS = BOARD.structure.groups;
  DEPTS = BOARD.structure.depts;
  PROJECTS = GROUPS.flatMap(g => g.projects);
  if (isAdmin()) $('nav-members').hidden = false;
  $('sync-state').textContent = '已连接 · ' + fmtTime(BOARD.serverTime, false);
  $('sync-state').className = 'pill live';
  if (!quiet) { /* 首次渲染由 boot 统一处理 */ }
}

/* 用服务端返回的单条任务替换本地副本 */
function absorb(task) {
  const i = TASKS.findIndex(t => t.id === task.id);
  if (i >= 0) TASKS[i] = task; else TASKS.push(task);
  renderAll();
}

function guard(fn) {
  if (busy) return;
  busy = true;
  Promise.resolve()
    .then(fn)
    .catch(e => { if (e && e.message !== '会话已过期') notify('err', e.message); })
    .finally(() => { busy = false; });
}

/* ---------------------------------------------------------------- 渲染：总览 */
function kpi(icon, bg, label, val, foot) {
  return `<div class="kpi"><div class="k-top"><span>${esc(label)}</span>
    <span class="k-ico ${bg}"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><use href="#${icon}"/></svg></span></div>
    <div class="k-val">${esc(String(val))}<s>${esc(foot)}</s></div></div>`;
}

function scopeList() { return scope === 'all' ? TASKS : TASKS.filter(t => t.horizon === scope); }

function renderOverview() {
  const list = scopeList();
  const s = stat(list);
  const dueSoon = list.filter(t => t.status !== 'done' && daysLeft(t.due) <= 7 && daysLeft(t.due) >= 0).length;
  const overdue = list.filter(t => t.status !== 'done' && daysLeft(t.due) < 0).length;

  $('ov-sub').textContent = `${GROUPS.length} 个分组 · ${PROJECTS.length} 个游戏项目 · ${DEPTS.length} 个下发部门 · 共 ${TASKS.length} 条任务`;

  $('kpis').innerHTML = [
    kpi('i-board', 'bg-blue', '任务总数', s.n,
      `短期 ${list.filter(t => t.horizon === 'short').length} · 长期 ${list.filter(t => t.horizon === 'long').length}`),
    kpi('i-trend', 'bg-violet', '整体完成度', s.progress + '%', `${s.done} 条已完成`),
    kpi('i-clock', 'bg-blue', '进行中', s.doing, `${dueSoon} 条 7 日内到期`),
    kpi('i-block', s.blocked ? 'bg-danger' : 'bg-ok', '受阻', s.blocked, overdue ? `${overdue} 条已逾期` : '暂无逾期'),
    kpi('i-user-check', 'bg-warn', '待认领 / 待确认', s.unassigned + s.unacked,
      `待指派 ${s.unassigned} · 待确认 ${s.unacked}`)
  ].join('');

  $('project-groups').innerHTML = GROUPS.map(g => {
    const cards = g.projects.map(p => {
      const ps = stat(list.filter(t => t.project === p));
      const cls = ps.blocked ? 'danger' : (ps.progress >= 80 ? 'ok' : (ps.n && ps.progress < 35 ? 'warn' : ''));
      const chips = DEPTS.filter(d => list.some(t => t.project === p && t.dept === d))
        .map(d => {
          const ds = stat(list.filter(t => t.project === p && t.dept === d));
          return `<span class="tag${ds.blocked ? ' blk' : ''}">${esc(d)} ${ds.done}/${ds.n}</span>`;
        }).join('');
      const people = new Set(list.filter(t => t.project === p && t.assignee).map(t => t.assignee)).size;
      return `<button class="card" data-jump="${esc(p)}">
        <span class="card-top"><span class="card-name">${esc(p)}</span><span class="card-pct">${ps.progress}%</span></span>
        <span class="bar ${cls}"><i style="width:${ps.progress}%"></i></span>
        <span class="card-meta">${chips || '<span class="tag">暂无任务</span>'}</span>
        <span class="card-foot"><span>${ps.n} 条任务 · ${people} 人</span>
        ${ps.blocked ? `<span class="tag blk">受阻 ${ps.blocked}</span>` : `<span>完成 ${ps.done}</span>`}</span>
      </button>`;
    }).join('');
    return `<div class="group"><div class="group-h">${esc(g.name)}<i>${g.projects.length} 个项目</i></div><div class="cards">${cards}</div></div>`;
  }).join('');

  $('dept-rows').innerHTML = DEPTS.map(d => {
    const ds = stat(list.filter(t => t.dept === d));
    if (!ds.n) return `<tr><td>${esc(d)}</td><td>0</td><td colspan="4" style="color:var(--faint)">本范围内暂无任务</td></tr>`;
    return `<tr data-dept="${esc(d)}" style="cursor:pointer">
      <td><b style="font-weight:500">${esc(d)}</b></td><td>${ds.n}</td>
      <td><span class="mini-bar"><i style="width:${ds.progress}%"></i></span>${ds.progress}%</td>
      <td>${ds.doing}</td>
      <td>${ds.blocked ? `<span class="tag blk">${ds.blocked}</span>` : '0'}</td>
      <td>${ds.unassigned ? `<span class="tag asy">${ds.unassigned}</span>` : '0'}</td></tr>`;
  }).join('');

  const risks = list.filter(t => t.status === 'blocked' || (t.assignee && !t.ack) || !t.assignee)
    .sort((a, b) => daysLeft(a.due) - daysLeft(b.due));
  $('risk-count').textContent = risks.length + ' 项';
  $('risk-count').className = 'pill' + (risks.length ? ' danger' : '');
  $('risk-list').innerHTML = risks.length ? risks.slice(0, 8).map(t => {
    const d = daysLeft(t.due);
    const why = t.status === 'blocked' ? '受阻' : (!t.assignee ? '待指派' : '待接手确认');
    return `<div class="assign-row" style="border-top:0;border-bottom:1px solid var(--border)">
      <span style="flex:1"><b style="font-weight:500">${esc(t.title)}</b>
      <span class="mine-sub" style="margin-top:3px">${esc(t.project)} · ${esc(t.dept)} · ${why}${d < 0 ? ' · 已逾期 ' + (-d) + ' 天' : ' · 剩 ' + d + ' 天'}</span></span>
    </div>`;
  }).join('') : '<div class="empty">当前范围内没有受阻或待认领的任务</div>';

  const people = {};
  list.forEach(t => { if (!t.assignee) return; (people[t.assignee] = people[t.assignee] || []).push(t); });
  const sorted = Object.keys(people).sort((a, b) => {
    const oa = people[a].filter(t => t.status !== 'done').length;
    const ob = people[b].filter(t => t.status !== 'done').length;
    return ob - oa || a.localeCompare(b);
  });
  const shown = sorted.slice(0, 14);
  $('people-rows').innerHTML = shown.length ? shown.map(p => {
    const ps = people[p], open = ps.filter(t => t.status !== 'done');
    return `<tr><td><b style="font-weight:500">${esc(assigneeName(p))}</b></td><td>${open.length}</td>
      <td>${open.filter(t => t.horizon === 'short').length}</td>
      <td>${open.filter(t => t.horizon === 'long').length}</td>
      <td>${ps.filter(t => t.status === 'blocked').length || '0'}</td>
      <td style="color:var(--muted)">${[...new Set(ps.map(t => t.project))].map(esc).join('、')}</td></tr>`;
  }).join('') + (sorted.length > shown.length
    ? `<tr><td colspan="6" style="color:var(--faint);font-size:11px">另有 ${sorted.length - shown.length} 位接手人，可在「接手确认」视图查看完整分配</td></tr>`
    : '') : '<tr><td colspan="6" class="empty">当前还没有指派任务 · 请到「接手确认」为各部门指定接手人</td></tr>';
}

/* ---------------------------------------------------------------- 渲染：矩阵 */
function filtered() {
  const q = filters.q.trim().toLowerCase();
  return TASKS.filter(t =>
    (!filters.project || t.project === filters.project) &&
    (!filters.dept || t.dept === filters.dept) &&
    (!filters.horizon || t.horizon === filters.horizon) &&
    (!filters.status || t.status === filters.status) &&
    (!filters.assignee || (filters.assignee === '__none__' ? !t.assignee : t.assignee === filters.assignee)) &&
    (!q || t.title.toLowerCase().includes(q) || t.project.toLowerCase().includes(q))
  );
}

function renderMatrix() {
  const list = filtered();
  $('m-count').textContent = `显示 ${list.length} / ${TASKS.length} 条`;
  $('matrix-rows').innerHTML = list.length ? list.map(t => {
    const ok = t.checks.filter(c => c.done).length;
    const d = daysLeft(t.due);
    const late = d < 0 && t.status !== 'done';
    return `<tr data-id="${t.id}" style="cursor:pointer">
      <td class="t-proj">${esc(t.project)}</td>
      <td><span class="tag">${esc(t.dept)}</span></td>
      <td class="t-title">${esc(t.title)}</td>
      <td><span class="tag">${HORIZON[t.horizon]}</span></td>
      <td>${t.assignee ? esc(assigneeName(t.assignee)) + (t.ack ? '' : ' <span class="tag asy">待确认</span>') : '<span class="tag asy">待指派</span>'}</td>
      <td><span class="st ${STATUS[t.status].cls}">${STATUS[t.status].label}</span></td>
      <td><span class="mini-bar"><i style="width:${t.progress}%"></i></span>${t.progress}%</td>
      <td style="color:${late ? 'var(--danger)' : 'var(--muted)'};white-space:nowrap">${esc((t.due || '').slice(5))}${late ? ' 逾期' : ''}</td>
      <td class="chk">${ok}/${t.checks.length}</td></tr>`;
  }).join('') : '<tr><td colspan="9" class="empty">没有符合条件的任务</td></tr>';
}

/* ---------------------------------------------------------------- 渲染：接手确认 */
function renderAssign() {
  const s = stat(TASKS);
  $('assign-summary').textContent = `待指派 ${s.unassigned} · 已指派待确认 ${s.unacked} · 已确认 ${s.n - s.unassigned - s.unacked}`;
  $('assign-summary').className = 'pill' + (s.unassigned + s.unacked ? ' warn' : ' live');

  if (!isAdmin()) {
    const mine = TASKS.filter(t => t.assignee === me);
    $('assign-sub').textContent = '你名下任务的接手状态 · 指派与改派由管理员操作';
    $('assign-blocks').innerHTML = mine.length ? mine.map(t => `
      <div class="dept-block">
        <div class="dept-h"><b>${esc(t.project)}</b><span class="sub">${esc(t.dept)} · ${HORIZON[t.horizon]} · 截止 ${esc((t.due || '').slice(5))}</span>
          <span class="sum"><span class="confirm-chip ${t.ack ? 'c-yes' : 'c-no'}">${t.ack ? '已确认接手' : '待你确认'}</span>
          <button class="ghost sm" data-ack="${t.id}">${t.ack ? '撤回确认' : '确认接手'}</button></span></div>
        <div class="assign-row" style="border-top:0"><span class="a-title">${esc(t.title)}</span>
          <span class="st ${STATUS[t.status].cls}">${STATUS[t.status].label}</span></div>
      </div>`).join('') : '<div class="panel"><div class="empty">你名下暂无任务。等管理员在「任务矩阵」里把任务指派给你后，这里会出现确认入口。</div></div>';
    return;
  }

  $('assign-sub').textContent = '各部门填写接手人并确认接手 · 未确认的会一直挂在总览的待认领里';
  $('assign-blocks').innerHTML = DEPTS.map(d => {
    const list = TASKS.filter(t => t.dept === d);
    if (!list.length) return '';
    const ds = stat(list);
    const rows = list.map(t => `<div class="assign-row">
      <span class="a-proj">${esc(t.project)}</span>
      <span class="a-title">${esc(t.title)}<span class="mine-sub" style="margin-top:2px">${HORIZON[t.horizon]} · 截止 ${esc((t.due || '').slice(5))}</span></span>
      <input data-assign="${t.id}" value="${esc(t.assignee)}" placeholder="填写接手人账号" list="member-list">
      <span class="confirm-chip ${t.ack ? 'c-yes' : 'c-no'}">${t.ack ? '已确认' : (t.assignee ? '待确认' : '待指派')}</span>
      <button class="ghost sm" data-ack="${t.id}"${t.assignee ? '' : ' disabled'}>${t.ack ? '撤回' : '确认'}</button>
    </div>`).join('');
    return `<div class="dept-block">
      <div class="dept-h"><b>${esc(d)}</b><span class="sub">${ds.n} 条任务</span>
        <span class="sum">
          <span class="pill">待指派 ${ds.unassigned}</span>
          <span class="pill">待确认 ${ds.unacked}</span>
          <span class="pill live">完成度 ${ds.progress}%</span>
        </span></div>${rows}</div>`;
  }).join('');
}

/* ---------------------------------------------------------------- 渲染：我的自检 */
function renderMine() {
  const sel = $('who-select');
  const hint = document.querySelector('#view-mine .sub');
  if (isAdmin()) {
    sel.hidden = false;
    const people = [...new Set(TASKS.map(t => t.assignee).filter(Boolean))].sort();
    if (!me || !people.includes(me)) me = people[0] || '';
    sel.innerHTML = people.map(p => `<option value="${esc(p)}"${p === me ? ' selected' : ''}>${esc(assigneeName(p))}</option>`).join('')
      || '<option value="">暂无接手人</option>';
    if (hint) hint.textContent = '管理员可切换查看任意接手人 · 逐条勾选自检项 → 更新进展 → 提交确认（全程留时间戳与操作人）';
  } else {
    sel.hidden = true;
    me = auth().user;
    if (hint) hint.textContent = '逐条勾选自检项 → 更新进展 → 提交确认（留时间戳与操作人）';
  }

  const list = TASKS.filter(t => t.assignee === me);
  const editable = t => isAdmin() || (auth().role === 'editor' && t.assignee === auth().user);

  $('mine-list').innerHTML = list.length ? list.map(t => {
    const ok = t.checks.filter(c => c.done).length;
    const can = editable(t);
    const gate = ok === t.checks.length && t.checks.length > 0;
    return `<div class="mine-card" data-mine="${t.id}">
      <div class="mine-top">
        <span class="m-main">
          <div class="mine-title">${esc(t.title)}</div>
          <div class="mine-sub">${esc(t.project)} · ${esc(t.dept)} · ${HORIZON[t.horizon]} · 截止 ${esc(t.due)} · 自检 ${ok}/${t.checks.length}${t.ack ? ' · 已确认接手' : ' · 待确认接手'}</div>
        </span>
        <span class="st ${STATUS[t.status].cls}">${STATUS[t.status].label}</span>
      </div>
      <ul class="checklist">${t.checks.map((c, i) => `
        <li class="${c.done ? 'on' : ''}${can ? '' : ' readonly'}">
          <input type="checkbox" data-check="${t.id}:${i}" ${c.done ? 'checked' : ''} ${can ? '' : 'disabled'} id="ck-${t.id}-${i}">
          <label for="ck-${t.id}-${i}" style="cursor:${can ? 'pointer' : 'default'}">${esc(c.text)}</label>
          ${c.done && c.doneBy ? `<span class="who">${esc(c.doneBy)} · ${esc(fmtTime(c.doneAt, false))}</span>` : ''}
        </li>`).join('')}</ul>
      <div class="mine-foot">
        <span class="prog">进展
          <input type="range" min="0" max="100" step="5" value="${t.progress}" data-prog="${t.id}" ${can ? '' : 'disabled'}>
          <b style="font-weight:600;color:var(--ink)">${t.progress}%</b></span>
        <button class="ghost sm" data-open="${t.id}">${can ? '编辑详情' : '查看详情'}</button>
        <button class="primary" data-submit="${t.id}"${can && gate ? '' : ' disabled'}>提交确认</button>
      </div>
      ${can && !gate ? `<div class="mine-sub" style="margin-top:8px;color:var(--warn)">提交前需逐条通过全部自检项${t.checks.length ? '' : '（当前任务还没有自检项，请管理员补充）'}。</div>` : ''}
    </div>`;
  }).join('') : `<div class="panel"><div class="empty">${me ? '该接手人名下暂无任务' : '暂无可显示的接手人'}</div></div>`;
}

/* ---------------------------------------------------------------- 渲染：成员与权限 */
function renderMembers() {
  if (!isAdmin()) return;
  $('members-count').textContent = `共 ${MEMBERS.length} 个账号 · 管理员 ${MEMBERS.filter(m => m.role === 'admin').length} 人`;
  $('member-rows').innerHTML = MEMBERS.map(m => `<tr data-member="${esc(m.username)}">
    <td><b style="font-weight:500">${esc(m.username)}</b>${m.guard ? ' <span class="guard-tag">守护管理员</span>' : ''}</td>
    <td>${esc(m.displayName || '—')}</td>
    <td>${esc(m.dept || '—')}</td>
    <td>${m.guard
      ? '<span class="pill role-admin">admin · 管理员</span>'
      : `<select class="role-pick" data-role="${esc(m.username)}">
          <option value="viewer"${m.role === 'viewer' ? ' selected' : ''}>viewer · 只读</option>
          <option value="editor"${m.role === 'editor' ? ' selected' : ''}>editor · 可维护自己任务</option>
          <option value="admin"${m.role === 'admin' ? ' selected' : ''}>admin · 管理员</option>
        </select>`}</td>
    <td>${m.active ? '<span class="tag good">启用</span>' : '<span class="tag blk">已停用</span>'}</td>
    <td style="color:var(--muted)">${esc(m.note || '—')}</td></tr>`).join('');
}

/* ---------------------------------------------------------------- 抽屉 */
function closeDrawer() {
  $('drawer').classList.remove('open');
  $('drawer').setAttribute('aria-hidden', 'true');
  const s = $('scrim');
  if (s) s.remove();
  editingId = null;
}

function openDrawer(id) {
  const t = byId(id);
  if (!t) return;
  editingId = t.id;
  const admin = isAdmin();
  const mineTask = t.assignee && t.assignee === auth().user;
  const can = admin || (auth().role === 'editor' && mineTask);
  const full = admin;   // 结构性字段仅管理员可改

  $('d-eyebrow').textContent = `${t.project} · ${t.dept}`;
  $('d-title').textContent = t.title;
  $('d-sub').textContent = `${HORIZON[t.horizon]} · 截止 ${t.due}`
    + (t.assignee ? ` · 接手人 ${assigneeName(t.assignee)}${t.ack ? '（已确认）' : '（待确认）'}` : ' · 待指派');
  $('drawer').setAttribute('aria-hidden', 'false');

  const ro = v => esc(v || '—');
  let body = '';

  if (full) {
    body += `<div class="d-grid">
      <div class="field"><label>项目</label><select id="d-project">${PROJECTS.map(p => `<option${p === t.project ? ' selected' : ''}>${esc(p)}</option>`).join('')}</select></div>
      <div class="field"><label>下发部门</label><select id="d-dept">${DEPTS.map(d => `<option${d === t.dept ? ' selected' : ''}>${esc(d)}</option>`).join('')}</select></div>
    </div>
    <div class="field"><label>任务名称</label><input id="d-title-in" value="${esc(t.title)}"></div>
    <div class="d-grid">
      <div class="field"><label>类型</label><select id="d-horizon">
        <option value="short"${t.horizon === 'short' ? ' selected' : ''}>短期</option>
        <option value="long"${t.horizon === 'long' ? ' selected' : ''}>长期</option></select></div>
      <div class="field"><label>截止日期</label><input id="d-due" type="date" value="${esc(t.due)}"></div>
    </div>
    <div class="d-grid">
      <div class="field"><label>接手人账号</label><input id="d-assignee" value="${esc(t.assignee)}" placeholder="留空表示待指派" list="member-list" autocomplete="off"></div>
      <div class="field"><label>状态</label><select id="d-status">${Object.keys(STATUS).map(k => `<option value="${k}"${k === t.status ? ' selected' : ''}>${STATUS[k].label}</option>`).join('')}</select></div>
    </div>
    <div class="field"><label>进展 <b id="d-prog-lab" style="color:var(--accent-ink);font-weight:600">${t.progress}%</b></label>
      <input id="d-progress" type="range" min="0" max="100" step="5" value="${t.progress}" style="padding:0"></div>
    <div class="field"><label>自检清单（每行一条，行首 [x] 表示已通过）</label>
      <textarea id="d-checks">${esc(t.checks.map(c => (c.done ? '[x] ' : '[ ] ') + c.text).join('\n'))}</textarea></div>
    <div class="field"><label>变更说明（写入历史）</label><input id="d-note" placeholder="例：完成采招比价，待运营确认" autocomplete="off"></div>`;
  } else {
    body += `<div class="d-grid">
      <div class="field"><label>项目 / 部门</label><div>${ro(t.project)} · ${ro(t.dept)}</div></div>
      <div class="field"><label>类型 / 截止</label><div>${HORIZON[t.horizon]} · ${ro(t.due)}</div></div>
    </div>
    <div class="field"><label>接手人</label><div>${t.assignee ? ro(assigneeName(t.assignee)) : '待指派'}</div></div>`;
    if (can) {
      body += `<div class="field"><label>状态</label><select id="d-status">${Object.keys(STATUS).map(k => `<option value="${k}"${k === t.status ? ' selected' : ''}>${STATUS[k].label}</option>`).join('')}</select></div>
      <div class="field"><label>进展 <b id="d-prog-lab" style="color:var(--accent-ink);font-weight:600">${t.progress}%</b></label>
        <input id="d-progress" type="range" min="0" max="100" step="5" value="${t.progress}" style="padding:0"></div>
      <div class="field"><label>变更说明（写入历史）</label><input id="d-note" placeholder="例：已完成竞品采集复核" autocomplete="off"></div>`;
    } else {
      body += `<div class="field"><label>状态 / 进展</label><div>${STATUS[t.status].label} · ${t.progress}%</div></div>
      <div class="note lock" style="margin:0"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><use href="#i-lock"/></svg>
        <p>只读视图：你不是这条任务的接手人，或当前角色没有编辑权限。</p></div>`;
    }
    body += `<div class="field"><label>自检清单</label>
      <ul class="checklist" style="margin:0">${t.checks.map(c => `
        <li class="${c.done ? 'on' : ''} readonly"><span class="mark">${c.done
          ? '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><use href="#i-check"/></svg>'
          : '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><use href="#i-circle"/></svg>'}</span>
        <span>${esc(c.text)}</span>${c.doneBy ? `<span class="who">${esc(c.doneBy)}</span>` : ''}</li>`).join('') || '<li class="readonly">暂无自检项</li>'}</ul></div>`;
  }

  body += `<div class="field"><label>操作历史</label><div class="log" id="d-log">读取中…</div></div>`;
  $('d-body').innerHTML = body;

  const foot = [];
  if (admin) foot.push('<button class="ghost danger-btn" id="d-delete">删除任务</button>');
  foot.push('<span class="spacer"></span>');
  if (admin) foot.push('<button class="primary" id="d-save">保存修改</button>');
  else if (can) foot.push('<button class="primary" id="d-save">保存进展</button>');
  foot.push('<button class="ghost" id="d-close2">关闭</button>');
  $('d-foot').innerHTML = foot.join('');

  const scrim = document.createElement('div');
  scrim.className = 'scrim'; scrim.id = 'scrim';
  scrim.onclick = closeDrawer;
  document.body.appendChild(scrim);
  $('drawer').classList.add('open');

  const prog = $('d-progress');
  if (prog) prog.oninput = () => { $('d-prog-lab').textContent = prog.value + '%'; };

  api('GET', `/tasks/${t.id}/events`).then(d => {
    const host = $('d-log');
    if (!host) return;
    const rows = (d.events || []).slice(0, 12);
    host.innerHTML = rows.length ? rows.map(e => `<span>${esc(fmtTime(e.ts))} · ${esc(e.actor)} · ${
      esc(e.action === 'check' ? `自检「${e.note}」${e.newValue === 'done' ? '通过' : '取消'}`
        : e.action === 'submit' ? e.note
        : e.action === 'ack' ? '确认接手'
        : e.action === 'unack' ? '撤回接手确认'
        : e.action === 'create' ? '新建任务'
        : e.action === 'delete' ? '删除任务'
        : e.action === 'note' ? e.note
        : `${e.field} ${esc(e.oldValue)} → ${esc(e.newValue)}`)}</span>`).join('')
      : '<span>暂无操作记录</span>';
  }).catch(() => { const host = $('d-log'); if (host) host.textContent = '历史读取失败'; });
}

async function saveDrawer() {
  const t = byId(editingId);
  if (!t) return;
  const val = id => { const e = $(id); return e ? e.value : null; };
  const note = (val('d-note') || '').trim();
  let payload;

  if (isAdmin()) {
    payload = {
      project: val('d-project'), dept: val('d-dept'), title: (val('d-title-in') || '').trim(),
      horizon: val('d-horizon'), due: val('d-due'), assignee: (val('d-assignee') || '').trim(),
      status: val('d-status'), progress: Number(val('d-progress')),
      checks: (val('d-checks') || '').split('\n').map(l => l.trim()).filter(Boolean).map(l => ({
        done: /^\[x\]/i.test(l), text: l.replace(/^\[[ x]\]\s*/i, '')
      }))
    };
  } else {
    payload = { status: val('d-status'), progress: Number(val('d-progress')) };
  }
  if (note) payload.note = note;

  const task = await api('PATCH', `/tasks/${t.id}`, payload);
  absorb(task);
  notify('ok', `已保存任务 #${task.id}`);
  closeDrawer();
}

/* 成员下拉候选 */
function refreshMemberDatalist() {
  if ($('member-list')) return;
  const dl = document.createElement('datalist');
  dl.id = 'member-list';
  dl.innerHTML = MEMBERS.map(m => `<option value="${esc(m.username)}">${esc(m.displayName || m.username)}</option>`).join('');
  document.body.appendChild(dl);
}

/* ---------------------------------------------------------------- 视图切换 */
const VIEW_TITLE = { overview: '项目总览', matrix: '任务矩阵', assign: '接手确认', mine: '我的自检', members: '成员与权限' };

function setView(v) {
  view = v;
  ['overview', 'matrix', 'assign', 'mine', 'members'].forEach(k => {
    const el = $('view-' + k);
    if (el) el.hidden = (k !== v);
  });
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.view === v));
  $('crumb').textContent = VIEW_TITLE[v] || v;
  closeDrawer();
  renderAll();
}

function renderAll() {
  const s = stat(TASKS);
  const a = auth();
  $('nav-count').textContent = TASKS.length;
  $('nav-assign').textContent = s.unassigned + s.unacked;
  $('sb-name').textContent = a.user || '未识别';
  $('sb-role').textContent = (ROLE_LABEL[a.role] || a.role) + ' · ' + (a.isAdmin ? '可编辑全部任务' : a.role === 'editor' ? '只能维护自己名下任务' : '只读');
  $('sb-avatar').textContent = (a.user || '--').slice(0, 2);
  $('who-pill').textContent = `${a.user || '—'} · ${ROLE_LABEL[a.role] || a.role}`;
  $('who-pill').className = 'pill role-' + a.role;
  $('btn-new').hidden = !a.isAdmin;

  if (view === 'overview') renderOverview();
  if (view === 'matrix') renderMatrix();
  if (view === 'assign') renderAssign();
  if (view === 'mine') renderMine();
  if (view === 'members') renderMembers();
}

function initFilters() {
  const keep = { ...filters };
  const fill = (id, arr, all, cur) => {
    const el = $(id);
    el.innerHTML = `<option value="">${all}</option>` + arr.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
    el.value = arr.includes(cur) ? cur : '';
  };
  fill('f-project', PROJECTS, '全部项目', keep.project);
  fill('f-dept', DEPTS, '全部部门', keep.dept);
  $('f-status').innerHTML = '<option value="">全部状态</option>' +
    Object.keys(STATUS).map(k => `<option value="${k}">${STATUS[k].label}</option>`).join('');
  $('f-status').value = STATUS[keep.status] ? keep.status : '';
  $('f-assignee').innerHTML = '<option value="">全部接手人</option><option value="__none__">待指派</option>' +
    [...new Set(TASKS.map(t => t.assignee).filter(Boolean))].sort()
      .map(v => `<option value="${esc(v)}">${esc(assigneeName(v))}</option>`).join('');
  $('f-assignee').value = keep.assignee;
  $('f-horizon').value = keep.horizon;

  const deptSel = $('mb-dept');
  if (deptSel) {
    deptSel.innerHTML = '<option value="">未指定</option>' + DEPTS.map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join('');
  }
}

/* ---------------------------------------------------------------- 事件绑定 */
document.addEventListener('click', e => {
  const nav = e.target.closest('#nav button');
  if (nav) return setView(nav.dataset.view);

  const card = e.target.closest('[data-jump]');
  if (card) {
    filters = { project: card.dataset.jump, dept: '', horizon: scope === 'all' ? '' : scope, status: '', assignee: '', q: '' };
    initFilters();
    $('f-q').value = '';
    return setView('matrix');
  }
  const drow = e.target.closest('[data-dept]');
  if (drow) {
    filters = { project: '', dept: drow.dataset.dept, horizon: scope === 'all' ? '' : scope, status: '', assignee: '', q: '' };
    initFilters();
    $('f-q').value = '';
    return setView('matrix');
  }
  const row = e.target.closest('#matrix-rows tr[data-id]');
  if (row) return openDrawer(row.dataset.id);

  const open = e.target.closest('[data-open]');
  if (open) return openDrawer(open.dataset.open);

  const ack = e.target.closest('[data-ack]');
  if (ack) {
    const t = byId(ack.dataset.ack);
    if (!t) return;
    const input = document.querySelector(`[data-assign="${t.id}"]`);
    const wantAssign = input ? input.value.trim() : t.assignee;
    return guard(async () => {
      let cur = t;
      if (isAdmin() && wantAssign !== t.assignee) {
        cur = await api('PATCH', `/tasks/${t.id}`, { assignee: wantAssign });
      }
      if (!cur.assignee) { notify('err', '请先填写接手人账号再确认'); return; }
      const out = await api('POST', `/tasks/${t.id}/ack`, { on: !cur.ack });
      absorb(out);
      notify('ok', out.ack ? `已确认接手：${assigneeName(out.assignee)}` : '已撤回接手确认');
    });
  }

  const sub = e.target.closest('[data-submit]');
  if (sub) {
    const t = byId(sub.dataset.submit);
    if (!t) return;
    return guard(async () => {
      const out = await api('POST', `/tasks/${t.id}/submit`);
      absorb(out);
      notify('ok', `「${out.title}」自检全部通过，已提交确认为已完成`);
    });
  }

  if (e.target.id === 'btn-new') {
    return guard(async () => {
      const payload = {
        project: PROJECTS[0], dept: DEPTS[0], horizon: 'short', title: '新任务',
        due: new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10),
        checks: ['自检项一']
      };
      const t = await api('POST', '/tasks', payload);
      absorb(t);
      setView('matrix');
      openDrawer(t.id);
      notify('ok', '已创建任务草稿，请完善后保存');
    });
  }

  if (e.target.id === 'btn-refresh') {
    return guard(async () => {
      await loadBoard(true);
      initFilters();
      refreshMemberDatalist();
      renderAll();
      notify('ok', '已刷新到最新数据');
    });
  }

  if (e.target.id === 'btn-member-save') {
    return guard(async () => {
      const username = ($('mb-user').value || '').trim();
      const payload = {
        username, displayName: ($('mb-name').value || '').trim(),
        dept: $('mb-dept').value, role: $('mb-role').value
      };
      if (!username) { notify('err', '请填写统一登录账号'); return; }
      await api('POST', '/members', payload);
      await loadBoard(true);
      refreshMemberDatalist();
      renderAll();
      $('mb-user').value = ''; $('mb-name').value = '';
      notify('ok', `已保存成员 ${username}`);
    });
  }

  if (e.target.id === 'd-close' || e.target.id === 'd-close2') return closeDrawer();
  if (e.target.id === 'd-save') return guard(saveDrawer);
  if (e.target.id === 'd-delete') {
    const t = byId(editingId);
    if (!t) return;
    if (!confirm(`确认删除任务「${t.title}」？该操作不可撤销。`)) return;
    return guard(async () => {
      await api('DELETE', `/tasks/${t.id}`);
      TASKS = TASKS.filter(x => x.id !== t.id);
      closeDrawer();
      renderAll();
      notify('ok', `已删除任务「${t.title}」`);
    });
  }
  const seg = e.target.closest('#ov-range button');
  if (seg) {
    scope = seg.dataset.scope;
    document.querySelectorAll('#ov-range button').forEach(b => b.classList.toggle('active', b === seg));
    return renderOverview();
  }
});

document.addEventListener('change', e => {
  const f = e.target;
  if (f.id && f.id.startsWith('f-') && f.id !== 'f-q') {
    filters = { ...filters, [f.id.slice(2)]: f.value };
    return renderMatrix();
  }
  if (f.id === 'who-select') { me = f.value; return renderMine(); }

  const ck = f.dataset && f.dataset.check;
  if (ck) {
    const [id, i] = ck.split(':');
    const t = byId(id);
    if (!t) return;
    const want = f.checked;
    return guard(async () => {
      const out = await api('POST', `/tasks/${t.id}/checks`, { idx: Number(i), done: want });
      absorb(out);
      notify('ok', `自检「${out.checks[Number(i)].text}」${want ? '已通过' : '已取消'}`);
    });
  }

  const rp = f.dataset && f.dataset.role;
  if (rp) {
    return guard(async () => {
      await api('POST', '/members', { username: rp, role: f.value });
      await loadBoard(true);
      refreshMemberDatalist();
      renderAll();
      notify('ok', `${rp} 的角色已更新为 ${ROLE_LABEL[f.value]}`);
    });
  }

  const asg = f.dataset && f.dataset.assign;
  if (asg) {
    const t = byId(asg);
    if (!t) return;
    const v = f.value.trim();
    if (v === t.assignee) return;
    return guard(async () => {
      const out = await api('PATCH', `/tasks/${t.id}`, { assignee: v });
      absorb(out);
      notify('ok', v ? `已指派给 ${assigneeName(v)}，等待其确认接手` : '已取消指派');
    });
  }
});

document.addEventListener('input', e => {
  if (e.target.id === 'f-q') {
    filters.q = e.target.value;
    return renderMatrix();
  }
  const p = e.target.dataset && e.target.dataset.prog;
  if (p) {
    const t = byId(p);
    if (!t) return;
    t.progress = Number(e.target.value);
    const b = e.target.parentElement.querySelector('b');
    if (b) b.textContent = t.progress + '%';
  }
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeDrawer();
});
window.addEventListener('popstate', closeDrawer);

/* ---------------------------------------------------------------- 轮询与启动 */
function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    if (document.hidden || editingId) return;
    loadBoard(true).then(() => { initFilters(); refreshMemberDatalist(); renderAll(); }).catch(() => {
      $('sync-state').textContent = '同步中断 · 请刷新';
      $('sync-state').className = 'pill danger';
    });
  }, 60000);
}

async function boot() {
  try {
    await loadBoard();
    initFilters();
    refreshMemberDatalist();
    setView('overview');
    $('boot').hidden = true;
    startPolling();
  } catch (e) {
    $('boot').innerHTML = `<div class="box"><svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#b0403a" stroke-width="1.6" stroke-linecap="round"><use href="#i-warn"/></svg>
      <span style="color:#b0403a">${esc(e.message || '任务台数据读取失败')}</span>
      <button class="ghost" id="boot-retry">重新加载</button></div>`;
    const r = $('boot-retry');
    if (r) r.onclick = () => location.reload();
  }
}

boot();
