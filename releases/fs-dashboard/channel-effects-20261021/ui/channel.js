import {protectedRead, sessionIdentity} from '/dashboard/workspace-assets/workspace-native-20261006-ba0a83afd594/runtime.js';

const $ = id => document.getElementById(id);
const form = $('filters');
const field = key => form.elements.namedItem(key);
const usd = value => value == null ? '—' : new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(value);
const cny = value => value == null ? '—' : '¥' + new Intl.NumberFormat('en-US', {maximumFractionDigits:2}).format(value);
const count = value => new Intl.NumberFormat('en-US').format(value);
const pct = value => value == null ? '—' : (100 * value).toFixed(1) + '%';
const text = (tag, value, cls) => {
  const node = document.createElement(tag);
  if (value != null) node.textContent = value;
  if (cls) node.className = cls;
  return node;
};
let data = null;
let page = 1;
let direction = 'desc';
let readController = null;
let poll = null;
let generation = 0;
let denied = false;
let identity = null;
const lifetime = new AbortController();
const beijingDay = () => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
const shift = (day, amount) => { const d = new Date(day + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + amount); return d.toISOString().slice(0, 10); };
field('end').value = shift(beijingDay(), -1);
field('start').value = shift(field('end').value, -6);
field('start').max = field('end').max = beijingDay();
$('theme').value = window.FSTheme?.get() || 'system';
$('theme').addEventListener('change', event => window.FSTheme?.set(event.target.value));
addEventListener('fs-theme-change', () => { $('theme').value = window.FSTheme?.get() || 'system'; });

function show(message, state = 'available') {
  $('status').textContent = message;
  $('status').dataset.state = state;
}
function deny(code) {
  denied = true;
  readController?.abort(); clearTimeout(poll); data = null;
  $('results').hidden = true; $('refresh').disabled = true;
  for (const node of form.querySelectorAll('input,select,button')) node.disabled = true;
  show(code === 403 ? '当前账号未获渠道效果看板授权，请联系管理员。' : '登录已失效，请重新登录。', 'error');
}
function params(refresh = false) {
  const query = new URLSearchParams();
  for (const [key, value] of new FormData(form)) {
    if (key === 'code') {
      if (value) query.set(key, JSON.parse(value));
    } else if (value) query.set(key, value);
  }
  query.set('page', String(page)); query.set('sort', $('sort').value); query.set('direction', direction);
  if (refresh) query.set('refresh', '1');
  return query;
}
function selectOptions(key, rows, label) {
  const select = field(key), old = select.value;
  select.replaceChildren(new Option(label, ''));
  for (const [value, name] of rows) select.add(new Option(name, value));
  if (old && ![...select.options].some(o => o.value === old)) select.add(new Option('已选：' + (key === 'code' ? JSON.parse(old) || '推荐人无码' : old), old));
  select.value = old;
}
function cell(value) { return value instanceof Node ? value : document.createTextNode(value == null ? '—' : String(value)); }
function table(hostId, headers, rows, makeCells, title, selected = () => false) {
  const host = $(hostId); host.replaceChildren();
  if (!rows.length) { host.append(text('p', '当前范围没有记录。', 'empty')); return; }
  const wrap = text('div', null, 'table-wrapper');
  wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', title);
  const grid = text('table');
  const thead = text('thead'), head = text('tr');
  for (const label of headers) { const th = text('th', label); th.scope = 'col'; head.append(th); }
  thead.append(head); grid.append(thead);
  const body = text('tbody');
  for (const row of rows) {
    const tr = text('tr'); tr.dataset.selected = String(selected(row));
    for (const value of makeCells(row)) { const td = text('td'); td.append(cell(value)); tr.append(td); }
    body.append(tr);
  }
  grid.append(body); wrap.append(grid); host.append(wrap);
}
function drill(label, key, value, secondary = '') {
  const button = text('button', label, 'table-link'); button.type = 'button';
  button.addEventListener('click', () => { field(key).value = value; if (key === 'project') field('code').value = ''; page = 1; load(); });
  if (secondary) button.append(text('span', secondary, 'cell-secondary'));
  return button;
}
function comparison() {
  const coupon = field('mode').value === 'coupon';
  const columns = ['订单数', '销售额 $', '采购 ¥', '毛利 ¥', '利润率'];
  const values = row => [count(row.orders), usd(row.salesUsd), cny(row.costCny), cny(row.profitCny), pct(row.margin)];
  table('projects', [coupon ? '模板 / 活动' : '项目 / 渠道', ...columns, '推荐人无码'], data.projects, row => {
    const label = !coupon && row.key === '无推广归属' ? text('span', '无推广归属（对照）', 'control') : drill(row.label, 'project', row.key);
    return [label, ...values(row), count(row.referrerOnly)];
  }, coupon ? '优惠券模板效果' : '项目效果对比', row => row.key === field('project').value);
  table('codes', [coupon ? '发放批次' : '折扣码 / 推广人', ...columns], data.codes, row => [drill(row.label, 'code', JSON.stringify(row.key), coupon ? '' : row.promoters), ...values(row)], coupon ? '优惠券批次效果' : '折扣码效果', row => JSON.stringify(row.key) === field('code').value);
}
function breakdown(host, key, title) {
  const rows = data.breakdowns[key];
  const maximum = Math.max(1, ...rows.map(row => row.salesUsd));
  table(host, [title, '订单数', '销售额 $', '采购 ¥', '毛利 ¥', '利润率'], rows, row => {
    const name = text('span', row.label);
    const track = text('span', null, 'bar-track'), fill = text('span', null, 'bar-fill');
    fill.style.width = (100 * row.salesUsd / maximum) + '%'; track.append(fill); name.append(track);
    return [name, count(row.orders), usd(row.salesUsd), cny(row.costCny), cny(row.profitCny), pct(row.margin)];
  }, title + '效果明细');
}
function kpis() {
  const s = data.summary, coupon = field('mode').value === 'coupon';
  const labels = [
    ['订单数', count(s.orders), coupon ? '去重后的用券订单' : '用码 + 推荐人无码'],
    ['销售额（USD）', usd(s.salesUsd), '订单美元实付合计'],
    ['销售额（¥）', cny(s.saleCny), '已关联发货记录原值'],
    ['采购成本（¥）', cny(s.costCny), `${s.coveredOrders} / ${s.orders} 单有关联发货`],
    ['毛利（¥）', cny(s.profitCny), '已关联发货销售 − 采购'],
    ['综合利润率', pct(s.margin), '仅发货覆盖单 · 加权'],
    ['客单价（USD）', usd(s.aovUsd), '美元销售额 / 订单数'],
    coupon ? ['用券订单占全站', pct(s.couponShareSite), `${count(s.overlapOrders)} 单同时使用优惠码`] : ['用码订单占比', pct(s.shareAllCodes) + ' / ' + pct(s.shareSite), '占全部用码 / 全站订单']
  ];
  $('kpis').replaceChildren(...labels.map(([name, value, hint]) => {
    const card = text('article', null, 'panel kpi'); card.append(text('span', name, 'name'), text('strong', value), text('small', hint)); return card;
  }));
  $('coverage').textContent = `发货匹配 ${count(s.coveredOrders)} / ${count(s.orders)} 单`;
  const paragraphs = [
    `范围：MMOEXP；${data.period.start} 至 ${data.period.end}，按订单付款日期、北京时间。${coupon ? '按模板/活动与批次追踪，渠道无依据保持未归类。' : '渠道业绩包含实际用码与推荐人无码；无码且无推荐人只作对照，不等同于已证明的自然流量。'}`,
    `全站分母 ${count(data.denominator.orders)} 单，用码分母 ${count(data.denominator.codedOrders)} 单；均沿用当前游戏、国家、支付与状态筛选，不随项目/单码筛选缩小。${count(s.referrerOnly)} 单为推荐人无码，不算用码订单。`,
    `销售额、客单价：Admin 订单美元金额。人民币销售、成本、毛利、利润率：仅匹配的 Order「订单发货」记录，先加总再相除。缺成本不当作零；匹配不证明全部交付、退款后净收入或最终结算。${count(s.conflicts)} 单有归因冲突待核。`,
    `成本来源：${data.sources.cost.source}；${data.sources.cost.generatedAt ? new Date(data.sources.cost.generatedAt).toLocaleString('zh-CN', {hour12:false,timeZone:'Asia/Shanghai'}) : '尚无数据'}。${data.sources.cost.limitation}`,
    `优惠码与优惠券分开统计，同一订单可重叠；模板、批次分项也可能重叠，不能直接相加。状态保留后台原值；“排除退款”不代表全部为已完成订单。`,
    `归因：保留原码，忽略大小写；同码冲突待核。分销是推广分类，站点单独筛选。${data.sources.attribution.historical}。`
  ];
  $('definitions').replaceChildren(...paragraphs.map(p => text('p', p)));
}
const svgNode = (tag, attributes, content) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (content != null) node.textContent = content;
  return node;
};
function trend() {
  const rows = data.trend, width = 1000, height = 300, left = 70, right = 920, top = 32, bottom = 250;
  const maxSales = Math.max(1, ...rows.map(r => r.salesUsd));
  const profits = rows.filter(r => r.profitCny != null).map(r => r.profitCny);
  const minProfit = Math.min(0, ...profits), maxProfit = Math.max(1, ...profits);
  const x = i => left + (right - left) * (i + .5) / rows.length;
  const ySales = v => bottom - (bottom - top) * v / maxSales;
  const yProfit = v => bottom - (bottom - top) * (v - minProfit) / (maxProfit - minProfit);
  const chart = svgNode('svg', {viewBox:`0 0 ${width} ${height}`, class:'chart', role:'img', 'aria-labelledby':'daily-chart-title daily-chart-desc'});
  chart.append(svgNode('title', {id:'daily-chart-title'}, '每日销售与毛利趋势'), svgNode('desc', {id:'daily-chart-desc'}, '柱形为美元销售，折线为人民币毛利。缺失成本保留断点；完整数值见下方每日数据表。'));
  chart.append(svgNode('text', {x:left, y:17}, '销售额 USD'), svgNode('text', {x:right, y:17, 'text-anchor':'end'}, '毛利 CNY'));
  for (let i = 0; i <= 4; i++) {
    const y = top + (bottom - top) * i / 4;
    chart.append(svgNode('line', {x1:left,x2:right,y1:y,y2:y,class:'axis'}));
    chart.append(svgNode('text', {x:left - 10,y:y + 4,'text-anchor':'end'}, '$' + count(Math.round(maxSales * (1 - i / 4)))));
    if (profits.length) chart.append(svgNode('text', {x:right + 10,y:y + 4}, '¥' + count(Math.round(maxProfit - (maxProfit - minProfit) * i / 4))));
  }
  let segment = [];
  const flush = () => { if (segment.length) chart.append(svgNode('polyline', {points:segment.join(' '),class:'profit'})); segment = []; };
  rows.forEach((r, i) => {
    const bar = svgNode('rect', {x:x(i) - Math.min(22, 270 / rows.length), y:ySales(r.salesUsd), width:Math.min(44, 540 / rows.length), height:Math.max(0, bottom - ySales(r.salesUsd)), rx:2, class:'sales'});
    bar.append(svgNode('title', {}, `${r.key} · 销售 ${usd(r.salesUsd)} · 毛利 ${cny(r.profitCny)}`)); chart.append(bar);
    if (r.profitCny == null) flush(); else segment.push(`${x(i)},${yProfit(r.profitCny)}`);
    if (i % Math.max(1, Math.ceil(rows.length / 9)) === 0 || i === rows.length - 1) chart.append(svgNode('text', {x:x(i),y:bottom + 24,'text-anchor':'middle'}, r.key.slice(5)));
  }); flush();
  if (rows.length <= 31) rows.forEach((r, i) => { if (r.profitCny != null) chart.append(svgNode('circle', {cx:x(i),cy:yProfit(r.profitCny),r:3,class:'point'})); });
  const legend = text('div', null, 'chart-legend'); legend.append(text('span', '销售额（USD，左轴）'), text('span', '毛利（¥，右轴；仅发货覆盖）'));
  $('trend').replaceChildren(chart, legend);
  table('trend-table', ['日期', '订单数', '销售额 $', '采购 ¥', '毛利 ¥', '利润率', '发货覆盖'], rows, r => [r.key,count(r.orders),usd(r.salesUsd),cny(r.costCny),cny(r.profitCny),pct(r.margin),`${r.coveredOrders} / ${r.orders}`], '每日销售与毛利数值');
}
function orders() {
  const coupon = field('mode').value === 'coupon';
  table('orders', ['付款时间', '订单号', '游戏', coupon ? '优惠券渠道' : '项目 / 归属', coupon ? '关联用码 / 推荐人（独立）' : '推广人', '折扣码', '优惠券 / 批次', '国家', '支付方式', '销售额 $', '发货销售 ¥', '采购 ¥', '毛利 ¥', '利润率', '状态'], data.orders, r => [
    r.paidAt, r.orderNo, r.game, coupon ? '未归类' : r.project + ' · ' + r.attribution, r.promoter, r.code || '—',
    r.coupons.map(c => c.title + ' / ' + c.batch).join('；') || '—', r.country,r.payment,usd(r.salesUsd),cny(r.saleCny),cny(r.costCny),cny(r.profitCny),pct(r.saleCny ? r.profitCny / r.saleCny : null),r.status
  ], '当前筛选订单明细');
  $('total').textContent = '共 ' + count(data.total) + ' 单 · 每页 50 单';
  $('page').textContent = `${data.page} / ${data.pages}`;
  $('prev').disabled = data.page <= 1; $('next').disabled = data.page >= data.pages;
  page = data.page;
}
function render() {
  const coupon = field('mode').value === 'coupon';
  $('project-label').textContent = coupon ? '优惠券模板 / 活动' : '项目 / 渠道';
  $('code-label').textContent = coupon ? '发放批次' : '折扣码';
  $('projects-title').textContent = coupon ? '优惠券模板 / 活动效果对比' : '项目效果对比';
  $('codes-title').textContent = coupon ? '发放批次效果对比' : '折扣码效果对比';
  $('code-hint').textContent = coupon ? '当前模板 / 活动下的批次；渠道没有依据保持未归类。' : '当前项目下各折扣码；推荐人无码单列。';
  selectOptions('gid', data.options.games, '全部游戏');
  selectOptions('country', data.options.countries.map(v => [v,v]), '全部国家 / 地区');
  selectOptions('payment', data.options.payments.map(v => [v,v]), '全部支付方式');
  selectOptions('project', data.projects.filter(r => coupon || r.key !== '无推广归属').map(r => [r.key,r.label]), coupon ? '全部模板 / 活动' : '全部项目');
  selectOptions('code', data.codes.map(r => [JSON.stringify(r.key),r.label]), coupon ? '全部发放批次' : '全部折扣码');
  $('scope').textContent = `${data.period.start} — ${data.period.end} · ${field('gid').selectedOptions[0].text} · ${field('project').selectedOptions[0].text} · ${coupon ? '用券订单（跨模板去重）' : '实际用码 + 推荐人无码；无推广归属仅作对照'} · ${field('status').selectedOptions[0].text}`;
  $('freshness').textContent = '更新 ' + new Date(data.generatedAt).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'});
  kpis(); comparison(); trend(); orders();
  for (const [host,key,title] of [['games','game','游戏'],['countries','country','国家 / 地区'],['payments','payment','支付方式'],['customers','customerType','新老客'],['states','status','订单状态']]) breakdown(host,key,title);
  $('results').hidden = false;
  if (data.costRefreshing) show('订单已取得，正在从共享源关联采购成本；当前毛利仅代表已匹配发货。', 'partial');
  else if (data.costError) show('本次采购成本读取未完成，订单与优惠券结果保留；成本缺口见覆盖说明，可稍后刷新。', 'partial');
  else if (data.sourceError) show('本次刷新失败，保留上次完整订单结果；时间与覆盖范围见下方。', 'partial');
  else if (data.refreshing) show('正在刷新，当前展示上次完整结果。', 'partial');
  else if (data.summary.coveredOrders < data.summary.orders) show('订单与优惠券关联已完成；部分订单缺少采购成本，毛利和利润率仅代表发货覆盖单。', 'partial');
  else show(data.summary.orders ? '当前范围已读取，归因与成本覆盖见下方说明。' : '当前筛选没有渠道订单。无推广归属可在左侧对照表查看。');
}
async function load(refresh = false) {
  if (denied || document.hidden || !form.reportValidity()) return;
  clearTimeout(poll); readController?.abort(); readController = new AbortController();
  const mine = ++generation;
  $('refresh').disabled = true;
  $('results').hidden = true;
  show('正在读取当前筛选范围…');
  try {
    const response = await protectedRead('./data.json?' + params(refresh), {credentials:'same-origin', cache:'no-store', redirect:'error', signal:AbortSignal.any([readController.signal, lifetime.signal, AbortSignal.timeout(25000)])}, deny);
    if (mine !== generation || denied) return;
    const next = await response.json();
    if (mine !== generation) return;
    if (response.status === 202 || response.status === 429) {
      show(response.status === 429 ? '已有查询正在执行，稍后继续读取。' : '正在从共享数据源整理订单与优惠券记录…');
      poll = setTimeout(() => load(), (next.retryAfter || 3) * 1000); return;
    }
    if (!response.ok || next.version !== 'channel-effects-v1') throw Error('source_failed');
    data = next; render();
    if (next.refreshing) poll = setTimeout(() => load(), 3000);
  } catch (error) {
    if (mine !== generation || denied || error.name === 'AbortError') return;
    show('本次数据未取得。请稍后刷新；不会把失败、缺数或旧范围显示成零。', 'error');
  } finally { if (mine === generation && !denied) $('refresh').disabled = false; }
}
form.addEventListener('submit', event => { event.preventDefault(); page = 1; load(); });
for (const key of ['mode','gid','project','code','status','country','payment']) field(key).addEventListener('change', () => {
  if (['mode','gid','project'].includes(key)) field('code').value = '';
  if (key === 'mode') field('project').value = '';
  page = 1; load();
});
for (const button of form.querySelectorAll('[data-days]')) button.addEventListener('click', () => {
  field('end').value = beijingDay(); field('start').value = shift(field('end').value, 1 - Number(button.dataset.days)); page = 1; load();
});
$('reset').addEventListener('click', () => { form.reset(); field('end').value = shift(beijingDay(), -1); field('start').value = shift(field('end').value, -6); page = 1; load(); });
$('refresh').addEventListener('click', () => load(true));
$('sort').addEventListener('change', () => { page = 1; load(); });
$('direction').addEventListener('click', () => { direction = direction === 'desc' ? 'asc' : 'desc'; $('direction').textContent = direction === 'desc' ? '降序 ↓' : '升序 ↑'; page = 1; load(); });
$('prev').addEventListener('click', () => { page--; load(); }); $('next').addEventListener('click', () => { page++; load(); });
async function checkIdentity() {
  if (denied || document.hidden) return;
  try {
    const next = await sessionIdentity(lifetime.signal);
    if (!next?.name || next.role !== 'admin' || (identity && identity.name !== next.name)) { deny(next?.name ? 403 : 401); return; }
    identity = next;
  } catch { deny(401); }
}
document.addEventListener('visibilitychange', async () => { if (document.hidden) { clearTimeout(poll); readController?.abort(); } else { await checkIdentity(); if (!denied) load(); } });
addEventListener('pagehide', () => { lifetime.abort(); readController?.abort(); clearTimeout(poll); clearInterval(identityTimer); }, {once:true});
const identityTimer = setInterval(checkIdentity, 60000);
await checkIdentity();
if (!denied) { $('refresh').disabled = false; load(); }
