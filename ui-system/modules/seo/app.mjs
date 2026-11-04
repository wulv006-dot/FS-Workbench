import {SnapshotClient, value} from './model.mjs';
const client = new SnapshotClient(), select = document.querySelector('#scope'), panel = document.querySelector('#panel'), status = document.querySelector('#status');
const views = {overview: ['总览', 'history'], rankings: ['关键词/竞品', 'rankings'], pages: ['页面健康', 'pages'], orders: ['自然搜索成交', 'orders'], ai: ['行动与AI分析', null], sources: ['数据/费用状态', 'sources']};
let active = 'overview', epoch = 0;
const detailColumns = {rankings: [['source_date', '来源日期'], ['keyword', '关键词'], ['rank', '自然名次'], ['status', '状态'], ['observed_at', '观察时间']], pages: [['source_date', '来源日期'], ['url', '页面'], ['status_code', 'HTTP状态'], ['title', '标题'], ['observed_at', '观察时间']], orders: [['source_date', '付款日期'], ['key', '记录引用']], sources: [['source_date', '源日期'], ['source', '来源'], ['status', '状态'], ['source_timezone', '源时区'], ['collected_at', '最近读取'], ['error', '原因']]};
const text = (tag, content, className) => {const e = document.createElement(tag); e.textContent = content; if (className) e.className = className; return e;};
function table(headers, rows, caption) {
  const region = document.createElement('div'); region.className = 'table-wrapper'; region.tabIndex = 0; region.setAttribute('role', 'region'); region.setAttribute('aria-label', caption);
  const t = document.createElement('table'), head = document.createElement('thead'), tr = document.createElement('tr'), body = document.createElement('tbody');
  t.append(text('caption', caption));
  headers.forEach(h => {const th = text('th', h); th.scope = 'col'; tr.append(th);}); head.append(tr); t.append(head, body);
  rows.forEach(row => {const tr = document.createElement('tr'); row.forEach((v, n) => {const cell = text(n ? 'td' : 'th', v ?? '—'); if (!n) cell.scope = 'row'; tr.append(cell);}); body.append(tr);});
  region.append(t); return region;
}
function selectedURL() {const url = new URL(location.href); url.searchParams.set('snapshot_id', client.id); url.searchParams.set('game', select.value); url.searchParams.set('tab', active); history.replaceState(null, '', url);}
async function render() {
  const request = ++epoch, scope = select.value;
  selectedURL(); panel.replaceChildren(text('div', '正在读取已发布快照…', 'loading')); panel.setAttribute('aria-busy', 'true');
  document.querySelectorAll('[role=tab]').forEach(b => {const chosen = b.dataset.view === active; b.setAttribute('aria-selected', String(chosen)); b.tabIndex = chosen ? 0 : -1;});
  panel.setAttribute('aria-labelledby', 'tab-' + active);
  try {
    if (active === 'ai') {
      panel.replaceChildren(text('h2', '行动与可选AI分析'));
      const reminders = document.createElement('div'); panel.append(reminders);
      client.load('rules', scope).then(result => {if (request === epoch) result.rows.forEach(r => reminders.append(text('p', r.message)));}).catch(() => {if (request === epoch) reminders.append(text('p', '基础提醒暂不可用。', 'error'));});
      const box = document.createElement('div'); panel.append(box);
      import('./ai.mjs').then(module => {if (request === epoch) module.mount(box, client);}).catch(() => {if (request === epoch) box.replaceChildren(text('p', 'AI组件暂不可用，基础数据可继续查看。', 'error'));});
      return;
    }
    const kind = views[active][1], data = await client.load(kind, scope);
    if (request !== epoch) return;
    panel.replaceChildren();
    if (active === 'overview') {
      const available = data.rows.filter(r => Object.values(r.metrics).some(v => v !== null)).length;
      panel.append(text('h2', `${scope} · 近30天`), text('p', `目标30天 · 可用${available}天 · 缺失${30-available}天`, 'muted'));
      panel.append(table(['来源日期', 'GSC点击', 'GSC展示', 'GSC CTR', 'GA4自然会话', 'SEO付款额（$）'], data.rows.map(r => [r.source_date, value(r.metrics.gsc?.clicks), value(r.metrics.gsc?.impressions), value(r.metrics.gsc?.ctr, true), value(r.metrics.ga4?.sessions), value(r.metrics.orders?.seo_revenue_usd)]), '每日搜索与成交 · 各来源按自己的统计时区'));
    } else if (!data.rows.length) {
      panel.append(text('div', (client.meta.sources?.[kind === 'rankings' ? 'serp' : kind] === 'not_configured') ? '该数据源尚未接入。其他数据可正常查看。' : '此版本暂无可用记录，等待后续夜间采集。', 'empty'));
    } else if (active === 'sources') {
      panel.append(table(['源日期', '来源', '状态', '源时区', '最近读取', '原因'], data.rows.map(r => [r.source_date, r.source, r.status, r.source_timezone, r.collected_at, r.error]), '数据来源与覆盖状态'));
      panel.append(text('p', 'AI未接入费用账本；暂无可核验的SEO模型费用。', 'muted'));
    } else {
      const columns = detailColumns[active];
      panel.append(table(columns.map(c => c[1]), data.rows.map(r => columns.map(c => r[c[0]])), views[active][0]));
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
    const rows = data.rows.map(r => columns.map(c => r[c[0]]));
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
document.querySelector('#export').addEventListener('click', async event => {
  const button = event.currentTarget; button.disabled = true;
  try {
    const result = await client.load('history', select.value);
    const rows = [['snapshot_id', 'facts_hash', 'game', 'source_date', 'gsc_clicks', 'ga4_sessions', 'seo_revenue_usd'], ...result.rows.map(r => [client.id, client.meta.facts_hash, select.value, r.source_date, r.metrics.gsc?.clicks, r.metrics.ga4?.sessions, r.metrics.orders?.seo_revenue_usd])];
    const csv = rows.map(row => row.map(v => '"' + String(v ?? '').replace(/"/g, '""') + '"').join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob(['\ufeff' + csv], {type: 'text/csv;charset=utf-8'})), link = document.createElement('a');
    link.href = url; link.download = `${client.id}-${select.value}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {status.textContent = error.message;}
  finally {button.disabled = false;}
});
(async () => {
  try {
    const params = new URLSearchParams(location.search), meta = await client.init(params.get('snapshot_id'));
    Array.from(select.options).forEach(o => {o.disabled = !meta.games.includes(o.value);});
    select.value = meta.games.includes(params.get('game')) ? params.get('game') : meta.games[0]; select.disabled = false;
    active = Object.hasOwn(views, params.get('tab')) ? params.get('tab') : 'overview';
    document.querySelector('#version').textContent = `发布 ${meta.publication_date} · 业务目标 ${meta.report_date} · ${meta.snapshot_id}`;
    status.textContent = meta.data_status === 'partial' ? '已发布固定数据；部分来源待发布或尚未接入。' : '已发布固定数据。';
    document.querySelector('#export').disabled = false; await render();
  } catch (error) {status.textContent = error.message; panel.replaceChildren(text('div', '暂无可读取的已发布数据。', 'empty')); panel.setAttribute('aria-busy', 'false');}
})();
