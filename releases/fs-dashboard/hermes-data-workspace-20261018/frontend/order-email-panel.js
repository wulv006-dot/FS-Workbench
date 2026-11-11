import { orderEmailCsv } from './order-email-csv.js';

const id = value => typeof value === 'string' && /^[0-9]{1,20}$/.test(value);
function directory(entries) {
  if (!Array.isArray(entries) || !entries.length) throw new TypeError('Directory required');
  const seen = new Set();
  return entries.map(entry => {
    if (!entry || !id(entry.value) || typeof entry.label !== 'string' ||
        !entry.label.trim() || seen.has(entry.value)) throw new TypeError('Invalid directory');
    seen.add(entry.value);
    return { value: entry.value, label: entry.label };
  });
}

function date(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '0001-01-01')
    throw new TypeError('Invalid date');
  const parsed = new Date(value + 'T00:00:00.000Z');
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value)
    throw new TypeError('Invalid date');
  return parsed;
}

/** Inclusive calendar dates; UTC arithmetic avoids local DST and timezone shifts.
 * Server remains authoritative for permissions and the rolling date boundary.
 */
export function orderEmailRequest({ site_id, game_ids, start, end }, sites, games) {
  const siteIds = new Set(directory(sites).map(entry => entry.value));
  const gameIds = new Set(directory(games).map(entry => entry.value));
  if (!siteIds.has(site_id) || !Array.isArray(game_ids) || !game_ids.length ||
      game_ids.length > 100 || new Set(game_ids).size !== game_ids.length ||
      Array.from(game_ids).some(value => !gameIds.has(value))) throw new TypeError('Invalid selection');
  const first = date(start), last = date(end);
  const days = (last - first) / 86400000 + 1;
  if (days < 1 || days > 366 || end === '9999-12-31') throw new TypeError('Invalid range');
  last.setUTCDate(last.getUTCDate() + 1);
  return { site_id, game_ids: [...game_ids], start, end_exclusive: last.toISOString().slice(0, 10) };
}

/** Standalone only: caller supplies a verified endpoint and real directories.
 * No persistence, email preview, automatic mount, or production route default.
 */
export function mountOrderEmailExport(root, { endpoint, sites, games, fetch: fetcher } = {}) {
  const doc = root.ownerDocument;
  const win = doc.defaultView;
  let url;
  try {
    if (typeof endpoint !== 'string' || !endpoint.trim()) throw new Error();
    url = new URL(endpoint, win.location.href);
    if (!/^https?:$/.test(url.protocol) || url.origin !== win.location.origin ||
        url.username || url.password || url.search || url.hash || /[?#]/.test(endpoint)) throw new Error();
  } catch { throw new TypeError('Explicit same-origin endpoint without query or fragment required'); }
  sites = directory(sites); games = directory(games);
  fetcher = fetcher || win.fetch.bind(win);
  const el = (tag, text, className) => {
    const node = doc.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const panel = el('article', null, 'native-card');
  panel.append(el('h3', '订单用户邮箱导出'));
  panel.append(el('p', '当前范围：仅付款日期、站点、游戏；不是下单日期。其他 Admin 筛选暂不可用。'));
  panel.append(el('p', '当前源限时 45 秒、最多 1000 页、约 1 MiB 响应，无续跑；全年导出尚未验收。实时分页非快照，失败或超限不提供部分名单。日期仍受服务端近 365 天及权限限制。'));
  panel.append(el('p', '订单邮箱不代表营销订阅；发送前请应用退订与拒收名单。本工具仅导出，不发送邮件。CSV 对公式前缀添加安全单引号，导入营销系统前请核对这些地址。'));
  const form = el('form', null, 'fc-actions');
  const field = (text, tag, name) => {
    const label = el('label', text);
    const input = el(tag, null, 'native-form'); input.name = name; input.required = true;
    label.append(input); form.append(label); return input;
  };
  const site = field('站点', 'select', 'site_id');
  const game = field('游戏（可多选）', 'select', 'game_ids'); game.multiple = true;
  for (const [select, entries] of [[site, sites], [game, games]]) {
    const placeholder = select === site ? el('option', '请选择站点') : null;
    if (placeholder) { placeholder.value = ''; select.append(placeholder); }
    for (const entry of entries) {
      const option = el('option', entry.label); option.value = entry.value; select.append(option);
    }
  }
  const start = field('付款开始日期', 'input', 'start'); start.type = 'date';
  const end = field('付款结束日期（含当天）', 'input', 'end'); end.type = 'date';
  const button = (text, type) => { const node = el('button', text, 'ghostbtn'); node.type = type; return node; };
  const query = button('查询完整名单', 'submit');
  const cancel = button('取消并清除', 'button');
  const download = button('下载 CSV', 'button'); download.disabled = true;
  form.append(query, cancel, download); panel.append(form);
  const status = el('p', '请选择范围后查询。');
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  status.setAttribute('aria-atomic', 'true'); panel.append(status); root.append(panel);
  let sequence = 0, controller = null, payload = null, blobUrl = null, disposed = false;
  const revoke = () => { if (blobUrl !== null) win.URL.revokeObjectURL(blobUrl); blobUrl = null; };
  const clear = () => {
    sequence++; controller?.abort(); controller = null; payload = null; revoke();
    download.disabled = true; query.disabled = false; panel.removeAttribute('aria-busy');
  };
  const invalidate = () => { if (!disposed) { clear(); status.textContent = '条件已变更，请重新查询。'; } };
  const onCancel = () => { if (!disposed) { clear(); status.textContent = '已取消并清除名单。'; } };
  const onSubmit = async event => {
    event.preventDefault(); if (disposed) return;
    clear();
    let request;
    try { request = orderEmailRequest({ site_id: site.value,
      game_ids: Array.from(game.selectedOptions, option => option.value), start: start.value, end: end.value }, sites, games); }
    catch { status.textContent = '请选择有效站点、游戏及付款日期（含结束日，最多 366 天）。'; return; }
    const current = sequence;
    controller = new win.AbortController();
    query.disabled = true; panel.setAttribute('aria-busy', 'true');
    status.textContent = '正在读取完整名单，可修改条件或取消；尚不可导出。';
    try {
      const response = await fetcher(url.href, { method: 'POST', credentials: 'same-origin',
        redirect: 'error', cache: 'no-store', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(request), signal: controller.signal });
      if (disposed || current !== sequence) return;
      if (!response.ok || response.redirected) throw new Error();
      const result = await response.json();
      if (disposed || current !== sequence) return;
      orderEmailCsv(result);
      if (result.period?.start !== request.start || result.period?.end_exclusive !== request.end_exclusive ||
          result.scope.site_id !== request.site_id || result.scope.game_ids.length !== request.game_ids.length ||
          result.scope.game_ids.some(value => !request.game_ids.includes(value))) throw new Error();
      payload = result; download.disabled = false;
      status.textContent = `完整读取完成：${result.unique_emails} 个用户邮箱；${result.missing_email_orders} 笔订单缺少邮箱。实时非快照。`;
    } catch {
      if (disposed || current !== sequence) return;
      clear(); status.textContent = '查询未完成或结果无效，无法导出。请检查权限、日期范围或稍后重试。';
    } finally {
      if (!disposed && current === sequence) {
        controller = null; query.disabled = false; panel.removeAttribute('aria-busy');
      }
    }
  };
  const onDownload = () => {
    if (disposed || !payload || download.disabled) return;
    let link;
    try {
      revoke();
      blobUrl = win.URL.createObjectURL(new win.Blob([orderEmailCsv(payload)], { type: 'text/csv;charset=utf-8' }));
      link = el('a'); link.href = blobUrl; link.download = 'order-user-emails.csv';
      panel.append(link); link.click();
    } catch { clear(); status.textContent = '下载失败，名单已清除，请重新查询。'; }
    finally { link?.remove(); }
  };
  form.addEventListener('submit', onSubmit);
  form.addEventListener('input', invalidate); form.addEventListener('change', invalidate);
  cancel.addEventListener('click', onCancel); download.addEventListener('click', onDownload);
  return { dispose() {
    if (disposed) return;
    disposed = true; clear();
    form.removeEventListener('submit', onSubmit);
    form.removeEventListener('input', invalidate); form.removeEventListener('change', invalidate);
    cancel.removeEventListener('click', onCancel); download.removeEventListener('click', onDownload);
    panel.remove();
  } };
}
