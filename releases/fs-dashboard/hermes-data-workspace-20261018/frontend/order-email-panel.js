import { orderEmailCsv, orderEmailTraversalCsv } from './order-email-csv.js';

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
export function orderEmailRequest({ site_id, game_ids, start, end, filters, server_ids }, sites, games) {
  const siteIds = new Set(directory(sites).map(entry => entry.value));
  const gameIds = new Set(directory(games).map(entry => entry.value));
  if (!siteIds.has(site_id) || !Array.isArray(game_ids) || !game_ids.length ||
      game_ids.length > 100 || new Set(game_ids).size !== game_ids.length ||
      Array.from(game_ids).some(value => !gameIds.has(value))) throw new TypeError('Invalid selection');
  if (filters !== undefined) {
    const allowed = ['progress', 'status', 'cid', 'content', 'aid', 'recommend_uid', 'discount_code', 'promotion_id', 'pid', 'admin_id', 'country'];
    if (!filters || typeof filters !== 'object' || Array.isArray(filters) ||
        Object.keys(filters).some(key => !allowed.includes(key) || typeof filters[key] !== 'string' ||
          !filters[key].length || filters[key].length > 320 || /[\u0000-\u001f\u007f]/.test(filters[key]))) throw new TypeError('Invalid filters');
  }
  if (server_ids !== undefined && (!server_ids || typeof server_ids !== 'object' || Array.isArray(server_ids) ||
      Object.hasOwn(filters || {}, 'aid') || Object.entries(server_ids).some(([game, aid]) => !game_ids.includes(game) || !id(aid))))
    throw new TypeError('Invalid servers');
  const first = date(start), last = date(end);
  const days = (last - first) / 86400000 + 1;
  if (days < 1 || days > 366 || end === '9999-12-31') throw new TypeError('Invalid range');
  last.setUTCDate(last.getUTCDate() + 1);
  return { site_id, game_ids: [...game_ids], start, end_exclusive: last.toISOString().slice(0, 10),
    ...(filters && Object.keys(filters).length ? { filters: { ...filters } } : {}),
    ...(server_ids && Object.keys(server_ids).length ? { server_ids: { ...server_ids } } : {}) };
}

/** Standalone only: caller supplies a verified endpoint and real directories.
 * No persistence, email preview, automatic mount, or production route default.
 * paged:true lazily loads OrderEmailRun and requires an explicit HTTP 206 page
 * endpoint; the public mapping of /users/order-email-export-page is caller-owned.
 */
/** Excel entry point; legacy CSV callers retain their existing API. */
export function mountOrderEmailExcelExport(root, options = {}) {
  return mountOrderEmailExport(root, { ...options, format: 'xlsx' });
}

export function mountOrderEmailExport(root, { endpoint, sites, games, fetch: fetcher, paged = false, format = 'csv' } = {}) {
  if (!['csv', 'xlsx'].includes(format)) throw new TypeError('Invalid export format');
  const doc = root.ownerDocument;
  const win = doc.defaultView;
  let url;
  try {
    if (typeof endpoint !== 'string' || !endpoint.trim()) throw new Error();
    url = new URL(endpoint, win.location.href);
    if (!/^https?:$/.test(url.protocol) || url.origin !== win.location.origin ||
        url.username || url.password || url.search || url.hash || /[?#]/.test(endpoint)) throw new Error();
  } catch { throw new TypeError('Explicit same-origin endpoint without query or fragment required'); }
  const remoteOptions = sites === undefined && games === undefined;
  sites = remoteOptions ? [] : directory(sites); games = remoteOptions ? [] : directory(games);
  fetcher = fetcher || win.fetch.bind(win);
  const el = (tag, text, className) => {
    const node = doc.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const panel = el('article', null, 'fc-card');
  panel.append(el('h3', '订单用户邮箱导出'));
  panel.append(el('p', '筛选条件均为可选，未指定的条件不传，使用 Admin API 源默认范围，不代表已支付或已完成。订单状态随进度加载，产品类型及服务区随所选游戏加载。下单时间使用 Admin 实际字段 paytime（Asia/Shanghai），不改为 create_time。'));
  panel.append(el('p', paged
    ? '逐页串行读取，全部计划窗口遍历结束后才能导出。暂停仅在当前页面内存中续跑，刷新页面丢失进度；服务端进程重启后游标失效，须重新查询。付款日期按 Asia/Shanghai，受服务端滚动近 365 天及权限限制。实时分页非快照。'
    : '当前源限时 45 秒、最多 1000 页、约 1 MiB 响应，无续跑；全年导出尚未验收。实时分页非快照，失败或超限不提供部分名单。日期仍受服务端近 365 天及权限限制。'));
  panel.append(el('p', '订单邮箱不代表营销订阅；发送前请应用退订与拒收名单。本工具仅导出，不发送邮件。Excel 导出将地址保存为文本，保留原地址；旧 CSV 导出对公式前缀添加安全单引号。'));
  const form = el('form', null, 'fc-actions');
  form.setAttribute('style', 'align-items:flex-start');
  const field = (text, tag, name, container = form) => {
    const label = el('label', text);
    label.setAttribute('style', 'display:flex;flex-direction:column;gap:6px;flex:1 1 200px;min-width:0;max-width:100%');
    const input = el(tag, null, tag === 'select' ? 'hsel' : 'dinput'); input.name = name; input.required = true;
    input.setAttribute('style', 'width:100%;min-width:0;box-sizing:border-box');
    label.append(input); container.append(label); return input;
  };
  const site = field('站点', 'select', 'site_id');
  // Keep the native select as the single source of request/legacy selection state.
  const game = el('select'); game.name = 'game_ids'; game.multiple = true; game.hidden = true;
  form.append(game);
  const gameField = el('div');
  gameField.setAttribute('style', 'flex:1 1 320px;min-width:0;max-width:100%');
  const gamePicker = el('details', null, 'source-details');
  gamePicker.setAttribute('style', 'margin:0;box-sizing:border-box;width:100%');
  const gameSummary = el('summary', '游戏（可多选） · 请选择');
  const gameSearch = el('input', null, 'dinput'); gameSearch.type = 'search';
  gameSearch.placeholder = '搜索游戏名称或 ID'; gameSearch.setAttribute('aria-label', '搜索游戏名称或 ID');
  gameSearch.setAttribute('style', 'width:100%;min-width:0;box-sizing:border-box;margin:10px 0');
  const gameList = el('div');
  gameList.setAttribute('style', 'max-height:240px;overflow:auto');
  const gameMatches = el('p'); gameMatches.setAttribute('role', 'status');
  const gameSelection = el('p', '尚未选择游戏');
  gameSelection.setAttribute('style', 'margin:6px 0;max-height:6rem;overflow:auto;overflow-wrap:anywhere');
  gameSelection.setAttribute('aria-live', 'polite');
  gamePicker.append(gameSummary, gameSearch, gameMatches, gameList);
  gameField.append(gamePicker, gameSelection); form.append(gameField);
  let gameRows = [];
  const searchGames = () => {
    const term = gameSearch.value.trim().toLocaleLowerCase();
    let visible = 0;
    for (const item of gameRows) {
      item.row.hidden = !item.text.toLocaleLowerCase().includes(term);
      if (!item.row.hidden) visible++;
    }
    gameMatches.textContent = visible ? `显示 ${visible} / ${gameRows.length} 款游戏（最多选择 100 款）` : '没有匹配的游戏';
  };
  const syncGames = () => {
    const selected = Array.from(game.selectedOptions);
    gameSummary.textContent = selected.length ? `游戏（可多选） · 已选 ${selected.length} 款` : '游戏（可多选） · 请选择';
    gameSelection.textContent = selected.length ? selected.map(option => option.textContent).join('、') : '尚未选择游戏';
    for (const item of gameRows) {
      item.check.checked = item.option.selected;
      item.check.disabled = !item.option.selected && selected.length >= 100;
    }
  };
  const renderGames = () => {
    while (gameList.children.length) gameList.children[0].remove();
    gameRows = Array.from(game.children, option => {
      const row = el('label');
      row.setAttribute('style', 'display:flex;align-items:center;gap:8px;padding:6px 0;overflow-wrap:anywhere');
      const check = el('input'); check.type = 'checkbox'; check.value = option.value;
      check.setAttribute('style', 'flex:none;width:auto');
      const prefix = `${option.value} | `;
      const text = option.textContent.startsWith(prefix) ? option.textContent : prefix + option.textContent;
      row.append(check, el('span', text)); gameList.append(row);
      return { row, check, option, text };
    });
    syncGames(); searchGames();
  };
  for (const [select, entries] of [[site, sites], [game, games]]) {
    const placeholder = select === site ? el('option', '请选择站点') : null;
    if (placeholder) { placeholder.value = ''; select.append(placeholder); }
    for (const entry of entries) {
      const option = el('option', entry.label); option.value = entry.value; select.append(option);
    }
  }
  renderGames();
  const filters = {};
  for (const [name, label, tag] of [
    ['progress', '订单进度', 'select'], ['status', '订单状态', 'select'],
    ['cid', '产品类型', 'select'], ['content', '游戏/服务器/产品（包含）', 'input'],
    ['aid', '服务区', 'select'], ['recommend_uid', '推广人ID', 'input'],
    ['discount_code', '折扣码完整', 'input'], ['promotion_id', '促销活动ID', 'input'],
    ['pid', '商品ID', 'input'], ['country', '国家（包含）', 'select']]) {
    const control = field(label, tag, name); control.required = false;
    if (tag === 'select') { const option = el('option', '不限'); option.value = ''; control.append(option); }
    filters[name] = control;
  }
  for (const name of ['progress', 'status', 'cid', 'aid']) filters[name].disabled = true;
  const serverGroup = el('div'); serverGroup.setAttribute('style', 'display:contents'); form.append(serverGroup);
  const serverControls = new Map();
  const resetServers = () => { while (serverGroup.children.length) serverGroup.children[0].remove(); serverControls.clear(); };
  if (remoteOptions) (filters.aid.parentNode || filters.aid.parent).hidden = true;
  const start = field('下单时间开始（paytime）', 'input', 'start'); start.type = 'date';
  const end = field('下单时间结束（含当天）', 'input', 'end'); end.type = 'date';
  const button = (text, type) => { const node = el('button', text, 'ghostbtn'); node.type = type; return node; };
  const query = button('查询完整名单', 'submit');
  const cancel = button('取消并清除', 'button');
  const download = button(format === 'xlsx' ? '下载 Excel（.xlsx）' : '下载 CSV', 'button'); download.disabled = true;
  form.append(query, cancel, download); panel.append(form);
  const pause = paged ? button('暂停', 'button') : null;
  const resume = paged ? button('继续 / 重试', 'button') : null;
  if (paged) { pause.disabled = resume.disabled = true; form.append(pause, resume); }
  const status = el('p', '请选择范围后查询。');
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  status.setAttribute('aria-atomic', 'true'); panel.append(status); root.append(panel);
  let sequence = 0, controller = null, payload = null, blobUrl = null, disposed = false;
  let run = null, paused = false, retryAt = 0;
  const csv = result => result.traversal_exhausted ? orderEmailTraversalCsv(result) : orderEmailCsv(result);
  const revoke = () => { if (blobUrl !== null) win.URL.revokeObjectURL(blobUrl); blobUrl = null; };
  const clear = () => {
    sequence++; controller?.abort(); controller = null; payload = null; revoke();
    run?.clear(); run = null; paused = false;
    if (paged) pause.disabled = resume.disabled = true;
    download.disabled = true; query.disabled = !metadataReady; panel.removeAttribute('aria-busy');
  };
  const invalidate = event => {
    if (event?.target === gameSearch) { searchGames(); return; }
    if (!disposed) { clear(); status.textContent = '条件已变更，请重新查询。'; }
  };
  const onCancel = () => { if (!disposed) { clear(); status.textContent = '已取消并清除名单。'; } };
  let metadataSequence = 0, metadataReady = !remoteOptions;
  const fill = (select, entries) => {
    if (!Array.isArray(entries)) throw new TypeError('Invalid options');
    const seen = new Set();
    const options = entries.map(entry => {
      if (!entry || typeof entry.value !== 'string' || !entry.value || seen.has(entry.value) ||
          typeof entry.label !== 'string' || !entry.label.trim()) throw new TypeError('Invalid option');
      seen.add(entry.value);
      const option = el('option', entry.label); option.value = entry.value; return option;
    });
    while (select.children.length) select.children[0].remove();
    if (!select.multiple) { const option = el('option', select === site ? '请选择站点' : '不限'); option.value = ''; select.append(option); }
    select.append(...options); select.value = '';
    if (select === game) renderGames();
  };
  const loadOptions = async (initial = false) => {
    const current = ++metadataSequence; metadataReady = false; query.disabled = true;

    status.textContent = '正在读取 Admin 筛选选项。';

    try {
      const response = await fetcher(url.href, { method: 'POST', credentials: 'same-origin', redirect: 'error',
        cache: 'no-store', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ kind: 'order_email_export_options', ...(initial ? {} : {
          progress: filters.progress.value, game_ids: Array.from(game.selectedOptions, option => option.value) }) }) });
      if (disposed || current !== metadataSequence) return;
      if (!response.ok || response.redirected) throw new Error();
      const data = await response.json();
      if (disposed || current !== metadataSequence) return;
      if (!data.options || data.error) throw new Error();
      if (initial) {
        sites = directory(data.options.sites); games = directory(data.options.games);
        fill(site, sites); fill(game, games);
        if (!data.options.country?.length) throw new Error();
        fill(filters.country, data.options.country);
        fill(filters.progress, data.options.progress);
        filters.progress.disabled = false;
      }
      // Do not replace independent directories or resurrect a cleared selection.
      for (const name of (remoteOptions ? ['status', 'cid'] : ['status', 'cid', 'aid'])) {
        const selected = filters[name].value;
        fill(filters[name], data.options[name]);
        if (Array.from(filters[name].children).some(option => option.value === selected)) filters[name].value = selected;
        filters[name].disabled = name === 'status' ? !filters.progress.value : !game.selectedOptions.length;
      }
      const selectedGames = Array.from(game.selectedOptions, option => option.value);
      const directories = data.options.servers_by_game || {};
      if (!directories || typeof directories !== 'object' || Array.isArray(directories) ||
          Object.keys(directories).some(key => !selectedGames.includes(key))) throw new Error();
      const previous = new Map(Array.from(serverControls, ([key, control]) => [key, control.value]));
      resetServers();
      for (const gameId of selectedGames) {
        const entries = directories[gameId] === undefined && data.unavailable?.aid ? [] : directories[gameId];
        if (!Array.isArray(entries) || entries.some(entry => !id(entry.value))) throw new Error();
        const control = field(`服务区 · ${games.find(entry => entry.value === gameId).label}`, 'select', `aid_${gameId}`, serverGroup);
        control.required = false; fill(control, entries); control.disabled = !!data.unavailable?.aid;
        if (entries.some(entry => entry.value === previous.get(gameId))) control.value = previous.get(gameId);
        serverControls.set(gameId, control);
      }
      metadataReady = true; query.disabled = false; status.textContent = '请选择范围后查询。';
    } catch {
      if (disposed || current !== metadataSequence) return;
      clear(); resetServers(); metadataReady = false; query.disabled = true;
      filters.status.disabled = filters.cid.disabled = filters.aid.disabled = true;
      status.textContent = 'Admin 筛选选项读取失败，请重新打开面板重试。';
    }
  };
  const dependentChange = event => {
    if (event.target === gameSearch) return;
    const item = gameRows.find(item => item.check === event.target);
    if (item) item.option.selected = item.check.checked;
    invalidate();
    if (event.target === game || item) {
      syncGames();
      if (remoteOptions) {
        resetServers(); fill(filters.cid, []); fill(filters.aid, []);
        filters.cid.disabled = filters.aid.disabled = true;
        return loadOptions();
      }
    }
    if (remoteOptions && event.target === filters.progress) {
      fill(filters.status, []); filters.status.disabled = true;
      return loadOptions();
    }
  };
  const progress = () => {
    const s = run.snapshot();
    return `已接受 ${s.accepted_pages} 页；已完成窗口 ${s.exhausted_windows}/${s.total_windows}。`;
  };
  const onPause = () => {
    if (disposed || !run || paused || run.snapshot().state !== 'active') return;
    if (!paged) throw new Error('Traversal interrupted');
    sequence++; controller?.abort(); controller = null; paused = true;
    pause.disabled = true; resume.disabled = false; query.disabled = false;
    panel.removeAttribute('aria-busy');
    status.textContent = `${progress()} 已暂停，尚不可导出；可在本页继续。`;
  };
  // Only transport failures and explicit throttling/unavailability retain the
  // pending request. Source/JSON/authorization errors erase the entire run.
  const readPages = async () => {
    if (disposed || !run || controller) return;
    if (Date.now() < retryAt) {
      status.textContent = `${progress()} 冷却中，请等待 ${Math.ceil((retryAt - Date.now()) / 1000)} 秒后手动重试。`;
      return;
    }
    paused = false; if (paged) { resume.disabled = true; pause.disabled = false; } query.disabled = true;
    const current = ++sequence;
    const activeRun = run;
    controller = new win.AbortController();
    const signal = controller.signal;
    const stale = () => disposed || current !== sequence;
    panel.setAttribute('aria-busy', 'true');
    try {
      for (let request = activeRun.nextRequest(); request; request = activeRun.nextRequest()) {
        status.textContent = `${progress()} 正在读取，尚不可导出。`;
        let response;
        try {
          response = await fetcher(url.href, { method: 'POST', credentials: 'same-origin',
            redirect: 'error', cache: 'no-store', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify(request), signal });
        } catch {
          if (stale()) return;
          onPause();
          status.textContent = `${progress()} 网络中断，已暂停；请手动重试。`;
          return;
        }
        if (stale()) return;
        if (response.redirected) throw new Error();
        if (response.status === 429 || response.status === 503) {
          const header = response.headers?.get('Retry-After');
          const seconds = typeof header === 'string' && /^\d+$/.test(header.trim()) ? Number(header) : NaN;
          const deadline = Number.isFinite(seconds) ? Date.now() + seconds * 1000 : Date.parse(header);
          // The existing API returns retryAfter in JSON, not an HTTP header.
          let guidance;
          try { guidance = await response.json(); } catch { /* No valid JSON guidance. */ }
          if (stale()) return;
          // Unknown/terminal source failures are not permission to retain PII.
          const transient = new Set(['source_busy', 'source_timeout', 'source_unavailable', 'live_source_unavailable', 'export_source_unavailable']);
          if (guidance?.error && !transient.has(guidance.error)) throw new Error();
          const bodySeconds = guidance?.retryAfter;
          const bodyDeadline = Number.isSafeInteger(bodySeconds) && bodySeconds >= 0
            ? Date.now() + bodySeconds * 1000 : NaN;
          const deadlines = [deadline, bodyDeadline].filter(Number.isFinite);
          retryAt = deadlines.length ? Math.max(Date.now(), ...deadlines) : Date.now() + 60000;
          onPause();
          status.textContent = `${progress()} ${guidance?.error === 'source_timeout' ? '本页读取超时' : '服务暂不可用'}，已暂停；请等待 ${Math.ceil((retryAt - Date.now()) / 1000)} 秒后手动重试。`;
          return;
        }
        if (!response.ok || response.status !== 206) throw new Error();
        let page;
        try { page = await response.json(); }
        catch (error) {
          if (stale()) return;
          // Native Response body-read transport failures reject with TypeError;
          // invalid JSON is SyntaxError and must invalidate the run instead.
          if (error?.name !== 'TypeError') throw error;
          onPause();
          status.textContent = `${progress()} 网络中断，已暂停；请手动重试。`;
          return;
        }
        if (stale()) return;
        activeRun.acceptPage(page);
      }
      const result = activeRun.result();
      csv(result);
      payload = result; download.disabled = false; if (paged) pause.disabled = resume.disabled = true;
      status.textContent = `${progress()} 全部计划窗口遍历结束，可下载 ${format === 'xlsx' ? 'Excel' : 'CSV'}；实时非快照。`;
    } catch {
      if (stale()) return;
      clear(); status.textContent = '查询结果、权限或游标无效，名单已清除，无法导出。请重新查询。';
    } finally {
      if (!stale()) { controller = null; query.disabled = false; panel.removeAttribute('aria-busy'); }
    }
  };
  const onResume = () => { if (!disposed && paused && run) return readPages(); };
  const onSubmit = async event => {
    event.preventDefault(); if (disposed || !metadataReady) return;
    if (paged && Date.now() < retryAt) {
      status.textContent = `冷却中，请等待 ${Math.ceil((retryAt - Date.now()) / 1000)} 秒后手动重试。`;
      return;
    }
    clear();
    let request;
    try { request = orderEmailRequest({ site_id: site.value,
      game_ids: Array.from(game.selectedOptions, option => option.value), start: start.value, end: end.value,
      ...(remoteOptions ? { server_ids: Object.fromEntries(Array.from(serverControls).filter(([, control]) => control.value !== '').map(([key, control]) => [key, control.value])) } : {}),
      filters: Object.fromEntries(Object.entries(filters).filter(([name, control]) => !control.disabled && control.value !== '').map(([name, control]) => [name, control.value])) }, sites, games); }
    catch { status.textContent = '请选择有效站点、游戏及付款日期（含结束日，最多 366 天）。'; return; }
    const current = sequence;
    if (paged || request.server_ids) {
      query.disabled = true;
      status.textContent = '正在准备分页查询，尚不可导出。';
      try {
        // Lazy import preserves the synchronous legacy mount and its loaders.
        const { OrderEmailRun } = await import('./order-email-run.js');
        if (disposed || current !== sequence) return;
        run = new OrderEmailRun(request);
        await readPages();
      } catch {
        if (disposed || current !== sequence) return;
        clear(); status.textContent = '无法准备分页查询，请重新查询。';
      }
      return;
    }
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
      if (request.filters && (!result.filters || Object.keys(result.filters).length !== Object.keys(request.filters).length ||
          Object.keys(request.filters).some(key => result.filters[key] !== request.filters[key]))) throw new Error();
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
  const onDownload = async () => {
    if (disposed || !payload || download.disabled) return;
    const current = sequence, selected = payload;
    let link;
    try {
      let bytes, type, extension;
      if (format === 'xlsx') {
        download.disabled = true;
        const writer = await import('./order-email-xlsx.js');
        if (disposed || current !== sequence || payload !== selected) return;
        bytes = (selected.traversal_exhausted ? writer.orderEmailTraversalXlsx : writer.orderEmailXlsx)(selected);
        type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'; extension = 'xlsx';
      } else {
        bytes = csv(selected); type = 'text/csv;charset=utf-8'; extension = 'csv';
      }
      revoke();
      blobUrl = win.URL.createObjectURL(new win.Blob([bytes], { type }));
      link = el('a'); link.href = blobUrl; link.download = 'order-user-emails.' + extension;
      panel.append(link); link.click();
    } catch {
      if (!disposed && current === sequence) { clear(); status.textContent = '下载失败，名单已清除，请重新查询。'; }
    } finally {
      link?.remove();
      if (!disposed && current === sequence && payload === selected) download.disabled = false;
    }
  };
  const onSearchKey = event => {
    if (event.key === 'Enter') event.preventDefault();
    if (event.key === 'Escape') { gamePicker.open = false; gameSummary.focus(); }
  };
  gameSearch.addEventListener('keydown', onSearchKey);
  form.addEventListener('submit', onSubmit);
  form.addEventListener('input', invalidate); form.addEventListener('change', dependentChange);
  cancel.addEventListener('click', onCancel); download.addEventListener('click', onDownload);
  pause?.addEventListener('click', onPause); resume?.addEventListener('click', onResume);
  if (remoteOptions) loadOptions(true);
  return { dispose() {
    if (disposed) return;
    disposed = true; clear();
    gameSearch.removeEventListener('keydown', onSearchKey);
    form.removeEventListener('submit', onSubmit);
    form.removeEventListener('input', invalidate); form.removeEventListener('change', dependentChange);
    cancel.removeEventListener('click', onCancel); download.removeEventListener('click', onDownload);
    pause?.removeEventListener('click', onPause); resume?.removeEventListener('click', onResume);
    panel.remove();
  } };
}
