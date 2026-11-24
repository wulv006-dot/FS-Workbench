(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const content = get('phase-content');
  if (!content) return;
  const manual = Boolean(get('phase-manual'));
  const status = get('phase-status');
  const more = get('phase-more');
  const API = '/dashboard/fs-home/advisor.json';
  const busy = new Set();
  const labels = {
    ultra: '超高', high: '高', recent: '近期', silent: '沉默', lost: '流失', long_lost: '长期流失',
    new: '新客', old: '老客', unverified: '待核', reviewing: '待复核', held: '暂缓',
    ready: '待发区', confirmed: '已确认', auto_confirmed: '超时自动确认', expired: '已过期',
    removed: '已剔除', void: '已作废', deferred: '顺延', recheck_failed: '重验未过',
    dispatching: '派发中', issued: '已发放', limited: '限额', rejected: '已拒绝',
    unknown: 'UNKNOWN', pending_register: '待注册', manually_closed: '已人工结清',
    payments: '已有新付款', exceptions: '售后、退款或问题单', automatic: '30 天内已有自动券',
    manual_coupons: '30 天内已有人工券', contacts: '已联系',
    tier_changed: '当前价值档不符', customer_type_changed: '当前新老客条件不符', stage_changed: '当前阶段不符',
    recipient_changed: '收件邮箱变化', rule_changed: '规则已变更', template_changed: '券模板已变更或过期',
    event_invalid: '原末购已失效', pending_identity: '身份待核',
    email_conflict: '邮箱与其他客户冲突', case_binding_pending: '案件归属待确认',
    customer_quota: '客户 30 天内已占用额度', daily_quota: '当日规则额度已满',
    owner_conflict: '当前负责人已变化'
  };
  const label = value => labels[value] || value || '—';
  let offset = 0;
  let next = null;
  let windowDays = 30;
  let sequence = 0;
  let pending = false;
  const view = () => manual ? 'manual' : get('phase-view').value;
  const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  function button(text, on, className = 'fs-btn') {
    const item = node('button', text, className);
    item.type = 'button';
    item.addEventListener('click', on);
    return item;
  }
  function requestId() {
    return crypto.randomUUID().replace(/-/g, '');
  }
  async function read(name, fields = {}) {
    const args = new URLSearchParams({mode: 'hermes', structure: 'customer_tracking', view: 'phase_' + name, ...fields});
    return fetchJson(API + '?' + args);
  }
  async function fetchJson(url, options = {}) {
    const answer = await fetch(url, {cache: 'no-store', redirect: 'error', credentials: 'same-origin',
      signal: AbortSignal.timeout(35000), ...options});
    const data = await answer.json();
    if (!answer.ok) throw Error(data.error || 'maintenance_request_failed');
    return data;
  }
  async function write(control, action, fields, after = load) {
    if (busy.size) return;
    busy.add(control);
    control.disabled = true;
    try {
      status.textContent = '正在保存…';
      await fetchJson(API, {method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-FS-Advisor-Action': 'submit'},
        body: JSON.stringify({kind: 'hermes_customer_tracking', action: 'phase_' + action, ...fields})});
      status.textContent = '已保存';
      await after();
    } catch (error) {
      status.textContent = '保存结果待核，请刷新核对当前状态。' + (error.message ? ' ' + error.message : '');
    } finally {
      busy.delete(control);
      control.disabled = false;
    }
  }
  function table(headings, rows) {
    if (!rows.length) return node('p', '暂无条目', 'hint');
    const wrapper = node('div', undefined, 'phase-table');
    const grid = node('table');
    const thead = node('thead');
    const header = node('tr');
    for (const title of headings) {
      const th = node('th', title);
      th.scope = 'col';
      header.append(th);
    }
    thead.append(header);
    const body = node('tbody');
    for (const row of rows) {
      const tr = node('tr');
      for (const value of row) {
        const td = node('td');
        td.append(value instanceof Node ? value : String(value ?? '—'));
        tr.append(td);
      }
      body.append(tr);
    }
    grid.append(thead, body);
    wrapper.append(grid);
    return wrapper;
  }
  function control(form, title, name, kind, val, options = []) {
    const label = node('label', title);
    const input = node(options.length ? 'select' : 'input');
    if (options.length) {
      for (const [value, text] of options) input.add(new Option(text, value));
    } else input.type = kind;
    input.name = name;
    if (kind === 'checkbox') input.checked = val;
    else input.value = val ?? '';
    label.append(input);
    form.append(label);
    return input;
  }
  function formRun(form, submitText, handler) {
    const submit = node('button', submitText, 'fs-btn fs-btn--primary');
    submit.type = 'submit';
    form.append(submit);
    form.addEventListener('submit', event => {
      event.preventDefault();
      handler(submit);
    });
  }
  function pageGroups(data) {
    const snapshot = data.last_run;
    status.textContent = data.status === 'waiting'
      ? '等待 ' + data.waiting_for + ' 日数据' + (snapshot ? '，当前显示 ' + snapshot.day : '')
      : '观察日 ' + snapshot.day + ' · 配置 v' + snapshot.config_version;
    const groups = data.groups.map(row =>
      [label(row.tier), label(row.stage), label(row.customer_type), row.count]);
    const list = data.items.map(row => {
      const open = button(row.email || row.customer_id, () => customer(row.customer_id));
      return [open, label(row.override_tier || row.tier), label(row.stage), label(row.customer_type),
        '$' + row.amount_usd + (row.unknown_amount_orders ? ' · ' + row.unknown_amount_orders + ' 笔金额未知' : ''),
        row.case_status === 'pending_identity' ? '身份待核' : row.owner || '未分配',
        row.alert ? node('span', '待跟进', 'phase-alert') : '—'];
    });
    content.replaceChildren(table(['价值档', '阶段', '新老客', '人数'], groups),
      table(['客户', '名单档位', '阶段', '新老客', '有效消费', '负责人', '提醒'], list),
      node('div', undefined, 'phase-detail'));
  }
  async function customer(id) {
    const target = content.querySelector('.phase-detail');
    try {
      const data = await read('customer', {id});
      const row = data.customer;
      target.replaceChildren(node('h3', row.email || row.customer_id),
        table(['事件时间', '阶段', '配置', '状态'], data.timeline.map(e =>
          [e.at, label(e.stage), 'v' + e.config_version, e.status])),
        table(['记录时间', '操作人', '跟进记录'], data.contacts.map(e =>
          [e.at, e.actor, e.notes || e.reason || label(e.event)])));
      const c = data.case;
      if (c?.case_id) {
        const form = node('form', undefined, 'phase-form');
        const owner = control(form, '负责人账号', 'owner', 'text', c.owner);
        owner.maxLength = 64;
        formRun(form, '改派', submit => write(submit, 'owner',
          {request_id: requestId(), customer_id: id, expected: c.owner, value: owner.value.trim() || null},
          () => customer(id)));
        target.append(form);
        const follow = node('form', undefined, 'phase-form');
        const notes = control(follow, '跟进备注', 'notes', 'text', '');
        notes.required = true;
        notes.maxLength = 1000;
        const touched = control(follow, '已联系客户', 'contacted', 'checkbox', false);
        formRun(follow, '保存跟进', submit => write(submit, 'feedback', {
          request_id: requestId(), customer_id: id, case_id: c.case_id, notes: notes.value,
          event: touched.checked ? 'contacted' : 'feedback',
          ...(touched.checked ? {contacted_at: new Date().toISOString()} : {})
        }, () => customer(id)));
        target.append(follow, button('领取给我', event => write(event.currentTarget, 'feedback', {
          request_id: requestId(), customer_id: id, case_id: c.case_id, event: 'claim'
        }, () => customer(id))));
      } else if (row.email_conflict) {
        target.append(node('p', '多个客户记录共用同一邮箱，身份待核。', 'phase-alert'));
      } else if (c?.status === 'pending_identity') {
        target.append(node('p', '案件归属待核，联系证据缺失。', 'phase-alert'));
        const form = node('form', undefined, 'phase-form');
        const choices = data.matching_cases.length ? data.matching_cases.map(value => [value, value]) : [['', '为已核邮箱新建案件']];
        const selection = control(form, '按已核邮箱选择案件', 'case', 'text', choices[0][0], choices);
        formRun(form, '确认案件归属', submit => write(submit, 'case', {
          request_id: requestId(), customer_id: id, case_id: selection.value || null
        }, () => customer(id)));
        target.append(form);
      }
      const tier = node('form', undefined, 'phase-form');
      const value = control(tier, '名单展示档位', 'tier', 'text', data.display_tier || '',
        [['', '使用系统档位'], ['high', '高'], ['ultra', '超高']]);
      formRun(tier, '保存展示档位', submit => write(submit, 'tier', {
        request_id: requestId(), customer_id: id, expected: data.display_tier, value: value.value || null
      }, () => customer(id)));
      target.append(tier);
      target.scrollIntoView({block: 'nearest'});
    } catch (error) {
      status.textContent = '客户详情读取失败。' + error.message;
    }
  }
  function pageQueue(data) {
    const current = view();
    const controls = node('div', undefined, 'phase-actions');
    if (current === 'ready' && data.items.length) controls.append(button('确认待发区全部条目', event => {
      if (window.confirm('确认待发区全部条目，包括本页之外的条目？后台派发前还会重验。')) {
        write(event.currentTarget, 'decide', {ids: 'all', decision: 'confirmed'});
      }
    }, 'fs-btn fs-btn--primary'));
    const rows = data.items.map(row => {
      const evidence = node('div');
      if (row.review?.manual_coupon_notice) evidence.append(node('div', row.review.manual_coupon_notice));
      const reasons = (row.review?.reasons || []).map(label);
      if (row.result?.reason) reasons.push(label(row.result.reason));
      if (reasons.length) evidence.append(node('div', reasons.join('、')));
      const actions = node('div', undefined, 'phase-actions');
      if (current === 'ready') actions.append(button('剔除', event => {
        if (window.confirm('剔除这一条发券记录？')) {
          write(event.currentTarget, 'decide', {ids: [row.id], decision: 'removed'});
        }
      }), button('确认', event => write(event.currentTarget, 'decide', {ids: [row.id], decision: 'confirmed'})));
      if (current === 'manual') {
        const form = node('form', undefined, 'phase-form');
        const nextState = control(form, 'Admin 核对结果', 'state', 'text', 'issued',
          [['issued', '已发放'], ['rejected', '已拒绝'], ['manually_closed', '已人工结清']]);
        const proof = control(form, '核对依据', 'evidence', 'text', '');
        proof.required = true;
        proof.maxLength = 300;
        formRun(form, '登记结果', submit => write(submit, 'result',
          {id: row.id, batch: row.batch, state: nextState.value, evidence: proof.value}));
        actions.append(form);
      }
      let state = label(row.state);
      if (row.identity_status === 'pending_identity') {
        state += ' · ' + label(row.identity_status);
        if (row.identity_reason) state += '：' + label(row.identity_reason);
      }
      return [row.email, row.rule_id, state, row.batch || '—', evidence, actions];
    });
    content.replaceChildren(controls, table(['收件邮箱', '规则', '状态', '原批次', '复核依据', '操作'], rows));
  }
  function ruleForm(rule = {}) {
    const form = node('form', undefined, 'phase-form');
    const ident = control(form, '规则 ID', 'id', 'text', rule.id || '');
    ident.required = true;
    ident.readOnly = Boolean(rule.id);
    ident.maxLength = 128;
    const tier = control(form, '价值档', 'tier', 'text', rule.tier || 'high',
      [['high', '高'], ['ultra', '超高']]);
    const stage = control(form, '阶段', 'stage', 'text', rule.stage || 'silent',
      [['silent', '沉默'], ['lost', '流失'], ['long_lost', '长期流失']]);
    const type = control(form, '新老客条件', 'type', 'text', rule.customer_type || '',
      [['', '不限'], ['new', '新客'], ['old', '老客']]);
    const priority = control(form, '优先级', 'priority', 'number', rule.priority ?? 100);
    const quota = control(form, '每日额度', 'daily_quota', 'number', rule.daily_quota ?? 1);
    const coupon = control(form, '定向券 ID', 'coupon_id', 'number', rule.coupon_id || '');
    const owner = control(form, '规则分配账号', 'owner', 'text', rule.owner || '');
    const alert = control(form, '待跟进预警', 'alert', 'checkbox', rule.alert || false);
    const enabled = control(form, '启用规则', 'enabled', 'checkbox', rule.enabled || false);
    priority.min = '0';
    quota.min = '1';
    coupon.min = '1';
    owner.maxLength = 64;
    formRun(form, '保存规则', submit => write(submit, 'rule', {
      id: ident.value.trim(), expected_version: rule.version ?? 0, tier: tier.value, stage: stage.value,
      customer_type: type.value || null, priority: Number(priority.value), daily_quota: Number(quota.value),
      coupon_id: coupon.value ? Number(coupon.value) : null, owner: owner.value.trim() || null,
      alert: alert.checked, enabled: enabled.checked
    }));
    return form;
  }
  function pageRules(data) {
    status.textContent = data.dispatch_enabled ? '派发器运行已启用' : '派发器尚未启用';
    const list = data.items.map(rule => {
      const card = node('details', undefined, 'phase-detail');
      card.append(node('summary', rule.id + ' · ' + label(rule.tier) + '/' + label(rule.stage)
        + (rule.enabled ? ' · 启用' : ' · 停用')), ruleForm(rule));
      const auto = button(rule.auto_enabled ? '关闭 72 小时自动确认' : '开启 72 小时自动确认', event => {
        if (rule.auto_enabled || window.confirm('开启后，到期时仍待发的条目将自动确认。确认开启？')) {
          write(event.currentTarget, 'auto', {id: rule.id, enabled: !rule.auto_enabled});
        }
      });
      card.append(auto);
      return card;
    });
    const create = node('details', undefined, 'phase-detail');
    create.append(node('summary', '新建维护规则'), ruleForm());
    content.replaceChildren(...list, create);
  }
  function pageConfig(data) {
    const form = node('form', undefined, 'phase-form');
    const ticks = ['沉默起始天数', '流失起始天数', '长期流失起始天数'].map((text, index) =>
      control(form, text, 'day' + index, 'number', data.stages[index]));
    const high = control(form, '高价值门槛（USD）', 'high', 'number', data.tiers.high);
    const ultra = control(form, '超高价值门槛（USD）', 'ultra', 'number', data.tiers.ultra);
    for (const item of [...ticks, high, ultra]) {
      item.required = true;
      item.min = '1';
    }
    high.step = ultra.step = '.01';
    formRun(form, '保存门槛', submit => write(submit, 'config', {
      expected_version: data.version, stages: ticks.map(x => Number(x.value)), high: high.value, ultra: ultra.value
    }));
    status.textContent = '配置 v' + data.version + '，下一次完整日更新时生效。';
    content.replaceChildren(form);
  }
  function pageEffect(data) {
    const form = node('div', undefined, 'phase-form');
    const days = control(form, '观察窗口', 'days', 'text', String(windowDays),
      [['7', '7 天'], ['30', '30 天'], ['60', '60 天']]);
    days.addEventListener('change', () => { windowDays = Number(days.value); load(); });
    const percent = n => n == null ? '待核' : (n * 100).toFixed(1) + '%';
    status.textContent = data.status === 'waiting' ? '等待读取规则效果' :
      (data.season || '') + ' · ' + (data.season_note || '') + (data.status === 'partial' ? ' · 用券记录暂不可用' : '');
    content.replaceChildren(form, table(['规则', '成熟触发条目', '触发回购率', '成熟发放条目', '发放回购率',
      '归属回购订单', '用券', '用券并付款', '基准回购率', 'UNKNOWN', '顺延'], data.items.map(row =>
      [row.rule_id, row.trigger_events, percent(row.trigger_rate), row.issued_events, percent(row.issued_rate),
        row.issued_orders, row.coupon_uses, row.coupon_paid_uses, percent(row.baseline?.rate), row.unknown, row.deferred])));
  }
  async function load() {
    const request = ++sequence;
    const current = view();
    const paged = ['groups', 'review', 'ready', 'manual', 'delivery'].includes(current);
    pending = true;
    more.disabled = true;
    more.hidden = true;
    status.textContent = '正在读取…';
    content.replaceChildren();
    try {
      const fields = paged ? {offset} : current === 'effect' ? {days: windowDays} : {};
      const data = await read(current, fields);
      if (request !== sequence) return;
      status.textContent = '';
      if (current === 'groups') pageGroups(data);
      else if (current === 'config') pageConfig(data);
      else if (current === 'rules') pageRules(data);
      else if (current === 'effect') pageEffect(data);
      else pageQueue(data);
      next = data.next_offset ?? null;
      more.hidden = next === null;
    } catch (error) {
      if (request === sequence) status.textContent = '读取失败。' + error.message;
    } finally {
      if (request === sequence) {
        pending = false;
        more.disabled = false;
      }
    }
  }
  get('phase-refresh').addEventListener('click', () => load());
  more.addEventListener('click', () => { if (!pending && next !== null) { offset = next; load(); } });
  if (manual) load();
  else {
    get('phase-view').addEventListener('change', () => { offset = 0; load(); });
    get('phase-scope').addEventListener('click', () => {
      get('vip-week-panel').hidden = true;
      get('phase-panel').hidden = false;
      get('app').classList.add('phase-current');
      for (const item of get('vip-scopes').querySelectorAll('button')) {
        item.setAttribute('aria-pressed', String(item === get('phase-scope')));
      }
      offset = 0;
      load();
    });
  }
})();