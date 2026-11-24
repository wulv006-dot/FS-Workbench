(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const content = get('phase-content');
  if (!content) return;
  const manual = Boolean(get('phase-manual'));
  const status = get('phase-status');
  const overview = get('phase-overview');
  const moneyFormat = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'});
  const numberFormat = new Intl.NumberFormat('zh-CN');
  const dateFormat = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    hourCycle: 'h23'
  });
  const amount = value => value == null || value === '' ? '—' : moneyFormat.format(Number(value));
  const count = value => value == null ? '—' : numberFormat.format(value);
  const tiers = ['ultra', 'high'];
  const stages = ['recent', 'silent', 'lost', 'long_lost', 'unverified'];
  const queueFilter = {tier: '', stage: ''};
  let readyTimer;
  let bulkPending = false;
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
    invalid_email: '收件邮箱无效', uid_case_conflict: '案件归属待核：UID 关联到另一未结案件',
    email_case_conflict: '案件归属待核：邮箱关联到另一未结案件',
    multiple_open_cases: '案件归属待核：同一邮箱存在多个未结案件',
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
  function post(action, fields) {
    return fetchJson(API, {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-FS-Advisor-Action': 'submit'},
      body: JSON.stringify({kind: 'hermes_customer_tracking', action: 'phase_' + action, ...fields})});
  }
  async function write(control, action, fields, after = load) {
    if (busy.size) return;
    busy.add(control);
    control.disabled = true;
    try {
      status.textContent = '正在保存…';
      await post(action, fields);
      status.textContent = '已保存';
      await after();
    } catch (error) {
      status.textContent = '保存结果待核，请刷新核对当前状态。' + (error.message ? ' ' + error.message : '');
    } finally {
      busy.delete(control);
      control.disabled = false;
    }
  }
  function table(headings, rows, name = headings.join('、'), rowHeaders = false) {
    if (!rows.length) return node('p', '暂无条目', 'hint');
    const wrapper = node('div', undefined, 'phase-table');
    wrapper.tabIndex = 0;
    wrapper.setAttribute('role', 'region');
    wrapper.setAttribute('aria-label', name);
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
      for (const [index, value] of row.entries()) {
        const td = node(rowHeaders && index === 0 ? 'th' : 'td');
        if (td.tagName === 'TH') td.scope = 'row';
        if (value instanceof Node && value.classList.contains('phase-cell')) td.className = 'phase-' + value.dataset.stage;
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
  function board(title, description, className = '') {
    const host = node('section', undefined, 'phase-board ' + className);
    host.append(node('h3', title), node('p', description, 'hint'));
    return host;
  }
  function kpi(title, value, note) {
    const card = node('div', undefined, 'phase-kpi');
    card.append(node('span', title), node('strong', count(value)), node('small', note));
    return card;
  }
  function renderOverview(groups, rules, config) {
    const snapshot = groups?.last_run;
    const stamp = groups?.status === 'waiting'
      ? '等待 ' + groups.waiting_for + ' 日数据' + (snapshot ? '，当前显示 ' + snapshot.day : '')
      : snapshot ? '观察日 ' + snapshot.day + ' · 配置 v' + snapshot.config_version : '观察日及配置不可用';
    const activeRules = rules?.items?.filter(rule => rule.enabled);
    const matchingConfig = snapshot && snapshot.config_version === config?.version ? config : null;
    const thresholds = matchingConfig?.stages;
    const membership = (tier, filter = () => true) => snapshot && groups?.groups
      ? groups.groups.filter(row => (tier == null || row.tier === tier) && filter(row))
          .reduce((sum, row) => sum + row.count, 0)
      : null;
    const queue = groups?.queue_counts;
    const stateCount = (...states) => queue ? states.reduce((sum, state) => sum + (queue[state] ?? 0), 0) : null;
    const ready = stateCount('ready');
    const kpis = node('div', undefined, 'phase-kpis');
    kpis.append(kpi('维护池', membership(null), matchingConfig ? 'FC27 累计有效消费 ≥ ' + amount(matchingConfig.tiers.high) : '按最近一次日更入池'),
      ...tiers.map(tier => kpi(label(tier) + '价值', membership(tier),
        '沉默或流失 ' + count(membership(tier, row => ['silent', 'lost', 'long_lost'].includes(row.stage))) + ' 人')),
      kpi('待你确认', ready, '当前待发区 · 发放前会再次核验'));
    const flow = board('每天怎么运转', '启用规则筛选新进入阶段的客户，由程序复核。待发区需要管理员确认或剔除。');
    const steps = node('ol', undefined, 'phase-flow');
    for (const [index, [name, value, note]] of [
      ['规则挑人', activeRules?.length, '启用中的规则'],
      ['程序复核', stateCount('reviewing'), '当前待复核条目'],
      ['进入待发区', ready, '当前复核通过待确认'],
      ['确认或剔除', stateCount('confirmed', 'auto_confirmed', 'deferred'), '当前已确认、自动确认或顺延'],
      ['发券并对账', stateCount('dispatching', 'unknown', 'pending_register'), '当前派发中、待注册或待对账 · 累计已发放 ' + count(stateCount('issued')) + ' 条'],
    ].entries()) {
      const item = node('li', undefined, index === 3 ? 'phase-you' : '');
      item.append(node('span', '第 ' + (index + 1) + ' 步 · ' + (index === 3 ? '你' : '自动')),
        node('strong', name), node('b', value == null ? '—' : count(value) + ' 条'), node('small', note));
      steps.append(item);
    }
    flow.append(steps);
    const matrix = board('客户分层与对应动作', '各格显示名单人数与启用规则。仅新进入阶段且满足规则条件的客户可触发动作。');
    const windows = thresholds ? ['<' + thresholds[0], thresholds[0] + '–<' + thresholds[1],
      thresholds[1] + '–<' + thresholds[2], '≥' + thresholds[2]] : [];
    const displayStages = stages.slice(0, 4);
    if (membership(null, row => row.stage === 'unverified')) displayStages.push('unverified');
    const matrixTable = table(['价值档', ...displayStages.map((stage, i) => label(stage) + (windows[i] ? '（' + windows[i] + ' 天）' : ''))],
      tiers.map(tier => [
        label(tier) + '价值',
        ...displayStages.map(stage => {
          const cell = node('div', undefined, 'phase-cell');
          cell.dataset.stage = stage;
          cell.append(node('strong', count(membership(tier, row => row.stage === stage)) + ' 人'));
          const matches = activeRules?.filter(rule => rule.tier === tier && rule.stage === stage);
          if (matches?.length) {
            for (const rule of matches) {
              const actions = [rule.alert && '待跟进', rule.owner && '分配给 ' + rule.owner,
                rule.coupon_id && '发券 #' + rule.coupon_id].filter(Boolean);
              cell.append(node('small', (rule.customer_type ? label(rule.customer_type) + ' · ' : '') +
                (actions.join(' · ') || '无配置动作')));
            }
          } else {
            const text = stage === 'recent' ? '近期观察' : stage === 'unverified' ? '等待覆盖核对' :
              matches ? '暂无启用规则' : '规则暂不可用';
            cell.append(node('small', text));
          }
          return cell;
        }),
      ]), '客户分层与对应动作', true);
    matrixTable.classList.add('phase-matrix');
    matrix.append(node('p', '向右滚动可查看其余阶段。', 'hint phase-scroll-hint'), matrixTable);
    const guide = node('details', undefined, 'phase-guide');
    const example = displayStages.filter(stage => stage !== 'recent').map(stage => [stage, membership('ultra', row => row.stage === stage)]).find(([, value]) => value > 0);
    guide.append(node('summary', '这块怎么读？'),
      node('p', '价值档按 FC27 累计有效消费分层，阶段按末次有效购买后的天数划分。名单可能包含人工展示档位。'),
      node('p', example ? '当前名单中有 ' + count(example[1]) + ' 位超高价值客户处于' + label(example[0]) + '阶段。可展开分组名单查看。' : '当前没有可用的分层示例。'));
    matrix.append(guide);
    overview.replaceChildren(node('p', stamp, 'phase-meta'), kpis, flow, matrix);
  }
  function pageGroups(data) {
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
    const rows = data.items.map(row => {
      const evidence = node('div');
      if (row.review?.manual_coupon_notice) evidence.append(node('div', row.review.manual_coupon_notice));
      const reasons = (row.review?.reasons || []).map(label);
      if (row.result?.reason) reasons.push(label(row.result.reason));
      if (row.result?.identity_conflicts?.length) {
        reasons.push('回执身份冲突（' + row.result.identity_conflicts.join('、') + '）');
      }
      if (reasons.length) evidence.append(node('div', reasons.join('、')));
      const actions = node('div', undefined, 'phase-actions');
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
        if (current === 'review' && row.identity_checked_at) {
          const shown = new Date(row.identity_checked_at).toLocaleString('zh-CN',
            {timeZone: 'Asia/Shanghai', hour12: false});
          const checked = node('time', '检查时间 ' + shown + '（北京时间）');
          checked.dateTime = row.identity_checked_at;
          evidence.append(checked);
        }
      }
      return [row.email, row.rule_id, state, row.batch || '—', evidence, actions];
    });
    content.replaceChildren(table(['收件邮箱', '规则', '状态', '原批次', '复核依据', '操作'], rows));
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
      const card = node('details', undefined, 'phase-rule');
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
    const create = node('details', undefined, 'phase-rule');
    create.append(node('summary', '新建维护规则'), ruleForm());
    const section = board('维护规则', '展开规则查看或编辑匹配人群、发券模板、日额度及负责人。');
    section.append(...list, create);
    content.replaceChildren(section);
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
  const validNumber = value => value != null && value !== '' && Number.isFinite(Number(value));
  function shanghaiTime(value) {
    const milliseconds = Date.parse(value);
    return Number.isFinite(milliseconds) ? dateFormat.format(milliseconds) : '—';
  }
  function couponDetails(coupon, ruleId) {
    const host = node('div');
    const mode = Number(coupon?.mode_type);
    const value = Number(coupon?.reduce);
    let discount = '折扣待核';
    if (validNumber(coupon?.reduce) && mode === 1 && value >= 0) discount = '立减 ' + amount(value);
    if (validNumber(coupon?.reduce) && mode === 2 && value >= 0 && value <= 100) {
      discount = '减 ' + numberFormat.format(100 - value) + '%';
    }
    const max = Number(coupon?.max_reduce);
    const cap = mode === 1 && validNumber(coupon?.reduce) && value >= 0 ? '最多减 ' + amount(value)
      : validNumber(coupon?.max_reduce) && max > 0 ? '最多减 ' + amount(max)
      : validNumber(coupon?.max_reduce) && max === 0 ? '无封顶金额' : '封顶金额待核';
    const date = raw => raw ? shanghaiTime(raw.replace(' ', 'T') + (/([+-]\d\d:\d\d|Z)$/i.test(raw) ? '' : '+08:00')) : '—';
    const validity = Number(coupon?.time_effect) === 2 && validNumber(coupon?.days) && Number(coupon.days) > 0
      ? count(coupon.days) + ' 天有效'
      : Number(coupon?.time_effect) === 1 && coupon.end_time
        ? '有效期 ' + date(coupon.start_time) + ' 至 ' + date(coupon.end_time) + '（北京时间）' : '有效期待核';
    host.append(node('strong', discount), node('small', cap), node('small', validity), node('small', '规则 ' + ruleId, 'hint'));
    return host;
  }
  function updateCountdown(row, clock, at = Date.now()) {
    const remaining = Date.parse(row.ready_at) + 72 * 60 * 60 * 1000 - at;
    const minutes = Math.ceil(remaining / 60000);
    clock.textContent = !Number.isFinite(minutes) ? '到期时间待核' : remaining <= 0 ? '已到期 · 待处理'
      : '剩 ' + Math.floor(minutes / 60) + ' 小时 ' + minutes % 60 + ' 分';
  }
  async function readReady() {
    const items = new Map();
    let pageOffset = 0;
    while (pageOffset !== null) {
      const data = await read('ready', {offset: pageOffset});
      for (const row of data.items) items.set(row.id, row);
      const following = data.next_offset ?? null;
      if (following !== null && (!Number.isInteger(following) || following <= pageOffset)) {
        throw Error('maintenance_queue_pagination');
      }
      pageOffset = following;
    }
    return {items: [...items.values()]};
  }
  async function decideSelected(ids, decision, setDisabled) {
    if (!ids.length || bulkPending || busy.size) return;
    bulkPending = true;
    setDisabled();
    get('phase-view').disabled = get('phase-refresh').disabled = true;
    status.textContent = '正在处理所选条目…';
    let changed = 0;
    let skipped = 0;
    try {
      for (let start = 0; start < ids.length; start += 100) {
        const batch = ids.slice(start, start + 100);
        const receipt = await post('decide', {ids: batch, decision});
        if (!Array.isArray(receipt.changed) || !Number.isInteger(receipt.skipped) || receipt.skipped < 0 ||
            new Set(receipt.changed).size !== receipt.changed.length ||
            !receipt.changed.every(id => batch.includes(id)) || receipt.changed.length + receipt.skipped !== batch.length) {
          throw Error('maintenance_decision_receipt_invalid');
        }
        changed += receipt.changed.length;
        skipped += receipt.skipped;
      }
      if (!get('phase-panel').hidden) {
        await load();
        const result = '已' + (decision === 'removed' ? '剔除' : '确认') + ' ' + count(changed) + ' 条' +
          (skipped ? '，' + count(skipped) + ' 条状态已变更' : '') + '。';
        status.textContent = [result, status.textContent].filter(Boolean).join(' ');
      }
    } catch {
      if (!get('phase-panel').hidden) {
        await load();
        status.textContent = '已核到 ' + count(changed) + ' 条，部分操作结果待核。已停止提交其余条目，请核对重新读取的待发区。' +
          (status.textContent ? ' ' + status.textContent : '');
      }
    } finally {
      bulkPending = false;
      get('phase-view').disabled = get('phase-refresh').disabled = false;
    }
  }
  function pageReady(data) {
    const rows = data.items;
    const selected = new Set();
    const section = board('待发区', '在当前筛选范围内勾选客户。确认后进入发放前重验，剔除为终态。', 'phase-ready');
    const filters = node('div', undefined, 'phase-form');
    const tier = control(filters, '待发价值档', 'tier', 'text', queueFilter.tier,
      [['', '全部'], ...tiers.map(item => [item, label(item) + '价值'])]);
    const stage = control(filters, '待发阶段', 'stage', 'text', queueFilter.stage,
      [['', '全部'], ...[...new Set(rows.map(row => row.stage).filter(Boolean))].map(item => [item, label(item)])]);
    if (queueFilter.stage && !stage.value) {
      stage.add(new Option(label(queueFilter.stage), queueFilter.stage));
      stage.value = queueFilter.stage;
    }
    const actions = node('div', undefined, 'phase-actions');
    const selector = node('label', undefined);
    const selectAll = node('input');
    selectAll.type = 'checkbox';
    selector.append(selectAll, '全选当前筛选');
    const confirm = button('确认所选', () => decideSelected([...selected], 'confirmed', disable), 'fs-btn fs-btn--primary');
    const remove = button('剔除所选', () => {
      const dialog = get('phase-remove-dialog');
      dialog.returnValue = '';
      get('phase-remove-copy').textContent = count(selected.size) + ' 条将标为已剔除，操作无法撤回。';
      dialog.onclose = () => {
        const confirmed = dialog.returnValue === 'remove';
        dialog.returnValue = '';
        if (confirmed) decideSelected([...selected], 'removed', disable);
      };
      dialog.showModal();
    }, 'fs-btn phase-danger');
    actions.append(selector, confirm, remove);
    const counter = node('p', undefined, 'hint');
    counter.setAttribute('role', 'status');
    const listing = node('div');
    let boxes = [];
    let countdowns = [];
    function syncSelection() {
      selectAll.disabled = !boxes.length;
      selectAll.checked = boxes.length > 0 && selected.size === boxes.length;
      selectAll.indeterminate = selected.size > 0 && selected.size < boxes.length;
      confirm.disabled = remove.disabled = !selected.size;
      counter.textContent = '符合筛选 ' + count(boxes.length) + ' 条，已选 ' + count(selected.size) + ' 条';
    }
    function disable() {
      for (const control of [confirm, remove, selectAll, tier, stage, ...boxes.map(([, checkbox]) => checkbox)]) {
        control.disabled = true;
      }
    }
    function updateClocks() {
      const now = Date.now();
      for (const [row, clock] of countdowns) updateCountdown(row, clock, now);
    }
    function renderList() {
      selected.clear();
      boxes = [];
      countdowns = [];
      const filtered = rows.filter(row => (!tier.value || row.tier === tier.value) && (!stage.value || row.stage === stage.value));
      scrollHint.hidden = !filtered.length;
      listing.replaceChildren(filtered.length ? table(
        ['选择与客户邮箱', '价值档', '触发阶段', 'FC27 累计消费', '复核结论', '拟发优惠券', '进入待发区及倒计时'],
        filtered.map(row => {
          const customer = node('label', undefined);
          const checkbox = node('input');
          checkbox.type = 'checkbox';
          checkbox.setAttribute('aria-label', '选择 ' + (row.email || row.id));
          customer.append(checkbox, row.email || '邮箱待核');
          boxes.push([row, checkbox]);
          checkbox.onchange = () => {
            if (checkbox.checked) selected.add(row.id);
            else selected.delete(row.id);
            syncSelection();
          };
          const evidence = node('div');
          const review = row.review;
          evidence.append(node('strong', review?.decision === 'pass' ? '复核通过' : '复核结论待核'));
          if (review?.manual_coupon_notice) evidence.append(node('small', review.manual_coupon_notice, 'hint'));
          if (row.identity_status === 'pending_identity') {
            evidence.append(node('small', '身份待核 · ' + label(row.identity_reason), 'phase-alert'));
          }
          const timing = node('div');
          const date = node('time', shanghaiTime(row.ready_at));
          if (row.ready_at) date.dateTime = row.ready_at;
          const clock = node('small');
          countdowns.push([row, clock]);
          timing.append(date, clock);
          const spend = amount(row.amount_usd) + (row.unknown_amount_orders ? ' · 含 ' + count(row.unknown_amount_orders) + ' 笔金额未知' : '');
          return [customer, label(row.tier), label(row.stage), spend, evidence, couponDetails(row.coupon, row.rule_id), timing];
        }), '待发区客户名单', true) : node('p', rows.length ? '当前筛选暂无条目。' : '暂无条目。复核通过的客户将出现在这里。', 'hint'));
      syncSelection();
      updateClocks();
    }
    tier.onchange = stage.onchange = () => {
      queueFilter.tier = tier.value;
      queueFilter.stage = stage.value;
      renderList();
    };
    selectAll.onchange = () => {
      selected.clear();
      for (const [row, checkbox] of boxes) {
        checkbox.checked = selectAll.checked;
        if (checkbox.checked) selected.add(row.id);
      }
      syncSelection();
    };
    const scrollHint = node('p', '向右滚动可查看复核、优惠券和倒计时。', 'hint phase-scroll-hint');
    section.append(filters, actions, counter, scrollHint, listing);
    content.replaceChildren(section);
    renderList();
    if (rows.length) readyTimer = setInterval(() => {
      if (get('phase-panel').hidden) clearInterval(readyTimer);
      else updateClocks();
    }, 15000);
  }
  async function load() {
    const request = ++sequence;
    const current = view();
    const paged = ['groups', 'review', 'manual', 'delivery'].includes(current);
    const fields = paged ? {offset} : current === 'effect' ? {days: windowDays} : {};
    clearInterval(readyTimer);
    pending = true;
    more.disabled = true;
    more.hidden = true;
    status.textContent = '正在读取…';
    content.replaceChildren();
    if (overview) overview.setAttribute('aria-busy', 'true');
    const main = current === 'ready' ? readReady() : read(current, fields);
    const related = manual ? [] : [
      current === 'groups' ? main : read('groups'),
      current === 'rules' ? main : read('rules'),
      current === 'config' ? main : read('config'),
    ];
    try {
      const [res, ...parts] = await Promise.allSettled([main, ...related]);
      if (request !== sequence) return;
      status.textContent = '';
      if (overview) {
        renderOverview(...parts.map(part => part.value));
        overview.setAttribute('aria-busy', 'false');
      }
      if (res.status === 'rejected') throw res.reason;
      const data = res.value;
      if (current === 'groups') pageGroups(data);
      else if (current === 'config') pageConfig(data);
      else if (current === 'rules') pageRules(data);
      else if (current === 'effect') pageEffect(data);
      else if (current === 'ready') pageReady(data);
      else pageQueue(data);
      next = data.next_offset ?? null;
      more.hidden = next === null;
      if (parts.some(part => part.status === 'rejected')) {
        status.textContent = [status.textContent, '概览有资料未能读取，请刷新。'].filter(Boolean).join(' ');
      }
    } catch (error) {
      if (request === sequence) status.textContent = '读取失败。' + error.message;
    } finally {
      if (request === sequence) {
        pending = false;
        more.disabled = false;
        if (overview) overview.setAttribute('aria-busy', 'false');
      }
    }
  }
  get('phase-refresh').addEventListener('click', () => { if (!bulkPending) { offset = 0; load(); } });
  more.addEventListener('click', () => { if (!pending && next !== null) { offset = next; load(); } });
  if (manual) load();
  else {
    get('phase-view').addEventListener('change', () => { offset = 0; load(); });
    get('phase-scope').addEventListener('click', () => {
      if (bulkPending) return;
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
