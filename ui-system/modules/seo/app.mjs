import {SnapshotClient, value} from './model.mjs';
const client = new SnapshotClient(), select = document.querySelector('#scope'), panel = document.querySelector('#panel'), status = document.querySelector('#status');
const views = {overview: ['总览', 'history'], rankings: ['关键词/竞品', 'rankings'], pages: ['页面健康', 'pages'], orders: ['自然搜索成交', 'history'], ai: ['行动与AI分析', null], sources: ['数据/费用状态', 'sources']};
let active = 'overview', epoch = 0;
const detailColumns = {rankings: [['source_date', '来源日期'], ['keyword', '关键词'], ['rank', '自然名次'], ['status', '状态'], ['observed_at', '观察时间']], pages: [['source_date', '来源日期'], ['url', '页面'], ['status_code', 'HTTP状态'], ['title', '标题'], ['observed_at', '观察时间']], orders: [['source_date', '付款日期'], ['revenue_usd', '已付款金额（$）'], ['attribution', 'SEO归因'], ['landing_game', '入口游戏'], ['purchased_game', '购买游戏'], ['key', '记录引用']], sources: [['source_date', '源日期'], ['source', '来源'], ['status', '状态'], ['source_timezone', '源时区'], ['collected_at', '最近读取'], ['attribution_link_status', '交易关联状态'], ['error', '原因']]};
const statusLabels = {available:'可用', provisional:'初步值', pending:'等待来源', no_rows:'暂无记录', failed:'失败', stale:'上次有效值（更新失败）'};
const detailCells = (kind, row) => detailColumns[kind].map(([key]) => key === 'status' && kind === 'sources' ? statusLabels[row.status] ?? row.status : key === 'key' ? row.key?.slice(0, 12) : key === 'attribution_link_status' ? row.quality?.attribution_link_status : key === 'attribution' ? ({A: '后台已核验', B: 'GA4交易已匹配', U: '未知'})[row.metrics?.attribution] : row[key] ?? row.metrics?.[key]);
const text = (tag, content, className) => {const e = document.createElement(tag); e.textContent = content; if (className) e.className = className; return e;};
function table(headers, rows, caption) {
  const region = document.createElement('div'); region.className = 'table-wrapper'; region.tabIndex = 0; region.setAttribute('role', 'region'); region.setAttribute('aria-label', caption);
  const t = document.createElement('table'), head = document.createElement('thead'), tr = document.createElement('tr'), body = document.createElement('tbody');
  t.append(text('caption', caption));
  headers.forEach(h => {const th = text('th', h); th.scope = 'col'; tr.append(th);}); head.append(tr); t.append(head, body);
  rows.forEach(row => {const tr = document.createElement('tr'); row.forEach((v, n) => {const cell = text(n ? 'td' : 'th', v ?? '—'); if (!n) cell.scope = 'row'; tr.append(cell);}); body.append(tr);});
  region.append(t); return region;
}
function selectedURL() {const url = new URL(location.href); if (client.id) url.searchParams.set('snapshot_id', client.id); else url.searchParams.delete('snapshot_id'); url.searchParams.set('game', select.value); url.searchParams.set('tab', active); history.replaceState(null, '', url); const download = document.querySelector('#export'); if (client.id) {download.href = client.exportURL(select.value); download.download = `${client.id}-${select.value}.csv`; download.setAttribute('aria-disabled','false');} else {download.removeAttribute('href'); download.setAttribute('aria-disabled','true');}}
async function render() {
  const request = ++epoch, scope = select.value;
  selectedURL(); panel.replaceChildren(text('div', '正在读取已发布快照…', 'loading')); panel.setAttribute('aria-busy', 'true');
  document.querySelectorAll('[role=tab]').forEach(b => {const chosen = b.dataset.view === active; b.setAttribute('aria-selected', String(chosen)); b.tabIndex = chosen ? 0 : -1;});
  panel.setAttribute('aria-labelledby', 'tab-' + active);
  try {
    if (active === 'ai') {
      panel.replaceChildren(text('h2', '行动与可选AI分析'));
      const reminders = document.createElement('div'); panel.append(reminders);
      if (client.id) client.load('rules', scope).then(result => {if (request === epoch) result.rows.forEach(r => reminders.append(text('p', r.message)));}).catch(() => {if (request === epoch) reminders.append(text('p', '基础提醒暂不可用。', 'error'));});
      if (!client.id) reminders.append(text('p', '基础提醒等待首个夜间批次。', 'muted'));
      const box = document.createElement('div'); panel.append(box);
      import('./ai.mjs').then(module => {if (request === epoch) module.mount(box, client);}).catch(() => {if (request === epoch) box.replaceChildren(text('p', 'AI组件暂不可用，基础数据可继续查看。', 'error'));});
      return;
    }
    if (!client.id) {panel.replaceChildren(text('div', '等待首个夜间批次发布。', 'empty')); return;}
    const kind = views[active][1], data = await client.load(kind, scope);
    if (request !== epoch) return;
    panel.replaceChildren();
    if (active === 'overview') {
      const available = data.rows.filter(r => Object.values(r.metrics).some(v => v !== null)).length;
      panel.append(text('h2', `${scope} · 近30天`), text('p','GA4为初步值，后续夜间可能修订；本次快照内保持固定。','muted'), text('p', `目标30天 · 可用${available}天 · 缺失${30-available}天`, 'muted'));
      const latest = data.rows[data.rows.length-1];
      if (latest) {
        panel.append(text('p', `业务目标 ${latest.source_date} · GA4自然会话 ${value(latest.metrics.ga4?.sessions)} · 购买次数 ${value(latest.metrics.ga4?.purchase_events)} · Admin客单价 $${value(latest.metrics.admin?.admin_customer_price_usd)} · 预估SEO成交额 $${value(latest.estimate?.revenue_usd)}`));
        const recent = [...data.rows].reverse().find(r => r.metrics.gsc !== null);
        if (recent) panel.append(text('p', `GSC最近源日 ${recent.source_date}（太平洋时间）· 点击 ${value(recent.metrics.gsc.clicks)}`, 'muted'));
        if (latest.source_status?.orders?.quality?.attribution_link_status === 'transaction_id_not_populated') panel.append(text('p', 'GA4交易标识未记录，当前SEO成交无法核验；没有填成零。', 'muted'));
      }
      panel.append(table(['来源日期', 'GSC点击', 'GSC展示', 'GSC CTR', 'GA4自然会话', '自然搜索购买次数', 'Admin客单价（$）', '预估成交额（$）'], data.rows.map(r => [r.source_date, value(r.metrics.gsc?.clicks), value(r.metrics.gsc?.impressions), value(r.metrics.gsc?.ctr, true), value(r.metrics.ga4?.sessions), value(r.metrics.ga4?.purchase_events), value(r.metrics.admin?.admin_customer_price_usd), value(r.estimate?.revenue_usd)]), '每日搜索与成交 · 各来源按自己的统计时区'));
    } else if (active === 'orders') {
      panel.append(text('h2', '自然搜索成交预估'), text('p', 'GA4自然搜索购买事件次数 × 同日同游戏MMOEXP主站Admin客单价。交易标识为空，无法关联具体订单或用户；此金额为预估。后台客单价为付费客户均额。GA4购买次数为初步值，后续夜间可能修订。', 'muted'));
      panel.append(table(['来源日期', '购买事件次数', 'Admin客单价（$）', '预估成交额（$）', '状态'], data.rows.map(r => [r.source_date, value(r.metrics.ga4?.purchase_events), value(r.metrics.admin?.admin_customer_price_usd), value(r.estimate?.revenue_usd), r.estimate?.status === 'estimated' ? '预估' : '缺少来源']), '按日预估 · 缺失不补零'));
    } else if (!data.rows.length) {
      panel.append(text('div', (client.meta.sources?.[kind === 'rankings' ? 'serp' : kind] === 'not_configured') ? '该数据源尚未接入。其他数据可正常查看。' : '此版本暂无可用记录，等待后续夜间采集。', 'empty'));
    } else if (active === 'sources') {
      panel.append(table(detailColumns.sources.map(c => c[1]), data.rows.map(r => detailCells('sources', r)), '数据来源与覆盖状态'));
      panel.append(text('p', 'AI未接入费用账本；暂无可核验的SEO模型费用。', 'muted'));
    } else {
      const columns = detailColumns[active];
      panel.append(table(columns.map(c => c[1]), data.rows.map(r => detailCells(active, r)), active === 'orders' ? '已付款记录与SEO归因 · 未知来源不计SEO收入' : views[active][0]));
    }
    if (data.next_cursor != null) {const next = text('button', '继续读取此版本'); next.type = 'button'; next.onclick = () => appendPage(kind, scope, data.next_cursor, request, next); panel.append(next);}
  } catch (error) {if (request === epoch) panel.replaceChildren(text('p', error.message, 'error'));}
  finally {if (request === epoch) panel.setAttribute('aria-busy', 'false');}
}
async function appendPage(kind, scope, cursor, request, button) {
  button.disabled = true;
  try {
    const data = await client.load(kind, scope, cursor); if (request !== epoch) return;
    const columns = detailColumns[kind];
    const rows = data.rows.map(r => detailCells(kind, r));
    const tbody = panel.querySelector('tbody'); table([], rows, '续页').querySelectorAll('tbody tr').forEach(tr => tbody.append(tr));
    button.replaceWith(); if (data.next_cursor != null) {button.disabled = false; button.onclick = () => appendPage(kind, scope, data.next_cursor, request, button); panel.append(button);}
  } catch (error) {button.disabled = false; status.textContent = error.message;}
}
for (const [key, [label]] of Object.entries(views)) {
  const b = text('button', label); b.type = 'button'; b.id = 'tab-' + key; b.dataset.view = key; b.setAttribute('role', 'tab'); b.setAttribute('aria-controls', 'panel');
  b.addEventListener('click', () => {active = key; render();}); document.querySelector('#tabs').append(b);
}
document.querySelector('#tabs').addEventListener('keydown', event => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const keys = Object.keys(views), i = keys.indexOf(active); event.preventDefault();
  active = keys[event.key === 'Home' ? 0 : event.key === 'End' ? keys.length-1 : (i + (event.key === 'ArrowRight' ? 1 : keys.length-1)) % keys.length];
  document.querySelector('#tab-' + active).focus(); render();
});
select.addEventListener('change', render);
(async () => {
  try {
    const params = new URLSearchParams(location.search), meta = await client.init(params.get('snapshot_id'));
    Array.from(select.options).forEach(o => {o.disabled = !meta.games.includes(o.value);});
    select.value = meta.games.includes(params.get('game')) ? params.get('game') : meta.games[0]; select.disabled = false;
    active = Object.hasOwn(views, params.get('tab')) ? params.get('tab') : 'overview';
    document.querySelector('#version').textContent = `发布 ${meta.publication_date} · 业务目标 ${meta.report_date} · ${meta.snapshot_id}`;
    status.textContent = meta.data_status === 'partial' ? '已发布固定数据；部分来源待发布或尚未接入。' : '已发布固定数据。';
    await render();
  } catch (error) {document.querySelector('#version').textContent = '暂未读取数据版本 · 每日03:20启动批次'; status.textContent = error.message; panel.replaceChildren(text('div', '暂无可读取的已发布数据。', 'empty')); panel.setAttribute('aria-busy', 'false');}
})();
