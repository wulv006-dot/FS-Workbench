import {protectedRead, sessionIdentity} from '/dashboard/workspace-assets/workspace-native-20261006-ba0a83afd594/runtime.js';
import {WORLD} from './world-map.js';

const $ = id => document.getElementById(id);
const form = $('filters');
const field = key => form.elements.namedItem(key);
const trackingFilters = ['status','country','payment','project','code','coupon_template','coupon_batch'];
const privateFilters = {q:'keyword_applied',code:'discount_code_applied',coupon_batch:'coupon_batch_applied'};
const usd = value => value == null ? '—' : new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(value);
const cny = value => value == null ? '—' : '¥' + new Intl.NumberFormat('en-US', {maximumFractionDigits:2}).format(value);
const count = value => new Intl.NumberFormat('en-US').format(value);
const pct = value => value == null ? '—' : (100 * value).toFixed(1) + '%';
const regions = new Intl.DisplayNames(['zh-CN'], {type:'region'});
const countryLabel = value => /^[A-Z]{2}$/.test(value) ? `${regions.of(value)}（${value}）` : value;
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
let renderedQuery = '';
let exportPending = false;
let detailPage = 1;
let detailController = null;
const snapshotKey = value => JSON.stringify([value.version, value.snapshot_id, value.revisions, value.totals, value.channels, value.coverage, value.status, value.refresh_deferred, value.refresh_reason, value.generatedAt, value.sources?.cost?.generatedAt, value.sources?.customer, value.sources?.accounting, value.sources?.cache, value.sources?.orderSource, value.sourceAttribution, value.refreshing, value.costRefreshing, value.costError, value.sourceError]);
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
  readController?.abort(); detailController?.abort(); clearTimeout(poll); data = null;
  $('results').hidden = true; $('refresh').disabled = true;
  $('export-facts').disabled = true;
  for (const node of form.querySelectorAll('input,select,button')) node.disabled = true;
  show(code === 403 ? '当前账号未获渠道效果看板授权，请联系管理员。' : '登录已失效，请重新登录。', 'error');
}
function params(refresh = false) {
  const query = new URLSearchParams();
  if (field('mode').value === 'order-facts') {
    for (const key of ['mode','start','end','channel']) query.set(key, field(key).value);
    query.set('site_id', '266'); query.set('gid', field('gid').value || 'all');
    for (const key of trackingFilters) {
      const value = field(key==='code'?'fact_code':key).value;
      if (value && !(key==='status' && value==='all')) query.set(key,key==='code'?value.trim().toLowerCase():value);
    }
    if (field('q').value) query.set('q',field('q').value);
    if (refresh) query.set('refresh', '1');
    return query;
  }
  for (const [key, value] of new FormData(form)) {
    if (key === 'code') {
      if (value) query.set(key, JSON.parse(value));
    } else if (key !== 'channel' && value) query.set(key, value);
  }
  query.set('page', String(page)); query.set('sort', $('sort').value); query.set('direction', direction);
  if (refresh) query.set('refresh', '1');
  return query;
}
function exportable() {
  return !denied && !exportPending && data?.version === 'order-facts-api-20261113-v1' && !!data.aggregate_csv &&
    renderedQuery === params().toString();
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
    const label = !coupon && row.key === '无推广归属' ? text('span', '自然流量（对照）', 'control') : drill(row.label, 'project', row.key);
    return [label, ...values(row), count(row.referrerOnly)];
  }, coupon ? '优惠券模板效果' : '项目效果对比', row => row.key === field('project').value);
  table('codes', [coupon ? '发放批次' : '折扣码 / 推广人', ...columns], data.codes, row => [drill(row.label, 'code', JSON.stringify(row.key), coupon ? '' : row.promoters), ...values(row)], coupon ? '优惠券批次效果' : '折扣码效果', row => JSON.stringify(row.key) === field('code').value);
}
function breakdown(host, key, title) {
  const rows = data.breakdowns[key];
  const maximum = Math.max(1, ...rows.map(row => row.salesUsd));
  table(host, [title, '订单数', '销售额 $', '采购 ¥', '毛利 ¥', '利润率'], rows, row => {
    const name = text('span', key === 'country' ? countryLabel(row.key) : row.label);
    const track = text('span', null, 'bar-track'), fill = text('span', null, 'bar-fill');
    fill.style.width = (100 * row.salesUsd / maximum) + '%'; track.append(fill); name.append(track);
    return [name, count(row.orders), usd(row.salesUsd), cny(row.costCny), cny(row.profitCny), pct(row.margin)];
  }, title + '效果明细');
}
function kpis() {
  const s = data.summary, coupon = field('mode').value === 'coupon', legacy = data.revenueBasis === 'legacy_delivery';
  const labels = [
    ['订单数', count(s.orders), (coupon ? '去重后的用券订单' : '用码 + 推荐人无码') + (s.testOrders ? ` · 排除 ${s.testOrders} 测试单` : '')],
    ['销售额（USD）', usd(s.salesUsd), 'Admin整单金额，排除验证未通过欺诈单'],
    ['销售额（¥）', cny(s.saleCny), legacy ? '旧发货收入字段 · Admin回补中' : '已完成且已核算的Admin订单金额'],
    ['采购成本（¥）', cny(s.costCny), `${s.coveredOrders} / ${s.completedOrders} 已完成单已核算`],
    ['毛利（¥）', cny(s.profitCny), legacy ? '旧收入口径 · 暂未切换新法' : '同群体Admin收入 − 实际采购成本'],
    ['综合利润率', pct(s.margin), legacy ? '旧收入口径 · 暂未切换新法' : '采购口径毛利 / 同群体收入'],
    ['客单价（USD）', usd(s.aovUsd), '美元销售额 / 订单数'],
    coupon ? ['用券订单占全站', pct(s.couponShareSite), `${count(s.overlapOrders)} 单同时使用优惠码`] : ['用码订单占比', pct(s.shareAllCodes) + ' / ' + pct(s.shareSite), '占全部用码 / 全站订单']
  ];
  $('kpis').replaceChildren(...labels.map(([name, value, hint]) => {
    const card = text('article', null, 'panel kpi'); card.append(text('span', name, 'name'), text('strong', value), text('small', hint)); return card;
  }));
  $('coverage').textContent = `已完成 ${count(s.completedOrders)} 单 · 成本未覆盖 ${count(s.missingCostOrders)} 单（SCM ${count(s.scmOrders)}） · 待完成 ${count(s.pendingOrders)} 单` + (s.testOrders ? ` · 排除测试 ${count(s.testOrders)} 单` : '');
  const paragraphs = [
    `范围：MMOEXP；${data.period.start} 至 ${data.period.end}，按订单付款日期、北京时间。${coupon ? '按模板/活动与批次追踪，渠道无依据保持未归类。' : '渠道业绩包含实际用码与推荐人无码；自然流量（对照）指无码且无推荐人，与GA4自然搜索渠道分开。'}`,
    `全站分母 ${count(data.denominator.orders)} 单，用码分母 ${count(data.denominator.codedOrders)} 单；均沿用当前游戏、国家、支付与状态筛选，不随项目/单码筛选缩小。${count(s.referrerOnly)} 单为推荐人无码，不算用码订单。`,
    `销售额、客单价：Admin整单美元金额；验证未通过欺诈单 ${count(s.fraudOrders)} 单、${usd(s.excludedFraudUsd || 0)} 从经营指标排除，原状态和明细保留。退款申请不等于已退款。成本、毛利和利润率仅核算同一已完成群体；待完成 ${count(s.pendingOrders)} 单不计成本和利润。已完成成本未覆盖 ${count(s.missingCostOrders)} 单，其中SCM发货 ${count(s.scmOrders)} 单：NBA2K、ARC由另一系统履约，当前源无成本，不补零。已确认零成本商品 ${count(s.zeroCostOrders)} 单按100%利润率。${count(s.conflicts)} 单有归因冲突待核。`,
    `${data.revenueBasis === 'legacy_delivery' ? '旧收入字段缓存回补中：本范围暂保持原发货销售额口径，不与新口径混算。' : '人民币收入：Admin订单原人民币金额，每单一次；采购成本：该单实际订单发货记录合计；采购毛利=收入−采购成本，毛利率=毛利合计/同群体收入合计。支付费用、退款结算等不全时，不称财务净利润；不拿已完成覆盖单的率冒充全站率。'}常规成本来源：${data.sources.cost.source}；${data.sources.cost.generatedAt ? new Date(data.sources.cost.generatedAt).toLocaleString('zh-CN', {hour12:false,timeZone:'Asia/Shanghai'}) : '尚无数据'}。已确认零成本历史商品使用用户确认及该笔Admin原人民币金额；不按Items类别泛化，也不套固定汇率。`,
    `新老客来源：该笔订单下单时 ES「是否新客户」，是为新客、否为老客。${data.sources.customer?.limitation || '字段未提供时保持未知。'}`,
    `优惠码与优惠券分开统计，同一订单可重叠；模板、批次分项也可能重叠，不能直接相加。状态保留后台原值；“排除退款”不代表全部为已完成订单。`,
    `用户确认的测试单从经营订单数、销售额、占比分子分母、成本和利润中排除；订单明细保留原支付金额并标注测试，不计作成本缺口。当前明细含 ${count(s.testOrders)} 笔测试单。`,
    `归因：保留原码，忽略大小写；同码冲突待核。分销是推广分类，站点单独筛选。${data.sources.attribution.historical}。`
  ];
  if (data.sources.cache) paragraphs.push(`缓存：${data.sources.cache.days} 个完整日归档直接合并；采集时间 ${data.sources.cache.oldest} 至 ${data.sources.cache.newest}。${data.sources.cache.limitation}`);
  $('definitions').replaceChildren(...paragraphs.map(p => text('p', p)));
}
const svgNode = (tag, attributes, content) => {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (content != null) node.textContent = content;
  return node;
};
function trend(rows, facts = false) {
  const width = 1000, height = 300, left = 70, right = 920, top = 32, bottom = 250;
  const maxSales = Math.max(1, ...rows.map(r => r.salesUsd));
  const profits = rows.filter(r => r.profitCny != null).map(r => r.profitCny);
  const minProfit = Math.min(0, ...profits), maxProfit = Math.max(1, ...profits);
  const x = i => left + (right - left) * (i + .5) / rows.length;
  const ySales = v => bottom - (bottom - top) * v / maxSales;
  const yProfit = v => bottom - (bottom - top) * (v - minProfit) / (maxProfit - minProfit);
  const profitLabel = facts ? 'Order 原生利润' : '毛利';
  const chart = svgNode('svg', {viewBox:`0 0 ${width} ${height}`, class:'chart', role:'img', 'aria-labelledby':'daily-chart-title daily-chart-desc'});
  chart.append(svgNode('title', {id:'daily-chart-title'},  `每日销售与${profitLabel}趋势`), svgNode('desc', {id:'daily-chart-desc'}, `柱形为美元销售，折线为人民币${profitLabel}。完整数值见下方每日数据表。`));
  chart.append(svgNode('text', {x:left, y:17}, '销售额 USD'), svgNode('text', {x:right, y:17, 'text-anchor':'end'}, profitLabel+' CNY'));
  for (let i = 0; i <= 4; i++) {
    const y = top + (bottom - top) * i / 4;
    chart.append(svgNode('line', {x1:left,x2:right,y1:y,y2:y,class:'axis'}));
    chart.append(svgNode('text', {x:left - 10,y:y + 4,'text-anchor':'end'}, '$' + count(Math.round(maxSales * (1 - i / 4)))));
    if (profits.length) chart.append(svgNode('text', {x:right + 10,y:y + 4}, '¥' + count(Math.round(maxProfit - (maxProfit - minProfit) * i / 4))));
  }
  let segment = [];
  const flush = () => { if (segment.length) chart.append(svgNode('polyline', {points:segment.join(' '),class:'profit'})); segment = []; };
  rows.forEach((r, i) => {
    if (r.salesUsd != null) {
      const bar = svgNode('rect', {x:x(i) - Math.min(22, 270 / rows.length), y:ySales(r.salesUsd), width:Math.min(44, 540 / rows.length), height:Math.max(0, bottom - ySales(r.salesUsd)), rx:2, class:'sales'});
      bar.append(svgNode('title', {}, `${r.key} · 销售 ${usd(r.salesUsd)} · ${profitLabel} ${cny(r.profitCny)}`)); chart.append(bar);
    }
    if (r.profitCny == null) flush(); else segment.push(`${x(i)},${yProfit(r.profitCny)}`);
    if (i % Math.max(1, Math.ceil(rows.length / 9)) === 0 || i === rows.length - 1) chart.append(svgNode('text', {x:x(i),y:bottom + 24,'text-anchor':'middle'}, r.key.slice(5)));
  }); flush();
  if (rows.length <= 31) rows.forEach((r, i) => { if (r.profitCny != null) chart.append(svgNode('circle', {cx:x(i),cy:yProfit(r.profitCny),r:3,class:'point'})); });
  const legend = text('div', null, 'chart-legend'); legend.append(text('span', '销售额（USD，左轴）'), text('span', facts ? 'Order 原生利润（¥，右轴）' : '毛利（¥，右轴；已完成且已核算）'));
  $('trend').replaceChildren(chart, legend);
  if (facts) {
    table('trend-table', ['日期','已知订单数','已知金额 USD','Order原生利润 ¥','Order原生利润率','范围覆盖'], rows,
      r => [r.key,count(r.orders),usd(r.salesUsd),cny(r.profitCny),pct(r.margin),r.status === 'available' ? '已读' : '部分'], '后台归因每日数值');
  } else {
    table('trend-table', ['日期', '订单数', '销售额 $', '采购 ¥', '毛利 ¥', '利润率', '已完成核算'], rows, r => [r.key,count(r.orders),usd(r.salesUsd),cny(r.costCny),cny(r.profitCny),pct(r.margin),`${r.coveredOrders} / ${r.completedOrders}`], '每日销售与毛利数值');
  }
}
function orders() {
  const coupon = field('mode').value === 'coupon';
  table('orders', ['付款时间', '订单号', '游戏', '新老客（ES）', '订单来源（ES）', coupon ? '优惠券渠道' : '项目 / 归属', coupon ? '关联用码 / 推荐人（独立）' : '推广人', '折扣码', '优惠券 / 批次', '国家', '支付方式', '销售额 $', '核算销售 ¥', '采购 ¥', '毛利 ¥', '利润率', '状态 / 核算'], data.orders, r => [
    r.paidAt, r.orderNo, r.game, r.customerType, r.sourceStatus==='available'?(r.sourceRaw||'自然流量（业务默认）'):'来源未核', coupon ? '未归类' : r.project + ' · ' + r.attribution, r.promoter, r.code || '—',
    r.couponUnknown ? '未核' : r.coupons.map(c => c.title + ' / ' + c.batch).join('；') || '—', countryLabel(r.country),r.payment,usd(r.salesUsd),cny(r.saleCny),cny(r.costCny),cny(r.profitCny),pct(r.saleCny ? r.profitCny / r.saleCny : null),r.status + ' · ' + r.costStatus + (r.costBasis ? ' · ' + r.costBasis : '')
  ], '当前筛选订单明细');
  $('total').textContent = '共 ' + count(data.total) + ' 单 · 每页 50 单' + (data.summary.testOrders ? ` · 含 ${count(data.summary.testOrders)} 笔测试单，仅留明细、不计指标` : '');
  $('page').textContent = `${data.page} / ${data.pages}`;
  $('prev').disabled = data.page <= 1; $('next').disabled = data.page >= data.pages;
  page = data.page;
}
function sourceAttribution() {
  const source=data.sourceAttribution;
  $('distribution-charts').hidden = true;
  $('source-attribution-chart').replaceChildren();
  $('source-sales-chart').replaceChildren();
  $('source-attribution-associations').replaceChildren();
  $('source-attribution').replaceChildren();
  if(!source){$('source-attribution-note').textContent='旧快照尚未提供来源去重视图，未按零解释。';return;}
  const pmax=source.pmaxFc||{};
  $('source-attribution-note').textContent=`${source.basis}。PMax归FC项目：本筛选已核来源内FC成交 ${count(pmax.orders||0)} 单 / ${usd(pmax.salesUsd)}；已包含在广告行，不再相加。来源未核 ${count(source.unknownSourceOrders)} 单。跨游戏Google费用/平台价值/ROAS未整条归FC。下方优惠码/推荐人及券表保留协助视角，不能与此表相加。`;
  table('source-attribution',['去重主归属','订单数','订单金额 USD','已完成核算毛利 ¥'],source.projects,r=>[r.label,count(r.orders),usd(r.salesUsd),cny(r.profitCny)],'广告优先去重来源归属');
}
function modeControls() {
  const facts = field('mode').value === 'order-facts';
  field('code').disabled = facts; field('code').closest('label').hidden = facts;
  for (const key of ['fact_code','coupon_template','coupon_batch']) {
    field(key).disabled = !facts; field(key).closest('label').hidden = !facts;
  }
  field('channel').disabled = !facts; $('fact-channel-filter').hidden = !facts;
  if (!facts) $('promotion-filters').open = true;
  const longRange = form.querySelector('[data-days="30"]');
  longRange.textContent = facts ? '近28天' : '近30天';
}
function attributionBars(rows, title, id = 'source-attribution-chart') {
  const host = $(id);
  host.replaceChildren();
  if (!rows.length) return;
  const chart = svgNode('svg',{class:'attribution-bars',width:'100%',height:rows.length*37+36,
    role:'img','aria-labelledby':`${id}-title ${id}-description`});
  chart.append(svgNode('title',{id:id+'-title'},title),
    svgNode('desc',{id:id+'-description'},'横轴为订单占比，完整数值见下方表格。'+
      rows.map(row=>`${row.label} ${pct(row.order_share)} ${count(row.orders)} 单`).join('；')));
  for (const marker of [0,25,50,75,100]) {
    const x = `${35+marker*.48}%`;
    chart.append(svgNode('line',{x1:x,x2:x,y1:4,y2:rows.length*37+4,class:'distribution-axis'}),
      svgNode('text',{x,y:rows.length*37+24,'text-anchor':'middle',class:'distribution-tick'},`${marker}%`));
  }
  rows.forEach((row,index)=>{
    const y = index*37+12;
    const group = svgNode('g',{'aria-hidden':'true'});
    const label = svgNode('foreignObject',{x:0,y,width:'34%',height:17});
    label.append(text('div',row.label,'distribution-label'));
    group.append(svgNode('title',{},row.label),
      label,
      svgNode('rect',{x:'35%',y,width:`${(row.order_share??0)*48}%`,height:17,rx:3,class:'distribution-bar'}),
      svgNode('text',{x:'100%',y:y+13,'text-anchor':'end',class:'distribution-value'},pct(row.order_share)));
    chart.append(group);
  });
  host.append(chart);
}

function salesPie(rows, title, complete) {
  const host = $('source-sales-chart');
  host.replaceChildren();
  const segments = rows.filter(row=>row.sales_share>0).sort((a,b)=>b.sales_share-a.sales_share);
  if (!segments.length) {
    host.append(text('p','当前范围没有可绘制的销售额占比。','empty'));
    return;
  }
  const displayed = segments.slice(0,6);
  if (segments.length>6) displayed.push({label:'其余来源',sales_share:segments.slice(6).reduce((n,row)=>n+row.sales_share,0)});
  const chart = svgNode('svg',{viewBox:'0 0 160 160',class:'sales-pie',role:'img','aria-label':title});
  const legend = text('ul',null,'sales-pie-legend');
  let offset = 0;
  displayed.forEach((row,index)=>{
    const segment = svgNode('circle',{cx:80,cy:80,r:59,pathLength:100,fill:'none',
      'stroke-dasharray':`${row.sales_share*100} 100`,'stroke-dashoffset':-offset,
      transform:'rotate(-90 80 80)',class:'sales-pie-segment'});
    const label = `${row.label} · ${pct(row.sales_share)}`;
    segment.append(svgNode('title',{},label)); chart.append(segment);
    const item = text('li',label); item.dataset.segment = index; legend.append(item);
    offset += row.sales_share*100;
  });
  host.append(chart,legend);
  if (!complete) host.append(text('p','占比按已知销售额计算。','hint'));
}

function countryRanking(countries) {
  const host = $('fact-country-rank');
  const ranked = countries.filter(row=>row.label && row.sales_usd != null)
    .sort((a,b)=>Number(b.sales_usd)-Number(a.sales_usd)).slice(0,8);
  if (!ranked.length) {
    host.replaceChildren(text('p','当前范围没有可排名的地区销售额。','empty'));
    return;
  }
  const list = text('ol',null,'country-rank');
  const maxSales = Math.max(Number(ranked[0].sales_usd),1);
  ranked.forEach((row,index)=>{
    const item = text('li');
    const line = text('div',null,'country-rank-line');
    const rank = text('span',String(index+1),'country-rank-number');
    rank.setAttribute('aria-hidden','true');
    const values = text('span',null,'country-rank-values');
    values.append(text('strong',count(row.orders)+' 单'),text('span',usd(row.sales_usd)));
    line.append(rank,text('span',countryLabel(row.label)),values);
    const track = text('span',null,'bar-track'), fill = text('span',null,'bar-fill');
    track.setAttribute('aria-hidden','true');
    fill.style.width = Math.max(0,100*Number(row.sales_usd)/maxSales)+'%';
    track.append(fill);item.append(line,track);list.append(item);
  });
  host.replaceChildren(list);
}

function deviceDistribution(devices) {
  const chart = $('fact-device-chart'), host = $('fact-devices');
  chart.replaceChildren();
  host.replaceChildren();
  if (!devices.length) {
    host.append(text('p','当前范围没有设备记录。','empty'));
    return;
  }
  const colors = new Map([['PC','pc'],['移动端','mobile']]);
  const track = text('div',null,'device-distribution');
  track.setAttribute('role','img');
  track.setAttribute('aria-label','支付设备订单占比：'+devices.map(row=>
    `${row.label || '未知'} ${pct(row.order_share)}`).join('；'));
  const cards = text('ul',null,'device-cards');
  for (const row of devices) {
    const device = colors.get(row.label) || 'unknown';
    const share = text('span',row.order_share>=.08 ? pct(row.order_share) : '');
    share.dataset.device = device;
    share.style.flexBasis = 100*row.order_share+'%';
    share.setAttribute('aria-hidden','true');
    track.append(share);
    const card = text('li',null,'device-card');
    card.dataset.device = device;
    card.append(text('span',row.label || '未知','device-card-label'),text('strong',count(row.orders)+' 单'),
      text('span',`${pct(row.order_share)} · ${usd(row.sales_usd)}`,'device-card-values'));
    cards.append(card);
  }
  chart.append(track);
  host.append(cards);
}

function renderFactDimensions(dimensions) {
  const countries = dimensions?.country || [], devices = dimensions?.device || [];
  const map = $('fact-country-map');
  map.replaceChildren();
  countryRanking(countries);
  const visible = countries.filter(row=>row.label && Object.hasOwn(WORLD.cent,row.label));
  if (visible.length) {
    const countriesByCode = new Map(visible.map(row=>[row.label,row]));
    const svg = svgNode('svg',{viewBox:`0 0 ${WORLD.w} ${WORLD.h}`,class:'fact-world-map',role:'img',
      'aria-label':'订单国家 / 地区地图'});
    const land = [], maxOrders = Math.max(...visible.map(row=>row.orders),1);
    const maxSales = Math.max(...visible.map(row=>Number(row.sales_usd)||0),1);
    const ramp = [1,.5,.18,.06,.015,.004,0];
    for (const [code,path] of Object.entries(WORLD.paths)) {
      const row = countriesByCode.get(code);
      if (row) {
        const level = row.sales_usd==null ? 'unknown' : ramp.findIndex(floor=>Math.max(0,row.sales_usd/maxSales)>=floor);
        const region = svgNode('path',{d:path,class:'map-region','data-level':level});
        region.append(svgNode('title',{},`${countryLabel(code)} · ${count(row.orders)} 单 · ${usd(row.sales_usd)}`));
        svg.append(region);
      } else land.push(path);
    }
    svg.prepend(svgNode('path',{d:land.join(''),class:'map-land'}));
    for (const row of visible.slice(0,10)) {
      const [cx,cy] = WORLD.cent[row.label];
      svg.append(svgNode('circle',{cx,cy,r:4+17*Math.sqrt(row.orders/maxOrders),class:'map-order-dot'}));
    }
    const legend = text('div',null,'country-map-legend');
    const scale = text('span',null,'country-map-scale');
    scale.setAttribute('aria-hidden','true');
    for (const level of [6,5,4,3,2,1]) {
      const swatch = text('i',null,'map-region'); swatch.dataset.level=level; scale.append(swatch);
    }
    legend.append(text('span','销售额 低'),scale,text('span','高'),text('span','圆点大小表示订单量。','country-map-key'));
    map.append(svg,legend);
  } else {
    map.append(text('p','当前范围没有可绘制的地区数据。','empty'));
  }
  table('fact-countries',['国家 / 地区','订单数','订单占比','销售额 USD'],countries,
    row=>[row.label ? countryLabel(row.label) : '未知',count(row.orders),pct(row.order_share),usd(row.sales_usd)],'国家 / 地区订单排名');
  deviceDistribution(devices);
}

function factAssociations(rows) {
  const host = $('source-attribution-associations');
  host.replaceChildren();
  const entries = rows.flatMap(row => [
    ['优惠券模板',row.associations.coupon_templates],['推广项目',row.associations.promotion_projects],['订单来源',row.associations.order_sources]
  ].flatMap(([kind,items]) => items.map(item => [row.label,kind,item.label,count(item.orders)])));
  if (!entries.length) return;
  const details = text('details',null,'attribution-associations');
  const target = text('div');
  target.id = 'attribution-association-table';
  details.append(text('summary','查看同单关联的订单来源、优惠券和推广项目'),target);
  host.append(details);
  table(target.id,['渠道／来源','类型','名称','同单订单数'],entries,row=>row,'同单关联明细');
}

function renderFacts() {
  const s = data.totals, scope = data.effective_scope;
  selectOptions('gid', data.options.games, '全部游戏');
  selectOptions('country', (data.options.country || []).map(v=>[v,countryLabel(v)]), '全部国家 / 地区');
  selectOptions('payment', (data.options.payment || []).map(v=>[v,v]), '全部支付方式');
  selectOptions('project', (data.options.project || []).map(v=>[v,v]), '全部推广项目');
  selectOptions('coupon_template', data.options.coupon_templates || [], '全部优惠券');
  $('project-label').textContent = '推广项目';
  $('legacy-details').hidden = true;
  $('facts-detail').hidden = false;
  const game = data.options.games.find(([id]) => id === scope.gid)?.[1] || (scope.gid === 'all' ? '全部游戏' : scope.gid);
  const channel = [...field('channel').options].find(option => option.value === scope.channel)?.text || scope.channel;
  const filters = [scope.status==='valid'?'排除退款单':scope.status==='refund'?'仅退款单':'',
    scope.country?countryLabel(scope.country):'',scope.payment,scope.project,data.discount_code_applied?'已筛折扣码':'',
    scope.coupon_template?'已筛优惠券':'',data.coupon_batch_applied?'已筛优惠券批次':'',data.keyword_applied?'已用关键词':''].filter(Boolean);
  $('scope').textContent = `${scope.start} — ${scope.end} · MMOEXP · ${game} · ${channel} · Admin付款订单` + (filters.length ? ' · '+filters.join(' · ') : '');
  const revision = data.revisions?.attribution?.publication_id;
  $('freshness').textContent = revision ? '归因发布版本 ' + revision : '归因发布版本尚未取得';
  const pending = s.pending_channel_orders || 0;
  const attributed = s.orders - s.unknown_channel_orders - pending;
  const sourceDetail = data.breakdown.dimension === 'source_detail';
  const title = sourceDetail ? `${channel} · 来源明细占比` : '各归因渠道订单占比';
  $('source-attribution-title').textContent = sourceDetail ? `${channel} · 来源明细占比` : '各归因渠道订单占比与销售额';
  $('distribution-charts').hidden = false;
  $('fact-dimensions').hidden = false;
  $('kpis').dataset.mode = 'facts';
  $('definitions-title').textContent = '统计范围与利润来源';
  $('trend-title').textContent = '每日销售与 Order 原生利润';
  renderFactDimensions(data.dimensions);
  const cohort = data.status==='unavailable' ? '订单覆盖未知' : `${sourceDetail ? '所选渠道' : '全部渠道'}共 ${count(data.breakdown.denominator_orders)} 单`;
  const missingFilter = data.coverage?.unverified_filter_orders;
  const missingDays = data.coverage?.missing_days?.length;
  $('source-attribution-note').textContent = cohort + (data.status==='unavailable' ? '' : ` · 已归因 ${count(attributed)} / ${count(s.orders)} 单`) +
    (pending ? ` · 待归类 ${count(pending)} 单` : '') +
    (missingFilter ? ` · ${count(missingFilter)} 单筛选字段未核` : '') +
    (missingDays ? ` · 共享订单库缺 ${count(missingDays)} 天` : '') +
    (data.status !== 'unavailable' && (data.status !== 'available' || !data.admin_complete) ? ' · 占比按已取得的订单计算' : '') +
    (data.breakdown.rows.length>10 ? ' · 图中显示前10项，完整数值见表' : '');
  attributionBars(data.breakdown.rows.slice(0,10),title);
  salesPie(data.breakdown.rows,sourceDetail ? `${channel} · 来源销售额占比` : '各归因渠道销售额占比',
    data.status==='available' && data.admin_complete && !s.missing_admin_usd_orders);
  const association = (row,key) => {
    const {known_orders:known,unknown_orders:unknown} = row.associations[key];
    return unknown === row.orders ? '未核' : `${count(known)}${unknown ? ` · ${count(unknown)} 未核` : ''}`;
  };
  table('source-attribution',[sourceDetail?'来源明细':'归因渠道','订单数','订单占比','已知订单金额 USD','销售额占比','Order原生利润 ¥','Order原生利润率','有折扣码','有推广人','有优惠券'],data.breakdown.rows,
    row => [row.label,count(row.orders),pct(row.order_share),usd(row.missing_admin_usd_orders===row.orders?null:row.admin_paid_usd),
      pct(row.sales_share),cny(row.order_profit_cny),pct(row.order_profit_rate),
      ...['discount_code','promoter','coupon'].map(key=>association(row,key))],`${title}数据`);
  factAssociations(data.breakdown.rows);
  $('export-facts').hidden = false;
  $('trend-hint').textContent = '订单与销售按北京时间付款日，Order 原生利润按发货交易日。';
  if (data.trend_unallocated_orders) $('trend-hint').textContent += ` ${count(data.trend_unallocated_orders)} 单付款日期待核，已计入区间汇总。`;
  trend(data.trend.map(row => ({key:row.day,orders:row.orders,salesUsd:row.admin_paid_usd,
    profitCny:row.order_profit_cny,margin:row.order_profit_rate,status:row.status})), true);
  const labels = [
    ['去重订单数', data.status==='unavailable'?'—':count(s.orders), '所选渠道的付款订单'],
    ['已知订单金额（USD）', usd(data.status==='unavailable'?null:s.admin_paid_usd), `缺美元金额 ${count(s.missing_admin_usd_orders)} 单`],
    ['已知订单金额（¥）', cny(data.status==='unavailable'?null:s.admin_paid_cny), `缺人民币金额 ${count(s.missing_admin_cny_orders)} 单`],
    ['Order 原生利润（¥）', cny(s.order_profit_cny), '所选订单的 Order 发货记录'],
    ['Order 原生利润率', pct(s.order_profit_rate), '以同组 Order 发货销售额计算'],
    ['已归因订单', `${count(attributed)} / ${count(s.orders)}`, '所选付款订单']
  ];
  $('kpis').replaceChildren(...labels.map(([name,value,hint]) => {
    const card=text('article',null,'panel kpi');card.append(text('span',name,'name'),text('strong',value),text('small',hint));return card;
  }));
  $('coverage').textContent = '';
  const partial = data.status !== 'available' || !data.admin_complete || pending > 0 || s.unknown_channel_orders > 0 || s.missing_admin_usd_orders > 0 || s.missing_admin_cny_orders > 0;
  $('definitions').replaceChildren(...[
    '每单优先采用后台归因渠道、可核订单来源。无明确上级时，折扣码归 Direct 并按历史映射或操作客服细分，未映射归运营。仅有优惠券归 Direct 的新人/活动。',
    'Order 原生利润以选中订单在所选期间的同一发货记录销售额减采购额，利润率按发货销售额加权。',
    `未关联Admin记录 ${data.coverage?.unlinked_admin_rows == null ? '未核' : count(data.coverage.unlinked_admin_rows)}；未关联归因记录 ${data.coverage?.unlinked_attribution_rows == null ? '未核' : count(data.coverage.unlinked_attribution_rows)}。订单数与金额按去重订单统计，不将raw行非空率当客户或收入覆盖率。`,
    '多项优惠可能关联同一订单。渠道与来源占比使用各自去重订单分母；关联计数不与渠道订单数相加。'
  ].map(value => text('p',value)));
  $('results').hidden = false;
  if (data.status==='unavailable') {
    show('共享订单库暂未覆盖当前范围，订单数和金额未知。','partial');
    return;
  }
  if (data.refresh_deferred) {
    show(data.refresh_reason === 'shared_workers_busy' ? '共享查询正在执行，暂保留当前结果；稍后可再次刷新。' : `刚完成本范围读取，暂保留当前结果；${count(data.retryAfter)} 秒后可再次刷新。`, 'partial');
    return;
  }
  show(!s.orders ? (partial ? '当前范围的来源覆盖仍不完整，零条已关联订单不代表完整空集合。' : '当前范围没有付款订单。') : partial ? '当前范围已读取，部分归因或金额字段待补。' : '当前范围已读取。', partial ? 'partial' : 'available');
}
function render() {
  if (data.version === 'order-facts-api-20261113-v1') { renderFacts(); return; }
  $('facts-detail').hidden = true;
  $('fact-dimensions').hidden = true;
  delete $('kpis').dataset.mode;
  $('definitions-title').textContent = '统计范围与成本覆盖';
  $('trend-title').textContent = '每日销售与毛利趋势';
  $('legacy-details').hidden = false;
  $('export-facts').hidden = true;
  $('trend-hint').textContent = '销售额为 USD，采购毛利为同群体人民币收入减实际采购成本；来源及覆盖见统计范围，不按固定汇率互换。';
  $('source-attribution-title').textContent = '原订单来源对照 · 全站去重';
  const coupon = field('mode').value === 'coupon';
  $('project-label').textContent = coupon ? '优惠券模板 / 活动' : '项目 / 渠道';
  $('code-label').textContent = coupon ? '发放批次' : '折扣码';
  $('projects-title').textContent = coupon ? '优惠券模板 / 活动效果对比' : '项目效果对比';
  $('codes-title').textContent = coupon ? '发放批次效果对比' : '折扣码效果对比';
  $('code-hint').textContent = coupon ? '当前模板 / 活动下的批次；渠道没有依据保持未归类。' : '当前项目下各折扣码；推荐人无码单列。';
  selectOptions('gid', data.options.games, '全部游戏');
  selectOptions('country', data.options.countries.map(v => [v,countryLabel(v)]), '全部国家 / 地区');
  selectOptions('payment', data.options.payments.map(v => [v,v]), '全部支付方式');
  selectOptions('project', data.projects.filter(r => coupon || r.key !== '无推广归属').map(r => [r.key,r.label]), coupon ? '全部模板 / 活动' : '全部项目');
  selectOptions('code', data.codes.map(r => [JSON.stringify(r.key),r.label]), coupon ? '全部发放批次' : '全部折扣码');
  $('scope').textContent = `${data.period.start} — ${data.period.end} · ${field('gid').selectedOptions[0].text} · ${field('project').selectedOptions[0].text} · ${coupon ? '用券订单（跨模板去重）' : '实际用码 + 推荐人无码；自然流量仅作对照'} · ${field('status').selectedOptions[0].text}`;
  $('freshness').textContent = '更新 ' + new Date(data.generatedAt).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'});
  sourceAttribution(); kpis(); comparison(); trend(data.trend); orders();
  for (const [host,key,title] of [['games','game','游戏'],['countries','country','国家 / 地区'],['payments','payment','支付方式'],['customers','customerType','新老客'],['states','status','订单状态']]) breakdown(host,key,title);
  $('results').hidden = false;
  if (data.status==='partial') {
    const missing = data.sources.orders?.missing_days?.length || 0;
    const coupons = data.sources.coupons?.unknownOrders || 0;
    show(`共享订单库范围仍有缺口${missing ? `，缺 ${count(missing)} 天` : ''}${coupons ? `，${count(coupons)} 单优惠券未核` : ''}。当前展示已取得的订单。`,'partial');
  }
  else if (data.revenueBasis === 'legacy_delivery') show('正在回补Admin单笔人民币收入，暂展示旧口径完整缓存；新旧收入字段不会混算。' + (data.sourceError ? ' 本次来源读取失败，保留原数据待重试。' : ''), 'partial');
  else if (data.costRefreshing) show('订单已取得，正在关联已完成订单的成本；未完成订单不计毛利。', 'partial');
  else if (data.costError) show('本次采购成本读取未完成，订单与优惠券结果保留；成本缺口见覆盖说明，可稍后刷新。', 'partial');
  else if (data.sources.cost.status === 'unavailable') show('Order 共享源暂不可用，当前复用已有发货成本；未匹配成本保持缺失。', 'partial');
  else if (data.sourceError) show('本次刷新失败，保留上次完整订单结果；时间与覆盖范围见下方。', 'partial');
  else if (data.refreshing) show('正在刷新，当前展示上次完整结果。', 'partial');
  else if (data.summary.missingRevenueOrders) show(`${count(data.summary.missingRevenueOrders)} 笔已完成订单缺Admin人民币收入，采购成本保留，毛利保持未知。`, 'partial');
  else if (data.summary.missingCostOrders) show(`${count(data.summary.missingCostOrders)} 笔已完成订单成本未覆盖（SCM ${count(data.summary.scmOrders)} 笔）；${count(data.summary.pendingOrders)} 笔未完成订单暂不计成本和利润。`, 'partial');
  else if (data.summary.pendingOrders) show(`已完成订单已核算；${count(data.summary.pendingOrders)} 笔未完成订单暂不计成本和利润。`);
  else show(data.summary.orders ? '当前范围已读取，归因与成本覆盖见下方说明。' : data.summary.testOrders ? '当前筛选仅含测试单，已从经营指标排除，明细保留。' : '当前筛选没有渠道订单。自然流量可在左侧对照表查看。');
}
async function load(refresh = false) {
  if (denied || document.hidden) return;
  modeControls();
  exportPending = false;
  $('export-facts').disabled = true;
  clearTimeout(poll); readController?.abort(); ++generation;
  if (!form.reportValidity()) return;
  if (field('mode').value === 'order-facts' && (new Date(field('end').value)-new Date(field('start').value))/86400000 >= 28) {
    show('渠道总览每次最多查询28天，请缩短日期范围。', 'error'); return;
  }
  clearTimeout(poll); readController?.abort(); readController = new AbortController();
  const mine = ++generation;
  const query = params(refresh);
  const applied = new URLSearchParams(query); applied.delete('refresh');
  const sameView = data && renderedQuery === applied.toString();
  if (!sameView || refresh) {
    detailPage = 1;
    detailController?.abort();
    $('facts-detail-table').replaceChildren();
    $('facts-detail-page').textContent = '';
    $('facts-detail-status').textContent = '';
    for (const name of ['prev','next','export']) $('facts-detail-'+name).disabled = true;
  }
  exportPending = true;
  if (!data || (data.version === 'order-facts-api-20261113-v1') !== (query.get('mode') === 'order-facts')) $('results').hidden = true;
  $('results').setAttribute('aria-busy', 'true');
  if (!sameView || refresh) {
    $('refresh').disabled = true;
    show(refresh ? '正在刷新当前范围，保留已有结果…' : data ? '正在切换筛选，暂显示上次已完成范围…' : '正在读取当前筛选范围…');
  }
  try {
    const response = await protectedRead('./data.json?' + query, {credentials:'same-origin', cache:'no-store', redirect:'error', priority:sameView && !refresh ? 'low' : 'high', signal:AbortSignal.any([readController.signal, lifetime.signal, AbortSignal.timeout(25000)])}, deny);
    if (mine !== generation || denied) return;
    const next = await response.json();
    if (mine !== generation) return;
    if (response.status === 202 || response.status === 429) {
      show(response.status === 429 ? '已有查询正在执行，稍后继续读取。' : data ? '正在整理新范围，暂显示上次已完成结果…' : query.get('mode') === 'order-facts' ? '正在从共享数据源整理订单与归因记录…' : '正在从共享数据源整理订单与优惠券记录…');
      poll = setTimeout(() => load(), (next.retryAfter || 3) * 1000); return;
    }
    const expectedVersion = query.get('mode') === 'order-facts' ? 'order-facts-api-20261113-v1' : 'channel-effects-v1';
    if (!response.ok || next.version !== expectedVersion) throw Error('source_failed');
    if (query.get('mode') === 'order-facts' && (!next.snapshot_id || !Array.isArray(next.trend) || !Array.isArray(next.breakdown?.rows) ||
        ['start','end','site_id','gid','channel',...trackingFilters.filter(key=>!privateFilters[key])]
          .some(key => (next.effective_scope?.[key] ?? null) !== query.get(key)) ||
        Object.entries(privateFilters).some(([key,flag]) => Boolean(next[flag]) !== query.has(key)))) throw Error('source_scope_mismatch');
    const unchanged = sameView && snapshotKey(data) === snapshotKey(next);
    data = next;
    if (!unchanged || refresh) render();
    renderedQuery = applied.toString();
    exportPending = false;
    if ((!unchanged || refresh) && next.version==='order-facts-api-20261113-v1' && $('facts-detail').open) loadFactsDetail();
    if (next.refreshing) poll = setTimeout(() => load(), 3000);
  } catch (error) {
    if (mine !== generation || denied || error.name === 'AbortError') return;
    if (error.message === 'protected_read_failed_429') {
      show('已有查询正在执行，稍后继续读取。', 'partial');
      poll = setTimeout(() => load(), 10000); return;
    }
    exportPending = false;
    show(data ? '本次切换失败，仍展示上次已完成范围；请稍后重试。' : '本次数据未取得。请稍后刷新；不会把失败、缺数或旧范围显示成零。', 'error');
  } finally {
    if (mine === generation && !denied) {
      $('refresh').disabled = false;
      $('export-facts').disabled = !exportable();
      $('results').setAttribute('aria-busy', 'false');
    }
  }
}
form.addEventListener('input', () => {
  if (exportable()) { $('export-facts').disabled = false; return; }
  $('export-facts').disabled = true;
  detailController?.abort();
  $('facts-detail-table').replaceChildren();
  for (const name of ['prev','next','export']) $('facts-detail-'+name).disabled = true;
  if ($('facts-detail').open) $('facts-detail-status').textContent = '请先查询当前筛选，再查看明细。';
});
form.addEventListener('submit', event => { event.preventDefault(); page = 1; load(); });
for (const key of ['mode','gid','project','code','status','country','payment','channel','coupon_template']) field(key).addEventListener('change', () => {
  if (['mode','gid','project'].includes(key)) field('code').value = '';
  if (key === 'mode') field('project').value = '';
  page = 1; load();
});
for (const button of form.querySelectorAll('[data-days]')) button.addEventListener('click', () => {
  field('start').max = field('end').max = beijingDay();
  const days = field('mode').value === 'order-facts' ? Math.min(28,Number(button.dataset.days)) : Number(button.dataset.days);
  field('end').value = shift(beijingDay(), -1); field('start').value = shift(field('end').value, 1 - days); page = 1; load();
});
$('reset').addEventListener('click', () => { const mode=field('mode').value; HTMLFormElement.prototype.reset.call(form);field('mode').value=mode; field('status').value=mode==='order-facts'?'all':'valid'; field('end').value = shift(beijingDay(), -1); field('start').value = shift(field('end').value, -6); page = 1; load(); });
$('refresh').addEventListener('click', () => load(true));
function saveCsv(csv, filename) {
  const link = document.createElement('a');
  const url = URL.createObjectURL(new Blob([csv], {type:'text/csv;charset=utf-8'}));
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('export-facts').addEventListener('click', () => {
  if (!exportable()) return;
  const {start,end} = data.effective_scope;
  saveCsv(data.aggregate_csv,`渠道归属_${start}_${end}_${data.snapshot_id}.csv`);
});
async function loadFactsDetail(target = 1, download = false) {
  if (!exportable() || !$('facts-detail').open) return;
  detailController?.abort();
  const controller = detailController = new AbortController();
  const snapshot = data.snapshot_id;
  const scope = renderedQuery;
  const query = new URLSearchParams(scope);
  query.set('snapshot_id',snapshot);
  query.set(download?'detail_export':'detail_page',String(target));
  const pending = $('facts-detail-status');
  pending.textContent = download ? '正在准备明细导出…' : '正在读取本范围订单明细…';
  for (const name of ['prev','next','export']) $('facts-detail-'+name).disabled = true;
  try {
    const response = await protectedRead('./data.json?'+query,{credentials:'same-origin',cache:'no-store',redirect:'error',
      signal:AbortSignal.any([controller.signal,lifetime.signal,AbortSignal.timeout(25000)])},deny);
    const next = await response.json();
    if (controller.signal.aborted || denied || scope!==params().toString() || snapshot!==data?.snapshot_id) return;
    if (next.snapshot_id!==snapshot) throw Error('snapshot_expired');
    if (download) {
      const {start,end} = data.effective_scope;
      saveCsv(next.detail_csv,`渠道订单明细_${start}_${end}_${snapshot}.csv`);
    } else {
      detailPage = next.page;
      table('facts-detail-table',['付款时间','订单号','游戏','归因渠道','来源明细','推广项目','推广人','折扣码','优惠券','国家','支付方式','订单金额 USD','订单金额 ¥','Order原生利润 ¥','Order原生利润率','订单状态'],
        next.orders,r=>[r.paidAt,r.orderNo,r.game,r.channel,r.source,r.project,r.promoter,r.code,
          r.coupons===null?'未核':r.coupons.join('；')||'未用券',r.country?countryLabel(r.country):null,r.payment,
          usd(r.salesUsd),cny(r.saleCny),cny(r.orderProfitCny),pct(r.orderProfitRate),r.status],'同一快照订单明细');
      $('facts-detail-page').textContent = `共 ${count(next.total)} 单 · 第 ${next.page} / ${next.pages} 页`;
    }
    pending.textContent = '';
    $('facts-detail-prev').disabled = detailPage<=1;
    $('facts-detail-next').disabled = detailPage>=(next.pages || Math.max(1,Math.ceil(next.total/50)));
    $('facts-detail-export').disabled = !next.total;
  } catch (error) {
    if (controller.signal.aborted || denied) return;
    pending.textContent = /409|snapshot_expired/.test(error.message) ? '本次快照已失效，请重新查询当前范围。' : '本范围订单明细读取失败，请重新展开后重试。';
  }
}
$('facts-detail').addEventListener('toggle', () => {
  if ($('facts-detail').open) loadFactsDetail(detailPage); else detailController?.abort();
});
$('facts-detail-prev').addEventListener('click',()=>loadFactsDetail(detailPage-1));
$('facts-detail-next').addEventListener('click',()=>loadFactsDetail(detailPage+1));
$('facts-detail-export').addEventListener('click',()=>loadFactsDetail(1,true));
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
document.addEventListener('visibilitychange', async () => { if (document.hidden) { clearTimeout(poll); readController?.abort(); detailController?.abort(); } else { await checkIdentity(); if (!denied) load(); } });
addEventListener('pagehide', () => { lifetime.abort(); readController?.abort(); clearTimeout(poll); clearInterval(identityTimer); }, {once:true});
const identityTimer = setInterval(checkIdentity, 60000);
await checkIdentity();
if (!denied) { $('refresh').disabled = false; load(); }
