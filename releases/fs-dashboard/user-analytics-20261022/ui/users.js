const el = id => document.getElementById(id);
const filters = el('filters');
const emailForm = el('email-search');
const integer = new Intl.NumberFormat('zh-CN');
const dollars = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'});
const wholeDollars = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 0});
const compactDollars = new Intl.NumberFormat('en-US', {notation: 'compact', maximumFractionDigits: 1});
const SVG = 'http://www.w3.org/2000/svg';
const stageNames = {
  recent: '近期', silent: '沉默', lost: '流失', long_lost: '长期流失', unverified: '待核',
  silent_wakeup: '沉默唤醒', lost_return: '流失回流', any: '回流客户',
  first_order: '站内首单', repeat: '复购', purchase: '追加购买', enter: '进入阶段',
  new: '新客', old: '老客', unknown: '待核',
};
const whoNames = {new: '新客', old: '老客', all: '全部客户', compare: '新老客'};
const windowNames = {denominator: '已满期（计入）', observing: '观察中', coverage_gap: '数据缺口'};
const yesNo = value => value == null ? '' : value ? '是' : '否';
const errorText = {
  users_summary_query_expired: '查询已过期，请重新发起。',
  snapshot_version_retired: '旧版快照已退役，请重新查询。',
  users_summary_busy: '正在计算另一条查询，请稍后重试。',
  weekly_initial_publication_pending: '日更结果尚未发布。',
  user_scope_denied: '当前账号没有访问权限。',
  scope_or_admin_required: '当前账号没有访问权限。',
  login_required: '登录已失效，请重新登录。',
  invalid_user_query: '请核对日期、天数和筛选条件。',
  snapshot_not_found: '快照或客户记录不可用，请重新查询。',
};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const n = value => value == null ? '—' : integer.format(value);
const money = value => value == null ? '—' : dollars.format(Number(value));
const rate = value => value == null ? '—' : (value * 100).toFixed(2) + '%';
const pct1 = value => value == null ? '—' : (value * 100).toFixed(1) + '%';
const when = value => value ? value.slice(0, 19).replace('T', ' ') : '—';
let catalog;
let dates;
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
  const start = dateShift(cutoff, -90);
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

function table(host, columns, rows, className) {
  const grid = element('table', null, className);
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
  host.replaceChildren(rows.length ? grid : element('p', '所选范围暂无数据。', 'hint'));
}

function memberButton(label, group, count, tone) {
  const button = element('button');
  button.type = 'button';
  button.append(element('span', label), element('strong', n(count)));
  button.setAttribute('aria-label', label + ' ' + n(count) + ' 人，查看名单');
  if (tone != null) button.dataset.tone = tone;
  button.addEventListener('click', () => openMembers(group, label));
  return button;
}

function unknownAmount(value) {
  return value?.unknown_orders ? '，含 ' + n(value.unknown_orders) + ' 笔金额未知' : '';
}

function amount(value) {
  return money(value.known_usd) + unknownAmount(value);
}

function windowOf(batch, days) {
  return batch?.windows.find(window => window.days === days);
}

function population(window) {
  return window.denominator + window.observing + window.coverage_gap;
}

function latestMatureBatch(batches) {
  return batches.reduce((latest, batch) => {
    const window = windowOf(batch, 180);
    return window?.observing === 0 && population(window) > 0 && (!latest || batch.month > latest.month)
      ? batch : latest;
  }, null);
}

function sameMonth(batches, month) {
  return batches?.find(batch => batch.month === month);
}

/* ---------- 图表基础 ---------- */
function svgChart(host, width, height, label, {scroll = true, append = false} = {}) {
  const drawing = document.createElementNS(SVG, 'svg');
  drawing.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
  drawing.setAttribute('class', 'chart');
  drawing.setAttribute('role', 'img');
  drawing.setAttribute('aria-label', label);
  let mount = drawing;
  if (scroll) {
    mount = element('div', null, 'chart-scroll');
    mount.tabIndex = 0;
    mount.setAttribute('role', 'region');
    mount.setAttribute('aria-label', label);
    mount.append(drawing);
  }
  if (append) host.append(mount); else host.replaceChildren(mount);
  return (tag, attributes, text, parent = drawing) => {
    const node = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text != null) node.textContent = text;
    parent.append(node);
    return node;
  };
}

function legend(host, items) {
  const list = element('ul', null, 'legend');
  for (const [text, color, dashed] of items) {
    const item = element('li');
    const swatch = element('i', null, dashed ? 'dash' : '');
    swatch.setAttribute('aria-hidden', 'true');
    if (dashed) swatch.style.color = color; else swatch.style.background = color;
    item.append(swatch, text);
    list.append(item);
  }
  host.append(list);
}

const tones = ['var(--u-c1)', 'var(--u-c2)', 'var(--u-c3)', 'var(--u-c5)', 'var(--u-c4)'];

/* ---------- 顶部卡片与结论 ---------- */
function card(label, value, note, {accent = false, secondary} = {}) {
  const box = element('div', null, 'card' + (accent ? ' accent' : ''));
  const main = element('div', value, 'v');
  if (secondary) main.append(element('small', secondary));
  box.append(element('div', label, 'k'), main, element('div', note, 'n'));
  return box;
}

// Share of the customers who came back within 180 days that already came back in the first window.
function firstWindowShare(batch, windows) {
  const counts = batch?.first_repeat?.counts;
  const boundary = windows.indexOf(180);
  if (!counts?.length || boundary < 0) return null;
  const returned = counts.slice(0, boundary + 1).reduce((sum, value) => sum + value, 0);
  return returned ? counts[0] / returned : null;
}

function renderFindings(view) {
  const {batch, old, query, who, compare} = view;
  const after = query.return_after;
  const within = query.return_within;
  const short = windowOf(batch, 90);
  const long = windowOf(batch, 180);
  const silent = batch?.silent_return;
  const oldShort = windowOf(old, 90);
  const oldSilent = old?.silent_return;
  const none = '所选首单月份和游戏范围内，还没有满 180 天的批次。';
  el('cohort-kpis').replaceChildren(
    card('最近满 180 天的批次', batch?.month || '—',
      long ? n(population(long)) + ' 位' + (compare ? '新客' : who) + (long.coverage_gap ? '，' + n(long.coverage_gap) + ' 人数据缺口' : '') : none,
      {accent: true}),
    card('90 天回头率', pct1(short?.rate),
      short ? n(short.numerator) + ' 人 90 天内买了第二单' : '暂无可用分母',
      {secondary: compare && oldShort ? '老客 ' + pct1(oldShort.rate) : null}),
    card('沉默后回流率', pct1(silent?.rate),
      silent ? after + ' 天没买的 ' + n(silent.denominator) + ' 人里 ' + n(silent.numerator) + ' 人回来' : '暂无可用分母',
      {secondary: compare && oldSilent ? '老客 ' + pct1(oldSilent.rate) : null}),
    card('回流带来的复购额', silent?.denominator && silent.return_amount.known_usd != null ? wholeDollars.format(Number(silent.return_amount.known_usd)) : '—',
      '第 ' + (after + 1) + '–' + within + ' 天回流订单' + unknownAmount(silent?.return_amount)),
  );
  const share = firstWindowShare(batch, query.windows);
  const repeat = batch && short && long
    ? batch.month + ' 批' + (compare ? '新客' : who) + '中，90 天内 ' + n(short.numerator) + ' / ' + n(short.denominator) +
      ' 人买了第二单（' + pct1(short.rate) + '），180 天达 ' + pct1(long.rate) + '。' +
      (share != null ? '180 天内回来的人里，' + pct1(share) + ' 在首单后 ' + query.windows[0] + ' 天内就买了第二单。' : '') +
      (compare && oldShort ? '同批老客 90 天回头率 ' + pct1(oldShort.rate) + '。' : '')
    : none;
  const rates = view.batches.map(row => row.silent_return).filter(value => value?.denominator);
  const best = view.batches.filter(row => row.silent_return?.denominator)
    .reduce((top, row) => !top || row.silent_return.rate > top.silent_return.rate ? row : top, null);
  const low = Math.min(...rates.map(value => value.rate));
  const high = Math.max(...rates.map(value => value.rate));
  const returning = batch && silent
    ? batch.month + ' 批中，前 ' + after + ' 天没回购的 ' + n(silent.denominator) + ' 人里，有 ' + n(silent.numerator) +
      ' 人（' + pct1(silent.rate) + '）在第 ' + (after + 1) + '–' + within + ' 天回来，带来 ' +
      (silent.denominator ? amount(silent.return_amount) : '—') + ' 复购额。' +
      (rates.length > 1 ? '各批次在 ' + pct1(low) + '–' + pct1(high) + ' 之间，' + best.month + ' 批最高。' : '') +
      (compare && oldSilent ? '同批老客回流率 ' + pct1(oldSilent.rate) + '。' : '')
    : none;
  setFinding('repeat-finding', repeat);
  setFinding('return-finding', returning);
  el('repeat-example').textContent = batch ? '例：' + repeat : none;
  el('return-example').textContent = batch ? '例：' + returning : none;
}

function setFinding(id, text) {
  const host = el(id);
  host.replaceChildren(element('b', '结论：'), text);
}

/* ---------- 回头率曲线 ---------- */
const hasRate = batch => Boolean(batch?.windows.some(window => window.rate != null));

function pickSeries(batches, focus, limit = 5, usableBatch = hasRate) {
  const usable = batches.filter(usableBatch);
  if (usable.length <= limit) return usable;
  const chosen = new Set();
  for (let i = 0; i < limit; i += 1) chosen.add(usable[Math.round(i * (usable.length - 1) / (limit - 1))]);
  if (focus && usable.includes(focus) && !chosen.has(focus)) {
    chosen.delete([...chosen].find(batch => batch !== usable[0] && batch !== usable.at(-1)));
    chosen.add(focus);
  }
  return usable.filter(batch => chosen.has(batch));
}

function curveChart(host, view) {
  const windows = view.query.windows;
  const W = 520, H = 280, L = 42, R = 52, T = 16, B = 34;
  const xmax = windows.at(-1);
  const lines = [];
  if (view.compare) {
    // A month qualifies when either population has rates; draw whichever is available.
    const months = pickSeries(view.batches, view.batch, 3,
      batch => hasRate(batch) || hasRate(sameMonth(view.oldBatches, batch.month)));
    months.forEach((batch, index) => {
      if (hasRate(batch)) lines.push({label: batch.month + ' 新客', batch, color: tones[index]});
      const old = sameMonth(view.oldBatches, batch.month);
      if (hasRate(old)) lines.push({label: batch.month + ' 老客', batch: old, color: tones[index], dashed: true});
    });
  } else {
    pickSeries(view.batches, view.batch).forEach((batch, index) => lines.push({label: batch.month + ' 批', batch, color: tones[index]}));
  }
  const values = lines.flatMap(line => line.batch.windows.map(window => window.rate ?? 0));
  const ymax = Math.max(.1, Math.ceil(Math.max(0, ...values) * 10) / 10);
  const draw = svgChart(host, W, H, '各批次回头率曲线', {scroll: false});
  const x = days => L + (W - L - R) * days / xmax;
  const y = value => T + (H - T - B) * (1 - value / ymax);
  for (const value of [0, ymax / 2, ymax]) {
    draw('line', {class: 'gridline', x1: L, x2: W - R, y1: y(value), y2: y(value)});
    draw('text', {x: L - 8, y: y(value) + 4, 'text-anchor': 'end'}, Math.round(value * 100) + '%');
  }
  draw('text', {x: x(0), y: H - 12, 'text-anchor': 'middle'}, '首单');
  for (const days of windows) draw('text', {x: x(days), y: H - 12, 'text-anchor': days === xmax ? 'end' : 'middle'}, days + ' 天');
  const ends = [];
  for (const line of lines) {
    const points = [[0, 0], ...line.batch.windows.filter(window => window.rate != null).map(window => [window.days, window.rate])];
    if (points.length < 2) continue;
    draw('polyline', {points: points.map(([d, v]) => x(d) + ',' + y(v)).join(' '), fill: 'none', stroke: line.color,
      'stroke-width': 2.4, 'stroke-linejoin': 'round', 'stroke-dasharray': line.dashed ? '6 4' : 'none'});
    for (const [d, v] of points.slice(1)) {
      const dot = draw('circle', {cx: x(d), cy: y(v), r: 3.5, fill: line.color});
      draw('title', {}, line.label + '，' + d + ' 天：' + pct1(v), dot);
    }
    const [lastDay, lastValue] = points.at(-1);
    ends.push({day: lastDay, y: y(lastValue) + 4, value: lastValue, color: line.color});
  }
  // End labels sit in a column right of the plot, spread so they never overlap.
  for (const day of new Set(ends.map(end => end.day))) {
    const column = ends.filter(end => end.day === day).sort((a, b) => a.y - b.y);
    column.forEach((end, i) => { if (i) end.y = Math.max(end.y, column[i - 1].y + 13); });
    const overflow = column.at(-1).y - (H - B);
    if (overflow > 0) column.forEach(end => { end.y -= overflow; });
    for (const end of column) {
      const atEnd = day === xmax;
      draw('text', {x: x(day) + (atEnd ? 6 : 6), y: end.y, 'text-anchor': 'start', class: 'strong', fill: end.color, style: 'fill:' + end.color}, pct1(end.value));
    }
  }
  legend(host, lines.map(line => [line.label, line.color, line.dashed]));
}

/* ---------- 热力表 ---------- */
function heatLevel(value, low, high) {
  if (value == null) return '';
  if (high <= low) return 'h2';
  const step = (value - low) / (high - low);
  return step < .2 ? 'h0' : step < .4 ? 'h1' : step < .6 ? 'h2' : step < .8 ? 'h3' : 'h4';
}

function heatTable(view) {
  const windows = view.query.windows;
  const rates = view.batches.flatMap(batch => batch.windows.map(window => window.rate)).filter(value => value != null);
  const low = Math.min(...rates), high = Math.max(...rates);
  const rows = view.batches.map(batch => {
    const head = element('span', batch.month);
    head.append(element('small', n(population(batch.windows[0])) + ' 人'));
    return [head, ...batch.windows.map(window => {
      const old = view.compare ? windowOf(sameMonth(view.oldBatches, batch.month), window.days) : null;
      const button = element('button', null, 'cell');
      button.type = 'button';
      const empty = item => !item || population(item) === 0;
      if (empty(window) && empty(old)) {
        button.classList.add('obs');
        button.disabled = true;
        button.append(element('span', '无客户', 's'));
        button.setAttribute('aria-label', batch.month + ' ' + window.days + ' 天，无客户');
        return button;
      }
      if (window.rate == null && old?.rate == null) {
        // Customers exist but none can be counted yet: keep the gap visible and the drill open.
        button.classList.add('obs');
        for (const item of [window, old].filter(Boolean)) {
          const who = item === old ? '老客' : '';
          if (item.observing) button.append(element('span', who + '观察中 ' + n(item.observing), 's'));
          if (item.coverage_gap) button.append(element('span', who + '数据缺口 ' + n(item.coverage_gap), 's'));
        }
      } else {
        const level = heatLevel(window.rate, low, high);
        if (level) button.classList.add(level);
        button.append(element('span', pct1(window.rate), 'p'),
          element('span', window.rate == null ? '新客暂无数据' : n(window.numerator) + ' 人', 's'));
        if (old) button.append(element('span', '老客 ' + pct1(old.rate), 's'));
        if (window.observing) button.append(element('span', '观察中 ' + n(window.observing), 's'));
      }
      button.setAttribute('aria-label', batch.month + ' ' + window.days + ' 天，查看详情');
      button.addEventListener('click', () => {
        el('cohort-heat').querySelectorAll('.is-selected').forEach(node => node.classList.remove('is-selected'));
        button.classList.add('is-selected');
        showDrill(view, batch.month, window, old);
      });
      return button;
    })];
  });
  table(el('cohort-heat'), ['首单批次', ...windows.map(days => days + ' 天')], rows, 'heat');
  const host = el('heat-legend');
  host.replaceChildren();
  for (const [text, color] of [['低', 'var(--u-heat-0)'], ['中', 'var(--u-heat-2)'], ['高', 'var(--u-heat-4)'], ['未满期或数据缺口', 'var(--fs-surface-3)']]) {
    const item = element('li');
    const swatch = element('i');
    swatch.style.background = color;
    item.append(swatch, text);
    host.append(item);
  }
}

function drillText(label, window) {
  const pending = [window.observing && '观察中 ' + n(window.observing) + ' 人', window.coverage_gap && '数据缺口 ' + n(window.coverage_gap) + ' 人']
    .filter(Boolean).join('、');
  return label + '：已满期 ' + n(window.denominator) + ' 人，其中 ' + n(window.numerator) + ' 人买了第二单（' + rate(window.rate) + '）' +
    (pending ? '；' + pending + '暂不计入' : '') + '；复购金额 ' + (window.denominator ? amount(window.repeat_amount) : '—') +
    (window.repeat_per_customer_usd ? '，人均 ' + money(window.repeat_per_customer_usd) : '') + '。';
}

function showDrill(view, month, window, old) {
  const host = el('cohort-drill');
  const title = month + ' 批 · ' + window.days + ' 天';
  host.replaceChildren(element('b', title));
  const who = view.compare ? '新客' : view.who;
  host.append(' ' + drillText(who, window));
  const list = element('button', '查看' + (view.compare ? '新客' : '') + '名单');
  list.type = 'button';
  list.addEventListener('click', () => openMembers(window.group, title + ' ' + who));
  host.append(list);
  if (old) {
    host.append(element('br'), drillText('老客', old));
    const oldList = element('button', '查看老客名单');
    oldList.type = 'button';
    oldList.addEventListener('click', () => openMembers(old.group, title + ' 老客'));
    host.append(oldList);
  }
}

/* ---------- 第一次回购 ---------- */
function firstRepeat(view) {
  const windows = view.query.windows;
  const days = windows.at(-1);
  const labels = [...windows.map((limit, i) => (i ? windows[i - 1] : 1) + '–' + limit + ' 天'), days + ' 天内没回购'];
  const colors = [...windows.map((_, i) => tones[i]), 'var(--u-gray)'];
  const mature = batch => {
    const window = windowOf(batch, days);
    return window?.observing === 0 && window.denominator > 0;
  };
  const rows = [];
  // Each population qualifies on its own maturity.
  for (const batch of view.batches) {
    if (mature(batch)) rows.push({label: batch.month + (view.compare ? ' 新' : ''), batch});
    const old = view.compare && sameMonth(view.oldBatches, batch.month);
    if (old && mature(old)) rows.push({label: batch.month + ' 老', batch: old});
  }
  // Counts cover only customers with complete order coverage; excluded customers are reported per row.
  const gaps = rows.map(({batch}) => windowOf(batch, days)?.coverage_gap || 0);
  const excluded = gaps.reduce((sum, value) => sum + value, 0);
  el('first-repeat-basis').textContent = '只统计最长 ' + days + ' 天已全部满期的批次。每条横条 = 这批订单数据完整的客户 100%，按第一次买第二单的时间分段。' +
    (excluded ? '有 ' + n(excluded) + ' 人因订单数据缺口未计入，见下方明细。' : '');
  const host = el('first-repeat');
  if (!rows.length) {
    host.replaceChildren(element('p', '所选范围暂无已满期的批次。', 'hint'));
    return;
  }
  const W = 1000, L = 92, R = 8, rowH = 30, gap = 6;
  const draw = svgChart(host, W, rows.length * (rowH + gap) + 4, '首次回购时间分布');
  rows.forEach(({label, batch}, index) => {
    const window = windowOf(batch, days);
    const counts = batch.first_repeat.counts;
    const total = counts.reduce((sum, value) => sum + value, 0) || window.denominator;
    const y = 2 + index * (rowH + gap);
    draw('text', {x: L - 10, y: y + 19, 'text-anchor': 'end', class: 'strong'}, label);
    let x = L;
    counts.forEach((count, part) => {
      const width = (W - L - R) * count / total;
      if (width <= 0) return;
      const rect = draw('rect', {x, y, width: Math.max(width - 2, 0), height: rowH, rx: 5, fill: colors[part]});
      draw('title', {}, label + '，' + labels[part] + '：' + n(count) + ' 人（' + pct1(count / total) + '）', rect);
      if (width > 56) draw('text', {x: x + 8, y: y + 20, class: part === counts.length - 1 ? 'strong' : 'on-bar'}, Math.round(count / total * 100) + '%');
      x += width;
    });
  });
  legend(host, labels.map((label, i) => [label, colors[i]]));
  const details = element('details');
  const grid = element('div', null, 'table-scroll');
  grid.tabIndex = 0;
  grid.setAttribute('role', 'region');
  grid.setAttribute('aria-label', '首次回购人数明细');
  details.append(element('summary', '查看各段人数'), grid);
  table(grid, ['批次', ...labels, '数据缺口未计入'], rows.map(({label, batch}, index) =>
    [label, ...batch.first_repeat.counts.map(n), n(gaps[index]) + ' 人']));
  host.append(details);
}

/* ---------- 沉默后回流 ---------- */
function timeline(after, within) {
  const W = 1000, L = 30, R = 30, xmax = Math.max(within + 20, 200);
  const x = days => L + (W - L - R) * days / xmax;
  const draw = svgChart(el('return-timeline'), W, 86, '首单后前 ' + after + ' 天未复购，第 ' + (after + 1) + '–' + within + ' 天回来算回流', {scroll: false});
  const y = 30;
  draw('line', {x1: x(0), x2: x(xmax), y1: y, y2: y, stroke: 'var(--fs-line)', 'stroke-width': 2});
  draw('rect', {x: x(1), y: y - 12, width: x(after) - x(1), height: 24, rx: 6, fill: 'var(--fs-warn-soft)'});
  draw('text', {x: (x(1) + x(after)) / 2, y: y + 4, 'text-anchor': 'middle', class: 'strong'}, '沉默：' + after + ' 天内没买第二单');
  draw('rect', {x: x(after + 1), y: y - 12, width: x(within) - x(after + 1), height: 24, rx: 6, fill: 'var(--fs-brand-soft)'});
  draw('text', {x: (x(after + 1) + x(within)) / 2, y: y + 4, 'text-anchor': 'middle', class: 'strong'}, '回流窗口：第 ' + (after + 1) + '–' + within + ' 天回来下单就算回流');
  for (const [days, label] of [[0, '首单'], [after, '第 ' + after + ' 天'], [within, '第 ' + within + ' 天']]) {
    draw('circle', {cx: x(days), cy: y, r: 5, fill: 'var(--fs-brand)'});
    draw('text', {x: x(days), y: y + 34, 'text-anchor': 'middle'}, label);
  }
}

function barChart(host, label, groups, {format, axis = format, colors}) {
  const W = 520, H = 250, L = 52, R = 10, T = 40, B = 34;
  const values = groups.flatMap(group => group.bars.map(bar => bar.value)).filter(Number.isFinite);
  const ymax = Math.max(0, ...values) * 1.15 || 1;
  const draw = svgChart(host, Math.max(W, groups.length * 70 + L), H, label);
  const width = Math.max(W, groups.length * 70 + L);
  const y = value => T + (H - T - B) * (1 - value / ymax);
  for (let i = 0; i <= 4; i += 1) {
    const value = ymax * i / 4;
    draw('line', {class: 'gridline', x1: L, x2: width - R, y1: y(value), y2: y(value)});
    draw('text', {x: L - 8, y: y(value) + 4, 'text-anchor': 'end'}, axis(value));
  }
  const slot = (width - L - R) / groups.length;
  groups.forEach((group, index) => {
    const inner = slot * .64;
    const each = inner / group.bars.length;
    group.bars.forEach((bar, part) => {
      const x = L + index * slot + (slot - inner) / 2 + part * each;
      if (!Number.isFinite(bar.value)) return;
      const rect = draw('rect', {x: x + 2, y: y(bar.value), width: Math.max(each - 4, 2), height: Math.max(y(0) - y(bar.value), 1), rx: 5, fill: colors[part]});
      draw('title', {}, group.label + (bar.name ? ' ' + bar.name : '') + '：' + bar.detail, rect);
      // Paired bars stagger their value labels so neighbours never overlap.
      const lift = group.bars.length > 1 && part % 2 ? 22 : 8;
      draw('text', {x: x + each / 2, y: y(bar.value) - lift, 'text-anchor': 'middle', class: 'strong',
        style: group.bars.length > 1 ? 'font-size:11px' : ''}, format(bar.value));
    });
    draw('text', {x: L + index * slot + slot / 2, y: H - 16, 'text-anchor': 'middle'}, group.label);
    if (group.partial) draw('text', {x: L + index * slot + slot / 2, y: H - 2, 'text-anchor': 'middle'}, '部分');
  });
}

// A month is partial when, for any shown population, its return window still has customers under
// observation or with order-coverage gaps. The return window comes from the reference query when
// the selected repeat windows do not include it; unknown completeness also counts as partial.
function returnPartial(view, month) {
  const within = view.query.return_within;
  const sources = [[view.refBatches, view.batches]];
  if (view.compare) sources.push([view.refOldBatches, view.oldBatches]);
  return sources.some(([reference, shown]) => {
    const window = windowOf(sameMonth(reference, month), within) || windowOf(sameMonth(shown, month), within);
    return !window || Boolean(window.observing || window.coverage_gap);
  });
}

function renderReturns(view) {
  const {return_after: after, return_within: within} = view.query;
  document.querySelectorAll('[data-after-next]').forEach(node => { node.textContent = after + 1; });
  timeline(after, within);
  const groups = view.batches.filter(batch => batch.silent_return.denominator > 0 ||
      (view.compare && sameMonth(view.oldBatches, batch.month)?.silent_return.denominator > 0));
  const series = view.compare ? [['新客', null], ['老客', 'old']] : [[view.who, null]];
  const colors = ['var(--u-c1)', 'var(--u-c3)'];
  const amountColors = ['var(--u-c2)', 'var(--u-c3)'];
  const pick = (batch, key) => key === 'old' ? sameMonth(view.oldBatches, batch.month)?.silent_return : batch.silent_return;
  if (!groups.length) {
    for (const id of ['return-rates', 'return-amounts']) el(id).replaceChildren(element('p', '所选范围还没有满回流截止天数的批次。', 'hint'));
    return;
  }
  barChart(el('return-rates'), '各批次沉默后回流率', groups.map(batch => ({
    label: batch.month,
    partial: returnPartial(view, batch.month),
    bars: series.map(([name, key]) => {
      const value = pick(batch, key);
      return {name, value: value?.denominator ? value.rate : NaN,
        detail: value ? pct1(value.rate) + '，' + n(value.numerator) + ' / ' + n(value.denominator) + ' 人' : '—'};
    }),
  })), {format: pct1, axis: value => Math.round(value * 100) + '%', colors});
  // Unknown amounts stay missing (no bar) and partial sums are flagged; never plotted as $0.
  barChart(el('return-amounts'), '各批次回流复购金额', groups.map(batch => {
    const values = series.map(([, key]) => pick(batch, key));
    return {
      label: batch.month,
      partial: returnPartial(view, batch.month) ||
        values.some(value => value?.denominator && value.return_amount.unknown_orders),
      bars: series.map(([name], index) => {
        const value = values[index];
        const known = value?.denominator ? value.return_amount.known_usd : null;
        return {name, value: known == null ? NaN : Number(known),
          detail: value?.denominator ? amount(value.return_amount) : '—'};
      }),
    };
  }), {format: value => wholeDollars.format(value), axis: value => '$' + compactDollars.format(value), colors: amountColors});
  if (view.compare) {
    legend(el('return-rates'), [['新客', colors[0]], ['老客', colors[1]]]);
    legend(el('return-amounts'), [['新客', amountColors[0]], ['老客', amountColors[1]]]);
  }
  const breakdown = element('details');
  const grid = element('div', null, 'table-scroll');
  grid.tabIndex = 0;
  grid.setAttribute('role', 'region');
  grid.setAttribute('aria-label', '沉默后回流明细');
  breakdown.append(element('summary', '查看回流明细'), grid);
  const rows = [];
  for (const batch of groups) {
    for (const [name, key] of series) {
      const value = pick(batch, key);
      if (value) rows.push([batch.month + (view.compare ? ' ' + name : ''), n(value.numerator), n(value.denominator), pct1(value.rate), value.denominator ? amount(value.return_amount) : '—']);
    }
  }
  table(grid, ['批次', '回来的人数', '沉默的人数', '回流率', '回流金额'], rows);
  el('return-amounts').append(breakdown);
}

/* ---------- 客户健康 ---------- */
function renderStages(data) {
  const sections = data.stages;
  const total = sections.stages.reduce((sum, stage) => sum + stage.count, 0);
  const inactive = sections.stages.filter(({kind}) => ['silent', 'lost', 'long_lost'].includes(kind))
    .reduce((sum, stage) => sum + stage.count, 0);
  const returned = sections.returns.find(({kind}) => kind === 'any')?.count;
  const thresholds = data.lifecycle_policy?.thresholds_days;
  const start = data.query.start.slice(0, 10);
  const end = dateShift(data.query.end_exclusive.slice(0, 10), -1);
  el('stage-basis').textContent = start + ' 至 ' + end + ' 买过的客户，状态截至 ' + data.observation_date + '。' +
    (thresholds?.length === 3 ? '距最后一次购买 <' + thresholds[0] + ' 天为近期，' + thresholds[0] + '–' + (thresholds[1] - 1) + ' 天沉默，' +
      thresholds[1] + '–' + (thresholds[2] - 1) + ' 天流失，≥' + thresholds[2] + ' 天长期流失。' : '') +
    (sections.status === 'partial' ? '当前结果存在数据缺口。' : '');
  const missing = sections.daily_returns.filter(row => row.silent_wakeup == null || row.lost_return == null).length;
  const daily = sections.daily_returns.filter(row => row.silent_wakeup != null && row.lost_return != null)
    .map(row => row.silent_wakeup + row.lost_return);
  const observed = '所选期间买过的 ' + n(total) + ' 位客户中，' + n(inactive) + ' 人（' + pct1(total ? inactive / total : null) +
    '）已经沉默或流失；本期有 ' + n(returned) + ' 人回流' +
    (daily.length ? '，每天约 ' + n(Math.min(...daily)) + '–' + n(Math.max(...daily)) + ' 人' : '') + '。' +
    (missing ? '每日曲线有 ' + n(missing) + ' 天缺数据。' : '');
  setFinding('stage-finding', observed);
  el('stage-example').textContent = total ? '例：' + observed : '当前范围暂无客户数据。';
  el('stage-chart-title').textContent = '客户状态分布（' + n(total) + ' 人）';
  const host = el('stage-distribution');
  const colors = {recent: 'var(--u-c1)', silent: 'var(--u-c3)', lost: 'var(--u-c4)', long_lost: 'var(--u-c5)', unverified: 'var(--u-gray)'};
  const toneOf = {recent: 0, silent: 1, lost: 2, long_lost: 3, unverified: 4};
  if (total) {
    const W = 520;
    const draw = svgChart(host, W, 64, sections.stages.map(({kind, count}) => stageNames[kind] + ' ' + n(count) + ' 人').join('，'), {scroll: false});
    let x = 0;
    for (const {kind, count} of sections.stages) {
      const width = W * count / total;
      if (width <= 0) continue;
      const rect = draw('rect', {x, y: 4, width: Math.max(width - 3, 1), height: 56, rx: 8, fill: colors[kind]});
      draw('title', {}, stageNames[kind] + '：' + n(count) + ' 人（' + pct1(count / total) + '）', rect);
      if (width > 70) {
        draw('text', {x: x + 10, y: 28, class: kind === 'unverified' ? 'strong' : 'on-bar', style: 'font-size:15px'}, Math.round(count / total * 100) + '%');
        draw('text', {x: x + 10, y: 47, class: kind === 'unverified' ? '' : 'on-bar'}, stageNames[kind] + ' ' + n(count));
      }
      x += width;
    }
  } else {
    host.replaceChildren(element('p', '所选范围暂无购买客户。', 'hint'));
  }
  for (const [id, values, tone] of [['stage-counts', sections.stages, true], ['stage-inflow', sections.inflow], ['stage-returns', sections.returns]]) {
    el(id).replaceChildren(...values.map(({kind, group, count}) => {
      const item = element('li');
      item.append(memberButton(stageNames[kind], group, count, tone ? toneOf[kind] : null));
      return item;
    }));
  }
  dailyChart(sections.daily_returns);
  el('cross-flow').hidden = data.query.game !== 'all';
  if (sections.cross_game_flow) {
    table(el('cross-table'), ['已流失的游戏', '仍在买的游戏', '人数'],
        sections.cross_game_flow.map(({source, destination, group, count}) => [
          gameName(source), gameName(destination),
          memberButton(gameName(source) + ' → ' + gameName(destination), group, count),
        ]));
  }
}

function dailyChart(rows) {
  const host = el('return-trend');
  const W = 520, H = 220, L = 36, R = 12, T = 12, B = 30;
  const values = rows.flatMap(row => [row.silent_wakeup, row.lost_return]).filter(Number.isFinite);
  const ymax = Math.max(4, Math.ceil(Math.max(0, ...values) * 1.1 / 4) * 4);
  const draw = svgChart(host, W, H, '每日沉默唤醒与流失回流人数', {scroll: false});
  const x = i => L + (W - L - R) * i / Math.max(1, rows.length - 1);
  const y = value => T + (H - T - B) * (1 - value / ymax);
  for (const value of [0, ymax / 2, ymax]) {
    draw('line', {class: 'gridline', x1: L, x2: W - R, y1: y(value), y2: y(value)});
    draw('text', {x: L - 6, y: y(value) + 4, 'text-anchor': 'end'}, n(value));
  }
  const step = Math.max(1, Math.round(rows.length / 6));
  rows.forEach((row, i) => {
    const last = i === rows.length - 1;
    if ((i % step === 0 && rows.length - 1 - i >= step * .8) || last) {
      draw('text', {x: x(i), y: H - 10, 'text-anchor': i === rows.length - 1 ? 'end' : i === 0 ? 'start' : 'middle'}, row.date.slice(5));
    }
  });
  for (const [key, color] of [['silent_wakeup', 'var(--u-c3)'], ['lost_return', 'var(--u-c4)']]) {
    let path = '';
    rows.forEach((row, i) => {
      if (!Number.isFinite(row[key])) return;
      path += (Number.isFinite(rows[i - 1]?.[key]) ? ' L' : ' M') + x(i) + ' ' + y(row[key]);
    });
    draw('path', {d: path, fill: 'none', stroke: color, 'stroke-width': 2.2});
  }
  legend(host, [['沉默唤醒', 'var(--u-c3)'], ['流失回流', 'var(--u-c4)']]);
  const details = element('details');
  const grid = element('div', null, 'table-scroll');
  grid.tabIndex = 0;
  grid.setAttribute('role', 'region');
  grid.setAttribute('aria-label', '每日回流人数明细');
  details.append(element('summary', '查看每日回流人数'), grid);
  table(grid, ['日期', '沉默唤醒', '流失回流'], rows.map(row => [row.date, n(row.silent_wakeup), n(row.lost_return)]));
  host.append(details);
}

/* ---------- 查询 ---------- */
async function summary(args) {
  let result = await request('/dashboard/users/data.json', args);
  for (let attempts = 0; result.status === 202; attempts += 1) {
    if (attempts >= 24) throw new Error('计算等待超时，请重新发起查询。');
    el('query-status').textContent = '计算中，完成后自动显示。';
    await sleep(Math.max(1, result.value.retryAfter || 5) * 1000);
    result = await request('/dashboard/users/data.json', {query_id: result.value.query_id});
  }
  const data = result.value;
  if (data.contract_version !== 'fs-users-v4' || !data.snapshot_id) throw new Error('用户分析版本尚未就绪。');
  return data;
}

function pending(flag) {
  filters.querySelectorAll('button[type=submit]').forEach(button => { button.disabled = flag; });
  filters.setAttribute('aria-busy', String(flag));
}

function formArgs() {
  const form = filters.elements;
  const windows = [...new Set(['w1', 'w2', 'w3'].map(name => Number(form[name].value)).filter(value => Number.isInteger(value) && value >= 2))]
    .sort((a, b) => a - b);
  let start = form.start.value;
  let end = form.end.value;
  if (form.period.value !== 'custom') {
    end = dates.end;
    start = dateShift(end, 1 - Number(form.period.value));
    if (start < dates.origin) start = dates.origin;
  }
  return {
    game: form.game.value, cohort_start: form.cohort_start.value, cohort_end: form.cohort_end.value,
    windows: windows.join(','), return_after: form.return_after.value, return_within: form.return_within.value,
    cohort_type: form.cohort_type.value, start, end_exclusive: dateShift(end, 1),
    customer_type: form.customer_type.value, repeat_status: form.repeat_status.value,
  };
}

function updateLabels(type) {
  document.querySelectorAll('[data-who]').forEach(node => { node.textContent = whoNames[type]; });
  const note = el('segment-note');
  note.hidden = type === 'new';
  note.textContent = '老客没有真实首单日期，这里按 ' + (catalog?.history_backfill_start?.slice(0, 7) || '2026-01') +
    ' 起第一次在数据里出现的月份分批；第一个月的老客批次包含当月所有回头的老客，会偏大，比较趋势时以后续月份为准。';
}

let generation = 0;

async function query(event) {
  event?.preventDefault();
  if (el('run-query').disabled && event) return;
  // Only the latest request may render; a slower earlier one is dropped.
  const mine = ++generation;
  const stale = () => mine !== generation;
  pending(true);
  current = memberView = null;
  emailForm.querySelector('button').disabled = true;
  for (const id of ['member-panel', 'cohort-kpis', 'cohorts', 'returns', 'stages']) el(id).hidden = true;
  el('email-status').textContent = '';
  el('query-status').textContent = '正在读取用户分析…';
  try {
    const args = formArgs();
    updateLabels(args.cohort_type);
    const data = await summary(args);
    if (stale()) return;
    const focus = [...new Set([90, 180, data.query.return_within])].sort((a, b) => a - b);
    let reference = data;
    let warning = '';
    if (focus.some(days => !data.query.windows.includes(days))) {
      try {
        reference = await summary({...args, windows: focus.join(',')});
        if (reference.observation_date !== data.observation_date || reference.config_version !== data.config_version ||
            reference.data_version !== data.data_version) throw new Error('参考批次数据版本已更新。');
      } catch (error) {
        warning = '参考批次读取失败。' + error.message;
        reference = null;
      }
    }
    if (stale()) return;
    const type = data.query.cohort_type || args.cohort_type;
    const view = {
      query: data.query, who: whoNames[type], compare: type === 'compare',
      batches: data.cohorts.batches, oldBatches: data.cohorts.compare?.batches || [],
      refBatches: reference?.cohorts.batches || [], refOldBatches: reference?.cohorts.compare?.batches || [],
    };
    const batch = reference ? latestMatureBatch(reference.cohorts.batches) : null;
    renderFindings({...view, batch, old: batch && sameMonth(reference.cohorts.compare?.batches, batch.month),
      batches: reference ? reference.cohorts.batches : view.batches, query: {...data.query, windows: reference?.query.windows || data.query.windows}});
    if (warning) {
      setFinding('repeat-finding', warning);
      setFinding('return-finding', warning);
    }
    curveChart(el('repeat-curve'), {...view, batch: batch && sameMonth(view.batches, batch.month)});
    heatTable(view);
    firstRepeat(view);
    renderReturns(view);
    renderStages(data);
    current = data;
    el('cohort-drill').textContent = '点任意格子，这里显示该格的人数、复购金额和名单入口。';
    el('metadata').textContent = '数据截至 ' + data.observation_date + '（北京时间），MMOEXP 主站' +
      (data.coverage.order_missing_days ? '，订单缺 ' + n(data.coverage.order_missing_days) + ' 天' : '');
    el('query-status').textContent = data.coverage.new_customer_flags?.status === 'complete' ? '' :
        'ES 新老客标记覆盖有缺口，匹配不到的首单计入待核。';
    for (const id of ['cohort-kpis', 'cohorts', 'returns', 'stages']) el(id).hidden = false;
    emailForm.querySelector('button').disabled = false;
  } catch (error) {
    if (!stale()) el('query-status').textContent = error.message;
  } finally {
    if (!stale()) pending(false);
  }
}

/* ---------- 名单、详情、导出、查人 ---------- */
async function openMembers(group, label) {
  memberView = {group, label, snapshot: current.snapshot_id, cursors: [''], next: ''};
  el('member-panel').hidden = false;
  el('member-title').textContent = label + ' 名单';
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
    view.total = value.total;
    const cohort = view.group.startsWith('cohort:');
    const windowColumns = cohort ? ['时间窗状态', '计入复购'] : [];
    table(el('members'), ['客户邮箱', '站内首单', '末次购买', '阶段', ...windowColumns, '详情'], value.rows.map(row => [
      row.email, when(row.first_paid_at), when(row.last_paid_at), stageNames[row.stage],
      ...(cohort ? [windowNames[row.window_status], yesNo(row.in_numerator)] : []),
      detailsButton(row.customer_id, view.snapshot),
    ]));
    el('member-status').textContent = '共 ' + n(value.total) + ' 人，第 ' + view.cursors.length + ' 页';
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

async function exportMembers() {
  const view = memberView;
  const button = el('export');
  button.disabled = true;
  try {
    const {value} = await request('/dashboard/users/private.json', {action: 'export', snapshot_id: view.snapshot, group: view.group});
    if (view !== memberView) return;
    if (value.snapshot_id !== view.snapshot || value.group !== view.group ||
        value.exported_rows !== view.total || typeof value.csv !== 'string') {
      throw new Error('名单导出数据不完整。');
    }
    const blob = new Blob([value.csv], {type: 'text/csv;charset=utf-8'});
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
for (const radio of filters.querySelectorAll('input[name=cohort_type]')) radio.addEventListener('change', () => query());
filters.elements.period.addEventListener('change', () => { el('custom-period').hidden = filters.elements.period.value !== 'custom'; });
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
    const found = reportDates(catalog.weekly_update, origin);
    if (catalog.contract_version !== 'fs-users-v4' || !found) throw new Error('当前用户分析数据尚未发布。');
    dates = {...found, origin};
    const form = filters.elements;
    for (const [gid, game] of Object.entries(catalog.projects)) {
      const option = element('option', game.label);
      option.value = gid;
      form.game.append(option);
    }
    form.cohort_start.value = found.firstMonth;
    form.cohort_end.value = found.lastMonth;
    for (const name of ['cohort_start', 'cohort_end']) {
      form[name].min = origin.slice(0, 7);
      form[name].max = found.end.slice(0, 7);
    }
    form.start.value = found.start;
    form.end.value = found.end;
    for (const name of ['start', 'end']) {
      form[name].min = origin;
      form[name].max = found.end;
    }
    pending(false);
    await query();
  } catch (error) {
    el('query-status').textContent = error.message;
  }
}

const theme = el('theme');
if (window.FSTheme) {
  theme.value = window.FSTheme.get();
  theme.addEventListener('change', () => window.FSTheme.set(theme.value));
}
initialize();
