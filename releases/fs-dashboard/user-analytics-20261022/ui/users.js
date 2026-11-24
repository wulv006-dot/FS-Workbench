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
const windowNames = {denominator: '已满窗（分母）', observing: '观察中', coverage_gap: '覆盖缺口'};
const yesNo = value => value == null ? '' : value ? '是' : '否';
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

function unknownAmount(value) {
  return value.unknown_orders ? ' · 含 ' + n(value.unknown_orders) + ' 笔金额未知' : '';
}

function amount(value) {
  return money(value.known_usd) + unknownAmount(value);
}

function windowOf(batch, days) {
  return batch?.windows.find(window => window.days === days);
}

function coveredPopulation(window) {
  return window.denominator + window.observing + window.coverage_gap;
}

function latestMatureBatch(batches) {
  return batches.reduce((latest, batch) => {
    const window = windowOf(batch, 180);
    return window?.observing === 0 && coveredPopulation(window) > 0 && (!latest || batch.month > latest.month)
      ? batch : latest;
  }, null);
}

function kpi(label, value, note) {
  const card = element('div', null, 'kpi');
  card.append(element('span', label), element('strong', value), element('small', note));
  return card;
}

function renderFindings(batch, query) {
  const after = query.return_after;
  const within = query.return_within;
  const short = windowOf(batch, 90);
  const long = windowOf(batch, 180);
  const returnWindow = windowOf(batch, within);
  const value = batch?.silent_return;
  const none = '所选首单月份和游戏范围内，暂无已满 180 天的非空批次。';
  const range = after + ' 至 ' + within + ' 天（不含末端）';
  el('cohort-kpis').replaceChildren(
    kpi('最近满 180 天的首单批次', batch?.month || '—',
      long ? n(coveredPopulation(long)) + ' 位确认新客 · 180 天覆盖缺口 ' + n(long.coverage_gap) + ' 人' : none),
    kpi('90 天回头率', rate(short?.rate), short ? n(short.numerator) + ' / ' + n(short.denominator) + ' 人 · 已满窗且覆盖完整' : '暂无可用分母'),
    kpi('沉默后回流率', rate(value?.rate), value ? n(value.numerator) + ' / ' + n(value.denominator) + ' 人 · ' + range : '暂无可用分母'),
    kpi('回流带来的复购额', money(value?.denominator ? value.return_amount.known_usd : null), value ? range + unknownAmount(value.return_amount) : '暂无可用金额'),
  );
  const repeat = batch ? batch.month + ' 首单批次中，90 天内有 ' + n(short.numerator) + ' / ' + n(short.denominator) +
    ' 人买了第二单（' + rate(short.rate) + '），180 天回头率为 ' + rate(long.rate) + '。' : none;
  const returning = batch ? batch.month + ' 首单批次在 ' + range + '有 ' + n(value.numerator) + ' / ' + n(value.denominator) +
    ' 人沉默后回流（' + rate(value.rate) + '），已知复购额 ' + (value.denominator ? amount(value.return_amount) : '—') + '。' +
    completionNote(returnWindow) : none;
  el('repeat-finding').textContent = repeat + (long?.coverage_gap ? ' 180 天覆盖缺口 ' + n(long.coverage_gap) + ' 人。' : '');
  el('return-finding').textContent = returning;
  el('repeat-example').textContent = batch ? '按当前批次举例 · ' + repeat : none;
  el('return-example').textContent = batch ? '按当前批次举例 · ' + returning : none;
}

function completionNote(window) {
  if (!window) return '';
  const issues = [];
  if (window.observing) issues.push('观察中 ' + n(window.observing) + ' 人');
  if (window.coverage_gap) issues.push('覆盖缺口 ' + n(window.coverage_gap) + ' 人');
  return issues.length ? ' 全批次时间窗状态：' + issues.join('，') + '。' : '';
}

function svgChart(host, width, height, label, scroll = false) {
  const drawing = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  drawing.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
  drawing.setAttribute('class', 'chart');
  drawing.setAttribute('role', 'img');
  drawing.setAttribute('aria-label', label);
  if (scroll) {
    const wrapper = element('div', null, 'chart-scroll');
    wrapper.tabIndex = 0;
    wrapper.setAttribute('role', 'region');
    wrapper.setAttribute('aria-label', label);
    wrapper.append(drawing);
    host.replaceChildren(wrapper);
  } else host.replaceChildren(drawing);
  return (tag, attributes, text, parent = drawing) => {
    const node = document.createElementNS(drawing.namespaceURI, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text != null) node.textContent = text;
    parent.append(node);
    return node;
  };
}

function legend(host, labels) {
  const list = element('ul', null, 'legend');
  for (const [text, series] of labels) {
    const item = element('li', null, series);
    const swatch = element('i');
    swatch.setAttribute('aria-hidden', 'true');
    item.append(swatch, text);
    list.append(item);
  }
  host.append(list);
}

function seriesClass(index) {
  return 'series-' + index % 6;
}

function lineChart(host, {description, ticks, series, format, max, dashAfter = Infinity}) {
  const draw = svgChart(host, 540, 216, description, true);
  const x = i => 48 + i * 464 / Math.max(1, ticks.length - 1);
  const y = value => 178 - value * 151 / max;
  for (const value of [0, max / 2, max]) {
    draw('line', {class: 'gridline', x1: 48, x2: 512, y1: y(value), y2: y(value)});
    draw('text', {x: 42, y: y(value) + 4, 'text-anchor': 'end'}, format(value));
  }
  ticks.forEach((tick, index) => {
    if (tick) draw('text', {x: x(index), y: 204, 'text-anchor': 'middle'}, tick);
  });
  for (const {name, color, values, index} of series) {
    let path = '';
    values.forEach((point, i) => {
      if (!Number.isFinite(point?.value)) return;
      path += (Number.isFinite(values[i - 1]?.value) ? ' L' : ' M') + x(i) + ' ' + y(point.value);
    });
    draw('path', {class: color, d: path, 'stroke-dasharray': index >= dashAfter ? '5 4' : 'none'});
    values.forEach((point, i) => {
      if (!Number.isFinite(point?.value) || (ticks.length > 15 && !ticks[i])) return;
      const mark = draw('circle', {class: color, cx: x(i), cy: y(point.value), r: 4});
      draw('title', {}, name + ' · ' + (point.label || ticks[i]) + ' · ' + format(point.value), mark);
    });
  }
  legend(host, series.map(({name, color}) => [name, color]));
}

function openCohortDetail(month, window) {
  const title = month + ' · ' + window.days + ' 天';
  el('cohort-detail-title').textContent = title;
  el('cohort-detail-metrics').replaceChildren(...[
    ['回头率', rate(window.rate)],
    ['累计复购', n(window.numerator) + ' / ' + n(window.denominator) + ' 人'],
    ['观察中', n(window.observing) + ' 人'],
    ['覆盖缺口', n(window.coverage_gap) + ' 人'],
    ['复购金额', window.denominator ? amount(window.repeat_amount) : '—'],
    ['复购人均', money(window.repeat_per_customer_usd)],
  ].map(([label, value]) => {
    const row = element('div');
    row.append(element('dt', label), element('dd', value));
    return row;
  }));
  el('cohort-members').onclick = () => {
    el('cohort-detail').close();
    openMembers(window.group, title);
  };
  el('cohort-detail').showModal();
}

function renderCohorts(data) {
  const windows = data.query.windows;
  const batches = data.cohorts.batches;
  const values = batches.map((batch, index) => ({
    name: batch.month, color: seriesClass(index), index,
    values: batch.windows.map(window => ({value: window.rate})),
  })).filter(series => series.values.some(point => Number.isFinite(point.value)));
  const largest = Math.max(0, ...values.flatMap(series => series.values.map(({value}) => value ?? 0)));
  if (values.length) {
    lineChart(el('repeat-curve'), {description: '各批次回头率曲线', ticks: windows.map(days => days + ' 天'),
      series: values, format: rate, max: Math.max(.1, Math.ceil(largest * 10) / 10), dashAfter: 6});
  } else {
    el('repeat-curve').replaceChildren(element('p', '所选范围暂无可用比例。', 'muted'));
  }
  const rows = batches.map(batch => [
    batch.month,
    ...batch.windows.map(window => {
      const incomplete = window.observing || window.coverage_gap;
      const button = element('button', null, 'cohort-cell' + (incomplete ? ' is-incomplete' : ''));
      button.type = 'button';
      button.setAttribute('aria-label', batch.month + ' ' + window.days + ' 天，查看详情');
      button.setAttribute('aria-description', rate(window.rate) + '，' + n(window.numerator) + ' / ' +
        n(window.denominator) + ' 人。' + completionNote(window));
      button.style.setProperty('--heat', (4 + 28 * (window.rate ?? 0)) + '%');
      button.append(element('strong', rate(window.rate)), element('small', n(window.numerator) + '/' + n(window.denominator) + ' 人'));
      if (incomplete) {
        if (window.observing) button.append(element('small', '观察中 ' + n(window.observing)));
        if (window.coverage_gap) button.append(element('small', '缺口 ' + n(window.coverage_gap)));
      }
      button.addEventListener('click', () => openCohortDetail(batch.month, window));
      return button;
    }),
    n(batch.pending_classification),
  ]);
  table(el('cohort-heat'), ['首单批次', ...windows.map(days => days + ' 天'), '新老客待核'], rows);
  renderFirstRepeat(batches, windows);
}

function renderFirstRepeat(batches, windows) {
  const days = windows.at(-1);
  const labels = [...windows.map((limit, i) => (i ? windows[i - 1] : 1) + '–<' + limit + ' 天'), days + ' 天窗内未复购'];
  const mature = batches.filter(batch => {
    const window = windowOf(batch, days);
    return window?.observing === 0 && window.denominator > 0;
  });
  const host = el('first-repeat');
  el('first-repeat-basis').textContent = '最长 ' + days + ' 天窗口全部满期的批次。每条横条按覆盖完整的该批新客计算。';
  if (!mature.length) {
    host.replaceChildren(element('p', '所选范围暂无符合条件的批次。', 'muted'));
    return;
  }
  const draw = svgChart(host, 940, mature.length * 32 + 8, '按批次的首次回购时间分布', true);
  mature.forEach((batch, index) => {
    const window = windowOf(batch, days);
    const y = index * 32 + 4;
    const counts = batch.first_repeat.counts;
    draw('text', {x: 2, y: y + 15}, batch.month + ' · ' + n(window.denominator) + ' 人');
    let x = 135;
    counts.forEach((count, part) => {
      const fraction = count / window.denominator;
      const width = 620 * fraction;
      if (width > 0) {
        const color = part === counts.length - 1 ? 'series-unverified' : seriesClass(part);
        const rect = draw('rect', {class: color, x, y, width, height: 20, rx: 2});
        draw('title', {}, labels[part] + ' · ' + n(count) + ' 人（' + rate(fraction) + '）', rect);
      }
      x += width;
    });
    if (window.coverage_gap) draw('text', {x: 765, y: y + 15}, '覆盖缺口 ' + n(window.coverage_gap) + ' 人');
  });
  legend(host, labels.map((label, index) => [label, index === labels.length - 1 ? 'series-unverified' : seriesClass(index)]));
  const details = element('details');
  const grid = element('div', null, 'table-scroll');
  grid.tabIndex = 0;
  grid.setAttribute('role', 'region');
  grid.setAttribute('aria-label', '首次回购人数明细');
  details.append(element('summary', '查看各段人数'), grid);
  table(grid, ['首单批次', ...labels, '覆盖缺口'], mature.map(batch => [
    batch.month, ...batch.first_repeat.counts.map(n), n(windowOf(batch, days).coverage_gap),
  ]));
  host.append(details);
}

function barChart(host, description, rows, format, series, axis = format) {
  const width = Math.max(540, 60 * rows.length + 70);
  const draw = svgChart(host, width, 205, description, true);
  const values = rows.map(row => row.value).filter(Number.isFinite);
  const max = Math.max(0, ...values);
  const step = (width - 56) / Math.max(1, rows.length);
  const barWidth = Math.min(44, step - 8);
  const y = value => 154 - value * 113 / (max || 1);
  for (const value of new Set([0, max / 2, max])) {
    draw('line', {class: 'gridline', x1: 54, x2: width - 4, y1: y(value), y2: y(value)});
    draw('text', {x: 49, y: y(value) + 4, 'text-anchor': 'end'}, axis(value));
  }
  rows.forEach((row, index) => {
    const x = 54 + (index + .5) * step;
    const mark = draw('g', {});
    draw('title', {}, row.month + ' · ' + row.detail, mark);
    if (Number.isFinite(row.value)) {
      draw('rect', {class: series, x: x - barWidth / 2, y: Math.min(152, y(row.value)), width: barWidth,
        height: Math.max(2, 154 - y(row.value)), rx: 3}, null, mark);
    }
    draw('text', {x, y: Number.isFinite(row.value) ? y(row.value) - 8 : 145, 'text-anchor': 'middle'},
      row.short || format(row.value), mark);
    draw('text', {x, y: 174, 'text-anchor': 'middle'}, row.month, mark);
    if (row.partial) draw('text', {x, y: 193, 'text-anchor': 'middle'}, '部分', mark);
  });
}

function renderReturns(data, referenceBatches) {
  const {return_after: after, return_within: within} = data.query;
  const division = 44 + 446 * after / within;
  const draw = svgChart(el('return-timeline'), 540, 74, '首单后前 ' + after + ' 天未复购，观察至第 ' + within + ' 天');
  draw('line', {class: 'timeline-rule series-1', x1: 44, x2: division, y1: 27, y2: 27, 'stroke-width': 8});
  draw('line', {class: 'timeline-rule series-0', x1: division, x2: 490, y1: 27, y2: 27, 'stroke-width': 8});
  draw('text', {x: 44, y: 16}, '首单');
  draw('text', {x: 490, y: 16, 'text-anchor': 'end'}, '回流窗截止');
  draw('text', {x: 44, y: 53}, '前 ' + after + ' 天未复购');
  draw('text', {x: 490, y: 53, 'text-anchor': 'end'}, after + '–<' + within + ' 天观察回流');
  const batches = data.cohorts.batches;
  const details = batches.map(batch => {
    const window = windowOf(batch, within) || windowOf(referenceBatches.find(row => row.month === batch.month), within);
    const value = batch.silent_return;
    return {month: batch.month, value, note: completionNote(window),
      partial: Boolean(window?.observing || window?.coverage_gap)};
  });
  barChart(el('return-rates'), '各批次沉默后回流率', details.map(({month, value, partial, note}) => ({
    month, value: value.rate, partial, short: value.denominator ? n(value.numerator) + '/' + n(value.denominator) : '',
    detail: rate(value.rate) + ' · ' + n(value.numerator) + ' / ' + n(value.denominator) + ' 人。' + note,
  })), rate, 'series-0');
  const whole = new Intl.NumberFormat('en-US', {maximumFractionDigits: 0});
  const compact = new Intl.NumberFormat('en-US', {notation: 'compact', maximumFractionDigits: 1});
  barChart(el('return-amounts'), '各批次已知回流订单金额，美元', details.map(({month, value, partial, note}) => ({
    month, value: !value.denominator || value.return_amount.known_usd == null ? null : Number(value.return_amount.known_usd),
    detail: (value.denominator ? amount(value.return_amount) : '—') + '。' + note, partial: partial || Boolean(value.return_amount.unknown_orders),
  })), value => value == null ? '—' : '$' + whole.format(value), 'series-2', value => '$' + compact.format(value));
  const breakdown = element('details');
  const grid = element('div', null, 'table-scroll');
  grid.tabIndex = 0;
  grid.setAttribute('role', 'region');
  grid.setAttribute('aria-label', '沉默后回流明细');
  breakdown.append(element('summary', '查看回流金额与覆盖明细'), grid);
  table(grid, ['首单批次', '回流人数', '可比较沉默人数', '回流率', '回流金额', '窗口状态'],
    details.map(({month, value, note}) => [month, n(value.numerator), n(value.denominator), rate(value.rate),
      value.denominator ? amount(value.return_amount) : '—', note || '—']));
  el('return-amounts').append(breakdown);
}

function renderTrend(rows) {
  const host = el('return-trend');
  const ticks = rows.map((row, index) =>
    index === 0 || index === rows.length - 1 || index === Math.floor(rows.length / 2) ? row.date.slice(5) : '');
  const max = Math.max(2, ...rows.flatMap(row => [row.silent_wakeup, row.lost_return]).filter(Number.isFinite));
  lineChart(host, {description: '每日沉默唤醒与流失回流人数', ticks,
    series: [['silent_wakeup', 'silent'], ['lost_return', 'lost']].map(([key, color]) => ({
      name: stageNames[key], color, values: rows.map(row => ({value: row[key], label: row.date})),
    })), format: n, max: Math.ceil(max / 2) * 2});
  const details = element('details');
  const values = element('div', null, 'table-scroll');
  values.tabIndex = 0;
  values.setAttribute('role', 'region');
  values.setAttribute('aria-label', '每日回流人数明细');
  details.append(element('summary', '查看每日回流人数'), values);
  table(values, ['上海日期', '沉默唤醒', '流失回流'],
      rows.map(row => [row.date, n(row.silent_wakeup), n(row.lost_return)]));
  host.append(details);
}

function renderStages(data) {
  const sections = data.stages;
  const total = sections.stages.reduce((sum, stage) => sum + stage.count, 0);
  const inactive = sections.stages.filter(({kind}) => ['silent', 'lost', 'long_lost'].includes(kind))
    .reduce((sum, stage) => sum + stage.count, 0);
  const returned = sections.returns.find(({kind}) => kind === 'any')?.count;
  const missing = sections.daily_returns.filter(row => row.silent_wakeup == null || row.lost_return == null).length;
  const observed = '截至 ' + data.observation_date + '，所选期间 ' + n(total) + ' 位已覆盖购买客户中，' +
    n(inactive) + ' 人处于沉默或流失（' + rate(total ? inactive / total : null) + '），本期有 ' + n(returned) + ' 人回流。';
  const thresholds = data.lifecycle_policy?.thresholds_days;
  el('stage-basis').textContent = '仅统计所选期间至少有一笔有效订单的客户，阶段截至 ' + data.observation_date + '。' +
    (thresholds?.length === 3 ? ' 阶段起点：沉默 ' + thresholds[0] + ' 天、流失 ' + thresholds[1] + ' 天、长期流失 ' + thresholds[2] + ' 天。' : '') +
    (sections.status === 'partial' ? ' 当前结果存在覆盖或身份缺口。' : '');
  el('stage-finding').textContent = observed + (missing ? ' 每日曲线有 ' + n(missing) + ' 天缺口。' : '');
  el('stage-example').textContent = total ? '当前范围 · ' + observed : '当前范围暂无可用于说明的客户数据。';
  el('stage-chart-title').textContent = '客户状态分布（' + n(total) + ' 人）';
  const distribution = el('stage-distribution');
  if (total) {
    const draw = svgChart(distribution, 540, 42, sections.stages.map(({kind, count}) => stageNames[kind] + ' ' + n(count) + ' 人').join('，'));
    let x = 0;
    sections.stages.forEach(({kind, count}, index) => {
      const width = 540 * count / total;
      if (width <= 0) return;
      const group = draw('rect', {class: kind === 'unverified' ? 'series-unverified' : seriesClass(index),
        x, y: 0, width, height: 36, rx: 2});
      draw('title', {}, stageNames[kind] + ' · ' + n(count) + ' 人 · ' + rate(count / total), group);
      x += width;
    });
  } else {
    distribution.replaceChildren(element('p', '所选范围暂无购买客户。', 'muted'));
  }
  for (const [id, values] of [['stage-counts', sections.stages], ['stage-inflow', sections.inflow], ['stage-returns', sections.returns]]) {
    el(id).replaceChildren(...values.map(({kind, group, count}, index) => {
      const item = element('li');
      const button = memberButton(stageNames[kind], group, count);
      if (id === 'stage-counts') {
        button.classList.add(kind === 'unverified' ? 'series-unverified' : seriesClass(index));
      }
      item.append(button);
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

async function query(event) {
  event?.preventDefault();
  if (el('run-query').disabled) return;
  pending(true);
  current = memberView = null;
  emailForm.querySelector('button').disabled = true;
  for (const id of ['member-panel', 'cohort-kpis', 'cohorts', 'returns', 'stages']) el(id).hidden = true;
  el('email-status').textContent = '';
  el('query-status').textContent = '正在读取用户分析…';
  try {
    const args = Object.fromEntries(new FormData(filters));
    args.end_exclusive = dateShift(args.end, 1);
    delete args.end;
    const data = await summary(args);
    const focusWindows = [...new Set([90, 180, data.query.return_within])].sort((a, b) => a - b);
    let referenceBatches = data.cohorts.batches;
    let referenceWarning = '';
    if (focusWindows.some(days => !data.query.windows.includes(days))) {
      try {
        const reference = await summary({...args, windows: focusWindows.join(',')});
        if (reference.observation_date !== data.observation_date || reference.config_version !== data.config_version ||
            reference.data_version !== data.data_version) {
          throw new Error('参考批次数据版本已更新。');
        }
        referenceBatches = reference.cohorts.batches;
      } catch (error) {
        referenceWarning = '参考批次读取失败。' + error.message;
      }
    }
    renderFindings(referenceWarning ? null : latestMatureBatch(referenceBatches), data.query);
    if (referenceWarning) {
      el('repeat-finding').textContent = referenceWarning;
      el('return-finding').textContent = referenceWarning;
    }
    renderCohorts(data);
    renderReturns(data, referenceBatches);
    renderStages(data);
    current = data;
    el('metadata').textContent = '数据截止 ' + data.observation_date + ' · 配置 v' + data.config_version +
        ' · 订单覆盖缺 ' + n(data.coverage.order_missing_days) + ' 天';
    el('query-status').textContent = data.coverage.new_customer_flags?.status === 'complete' ? '' :
        'ES 新老客标记覆盖有缺口，匹配不到的首单计入待核。';
    for (const id of ['cohort-kpis', 'cohorts', 'returns', 'stages']) el(id).hidden = false;
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
    view.total = value.total;
    const cohort = view.group.startsWith('cohort:');
    const windowColumns = cohort ? ['时间窗状态', '计入分子'] : [];
    table(el('members'), ['客户邮箱', '站内首单', '末次购买', '阶段', ...windowColumns, '详情'], value.rows.map(row => [
      row.email, when(row.first_paid_at), when(row.last_paid_at), stageNames[row.stage],
      ...(cohort ? [windowNames[row.window_status], yesNo(row.in_numerator)] : []),
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
