const el = id => document.getElementById(id);
const filters = el('filters');
const emailForm = el('email-search');
const integer = new Intl.NumberFormat('zh-CN');
const dollars = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'});
const stageNames = {
  recent: '近期', silent: '沉默', lost: '流失', long_lost: '长期流失', unverified: '待核',
  silent_wakeup: '沉默唤醒', lost_return: '流失回流', any: '回流客户',
  first_order: '站内首单', repeat: '复购', purchase: '追加购买', enter: '进入阶段',
  new: '新客', old: '老客', unknown: '待核',
};
const errorText = {
  users_summary_query_expired: '查询已过期，请重新发起。',
  snapshot_version_retired: '旧版快照已退役，请重新查询。',
  users_summary_busy: '正在计算另一条查询，请稍后重试。',
  weekly_initial_publication_pending: '日更结果尚未发布。',
  user_scope_denied: '当前账号没有访问权限。',
  scope_or_admin_required: '当前账号没有访问权限。',
  login_required: '登录已失效，请重新登录。',
  invalid_user_query: '请核对日期、时间窗和筛选条件。',
  snapshot_not_found: '快照或客户记录不可用，请重新查询。',
};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const n = value => value == null ? '—' : integer.format(value);
const money = value => value == null ? '—' : dollars.format(Number(value));
const rate = value => value == null ? '—' : (value * 100).toFixed(2) + '%';
const when = value => value ? value.slice(0, 19).replace('T', ' ') : '—';
let catalog;
let current;
let memberView;

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value != null) node.textContent = value;
  if (className) node.className = className;
  return node;
}

function gameName(gid) {
  return catalog.projects[gid]?.label || gid;
}

function dateShift(value, days) {
  const day = new Date(value + 'T00:00:00Z');
  day.setUTCDate(day.getUTCDate() + days);
  return day.toISOString().slice(0, 10);
}

function reportDates(info, origin) {
  const cutoff = info?.cutoff?.slice(0, 10);
  if (!cutoff || !origin || origin >= cutoff) return null;
  const end = dateShift(cutoff, -1);
  const firstMonth = origin.slice(0, 7);
  const previousMonth = dateShift(cutoff.slice(0, 7) + '-01', -1).slice(0, 7);
  const start = dateShift(cutoff, -7);
  return {cutoff, end, firstMonth, lastMonth: previousMonth < firstMonth ? firstMonth : previousMonth,
          start: start < origin ? origin : start};
}

async function request(path, parameters, body) {
  const url = path + (parameters ? '?' + new URLSearchParams(parameters).toString() : '');
  const options = {cache: 'no-store', credentials: 'same-origin', redirect: 'error',
                   signal: AbortSignal.timeout(25000)};
  if (body) Object.assign(options, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const response = await fetch(url, options);
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorText[value.error] || (response.status === 403 ? errorText.user_scope_denied : '读取失败，请重试。'));
  return {status: response.status, value};
}

function table(host, columns, rows) {
  const grid = element('table');
  const heading = grid.createTHead().insertRow();
  for (const column of columns) {
    const title = element('th', column);
    title.scope = 'col';
    heading.append(title);
  }
  const body = grid.createTBody();
  for (const row of rows) {
    const entry = body.insertRow();
    row.forEach((value, index) => {
      const cell = element(index === 0 ? 'th' : 'td');
      if (index === 0) cell.scope = 'row';
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value ?? '—';
      entry.append(cell);
    });
  }
  host.replaceChildren(rows.length ? grid : element('p', '所选范围暂无数据。', 'muted'));
}

function memberButton(label, group, count) {
  const button = element('button', typeof count === 'number' ? null : label);
  button.type = 'button';
  if (typeof count === 'number') {
    button.append(element('span', label), element('strong', n(count)));
    button.setAttribute('aria-label', label + ' ' + n(count) + ' 人，查看名单');
  }
  button.addEventListener('click', () => openMembers(group, label));
  return button;
}

function amount(value) {
  return money(value.known_usd) + (value.unknown_orders ? ' · 含 ' + n(value.unknown_orders) + ' 笔金额未知' : '');
}

function renderCohorts(data) {
  const windows = data.query.windows;
  const batches = data.cohorts.batches;
  const rows = batches.map(batch => [
    batch.month,
    ...batch.windows.map(window => {
      const button = memberButton(batch.month + ' · ' + window.days + ' 天', window.group);
      button.className = 'cohort-cell' + (window.observing || window.coverage_gap ? ' is-incomplete' : '');
      button.style.setProperty('--heat', (4 + 28 * (window.rate || 0)) + '%');
      button.replaceChildren(
        element('strong', rate(window.rate) + ' · ' + n(window.numerator) + '/' + n(window.denominator) + ' 人'),
        element('small', '观察中 ' + n(window.observing) + ' · 覆盖缺口 ' + n(window.coverage_gap)),
        element('small', '复购金额 ' + amount(window.repeat_amount)),
        element('small', '复购人均 ' + money(window.repeat_per_customer_usd)),
      );
      button.setAttribute('aria-label', batch.month + ' ' + window.days + ' 天，复购率 ' +
          rate(window.rate) + '，' + button.textContent + '，查看名单');
      return button;
    }),
    n(batch.pending_classification),
  ]);
  table(el('cohort-heat'), ['首单批次', ...windows.map(days => days + ' 天'), '新老客待核'], rows);
  const spans = windows.map((days, index) => '[' + (index ? windows[index - 1] : 1) + ', ' + days + ') 天');
  table(el('first-repeat'), ['首单批次', ...spans, '窗口内未复购'],
      batches.map(batch => [batch.month, ...batch.first_repeat.counts.map(n)]));
  table(el('silent-return'), ['首单批次', '回流人数', '满窗且前 ' + data.query.return_after +
      ' 天未复购', '回流率', '回流金额'],
      batches.map(({month, silent_return: value}) => [
        month, n(value.numerator), n(value.denominator), rate(value.rate), amount(value.return_amount),
      ]));
}

function renderTrend(rows) {
  const host = el('return-trend');
  const drawing = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  drawing.setAttribute('viewBox', '0 0 740 176');
  drawing.setAttribute('class', 'trend');
  drawing.setAttribute('role', 'img');
  drawing.setAttribute('aria-label', '每日沉默唤醒与流失回流人数');
  const draw = (tag, attributes, text) => {
    const node = document.createElementNS(drawing.namespaceURI, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text != null) node.textContent = text;
    drawing.append(node);
  };
  const max = Math.max(1, ...rows.flatMap(row => [row.silent_wakeup, row.lost_return].filter(Number.isFinite)));
  const x = i => 46 + i * 650 / Math.max(1, rows.length - 1);
  const y = value => 142 - value * 120 / max;
  for (const count of new Set([0, Math.round(max / 2), max])) {
    draw('line', {x1: 46, x2: 700, y1: y(count), y2: y(count), stroke: 'currentColor', opacity: '.2'});
    draw('text', {x: 38, y: y(count) + 4, 'text-anchor': 'end'}, n(count));
  }
  for (const [key, css] of [['silent_wakeup', 'silent'], ['lost_return', 'lost']]) {
    let path = '';
    rows.forEach((row, index) => {
      if (row[key] == null) return;
      const connect = index > 0 && rows[index - 1][key] != null;
      path += (connect ? ' L' : ' M') + x(index) + ' ' + y(row[key]);
      if (!connect && rows[index + 1]?.[key] == null) {
        path += ' l0.1 0';
      }
    });
    draw('path', {class: css, d: path, 'stroke-linecap': 'round'});
  }
  const ticks = new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1]);
  for (const index of ticks) {
    if (rows[index]) draw('text', {x: x(index), y: 165, 'text-anchor': 'middle'}, rows[index].date.slice(5));
  }
  const details = element('details');
  const values = element('div', null, 'table-scroll');
  details.append(element('summary', '查看每日回流人数'), values);
  table(values, ['上海日期', '沉默唤醒', '流失回流'],
      rows.map(row => [row.date, n(row.silent_wakeup), n(row.lost_return)]));
  host.replaceChildren(drawing, element('p', '蓝色为沉默唤醒，橙色为流失回流。缺失日期留空。', 'muted'), details);
}

function renderStages(data) {
  const sections = data.stages;
  el('stage-basis').textContent = '仅统计所选期间至少有一笔有效订单的客户，阶段截至 ' + data.observation_date + '。';
  for (const [id, values] of [['stage-counts', sections.stages], ['stage-inflow', sections.inflow], ['stage-returns', sections.returns]]) {
    el(id).replaceChildren(...values.map(({kind, group, count}) => {
      const item = element('li');
      item.append(memberButton(stageNames[kind], group, count));
      return item;
    }));
  }
  renderTrend(sections.daily_returns);
  el('cross-flow').hidden = data.query.game !== 'all';
  if (sections.cross_game_flow) {
    table(el('cross-table'), ['流失游戏', '近期购买游戏', '人数'],
        sections.cross_game_flow.map(({source, destination, group, count}) => [
          gameName(source), gameName(destination),
          memberButton(gameName(source) + ' → ' + gameName(destination), group, count),
        ]));
  }
}

function pending(flag) {
  filters.querySelectorAll('button[type=submit]').forEach(button => { button.disabled = flag; });
  filters.setAttribute('aria-busy', String(flag));
}

async function query(event) {
  event?.preventDefault();
  if (el('run-query').disabled) return;
  pending(true);
  current = memberView = null;
  emailForm.querySelector('button').disabled = true;
  for (const id of ['member-panel', 'cohorts', 'stages']) el(id).hidden = true;
  el('email-status').textContent = '';
  el('query-status').textContent = '正在读取用户分析…';
  try {
    const args = Object.fromEntries(new FormData(filters));
    args.end_exclusive = dateShift(args.end, 1);
    delete args.end;
    let result = await request('/dashboard/users/data.json', args);
    for (let attempts = 0; result.status === 202; attempts += 1) {
      if (attempts >= 24) throw new Error('计算等待超时，请重新发起查询。');
      el('query-status').textContent = '计算中，完成后自动显示。';
      await sleep(Math.max(1, result.value.retryAfter || 5) * 1000);
      result = await request('/dashboard/users/data.json', {query_id: result.value.query_id});
    }
    const data = result.value;
    if (data.contract_version !== 'fs-users-v4' || !data.snapshot_id) throw new Error('用户分析版本尚未就绪。');
    renderCohorts(data);
    renderStages(data);
    current = data;
    el('metadata').textContent = '数据截止 ' + data.observation_date + ' · 配置 v' + data.config_version +
        ' · 订单覆盖缺 ' + n(data.coverage.order_missing_days) + ' 天';
    el('query-status').textContent = data.coverage.new_customer_flags?.status === 'complete' ? '' :
        'ES 新老客标记覆盖有缺口，匹配不到的首单计入待核。';
    for (const id of ['cohorts', 'stages']) el(id).hidden = false;
    emailForm.querySelector('button').disabled = false;
  } catch (error) {
    el('query-status').textContent = error.message;
  } finally {
    pending(false);
  }
}

async function openMembers(group, label) {
  memberView = {group, label, snapshot: current.snapshot_id, cursors: [''], next: ''};
  el('member-panel').hidden = false;
  el('member-title').textContent = label + '名单';
  el('member-title').focus();
  await memberPage(memberView);
}

async function memberPage(view) {
  el('member-status').textContent = '正在读取名单…';
  for (const id of ['previous', 'next', 'export']) el(id).disabled = true;
  try {
    const {value} = await request('/dashboard/users/private.json', {
      action: 'members', snapshot_id: view.snapshot, group: view.group,
      limit: 50, cursor: view.cursors[view.cursors.length - 1],
    });
    if (view !== memberView) return;
    view.next = value.next_cursor;
    table(el('members'), ['客户邮箱', '站内首单', '末次购买', '阶段', '详情'], value.rows.map(row => [
      row.email, when(row.first_paid_at), when(row.last_paid_at), stageNames[row.stage],
      detailsButton(row.customer_id, view.snapshot),
    ]));
    el('member-status').textContent = '共 ' + n(value.total) + ' 人 · 第 ' + view.cursors.length + ' 页';
    el('previous').disabled = view.cursors.length <= 1;
    el('next').disabled = !view.next;
    el('export').disabled = !value.total;
  } catch (error) {
    if (view === memberView) {
      el('members').replaceChildren();
      el('member-status').textContent = error.message;
    }
  }
}

function detailsButton(id, snapshot) {
  const button = element('button', '查看订单');
  button.type = 'button';
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const {value} = await request('/dashboard/users/private.json', {action: 'detail', snapshot_id: snapshot, customer_id: id});
      if (current?.snapshot_id === snapshot) showDetail(value);
    } catch (error) {
      el('member-status').textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function showDetail(detail) {
  el('detail-email').textContent = detail.email;
  table(el('detail-timeline'), ['时间', '事件', '阶段'], detail.timeline.map(event => [
    when(event.at), stageNames[event.kind], stageNames[event.stage],
  ]));
  table(el('detail-orders'), ['付款时间', '游戏', '订单号', 'UID', '整单金额'], detail.orders.map(order => [
    when(order.paid_at), gameName(order.project_id), order.order_no, order.uid, money(order.amount_usd),
  ]));
  el('customer-detail').showModal();
}

function csvCell(value) {
  let text = String(value ?? '');
  if (/^[\s]*[=+\-@\t\r\n]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}

async function exportMembers() {
  const view = memberView;
  const button = el('export');
  button.disabled = true;
  try {
    const {value} = await request('/dashboard/users/private.json', {action: 'export', snapshot_id: view.snapshot, group: view.group});
    if (view !== memberView) return;
    if (value.rows.length !== value.total) throw new Error('名单导出数据不完整。');
    const rows = [['邮箱', '客户 ID', '站内首单', '末次购买', '阶段'],
      ...value.rows.map(row => [row.email, row.customer_id, row.first_paid_at, row.last_paid_at, stageNames[row.stage]])];
    const blob = new Blob(['\uFEFF', rows.map(row => row.map(csvCell).join(',')).join('\r\n')], {type: 'text/csv;charset=utf-8'});
    const href = URL.createObjectURL(blob);
    const link = element('a');
    link.href = href;
    link.download = 'FS-users-' + view.snapshot + '.csv';
    link.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  } catch (error) {
    if (view === memberView) el('member-status').textContent = error.message;
  } finally {
    if (view === memberView) button.disabled = false;
  }
}

filters.addEventListener('submit', query);
el('export').addEventListener('click', exportMembers);
el('previous').addEventListener('click', () => { memberView.cursors.pop(); memberPage(memberView); });
el('next').addEventListener('click', () => { memberView.cursors.push(memberView.next); memberPage(memberView); });
el('customer-detail').addEventListener('close', () => {
  el('detail-email').textContent = '';
  el('detail-timeline').replaceChildren();
  el('detail-orders').replaceChildren();
});

emailForm.addEventListener('submit', async event => {
  event.preventDefault();
  const snapshot = current?.snapshot_id;
  if (!snapshot) return;
  const button = emailForm.querySelector('button');
  button.disabled = true;
  el('email-status').textContent = '正在查找…';
  try {
    const {value} = await request(emailForm.action, null, {snapshot_id: snapshot, email: emailForm.elements.email.value});
    if (current?.snapshot_id !== snapshot) return;
    el('email-status').textContent = value.found ? '' : '当前快照范围内未找到有效购买记录。';
    if (value.found) showDetail(value);
  } catch (error) {
    if (current?.snapshot_id === snapshot) el('email-status').textContent = error.message;
  } finally {
    if (current?.snapshot_id === snapshot) button.disabled = false;
  }
});

async function initialize() {
  try {
    const response = await request('/dashboard/users/data.json', {action: 'catalog'});
    catalog = response.value;
    const origin = catalog.history_backfill_start?.slice(0, 10);
    const dates = reportDates(catalog.weekly_update, origin);
    if (catalog.contract_version !== 'fs-users-v4' || !dates) throw new Error('当前用户分析数据尚未发布。');
    const {start, end, firstMonth, lastMonth} = dates;
    for (const [gid, game] of Object.entries(catalog.projects)) {
      const option = element('option', game.label);
      option.value = gid;
      filters.elements.game.append(option);
    }
    filters.elements.cohort_start.value = firstMonth;
    filters.elements.cohort_end.value = lastMonth;
    for (const name of ['cohort_start', 'cohort_end']) {
      filters.elements[name].min = origin.slice(0, 7);
      filters.elements[name].max = end.slice(0, 7);
    }
    filters.elements.start.value = start;
    filters.elements.end.value = end;
    for (const name of ['start', 'end']) {
      filters.elements[name].min = origin;
      filters.elements[name].max = end;
    }
    await query();
  } catch (error) {
    el('query-status').textContent = error.message;
  }
}

const theme = el('theme');
theme.value = localStorage.getItem('fs-theme') || 'system';
theme.addEventListener('change', () => {
  localStorage.setItem('fs-theme', theme.value);
  if (theme.value === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.dataset.theme = theme.value;
});
initialize();
