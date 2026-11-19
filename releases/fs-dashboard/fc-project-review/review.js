'use strict';

document.addEventListener('DOMContentLoaded', () => {
  const byId = id => document.getElementById(id);
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const svgElement = (tag, attributes, text) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text != null) node.textContent = text;
    return node;
  };
  const readJson = id => JSON.parse(byId(id).textContent);
  const initial = readJson('review-data');
  const geometry = readJson('review-geometry');
  const seriesColors = ['--fs-brand', '--fs-info', '--fs-warn', '--fs-violet', '--fs-danger', '--fs-ok', '--fs-muted'];
  const statuses = {complete:'已覆盖', partial:'部分覆盖', unavailable:'未取得', stale:'使用已保存数据'};
  const lifecycleNames = {new:'新客', new_customer:'新客', returning:'复购客户', repeat:'复购客户', returning_customer:'复购客户', unknown:'未标记'};
  const categoryNames = {coins:'金币', players:'Players', player:'Players', sbc:'SBC', packs:'Packs', other:'其他', unknown:'未归属'};
  const regionName = new Intl.DisplayNames(['zh-CN'], {type:'region', fallback:'none'});
  const countryName = code => /^[A-Z]{2}$/.test(code || '') ? regionName.of(code) || code : code || '未知';
  const present = Number.isFinite;
  const list = value => Array.isArray(value) ? value : [];
  const valueFormat = (options = {}) => {
    const format = new Intl.NumberFormat('en-US', options);
    return value => present(value) ? format.format(value) : '—';
  };
  const count = valueFormat({maximumFractionDigits:1});
  const usd = valueFormat({style:'currency', currency:'USD'});
  const cny = valueFormat({style:'currency', currency:'CNY', currencyDisplay:'narrowSymbol'});
  const pct = value => present(value) ? value.toFixed(2) + '%' : '—';
  const ratio = value => present(value) ? value.toFixed(2) + '×' : '—';
  const minutes = value => present(value) ? count(value) + ' 分钟' : '—';
  const shortNumber = new Intl.NumberFormat('en-US', {notation:'compact', maximumFractionDigits:1});
  const dayMs = 86400000;
  const dateNumber = date => Date.parse(date + 'T00:00:00Z');
  const isoDate = time => new Date(time).toISOString().slice(0, 10);
  const isDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    present(dateNumber(value)) && isoDate(dateNumber(value)) === value;
  const shift = (date, days) => isoDate(dateNumber(date) + days * dayMs);
  const daysBetween = (start, end) => (dateNumber(end) - dateNumber(start)) / dayMs;
  const allDays = (start, end) => Array.from({length:daysBetween(start, end) + 1}, (_, i) => shift(start, i));
  const minDate = (a, b) => a < b ? a : b;
  const maxDate = (a, b) => a > b ? a : b;
  const monthStart = date => date.slice(0, 7) + '-01';
  const moveMonth = (date, delta) => {
    const d = new Date(dateNumber(monthStart(date)));
    d.setUTCMonth(d.getUTCMonth() + delta);
    return isoDate(d);
  };
  const today = isoDate(Date.now() + 8 * 3600000);
  const asOf = isDate(initial.asOf) ? initial.asOf : shift(today, -1);
  const season = game => {
    const recorded = list(initial.seasons).find(entry => entry.game === game);
    return {
      start:isDate(recorded?.start) ? recorded.start : game === 'FC26' ? '2025-09-01' : '2026-09-01',
      end:minDate(isDate(recorded?.end) ? recorded.end : game === 'FC26' ? '2026-09-30' : asOf, asOf),
    };
  };
  const validPeriod = item => ['FC26', 'FC27'].includes(item?.game) && isDate(item.start) &&
    isDate(item.end) && item.start <= item.end && daysBetween(item.start, item.end) <= 396;
  const key = item => [item.game, item.scope || 'all', item.start, item.end].join('|');
  const scopeLabel = scope => scope === 'all' ? '全部网站' : scope === 'main' ? 'MMOEXP' : scope;
  const rangeLabel = item => item.start === item.end ? item.start : item.start + ' 至 ' + item.end;
  const periods = new Map();
  let selected, selectedPrevious, categoryMode = 'salesUsd', spendMode = 'customers', activeRequest;
  const resizeObservers = [];
  const loadedSelect = byId('loaded-period');

  function updatePackets(data) {
    const incoming = list(data?.packets).filter(validPeriod);
    for (const packet of incoming) {
      const scope = packet.scope || 'all';
      if (![...byId('scope').options].some(option => option.value === scope)) {
        byId('scope').append(new Option(scopeLabel(scope), scope));
      }
      periods.set(key(packet), {...periods.get(key(packet)), ...packet, scope});
    }
    loadedSelect.replaceChildren(new Option('选择区间', ''));
    const sorted = [...periods.values()].sort((a, b) => b.end.localeCompare(a.end) || a.game.localeCompare(b.game));
    for (const packet of sorted) {
      loadedSelect.append(new Option([packet.game, scopeLabel(packet.scope), rangeLabel(packet)].join(' · '), key(packet)));
    }
    byId('loaded-field').hidden = !sorted.length;
    return incoming.length;
  }

  function rangeFor(game, scope, grain, anchor, end) {
    const border = season(game);
    const weekStart = date => shift(date, -((new Date(dateNumber(date)).getUTCDay() + 6) % 7));
    const first = grain === 'week' ? weekStart(anchor) : grain === 'month' ? monthStart(anchor) : anchor;
    const last = grain === 'week' ? shift(first, 6) : grain === 'month' ? shift(moveMonth(first, 1), -1) :
      grain === 'custom' ? end : anchor;
    return {game, scope, start:maxDate(first, border.start), end:minDate(last, border.end), grain};
  }

  function previousFor(query) {
    const packet = periods.get(key(query));
    const comparison = packet?.previousPeriod || packet?.traffic?.periods?.previous;
    if (isDate(comparison?.start) && isDate(comparison?.end)) {
      return {...query, start:comparison.start, end:comparison.end};
    }
    if (query.grain === 'week') return {...query, start:shift(query.start, -7), end:shift(query.end, -7)};
    if (query.grain === 'month') {
      const first = moveMonth(query.start, -1);
      const last = shift(moveMonth(first, 1), -1);
      return {...query, start:first, end:query.end === shift(moveMonth(query.start, 1), -1) ? last :
        minDate(last, shift(first, daysBetween(query.start, query.end)))};
    }
    const length = daysBetween(query.start, query.end) + 1;
    return {...query, start:shift(query.start, -length), end:shift(query.end, -length)};
  }

  function syncFields() {
    const game = byId('game').value;
    const grain = document.querySelector('input[name="grain"]:checked').value;
    const explicit = grain === 'custom';
    const label = {day:'日期', week:'周内日期', month:'月内日期', custom:'开始日'};
    const border = season(game);
    byId('start-label').textContent = label[grain];
    byId('end-field').hidden = !explicit;
    byId('end').disabled = !explicit;
    for (const id of ['start', 'end']) {
      const field = byId(id);
      field.min = border.start;
      field.max = border.end;
      if (field.value && (field.value < border.start || field.value > border.end)) field.value = border.end;
      field.setCustomValidity('');
      field.removeAttribute('aria-invalid');
    }
    byId('range-help').textContent = '北京时间 · 包含所选结束日 · ' + game + ' 至 ' + border.end;
  }

  function showStatus(message) {
    byId('import-status').textContent = message;
    byId('import-status').hidden = !message;
  }

  function setMissing(query, packet, fetchState = '') {
    const pane = byId('request-pane');
    const target = packet ? '' : fetchState || (initial.packetUrl ?
      '所选网站和日期还没有区间汇总。' : '所选网站和日期还没有区间汇总。可载入这个区间的数据包。');
    pane.hidden = !target;
    byId('request-text').textContent = target;
    const request = {game:query.game, start:query.start, end:query.end, scope:query.scope};
    const command = typeof initial.requestCommand === 'string' && (request.scope === 'all' || initial.requestCommand.includes('{scope}')) ?
      initial.requestCommand.replace(/\{(game|start|end|scope)\}/g, (_, field) => request[field]) :
      [request.game, scopeLabel(request.scope), rangeLabel(request), '北京时间，含结束日'].join(' · ');
    byId('request-instructions').hidden = !target || !!initial.packetUrl;
    byId('request-command').textContent = command;
  }

  async function getPacket(query, signal) {
    const configured = initial.packetUrl;
    if (location.protocol === 'file:') return;
    const nativeFallback = async () => {
      if (initial.nativeFs === true && query.scope === 'all') {
        const packet = await nativePacket(query, signal);
        if (!signal.aborted) updatePackets({packets:[packet]});
      }
    };
    if (!configured) return nativeFallback();
    const url = new URL(configured, location.href);
    if (url.origin !== location.origin) throw Error('读取地址必须与看板同源。');
    const production = url.searchParams.get('mode') === 'fc-project-review';
    if (production && query.scope !== 'all') return;
    for (const field of ['start', 'end']) url.searchParams.set(field, query[field]);
    url.searchParams.set(production ? 'profile' : 'game', query.game);
    if (!production) url.searchParams.set('scope', query.scope);
    while (!signal.aborted) {
      const timeout = AbortSignal.any([signal, AbortSignal.timeout(30000)]);
      const result = await fetch(url, {signal:timeout, credentials:'same-origin', cache:'no-store', redirect:'error'});
      if ([401,403].includes(result.status)) throw Error('当前登录无权读取该区间。');
      if (result.status === 404) return nativeFallback();
      if (result.status === 202 || result.status === 429) {
        const pending = await result.json();
        const retry = present(pending.retryAfter) ? Math.max(1,Math.min(12,pending.retryAfter)) : 3;
        if (query === selected) setMissing(query, null, 'FS 正在汇总所选区间，请稍候…');
        await new Promise(resolve => {
          const stop = () => { clearTimeout(timer); signal.removeEventListener('abort',stop); resolve(); };
          const timer = setTimeout(stop,retry * 1000);
          if (signal.aborted) stop();
          else signal.addEventListener('abort',stop,{once:true});
        });
        continue;
      }
      if (!result.ok) throw Error('区间读取暂未完成，可稍后重试或载入数据包。');
      const data = await result.json();
      if (!list(data.packets).some(packet => validPeriod(packet) && key(packet) === key(query))) {
        throw Error('返回数据包的版本、网站或日期与筛选条件不一致。');
      }
      if (!signal.aborted) updatePackets(data);
      return;
    }
  }

  async function nativePacket(query, signal) {
    const {game, start, end} = query;
    const [gameId, orderGameId] = game === 'FC26' ? ['833','824'] : ['1327','1322'];
    const read = async mode => {
      const args = new URLSearchParams({profile:game, start, end, mode, grain:'day', profit_basis:'shipping', profit_site:'all', profit_category:'-1'});
      const response = await fetch('/dashboard/fs-home/range.json?' + args, {signal, credentials:'same-origin', cache:'no-store', redirect:'error'});
      if ([401,403].includes(response.status)) throw Error('当前登录无权读取所选区间。');
      if (!response.ok || response.status === 202) throw Error('FS 正在读取或暂未返回此区间，可稍后重试。');
      const value = await response.json();
      if (value.query?.start !== start || value.query?.end !== end || value.query?.profit_site !== 'all' ||
          value.query?.profit_category !== '-1') throw Error('FS 返回的站点、日期或类目不匹配。');
      return value;
    };
    const summary = await read('summary');
    const admin = summary.profile?.supplement, filters = admin?.filters;
    const expected = [start + ' 00:00', shift(end, 1) + ' 00:00'];
    if (summary.status !== 'available' || summary.profile?.key !== game ||
        admin?.effective_scope?.site !== 'all' || filters?.site !== '' || String(filters.game) !== gameId ||
        filters.pay_status !== 1 || JSON.stringify(filters.date) !== JSON.stringify(expected) ||
        ['product_type','cid','client','discount_code','country_code','pay_type','order_status'].some(field => filters[field])) {
      throw Error('FS 已付款汇总范围未核对通过。');
    }
    const metric = (metrics, key) => metrics?.[key]?.status === 'available' && present(metrics[key].value) ? metrics[key].value : null;
    const salesUsd = metric(admin.metrics, 'revenueUsd'), orders = metric(admin.metrics, 'orders');
    const newCustomers = metric(admin.metrics, 'newCustomers'), paying = metric(admin.metrics, 'payingCustomers');
    const newPct = present(newCustomers) && present(paying) && paying > 0 && newCustomers <= paying ? 100 * newCustomers / paying : null;
    const daily = allDays(start,end).map(date => ({date}));
    const byDate = new Map(daily.map(row => [row.date,row]));
    const adminRows = list(admin.rows);
    const unique = new Set();
    for (const row of adminRows) {
      const target = byDate.get(row.date?.slice(0,10));
      if (!target || unique.has(row.date) || !present(Number(row.amount)) || row.amount == null || !present(row.orders)) {
        unique.clear();
        break;
      }
      unique.add(row.date);
      target.salesUsd = (target.salesUsd || 0) + Number(row.amount);
      target.orders = (target.orders || 0) + row.orders;
    }
    if (!unique.size || !present(salesUsd) || Math.abs(daily.reduce((sum,row) => sum + (row.salesUsd || 0),0) - salesUsd) >= .01 ||
        daily.reduce((sum,row) => sum + (row.orders || 0),0) !== orders) {
      for (const row of daily) { delete row.salesUsd; delete row.orders; }
    }
    const shipping = summary.profile.shipping;
    const shipValid = shipping?.status === 'available' && !shipping.stale && shipping.profileKey === game &&
      shipping.sourceContract === 'order-shipping-v1' && shipping.currency === 'CNY' &&
      shipping.shippingSelection?.site === 'all' && shipping.shippingSelection?.cid === '-1' &&
      shipping.period?.start === admin.period?.start && shipping.period?.end === admin.period?.end;
    const coverage = [];
    const history = await read('profit-history').catch(error => {
      if (signal.aborted || error.message.includes('无权')) throw error;
      coverage.push(error.message);
    });
    if (history?.query?.profile === game && history.history?.contractId === 'order-native-daily-margin-v2') {
      for (const row of list(history.history.daily)) {
        const target = byDate.get(row.date);
        if (target && row.profileKey === game && row.status === 'available' && !row.stale && row.currency === 'CNY' &&
            row.sourceContract === 'order-shipping-v1' && row.scope?.sites === 'all-websites' &&
            String(row.scope?.orderGameId) === orderGameId && String(row.scope?.orderProductType) === '-1' &&
            String(row.scope?.orderStatus) === '-1' && String(row.scope?.orderAreaId) === '0' &&
            [row.profitCny,row.salesCny,row.costCny].every(present) &&
            Math.abs(row.salesCny - row.costCny - row.profitCny) <= .011) {
          target.profitCny = row.profitCny;
          if (row.salesCny !== 0) {
            target.marginPct = row.profitCny / row.salesCny * 100;
            target.costPct = row.costCny / row.salesCny * 100;
          }
        }
      }
    }
    return {...query, daily, coverage, sources:['Admin 已付款整单汇总','Order 发货统计'],
      kpi:{salesUsd, orders, newCustomers, newPct, returningPct:present(newPct) ? 100 - newPct : null,
        aov:orders > 0 && present(salesUsd) ? salesUsd / orders : null,
        profitCny:shipValid ? metric(shipping.metrics,'profitCny') : null,
        marginPct:shipValid ? metric(shipping.metrics,'profitMarginPct') : null}};
  }

  async function selectRange(query, request = true) {
    activeRequest?.abort();
    const owner = new AbortController();
    activeRequest = owner;
    selected = query;
    render();
    const canRead = initial.packetUrl || (initial.nativeFs === true && query.scope === 'all');
    if (!request || periods.has(key(query)) || location.protocol === 'file:' || !canRead) return;
    setMissing(query, null, '正在读取所选区间…');
    try {
      await getPacket(query, owner.signal);
      if (owner.signal.aborted) return;
      render();
      const comparison = selectedPrevious;
      if (periods.has(key(query)) && !periods.has(key(comparison)) && comparison.start >= season(query.game).start) {
        byId('compare-range').textContent = '对照期 ' + rangeLabel(comparison) + ' · 正在读取';
        try { await getPacket(comparison, owner.signal); }
        catch (error) {
          if (!owner.signal.aborted) byId('compare-range').textContent = '对照期 ' + rangeLabel(comparison) + ' · ' + error.message;
          return;
        }
        if (!owner.signal.aborted) render();
      }
    } catch (error) {
      if (!owner.signal.aborted) setMissing(query, null, error.name === 'TimeoutError' ? '本次读取超时，可稍后再查看。' : error.message);
    }
  }

  function rowsFor(data, field, game = selected.game) {
    return list(data?.[field]).filter(item => item && typeof item === 'object' && (!item.game || item.game === game));
  }

  function empty(message = '所选区间未取得此项数据。') {
    return element('p', message, 'empty');
  }

  function mount(id, node) {
    byId(id).replaceChildren(node);
  }

  function details(label, child) {
    const root = element('details', null, 'detail');
    root.append(element('summary', label), child);
    return root;
  }

  function dataTable(label, columns, rows, emptyMessage) {
    if (!rows.length) return empty(emptyMessage);
    const frame = element('div', null, 'fs-table-scroll');
    frame.tabIndex = 0;
    frame.setAttribute('role', 'region');
    frame.setAttribute('aria-label', label);
    const table = element('table');
    table.setAttribute('aria-label', label);
    const header = table.createTHead().insertRow();
    for (const title of columns) {
      const cell = element('th', title);
      cell.scope = 'col';
      header.append(cell);
    }
    const body = table.createTBody();
    for (const row of rows) {
      const line = body.insertRow();
      row.forEach((item, i) => {
        const cell = element(i === 0 ? 'th' : 'td', item);
        if (i === 0) cell.scope = 'row';
        line.append(cell);
      });
    }
    frame.append(table);
    return frame;
  }

  function coverage(id, entries) {
    const host = byId(id);
    const lines = list(entries).flatMap(item => {
      if (typeof item === 'string') return item.trim() ? [item] : [];
      if (!item || typeof item !== 'object') return [];
      const label = [item.label, statuses[item.status], item.reason || item.message || item.note,
        present(item.coveredOrders) && present(item.totalOrders) ? count(item.coveredOrders) + ' / ' + count(item.totalOrders) + ' 单' : null,
        isDate(item.start) && isDate(item.end) ? rangeLabel(item) : null].filter(Boolean).join(' · ');
      return label ? [label] : [];
    });
    host.replaceChildren();
    if (lines.length) {
      const values = element('ul');
      for (const value of new Set(lines)) values.append(element('li', value));
      const summary = details('查看覆盖与统计口径', values);
      summary.className = 'coverage';
      host.append(summary);
    }
  }

  function fieldCoverage(data, fields) {
    return fields.flatMap(([field, label]) => {
      const item = data?.coverage?.[field];
      return item ? [{label, ...item}] : [];
    });
  }

  function cards(id, specs, now = {}, prior = {}, opts = {}) {
    const host = byId(id);
    host.classList.toggle('mini-kpis', !!opts.mini);
    host.replaceChildren(...specs.map(([key, label, formatter = count, unit]) => {
      const current = now?.[key], previous = prior?.[key];
      const card = element('div', null, 'panel kpi');
      const value = element('strong', formatter(current), present(current) ? '' : 'no-value');
      if (!present(current)) value.setAttribute('aria-label', '未取得');
      card.append(element('span', label), value);
      if (present(current) && present(previous)) {
        const diff = current - previous;
        const numeric = unit === 'pp' ? diff : previous !== 0 ? diff / Math.abs(previous) * 100 : null;
        const delta = present(numeric) ?
          (numeric > 0 ? '+' : '') + numeric.toFixed(1) + (unit === 'pp' ? ' pp' : '%') :
          '上期 ' + formatter(previous);
        card.append(element('small', delta, diff > 0 ? 'up' : diff < 0 ? 'down' : 'flat'));
      } else {
        card.append(element('small', present(current) ? '上期未取得' : '未取得', 'flat'));
      }
      return card;
    }));
  }

  function coloredLabel(label, color) {
    const text = element('span');
    const mark = element('i', null, 'legend-dot');
    mark.style.setProperty('--series-color', 'var(' + color + ')');
    mark.setAttribute('aria-hidden', 'true');
    text.append(mark, document.createTextNode(label));
    return text;
  }

  function metricChart(id, rows, series, opts = {}) {
    const host = byId(id);
    const existing = resizeObservers.findIndex(([, , container]) => container === host);
    if (existing >= 0) {
      resizeObservers[existing][0].disconnect();
      resizeObservers.splice(existing, 1);
    }
    host.replaceChildren();
    const active = series.filter(item => rows.some(row => present(row[item.key])));
    if (!active.length) {
      host.append(empty(opts.empty));
      return;
    }
    const figure = element('figure', null, 'chart-wrap');
    const caption = element('figcaption', null, 'chart-caption');
    const canvas = element('canvas');
    const readout = element('p', '移动到图上查看数值，或展开下方明细。', 'chart-readout');
    const title = opts.title || host.closest('article').querySelector('h3').textContent;
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', title + '，精确数值见下方数据明细。');
    for (const item of active) caption.append(coloredLabel(item.label, item.color));
    figure.append(caption, canvas, readout);
    if (opts.subtitle) host.append(element('p',opts.subtitle,'card-sub'));
    const share = (row, item) => {
      const total = active.reduce((sum, key) => sum + (present(row[key.key]) ? row[key.key] : 0), 0);
      return opts.showShares && total > 0 && present(row[item.key]) ? '（' + pct(row[item.key] / total * 100) + '）' : '';
    };
    const valueText = (row,item) => {
      const samples = opts.showSamples ? row[item.key + 'Timed'] : null;
      return item.format(row[item.key]) + share(row,item) + (present(samples) ? '（' + count(samples) + ' 单）' : '');
    };
    host.append(figure, details('查看' + (opts.bucket || '每日') + '数值', dataTable(title, [opts.bucket || '日期', ...active.map(item => item.label)],
      rows.map(row => [row.label || row.date, ...active.map(item => valueText(row,item))]))));

    const context = canvas.getContext('2d');
    if (!context) return;
    const stacked = opts.stacked || false;
    const dual = active.some(item => item.axis === 1) && active.some(item => item.axis !== 1);
    const leftUnit = active.find(item => item.axis !== 1)?.unit || active[0].unit || '';
    const rightUnit = active.find(item => item.axis === 1)?.unit || '';
    const numbers = axis => rows.flatMap(row => {
      const values = active.filter(item => !dual || (item.axis || 0) === axis)
        .map(item => row[item.key]).filter(present);
      return stacked && values.length ? [values.reduce((total, value) => total + value, 0), ...values] : values;
    });
    const extent = axis => {
      const v = numbers(axis);
      const low = Math.min(0, ...v);
      return [low, Math.max(1, ...v) * 1.08];
    };
    const domains = [extent(0), extent(1)];
    let index = null, bounds;
    function draw() {
      const box = canvas.getBoundingClientRect();
      if (!box.width || !box.height) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(box.width * dpr);
      canvas.height = Math.round(box.height * dpr);
      context.scale(dpr, dpr);
      const theme = getComputedStyle(canvas);
      const color = name => theme.getPropertyValue(name).trim();
      const top = 12, bottom = box.height - 25, left = dual ? 51 : 44, right = box.width - (dual ? 51 : 8);
      const plot = right - left;
      const step = plot / rows.length;
      bounds = {left, step};
      const x = i => left + (i + .5) * step;
      const y = (value, axis = 0) => {
        const [low, high] = domains[dual ? axis : 0];
        return bottom - (bottom - top) * (value - low) / (high - low);
      };
      const tick = (value, unit) => unit === '%' ? shortNumber.format(value) + unit : unit + shortNumber.format(value);
      context.font = '11px ' + color('--fs-font');
      context.textBaseline = 'middle';
      for (let i = 0; i < 5; i++) {
        const yPos = top + (bottom - top) * i / 4;
        context.strokeStyle = color('--fs-line');
        context.beginPath(); context.moveTo(left, yPos); context.lineTo(right, yPos); context.stroke();
        context.fillStyle = color('--fs-muted');
        context.textAlign = 'right';
        const [low, high] = domains[0];
        context.fillText(tick(high - (high - low) * i / 4, leftUnit), left - 7, yPos, left - 8);
        if (dual) {
          context.textAlign = 'left';
          const [secondLow, secondHigh] = domains[1];
          context.fillText(tick(secondHigh - (secondHigh - secondLow) * i / 4, rightUnit), right + 7, yPos, box.width - right - 8);
        }
      }
      const labelInterval = Math.max(1, Math.ceil(rows.length / Math.max(2, Math.floor(plot / 60))));
      const stackTotals = new Array(rows.length).fill(0);
      for (const item of active) {
        const innerColor = color(item.color);
        const axis = item.axis || 0;
        context.strokeStyle = innerColor;
        context.fillStyle = innerColor;
        if (item.bar) {
          const width = Math.max(1, Math.min(32, step * .64));
          rows.forEach((row, i) => {
            const value = row[item.key];
            if (!present(value)) return;
            const base = stacked ? stackTotals[i] : 0;
            if (stacked) stackTotals[i] += value;
            const start = y(base, axis), end = y(base + value, axis);
            context.globalAlpha = .85;
            context.fillRect(x(i) - width / 2, Math.min(start, end), width, Math.max(1, Math.abs(start - end)));
            context.globalAlpha = 1;
          });
        } else {
          context.lineWidth = 2;
          context.beginPath();
          let previous = false;
          rows.forEach((row, i) => {
            if (!present(row[item.key])) { previous = false; return; }
            if (previous) context.lineTo(x(i), y(row[item.key], axis));
            else context.moveTo(x(i), y(row[item.key], axis));
            previous = true;
          });
          context.stroke();
          rows.forEach((row, i) => {
            if (!present(row[item.key])) return;
            const isolated = !present(rows[i - 1]?.[item.key]) && !present(rows[i + 1]?.[item.key]);
            if (!isolated && rows.length > 14 && index !== i) return;
            context.beginPath(); context.arc(x(i), y(row[item.key], axis), index === i ? 4 : 2.5, 0, Math.PI * 2); context.fill();
          });
        }
      }
      context.fillStyle = color('--fs-muted');
      context.textAlign = 'center';
      rows.forEach((row, i) => {
        if (i % labelInterval === 0) context.fillText(row.label || row.date.slice(5), x(i), bottom + 14, Math.max(30, labelInterval * step - 4));
      });
      if (index !== null) {
        context.strokeStyle = color('--fs-muted');
        context.lineWidth = 1;
        context.setLineDash([3, 3]);
        context.beginPath(); context.moveTo(x(index), top); context.lineTo(x(index), bottom); context.stroke();
        context.setLineDash([]);
      }
    }
    canvas.addEventListener('pointermove', event => {
      if (!bounds) return;
      const hovered = Math.max(0, Math.min(rows.length - 1, Math.floor((event.offsetX - bounds.left) / bounds.step)));
      if (hovered === index) return;
      index = hovered;
      const row = rows[index];
      readout.textContent = [row.label || row.date, ...active.map(item => item.label + ' ' + valueText(row,item))].join(' · ');
      draw();
    });
    canvas.addEventListener('pointerleave', () => { index = null; draw(); });
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    resizeObservers.push([observer, draw, host]);
  }

  function donut(id, rows, valueKey, formatter, title) {
    const host = byId(id);
    host.replaceChildren();
    const available = rows.filter(row => present(row[valueKey]));
    if (!available.length) {
      host.append(empty());
      return;
    }
    const total = available.reduce((sum, row) => sum + row[valueKey], 0);
    const breakdown = element('ul', null, 'legend-list');
    const chart = element('div', null, 'donut');
    chart.setAttribute('aria-hidden', 'true');
    let cumulative = 0;
    const canPlot = total > 0 && !available.some(item => item[valueKey] < 0);
    const parts = [];
    for (const [i, row] of available.entries()) {
      const base = cumulative;
      const share = canPlot ? row[valueKey] / total * 100 : null;
      const color = row.color || seriesColors[i % seriesColors.length];
      if (present(share) && share > 0) {
        cumulative += share;
        parts.push('var(' + color + ') ' + base + '% ' + cumulative + '%');
      }
      const line = element('li');
      const label = coloredLabel(row.label, color);
      if (present(share)) label.append(element('small', pct(share)));
      line.append(label, element('strong', formatter(row[valueKey])));
      breakdown.append(line);
    }
    if (canPlot) {
      chart.style.background = 'conic-gradient(' + parts.join(',') + ')';
      chart.append(element('span', formatter(total)));
      const wrapper = element('div', null, 'donut-layout');
      wrapper.append(chart, breakdown);
      host.append(wrapper);
    } else {
      host.append(breakdown, element('p', title + '含负值或合计为零，显示各项原值。', 'card-sub'));
    }
  }

  function ranking(id, rows, options = {}) {
    const valueKey = options.valueKey || 'salesUsd';
    const format = valueKey === 'orders' ? count : usd;
    const sorted = [...rows].filter(row => present(row[valueKey])).sort((a, b) => b[valueKey] - a[valueKey] || a.label.localeCompare(b.label));
    if (!sorted.length) {
      mount(id, empty(options.empty));
      return;
    }
    const top = sorted.slice(0, options.limit || 8);
    const rankList = element('ol', null, 'rank-list');
    const maximum = Math.max(1, top[0][valueKey]);
    for (const [i, row] of top.entries()) {
      const item = element('li');
      const meta = element('div', null, 'rank-title');
      const name = element('span', (i + 1) + '. ' + row.label);
      const value = element('strong', format(row[valueKey]) + (valueKey === 'orders' ? ' 单' : ''));
      if (valueKey !== 'orders' && present(row.orders)) value.append(element('small', count(row.orders) + ' 单'));
      const track = element('div', null, 'rank-track');
      track.setAttribute('aria-hidden', 'true');
      const fill = element('span', null, 'rank-fill');
      fill.style.width = (Math.max(0, row[valueKey]) / maximum * 100) + '%';
      track.append(fill);
      meta.append(name, value);
      item.append(meta, track);
      rankList.append(item);
    }
    const host = byId(id);
    host.replaceChildren();
    if (options.note) host.append(element('p', options.note, 'card-sub'));
    host.append(rankList);
    if (sorted.length > top.length) {
      host.append(details('查看全部 ' + sorted.length + ' 项', dataTable('完整排名', ['名称', '销售额 USD', '订单数'],
        sorted.map(row => [row.label, usd(row[valueKey]), count(row.orders)]))));
    }
  }


  function dailyRows(packet, dates) {
    const candidates = [...periods.values()]
      .filter(item => item.game === selected.game && item.scope === selected.scope && item.start <= selected.end && item.end >= selected.start)
      .sort((a, b) => daysBetween(b.start, b.end) - daysBetween(a.start, a.end));
    const registered = new Map();
    for (const row of [...candidates.flatMap(item => list(item.daily)), ...list(packet?.daily)]) {
      const normalized = {...row, date:row.date || row.d};
      if (isDate(normalized.date)) {
        const current = registered.get(normalized.date) || {};
        for (const [field, value] of Object.entries(normalized)) if (value != null) current[field] = value;
        registered.set(normalized.date, current);
      }
    }
    return dates.map(date => registered.get(date) || {date});
  }

  const kpiSpecs = [
    ['salesUsd','销售额',usd], ['orders','订单数'], ['profitCny','毛利',cny],
    ['marginPct','毛利率',pct,'pp'], ['newCustomers','新客人数'],
    ['newPct','新客占比',pct,'pp'], ['returningPct','复购率',pct,'pp'],
    ['discountPct','优惠率',pct,'pp'], ['aov','客单价',usd],
  ];
  const spec = (key, label, format, color, settings = {}) => ({key, label, format, color, ...settings});

  function renderOverview(packet, prior, dates) {
    const daily = dailyRows(packet, dates);
    cards('kpis', kpiSpecs, packet?.kpi, prior?.kpi);
    metricChart('sales-trend', daily, [
      spec('salesUsd', '销售 USD', usd, '--fs-brand', {unit:'$', bar:true}),
      spec('profitCny', '毛利 CNY', cny, '--fs-info', {unit:'¥', axis:1}),
    ]);
    metricChart('rate-trend', daily, [
      spec('marginPct', '毛利率', pct, '--fs-brand', {unit:'%'}),
      spec('costPct', '采购成本占比', pct, '--fs-violet', {unit:'%'}),
    ]);
    const missing = daily.filter(row => !present(row.salesUsd) || !present(row.profitCny)).length;
    coverage('overview-coverage', [
      'Admin 已付款整单 · 美元销售额 / 订单数。毛利使用 Order 发货统计的人民币发货额减采购额，毛利率与成本占比分母均为同范围人民币发货额。',
      ...(missing ? ['销售或毛利数据缺 ' + missing + ' / ' + dates.length + ' 天，图中保留空档。'] : []),
      ...list(packet?.coverage),
    ]);
  }

  function categoryKey(value) {
    const normalized = String(value || 'unknown').toLowerCase().replace(/[\s_-]+/g, '');
    return {gamecoins:'coins', coin:'coins', 金币:'coins', 球员卡:'players', player:'players',
      球员:'players', 球员卡players:'players', pack:'packs', 卡包:'packs', 其他:'other', 未知:'unknown',
      unclassified:'unknown', 未归属:'unknown'}[normalized] || normalized;
  }

  const categoryOrder = ['coins','players','sbc','packs','other','unknown'];
  const categoryColor = value => seriesColors[categoryOrder.indexOf(value)] || '--fs-muted';
  const categoryLabel = value => categoryNames[categoryKey(value)] || value || '未归属';

  function renderCategory(orderData, dates) {
    const useSales = categoryMode === 'salesUsd';
    for (const button of byId('category-mode').querySelectorAll('button')) {
      button.setAttribute('aria-pressed', String(button.dataset.mode === categoryMode));
    }
    const sales = rowsFor(orderData, 'categories');
    const profit = rowsFor(orderData?.fulfillment, 'rows');
    const totalRows = useSales ? sales : profit;
    const values = totalRows.filter(item => item.category && item.category !== 'all').map(item => ({
      ...item, label:categoryLabel(item.category), color:categoryColor(categoryKey(item.category)),
    }));
    const format = useSales ? usd : cny;
    const title = useSales ? '销售额' : '毛利';
    donut('category-share', values, categoryMode, format, title);
    if (useSales && values.length && !values.some(row => present(row.salesUsd))) {
      byId('category-share').append(dataTable('可取得的分类订单', ['品类','订单数','销售额 USD'],
        values.map(row => [row.label, count(row.orders), usd(row.salesUsd)])));
    }
    const currentDaily = useSales ? rowsFor(orderData, 'categoryDaily') :
      [...rowsFor(orderData, 'categoryProfitDaily'), ...rowsFor(orderData?.fulfillment, 'daily')];
    const bucket = new Map(dates.map(date => [date, {date}]));
    const types = new Set();
    for (const row of currentDaily) {
      const entry = bucket.get(row.date);
      const group = categoryKey(row.category);
      const metric = row[categoryMode] ?? (useSales ? null : row.profitCny);
      if (!entry || !present(metric)) continue;
      types.add(group);
      entry[group] = metric;
    }
    metricChart('category-trend', [...bucket.values()], [...types].map(type =>
      spec(type, categoryLabel(type), format, categoryColor(type), {unit:useSales ? '$' : '¥'})),
    {empty:useSales ? '所选区间未取得每日品类销售。' : '所选区间未取得按天、按整单分类的发货毛利。'});
    const products = rowsFor(orderData, 'products').map(row => ({...row, label:row.name || row.product || row.label || '未命名'}));
    ranking('players-rank', products.filter(row => categoryKey(row.category) === 'players'), {empty:'所选区间未取得可核对的 Players 单品排名。'});
    ranking('sbc-rank', products.filter(row => categoryKey(row.category) === 'sbc'), {empty:'所选区间未取得可核对的 SBC 单品排名。'});
    coverage('category-coverage', [
      ...fieldCoverage(orderData, [['categories','品类销售'],['fulfillment','品类毛利'],['products','商品排行']]),
      '整单归属依次为 Players、SBC、Packs、其他、金币。品类毛利使用同一订单组的 Order 发货金额与成本。',
    ]);
  }

  function renderPrices(prices) {
    const host = byId('observed-prices');
    host.replaceChildren();
    if (!prices) return;
    const tiers = list(prices.tiers);
    const panel = element('div');
    panel.append(element('p','MMOEXP 主站确认写入并读回的 100K / 1000K 价格，按独立操作与平台统计。','card-sub'));
    panel.append(dataTable('期内主站读回价', ['平台 / 数量','观测数','最低 USD','中位 USD','最高 USD'],
      tiers.map(row => [row.platform + ' · ' + count(row.purchaseK) + 'K',count(row.observations),
        usd(row.minUsd),usd(row.medianUsd),usd(row.maxUsd)]),
      '所选区间没有可核实的主站读回价观测。'));
    host.append(details('查看期内主站读回价',panel));
  }

  function renderMarket(orderData, adminDimensions) {
    const nativeCountries = list(adminDimensions?.countries);
    const nativePayments = list(adminDimensions?.payments);
    const countries = nativeCountries.length ?
      nativeCountries.map(row => ({country:row.code, label:row.code ? countryName(row.code) : row.name || '未知', orders:row.orders, salesUsd:row.revenueUsd})) :
      rowsFor(orderData, 'countries').map(row => ({...row, label:countryName(row.country)}));
    const payments = nativePayments.length ?
      nativePayments.map(row => ({label:row.name || '未知', orders:row.orders, salesUsd:row.revenueUsd})) :
      rowsFor(orderData, 'payments').map(row => ({...row, label:row.payment || row.method || row.label || '未知'}));
    const container = byId('world');
    container.replaceChildren();
    const regions = new Map(countries.filter(item => typeof item.country === 'string' && Object.hasOwn(geometry.paths || {}, item.country.toUpperCase()))
      .map(item => [item.country.toUpperCase(), item]));
    if (regions.size) {
      const hasSales = [...regions.values()].some(row => present(row.salesUsd));
      const metric = hasSales ? 'salesUsd' : 'orders';
      const label = hasSales ? '销售额' : '订单量';
      const map = svgElement('svg', {viewBox:'0 0 ' + geometry.w + ' ' + geometry.h, class:'map-frame', role:'img',
        'aria-label':'国家和地区订单地图，色阶表示' + label + '，圆点表示订单量。各国家的完整数值见下方列表。'});
      const maximum = Math.max(1, ...[...regions.values()].map(row => present(row[metric]) ? row[metric] : 0));
      const orderMax = Math.max(1, ...[...regions.values()].map(row => present(row.orders) ? row.orders : 0));
      const levels = [1,.5,.18,.06,.015,.004,0], intensities = [88,74,60,45,31,20,10];
      const mapColor = intensity => 'color-mix(in srgb,var(--fs-brand) ' + intensity + '%,var(--fs-surface-3))';
      const land = [];
      for (const [code, path] of Object.entries(geometry.paths)) {
        const row = regions.get(code);
        if (!row) { land.push(path); continue; }
        const intensity = present(row[metric]) ? intensities[levels.findIndex(level => Math.max(0,row[metric] / maximum) >= level)] : 0;
        const region = svgElement('path', {d:path, class:'map-region'});
        region.style.setProperty('--map-tone', mapColor(intensity));
        region.append(svgElement('title', {}, row.label + ' · ' + usd(row.salesUsd) + ' · ' + count(row.orders) + ' 单'));
        map.append(region);
      }
      map.prepend(svgElement('path', {d:land.join(''), class:'map-land'}));
      for (const [code, row] of [...regions].filter(([code, row]) => geometry.cent?.[code] && present(row.orders) && row.orders > 0)
        .sort((a,b) => b[1].orders - a[1].orders).slice(0,10)) {
        const [cx, cy] = geometry.cent[code];
        map.append(svgElement('circle', {cx, cy, r:4 + 15 * Math.sqrt(row.orders / orderMax), class:'map-dot'}));
      }
      const scale = element('span', null, 'map-ramp');
      scale.setAttribute('aria-hidden', 'true');
      for (const intensity of [...intensities].reverse()) {
        const swatch = element('i');
        swatch.style.setProperty('--map-tone', mapColor(intensity));
        scale.append(swatch);
      }
      const legend = element('div', null, 'map-legend');
      legend.append(element('span',label + ' 低'), scale, element('span','高'), element('span','圆点大小表示订单量'));
      if (!hasSales) legend.append(element('span','地区销售额未取得'));
      container.append(map, legend);
    } else if (!countries.length) {
      container.append(empty('所选区间未取得国家或地区数据。'));
    } else {
      container.append(element('p', '国家编码尚未与地图对应，以下显示已取得的数据。', 'card-sub'));
    }
    if (countries.length) {
      const ordered = [...countries].sort((a,b) => ((b.salesUsd ?? -Infinity) - (a.salesUsd ?? -Infinity)) || ((b.orders ?? 0) - (a.orders ?? 0)));
      container.append(dataTable('国家及地区销售额与订单', ['国家 / 地区','销售额 USD','订单数'],
        ordered.map(row => [row.label, usd(row.salesUsd), count(row.orders)])));
    }
    const bySales = payments.some(row => present(row.salesUsd));
    ranking('payments', payments, bySales ? {} : {valueKey:'orders', note:'按订单数排序 · 销售额未取得'});
    coverage('market-coverage', [
      ...(nativeCountries.length ? ['国家 / 地区 · Admin 已付款整单 · 按付款日'] : fieldCoverage(orderData, [['countries','国家 / 地区']])),
      ...(nativePayments.length ? ['支付方式 · Admin 已付款整单 · 按付款日'] : fieldCoverage(orderData, [['payments','支付方式']])),
    ]);
  }

  const lifecycleKey = row => {
    const marker = String(row.lifecycle || row.customerType || '').toLowerCase();
    if (['new','new_customer','newcustomer','新客','新客户'].includes(marker)) return 'new';
    if (['returning','returning_customer','repeat','existing','old','老客','复购','复购客户'].includes(marker)) return 'returning';
    return 'unknown';
  };

  function renderSpendBands(orderData, fallbackTotals) {
    const rows = rowsFor(orderData, 'spendBands');
    const names = [...new Set(rows.map(row => row.band).filter(band => band && band !== 'unknown'))];
    const select = byId('spend-band');
    const chosen = names.includes(select.value) ? select.value : '';
    const format = spendMode === 'customers' ? count : usd;
    const groups = new Map(names.map(band => [band, {label:band}]));
    for (const row of rows) {
      const type = lifecycleKey(row), bucket = groups.get(row.band);
      if (bucket && type !== 'unknown' && present(row[spendMode])) bucket[type] = row[spendMode];
    }
    for (const button of byId('spend-mode').querySelectorAll('button')) {
      button.setAttribute('aria-pressed', String(button.dataset.mode === spendMode));
    }
    const label = spendMode === 'customers' ? '人数' : '消费额';
    const dimension = spendMode === 'customers' ? {} : {unit:'$'};
    metricChart('customer-bands', [...groups.values()], [
      spec('new','新客' + label,format,'--fs-brand',{bar:true,...dimension}),
      spec('returning','复购客户' + label,format,'--fs-info',{bar:true,...dimension}),
    ], {stacked:true, showShares:true, bucket:'消费区间', empty:'所选区间未取得可按买家累计消费分层的数据。'});
    select.replaceChildren(new Option('全部消费区间',''), ...names.map(band => new Option(band + ' USD',band)));
    select.value = chosen;
    select.disabled = !names.length;
    const slice = chosen ? rows.filter(row => row.band === chosen) : rows.length ? rows : fallbackTotals;
    const breakdown = ['new','returning'].map(type => {
      const matching = slice.filter(row => lifecycleKey(row) === type && present(row[spendMode]));
      return {label:lifecycleNames[type], amount:matching.length ? matching.reduce((sum,row) => sum + row[spendMode],0) : null,
        color:type === 'new' ? '--fs-brand' : '--fs-info'};
    });
    donut('customer-share', breakdown, 'amount', format, label);
    if (breakdown.some(row => present(row.amount))) {
      byId('customer-share').append(element('p','按有新老客标记的' + label + '计算占比。','card-sub'));
    }
  }

  function renderCustomers(orderData, dates) {
    const totals = rowsFor(orderData, 'customerLifecycle');
    const trend = rowsFor(orderData, 'lifecycleDaily');
    renderSpendBands(orderData, totals);
    const bucket = new Map(dates.map(date => [date, {date}]));
    for (const row of trend) {
      const group = lifecycleKey(row);
      if (group !== 'unknown' && bucket.has(row.date) && present(row.salesUsd)) bucket.get(row.date)[group] = row.salesUsd;
    }
    metricChart('customer-trend', [...bucket.values()], [
      spec('new','新客消费',usd,'--fs-brand',{bar:true,unit:'$'}),
      spec('returning','复购客户消费',usd,'--fs-info',{bar:true,unit:'$'}),
    ], {stacked:true, empty:'所选区间未取得逐日的新客及复购客户消费。'});
    const amounts = new Map();
    for (const row of rowsFor(orderData, 'orderAmountBands')) {
      if (!row.band) continue;
      const values = amounts.get(row.band) || {};
      for (const measure of ['orders','salesUsd']) {
        if (present(row[measure])) values[measure] = (values[measure] || 0) + row[measure];
      }
      amounts.set(row.band,values);
    }
    mount('order-bands', dataTable('单笔订单金额分布', ['单笔金额 USD','订单数','销售额 USD'], [...amounts].map(([band,row]) =>
      [band === 'unknown' ? '金额未取得' : band, count(row.orders), usd(row.salesUsd)])));
    const unmarked = totals.find(row => lifecycleKey(row) === 'unknown');
    coverage('customer-coverage', [
      ...fieldCoverage(orderData, [['customerLifecycle','客户标记']]),
      unmarked && '未标记 ' + count(unmarked.orders) + ' 单 · ' + usd(unmarked.salesUsd) + '。消费占比按有标记订单的消费额计算。',
      '期内新客人数、订单新客标记和复购客户消费使用各自来源及分母。',
    ]);
  }

  const fractionalPct = x => present(x) ? pct(x * 100) : '—';
  const adsSpecs = [['cost','花费',usd],['value','平台转化价值',usd],['roas','ROAS',ratio],
    ['impressions','曝光'],['clicks','点击'],['conversions','转化数'],['cpc','CPC',usd],['cpa','CPA',usd]];
  const organicSpecs = [['sessions','会话'],['purchases','购买事件'],['purchase_rate','购买率',fractionalPct],['new_users','新用户']];
  const searchSpecs = [['clicks','点击'],['impressions','展示'],['ctr','点击率',fractionalPct],['position','平均排名']];

  function scopeText(channel) {
    return [statuses[channel?.status], channel?.scope].filter(item => typeof item === 'string' && item).join(' · ');
  }

  function trafficScope(channel, side) {
    const dates = channel?.coverage?.[side];
    const covered = dates?.compared_days || dates?.days;
    return list(covered).length ? (side === 'current' ? '本期 ' : '对照期 ') +
      rangeLabel({start:covered[0],end:covered[covered.length - 1]}) + '（' + covered.length + ' 天）' : null;
  }

  function trafficTable(id, heading, rows, specs, name = '名称', formatLabel = x => x) {
    const sortField = specs[0][0];
    const sorted = [...list(rows)].sort((a, b) => (b.current?.[sortField] ?? -Infinity) - (a.current?.[sortField] ?? -Infinity));
    const rowsWithValues = sorted.filter(row => row?.current || row?.previous);
    if (!rowsWithValues.length) { mount(id, empty()); return; }
    const used = rowsWithValues.map(row => [formatLabel(row.label || row.key),
      ...specs.map(([key, , format = count]) => format(row.current?.[key]) +
        (present(row.previous?.[key]) ? ' / ' + format(row.previous[key]) : ''))]);
    const hasComparison = rowsWithValues.some(row => specs.some(([key]) => present(row.previous?.[key])));
    const header = element('p', heading + (hasComparison ? ' · 本期 / 对照期' : ''), 'card-sub');
    const table = dataTable(heading, [name, ...specs.map(([, title]) => title)], used);
    byId(id).replaceChildren(header, table);
  }

  function renderTraffic(traffic) {
    const paid = traffic?.paid, organic = traffic?.organic, search = traffic?.search;
    byId('ads-scope').textContent = scopeText(paid);
    byId('organic-scope').textContent = 'MMOEXP 主站 · 独立流量来源';
    cards('ads-kpis', adsSpecs, paid?.current, paid?.previous);
    for (const [id, label, rows, format] of [['campaigns','广告系列',paid?.campaigns],
      ['ads-countries','投放国家 / 地区',paid?.countries,countryName]]) {
      trafficTable(id, label, rows, adsSpecs.slice(0,3), label, format);
    }
    coverage('ads-coverage', [
      paid && {label:'Google Ads', status:paid.status, reason:[paid.source, trafficScope(paid,'current'), trafficScope(paid,'previous')].filter(Boolean).join(' · ')},
      ...list(traffic?.limitations),
    ]);
    for (const [id, channel, specs] of [['organic-kpis',organic,organicSpecs],['search-kpis',search,searchSpecs]]) {
      const host = byId(id);
      host.className = 'kpi-grid';
      cards(id, specs, channel?.current, channel?.previous, {mini:true});
      if (channel?.status !== 'complete') {
        host.before(element('p', [scopeText(channel), trafficScope(channel,'current'), trafficScope(channel,'previous')].filter(Boolean).join(' · ') || '所选区间未取得此流量来源。', 'coverage traffic-status'));
      }
    }
    trafficTable('organic-countries','国家 / 地区',organic?.countries,organicSpecs.slice(0,3),'国家 / 地区',countryName);
    trafficTable('organic-pages','落地页',organic?.landing_pages,organicSpecs.slice(0,3),'页面');
    trafficTable('search-pages','Google 自然搜索落地页',search?.landing_pages,searchSpecs.slice(0,3),'页面');
    coverage('organic-coverage', [
      organic && {label:'GA4',status:organic.status,reason:[organic.source,organic.scope,trafficScope(organic,'current'),trafficScope(organic,'previous')].filter(Boolean).join(' · ')},
      search && {label:'Search Console',status:search.status,reason:[search.source,search.scope,trafficScope(search,'current'),trafficScope(search,'previous')].filter(Boolean).join(' · ')},
    ]);
  }

  function trafficFor(packet, query) {
    if (packet?.traffic) return packet.traffic;
    const related = [...periods.values()].find(item =>
      item.game === query.game && item.scope === query.scope &&
      item.traffic?.periods?.previous?.start === query.start && item.traffic.periods.previous.end === query.end)?.traffic;
    if (!related) return;
    const result = {limitations:related.limitations};
    for (const key of ['paid','organic','search']) {
      const channel = related[key];
      if (!channel) continue;
      const derived = {
        ...channel, current:channel.previous, previous:null,
        status:channel.previous ? channel.status : 'unavailable',
        coverage:{current:channel.coverage?.previous},
      };
      for (const field of ['campaigns','countries','landing_pages']) {
        derived[field] = list(channel[field]).filter(row => row.previous)
          .map(row => ({...row,current:row.previous,previous:null}));
      }
      result[key] = derived;
    }
    return result;
  }

  function deliveryBand(row) {
    if (row.quantityBand === 'under1000') return 'under1000';
    if (row.quantityBand === 'atLeast1000') return 'atLeast1000';
    return null;
  }

  function renderDelivery(orderData, dates) {
    const delivery = orderData?.delivery;
    const rows = Array.isArray(delivery) ? delivery : rowsFor(delivery,'rows');
    const scoped = byId('delivery-scope');
    const sample = delivery?.coverage?.sampled !== false && delivery?.status === 'partial';
    scoped.hidden = !rows.length || !sample;
    scoped.textContent = sample ? '以下为已核订单样本的数量与时长，用于比较顺利组与问题组的耗时。总体问题比例待完整覆盖。' : '';
    const labels = {smooth:'顺利', problem:'问题', unknown:'状态未知'};
    for (const [band, id] of [['under1000','delivery-small'],['atLeast1000','delivery-large']]) {
      const items = rows.filter(row => deliveryBand(row) === band && (!row.game || row.game === selected.game));
      const trendId = id + '-trend';
      const byDate = new Map(dates.map(date => [date,{date}]));
      for (const row of rowsFor(delivery,'daily')) {
        const record = byDate.get(row.date), kind = row.deliveryStatus;
        if (!record || row.quantityBand !== band || !['smooth','problem'].includes(kind) ||
            !present(row.meanMinutes) || !present(row.timedOrders) || row.timedOrders <= 0) continue;
        const known = record[kind + 'Timed'] || 0, total = known + row.timedOrders;
        record[kind] = ((record[kind] || 0) * known + row.meanMinutes * row.timedOrders) / total;
        record[kind + 'Timed'] = total;
      }
      metricChart(trendId,[...byDate.values()],[
        spec('smooth','顺利组平均耗时',minutes,'--fs-brand'),
        spec('problem','问题组平均耗时',minutes,'--fs-danger'),
      ], {showSamples:true, title:'按提单日比较样本完成耗时', subtitle:'按首次入队日志提单日 · 平均耗时（分钟）',
        empty:'所选区间未取得可核实的逐日完成耗时。'});
      if (!items.length) {
        mount(id, empty(delivery?.reason || '所选区间未取得数量和问题状态可对应的 Coins 发货订单。'));
        byId(trendId).replaceChildren();
        continue;
      }
      const host = byId(id);
      const amounts = Object.keys(labels).map(status => {
        const values = items.filter(row => row.deliveryStatus === status && present(row.orders));
        return values.length ? values.reduce((sum,row) => sum + row.orders, 0) : null;
      });
      const positiveTotal = amounts.filter(present).reduce((sum,val) => sum + Math.max(0,val), 0);
      const track = element('div',null,'stack-track');
      track.setAttribute('aria-hidden','true');
      const legend = element('div',null,'chart-caption');
      for (const [i, status] of Object.keys(labels).entries()) {
        if (!present(amounts[i])) continue;
        const color = ['--fs-brand','--fs-danger','--fs-muted'][i];
        if (positiveTotal > 0) {
          const fill = element('span');
          fill.style.width = Math.max(0, amounts[i]) / positiveTotal * 100 + '%';
          fill.style.setProperty('--series-color','var(' + color + ')');
          track.append(fill);
        }
        legend.append(coloredLabel(labels[status] + ' ' + count(amounts[i]) + ' 单', color));
      }
      const data = dataTable('发货质量', ['平台','状态',sample ? '样本订单数' : '订单数','已核时长','平均耗时','中位耗时','P90','问题至完成均值','问题至完成中位数','问题计时笔数'],
        items.map(row => [row.platform || '汇总',labels[row.deliveryStatus] || row.deliveryStatus || '状态未知',count(row.orders),
          count(row.timedOrders),minutes(row.meanMinutes),minutes(row.medianMinutes),minutes(row.p90Minutes),
          minutes(row.problemToCompleteMinutes?.meanMinutes),minutes(row.problemToCompleteMinutes?.medianMinutes),
          count(row.problemToCompleteMinutes?.orders)]));
      host.replaceChildren();
      if (delivery.status === 'partial') host.append(element('p','部分覆盖 · 时长只统计已观测发货订单。','card-sub'));
      host.append(legend, track, data);
    }
    coverage('delivery-coverage', [
      delivery && {label:'Coins 数量及状态', status:delivery.status, reason:delivery.reason || delivery.source},
      ...fieldCoverage(orderData, [['delivery','数量与状态'],['fulfillment','发货统计']]),
      '范围为 MMOEXP 主站 Order Coins。按购买数量划分为 1000K 以下与 1000K 及以上。状态未知及耗时未取得在表中留示。',
    ]);
    const completion = delivery?.completion;
    const holder = byId('delivery-completion');
    holder.hidden = !completion;
    if (!completion) return;
    const bandName = {under1000:'< 1000K', atLeast1000:'≥ 1000K', unknown:'数量未知'};
    const data = rowsFor(completion,'rows');
    const totals = completion.totals || {};
    const timestamp = typeof completion.asOf === 'string' && present(Date.parse(completion.asOf)) ?
      new Date(completion.asOf).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) + ' 北京时间' : null;
    const summary = [statuses[completion.status], timestamp,
      present(totals.completionRate) ? '全队列完成率 ' + fractionalPct(totals.completionRate) : '全队列完成率未取得',
      present(totals.orders) ? count(totals.completed) + ' / ' + count(totals.orders) + ' 单完成' : null,
    ].filter(Boolean).join(' · ');
    const cohort = dataTable('全付款队列完成率', ['平台','购买量','问题标记','已付款','已完成','未完结','已取消','完成率'],
      data.map(row => [row.platform || '未知',bandName[row.quantityBand] || '数量未知',labels[row.deliveryStatus] || '状态未知',
        count(row.orders),count(row.completed),count(row.open),count(row.canceled),fractionalPct(row.completionRate)]));
    const panel = byId('delivery-cohort');
    panel.replaceChildren(element('p',summary,'card-sub'),cohort);
    if (completion.reason) panel.append(element('p',completion.reason,'coverage'));
  }

  function sources(packet) {
    const root = byId('source-list');
    root.replaceChildren();
    const valid = [];
    const sourceList = value => Array.isArray(value) ? value : Object.values(value || {});
    for (const item of [...sourceList(initial.sources), ...sourceList(packet?.sources), ...sourceList(packet?.ordersData?.sources)]) {
      if (typeof item === 'string' && item) valid.push(item);
      else if (item && typeof item === 'object') {
        const line = [item.label || item.source || item.name, item.version, item.basis || item.description, item.date]
          .filter(value => typeof value === 'string' && value).join(' · ');
        if (line) valid.push(line);
      }
    }
    if (valid.length) {
      const ul = element('ul');
      for (const entry of new Set(valid)) ul.append(element('li',entry));
      root.append(ul);
    }
    const gaps = list(packet?.ordersData?.gaps).filter(item => typeof item === 'string');
    if (gaps.length) {
      const ul = element('ul');
      for (const entry of new Set(gaps)) ul.append(element('li',entry));
      root.append(ul);
    }
    const published = packet?.generatedAt || initial.generatedAt;
    root.append(element('p','数据截至 ' + asOf + '（北京时间完整日）' + (published ? ' · 打包时间 ' + published : '') + '。— 表示此数据未取得。'));
  }

  function render() {
    for (const [observer] of resizeObservers) observer.disconnect();
    resizeObservers.length = 0;
    const packet = periods.get(key(selected));
    selectedPrevious = previousFor(selected);
    const prior = periods.get(key(selectedPrevious));
    const dates = allDays(selected.start, selected.end);
    const orderData = packet?.ordersData;
    const traffic = trafficFor(packet, selected);
    byId('current-range').textContent = [selected.game, scopeLabel(selected.scope), rangeLabel(selected)].join(' · ');
    byId('compare-range').textContent = '对照期 ' + rangeLabel(selectedPrevious) + (prior ? '' : ' · 汇总未取得');
    loadedSelect.value = packet ? key(packet) : '';
    setMissing(selected, packet);
    renderOverview(packet, prior, dates);
    renderCategory(orderData, dates);
    renderPrices(packet?.prices);
    renderMarket(orderData, packet?.adminDimensions);
    renderCustomers(orderData, dates);
    document.querySelectorAll('.traffic-status').forEach(node => node.remove());
    renderTraffic(traffic);
    renderDelivery(orderData, dates);
    sources(packet);
  }

  function setForm(query) {
    byId('game').value = query.game;
    byId('scope').value = query.scope || 'all';
    byId('grain-' + query.grain).checked = true;
    byId('start').value = query.start;
    byId('end').value = query.end;
    syncFields();
  }

  const filters = byId('filters');
  filters.addEventListener('change', event => {
    if (event.target.id === 'game' || event.target.name === 'grain') syncFields();
  });
  filters.addEventListener('input', event => {
    if (event.target.type === 'date') {
      byId('end').setCustomValidity('');
      byId('end').removeAttribute('aria-invalid');
    }
  });
  filters.addEventListener('submit', event => {
    event.preventDefault();
    const fields = new FormData(filters);
    const grain = fields.get('grain');
    const start = fields.get('start'), end = fields.get('end');
    if (grain === 'custom' && start > end) {
      byId('end').setCustomValidity('结束日应为开始日或更晚。');
      byId('end').setAttribute('aria-invalid','true');
      byId('end').reportValidity();
      return;
    }
    const query = rangeFor(fields.get('game'), fields.get('scope'), grain, start, end);
    if (validPeriod(query)) selectRange(query);
  });

  byId('theme').value = window.FSTheme?.get() || 'light';
  byId('import-data').hidden = !!initial.packetUrl;
  byId('theme').addEventListener('change', event => window.FSTheme?.set(event.target.value));
  document.addEventListener('fs-theme-change', () => resizeObservers.forEach(([, draw]) => draw()));
  byId('category-mode').addEventListener('click', event => {
    const button = event.target.closest('button[data-mode]');
    if (button && button.dataset.mode !== categoryMode) {
      categoryMode = button.dataset.mode;
      renderCategory(periods.get(key(selected))?.ordersData, allDays(selected.start, selected.end));
    }
  });
  byId('spend-mode').addEventListener('click', event => {
    const button = event.target.closest('button[data-mode]');
    if (button && button.dataset.mode !== spendMode) {
      spendMode = button.dataset.mode;
      const order = periods.get(key(selected))?.ordersData;
      renderSpendBands(order, rowsFor(order, 'customerLifecycle'));
    }
  });
  byId('spend-band').addEventListener('change', () => {
    const order = periods.get(key(selected))?.ordersData;
    renderSpendBands(order, rowsFor(order, 'customerLifecycle'));
  });
  byId('import-data').addEventListener('click', () => byId('data-file').click());
  byId('data-file').addEventListener('change', async event => {
    const input = event.target, file = input.files[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const imported = updatePackets(data);
      if (!imported) throw Error('数据包内没有可用的 FC26 或 FC27 日期区间。');
      showStatus('已载入 ' + imported + ' 个日期区间。');
      await selectRange(selected, false);
    } catch (error) {
      showStatus('载入失败。' + (error instanceof SyntaxError ? '请选择有效的看板 JSON 数据包。' : error.message));
    } finally {
      input.value = '';
    }
  });
  loadedSelect.addEventListener('change', event => {
    const packet = periods.get(event.target.value);
    if (!packet) return;
    const query = {...packet, grain:packet.start === packet.end ? 'day' : 'custom'};
    setForm(query);
    selectRange(query, false);
  });
  function activeNav() {
    const hash = location.hash || '#overview';
    for (const link of document.querySelectorAll('.section-nav a')) {
      if (link.hash === hash) link.setAttribute('aria-current','location');
      else link.removeAttribute('aria-current');
    }
  }
  window.addEventListener('hashchange', activeNav);
  window.addEventListener('pagehide', () => activeRequest?.abort());
  window.addEventListener('pageshow', event => { if (event.persisted && !periods.has(key(selected))) selectRange(selected); });
  activeNav();
  updatePackets(initial);
  const latest = rangeFor('FC27', 'all', 'week', asOf);
  const configured = initial.defaultPeriod;
  const query = validPeriod(configured) ?
    {...configured, scope:configured.scope || 'all', grain:configured.grain || (key(configured) === key(latest) ? 'week' : 'custom')} : latest;
  setForm(query);
  selectRange(query);
});
