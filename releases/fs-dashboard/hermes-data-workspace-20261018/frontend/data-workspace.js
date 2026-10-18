/* Candidate only. Host supplies the existing FS styles, authorized endpoint and Hermes handoff. */
// Keep this option set aligned with admin_data_tools_20261018/source/es_order_structure.py GAME_LABELS.
export const GAME_PROFILES = [['FC27','FC 27'],['D4','Diablo 4'],['AION2','Aion 2'],['POE2','POE2'],['NBA2K27','NBA 2K27'],['NFL27','Madden NFL 27'],['MLB26','MLB 26'],['CFB27','College Football 27'],['RS','RS'],['ARC_RAIDERS','ARC Raiders'],['MAPLESTORY_CLASSIC','MapleStory Classic World'],['DARK_AND_DARKER','Dark and Darker'],['WOW_FOREVER','WoW Forever'],['ARENA_BREAKOUT_INFINITE','Arena Breakout: Infinite'],['COD_BO7','CoD: Black Ops 7']];
// These games are the intersection of ES GAME_LABELS and the two generic Admin GAME_IDS contracts.
const QUERY_PROFILES = GAME_PROFILES.map(([code]) => code);
export function mountDataWorkspace(root, options = {}) {
  const doc = root.ownerDocument;
  const win = doc.defaultView;
  const request = options.fetch || win.fetch.bind(win);
  const endpoint = options.endpoint || '/dashboard/fs-home/advisor.json';
  const el = (tag, text, cls) => { const node = doc.createElement(tag); if (text != null) node.textContent = String(text); if (cls) node.className = cls; return node; };
  const money = value => value == null ? '源未提供' : `${value} USD`;
  const section = el('section', null, 'fc-card');
  section.append(el('h2', '数据专区'), el('p', 'FS 查询并归档数据，Hermes 自主分析。查询按需执行，不自动扫描商品。', 'hint'));
  root.append(section);
  function field(form, title, name, choices, initial = '') {
    const label = el('label', title + ' ');
    const input = el(choices ? 'select' : 'input', null, choices ? 'hsel' : 'dinput');
    input.name = name;
    if (choices) for (const [value, text] of choices) { const option = el('option', text); option.value = value; input.append(option); }
    else { input.type = name === 'product_id' ? 'text' : 'date'; input.required = true; if (name === 'product_id') { input.inputMode = 'numeric'; input.pattern = '[1-9][0-9]{0,8}'; input.maxLength = 9; input.autocomplete = 'off'; input.spellcheck = false; input.setAttribute('autocapitalize','off'); } }
    input.value = initial || (choices ? choices[0][0] : '');
    label.append(input); form.append(label);
    return input;
  }
  function table(headers, rows) {
    const wrap = el('div', null, 'tblwrap'); wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', headers.join('、'));
    const t = el('table'), head = el('thead'), tr = el('tr');
    for (const text of headers) { const th = el('th', text); th.scope = 'col'; tr.append(th); } head.append(tr); t.append(head);
    const body = el('tbody');
    for (const row of rows) { const r = el('tr'); for (const value of row) r.append(el('td', value == null ? '源未提供' : value)); body.append(r); }
    t.append(body); wrap.append(t); return wrap;
  }
  function details(parent, label, node) { const d = el('details', null, 'source-details'); d.append(el('summary', label), node); parent.append(d); }
  function facts(parent, data) {
    const entries = Object.entries(data || {}).filter(([,value])=>value!==undefined);
    if (!entries.length) return;
    const list = el('dl'); for (const [key, value] of entries) { list.append(el('dt', key), el('dd', value==null?'源未提供':typeof value === 'object' ? JSON.stringify(value) : value)); }
    details(parent, '来源、分页覆盖与限制', list);
  }
  function renderProduct(body, d) {
    body.append(el('p', `去重关联订单 ${d.totals?.distinct_orders ?? '源未提供'} 单 · 关联整单金额 ${money(d.totals?.order_amount_usd)}`));
    body.append(el('p', '关联整单 USD 不是 SKU 收入或单价；商品行金额按原币分别列示。原状态是当前状态，不能还原历史日末。', 'hint'));
    for (const product of d.products || []) {
      body.append(el('h4', `${product.title} · ${product.platform}`));
      body.append(el('p', '商品数量（按原状态） · ' + ((product.groups || []).map(g => `${g.order_status} / ${g.payment_status}：${g.quantity ?? '源未提供'}`).join('；') || '无已返回商品行')));
      const rows = (product.groups || []).map(g => [g.order_status, g.payment_status, g.orders, g.quantity, money(g.order_amount_usd), Object.entries(g.item_line_by_currency || {}).map(([currency, amount]) => `${amount} ${currency}`).join(' / ') || '源未提供']);
      details(body, `原状态明细 · ${product.platform}`, table(['订单状态', '付款状态', '订单数', '商品数量', '关联整单金额', '原币商品行金额'], rows));
      facts(body, product.coverage);
    }
    facts(body, d.quality);
  }
  function renderDiscount(body, d) {
    const total = d.discount_totals;
    body.append(el('p', `订单 ${total?.orders ?? '源未提供'} 单 · 原始折扣 ${money(total?.discount_amount_usd)} · 缺失折扣 ${total?.unknown_discount_orders ?? '源未提供'} 单`));
    const groups = d.groups || [];
    const counts = new Map();
    // Truncated groups cannot establish complete customer counts.
    if (!d.quality?.discount_groups_truncated) for (const g of groups) counts.set(g.new_customer, (counts.get(g.new_customer) || 0) + g.orders);
    if (counts.size) body.append(table(['订单标志', '订单数'], [...counts]));
    body.append(el('p', 'ES 导出范围与主站范围分别标识；新客订单折扣不等于新客专属优惠核销，原始折扣不是退款后净让利，也不能从已扣折扣销售再减一次。', 'hint'));
    if (d.quality?.discount_groups_truncated) body.append(el('p', '细分已截断：不据此计算完整新老客占比或绘制全期趋势。'));
    details(body, '按原状态查看优惠细项', table(['分组', '新老客标志', '原状态', '订单数', '原始折扣 USD'], groups.map(g => [g.label, g.new_customer, g.order_status, g.orders, g.discount_amount_usd])));
    facts(body, d.quality);
  }
  function renderCohort(body, d) {
    body.append(el('p', '范围：可稳定关联客户的 ES 新客标记付费组；缺身份订单排除并单独显示覆盖，不代表所有新客。不等于已核全历史首购，也不单独证明优惠造成复购。', 'hint'));
    const coverage=d.coverage||{};
    body.append(el('p', `获客窗已付 ${coverage.acquisition_paid_orders ?? '源未提供'} 单 · ES 匹配 ${coverage.matched_es_orders ?? '源未提供'} 单 · 未匹配 ${coverage.unmatched_es_orders ?? '源未提供'} 单`));
    body.append(el('p', `获客窗 ES 新客标记 ${coverage.es_new_marked_paid_orders ?? '源未提供'} 单 · 可稳定关联 ${coverage.stable_es_new_marked_paid_orders ?? '源未提供'} 单 · 缺身份排除 ${coverage.excluded_es_new_identity_orders ?? '源未提供'} 单（均为订单数，不是客户人数）`));
    body.append(el('p', `已关联观察组客户 ${d.members ?? '源未提供'} 人 · 获取及后续观察付款范围排除缺身份订单 ${coverage.excluded_identity_orders ?? '源未提供'} 单`));
    if(d.reason==='initial_customer_linkage_incomplete_not_frozen')body.append(el('p','观察组尚未建立：首次扫描缺少客户关联，未冻结不完整成员。需完整扫描后再建立；当前不显示零客户或复购率。'));
    if(d.reason==='es_paid_link_incomplete_not_frozen')body.append(el('p','观察组尚未建立：ES 与已付订单匹配不完整或冲突，未冻结成员；当前不显示零客户或复购率。'));
    if (d.monitor) {
      const {state,next_due,frequency_seconds:seconds}=d.monitor;
      const status={active:'追踪中',paused:'已暂停',cancelled:'已取消',completed:'已完成',needs_review:'需复核',manual:'单次观察'}[state]||'状态待确认';
      const next=typeof next_due==='string'&&Number.isFinite(Date.parse(next_due))?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(next_due))+'（北京时间）':!next_due&&['paused','cancelled','completed','manual'].includes(state)?'无后续安排':'源未提供';
      const frequency=Number.isInteger(seconds)&&seconds>0?(seconds===86400?'每日一次':seconds%86400===0?`每 ${seconds/86400} 天一次`:seconds%3600===0?`每 ${seconds/3600} 小时一次`:seconds%60===0?`每 ${seconds/60} 分钟一次`:`每 ${seconds} 秒一次`):'源未提供';
      body.append(el('p', `追踪状态：${status} · 下次观察：${next} · 观察频率：${frequency}`));
    }
    if (d.windows?.length) body.append(table(['观察窗', '已关联组成熟客户', '待成熟客户', '已关联组复购客户', '已关联成熟组复购率'], d.windows.map(w => [w.days + ' 日', w.mature_customers, w.immature_customers, w.repeat_customers, w.repeat_rate == null ? w.mature_customers===0?(w.immature_customers>0?'尚未成熟':'暂无成熟客户'):'源未提供' : new Intl.NumberFormat('zh-CN',{style:'percent',maximumFractionDigits:1}).format(w.repeat_rate)])));
    else body.append(el('p', '当前尚无可展示的成熟观察窗，请查看能力与数据覆盖说明。'));
    facts(body, {members:d.members, definition:d.definition, identity_scope:d.identity_scope, campaign_eligibility:d.campaign_eligibility, coverage:d.coverage, limitations:d.limitations, capability:d.capability, observed_at:d.observed_at, progress:d.progress});
  }
  const panels = [];
  for (const [kind, title, render] of [['product_orders', '单品跟踪', renderProduct], ['discount', '优惠摘要', renderDiscount], ['cohort', '新客复购追踪', renderCohort]]) {
    const article = el('article', null, 'fc-card'); article.append(el('h3', title)); section.append(article);
    const form = el('form', null, 'fc-actions'); article.append(form);
    const profile = field(form, '游戏', 'profile', kind === 'discount' ? [['ALL','全局'],...GAME_PROFILES] : GAME_PROFILES, 'FC27');
    if (kind !== 'discount') for (const option of profile.options) option.disabled = !((options.supportedProfiles?.[kind] || QUERY_PROFILES).includes(option.value));
    const start = field(form, '开始日期', 'start', null, options.start || '');
    const end = field(form, '结束日期', 'end', null, options.end || '');
    if (kind === 'product_orders') {
      field(form, '商品 ID（Admin PID）', 'product_id', null);
      article.append(el('p', '按所选游戏和 Admin 商品 ID 查询；商品 ID 唯一定位商品，无需选平台。最长 31 个日历日。D4/Aion2 纳入本次真实验收；其他游戏按通用接口查询，服务端逐次核验游戏与商品 ID 归属。', 'hint'));
    }
    if (kind === 'discount') field(form, '细分', 'group_by', [['discount_new_customer','新老客'],['discount_type','优惠类型'],['discount_day','日期']]);
    if (kind === 'cohort') {
      const cohortPlatform = field(form, '平台', 'platform', [['all','全部平台'],['PS','PlayStation'],['XBOX','Xbox'],['PC','PC']]);
      const siteGroup = field(form, '站点组', 'site_group', [['main','MMOEXP 主站'],['satellite','卫星站'],['all','全部已授权站点']]);
      const syncScope = () => {
        const fc = profile.value === 'FC27';
        if (!fc) { cohortPlatform.value = 'all'; siteGroup.value = 'main'; }
        for (const option of cohortPlatform.options) option.disabled = !fc && option.value !== 'all';
        for (const option of siteGroup.options) option.disabled = !fc && option.value !== 'main';
      };
      profile.addEventListener('change', syncScope); syncScope();
      field(form, '持续观察', 'window_days', [['30','30 日'],['14','14 日'],['7','7 日']]);
      const yesterday=new Date(Date.now()+8*3600000-86400000).toISOString().slice(0,10);start.max=yesterday;end.max=yesterday;
      article.append(el('p','日期用于按游戏固定 ES Excel 新客标记付费组；缺稳定客户身份者排除并显示覆盖，不代表所有新客。创建后持续观察 7/14/30 日窗口。D4/Aion2 纳入本次真实验收；其余游戏结果须逐次核对覆盖和状态。','hint'));
    }
    const submit = el('button', '查询', 'applybtn'); submit.type = 'submit'; form.append(submit);
    const status = el('p', '尚未查询', 'hint'); status.setAttribute('role','status'); status.setAttribute('aria-live','polite'); article.append(status);
    const body = el('div'); article.append(body);
    const hermes = el('button', '交给 Hermes 提炼一句结论', 'ghostbtn'); hermes.type = 'button'; hermes.disabled = true; article.append(hermes);
    let epoch = 0, abort, result, selection, uncertain = false, uncertainKey = '', writing = false;
    const groupKey=q=>JSON.stringify(['profile','start','end','platform','site_group','window_days'].map(k=>String(q[k])));
    const actions = [];
    const archives = new Map();
    const invalidate = () => { ++epoch; abort?.abort(); result = null; selection = null; hermes.disabled = true; submit.disabled = false; body.replaceChildren(); status.textContent = '筛选已变更，请查询'; article.removeAttribute('aria-busy'); };
    form.addEventListener('input', invalidate);
    form.addEventListener('change', invalidate);
    hermes.addEventListener('click', () => { if (result && options.onHermes) options.onHermes({kind, selection:{...selection}, data:result, instruction:'根据本次筛选及已归档数据，提炼一句经营结论，并注明关键限制。'}); });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      if (start.value > end.value) { status.textContent = '开始日期不能晚于结束日期'; return; }
      if (kind === 'product_orders' && (Date.parse(end.value) - Date.parse(start.value)) / 86400000 > 30) { status.textContent = '单品区间最多 31 个日历日'; return; }
      invalidate(); const token = epoch; abort = new win.AbortController();
      const params = new URLSearchParams({mode:'hermes',structure:kind === 'discount' ? 'es' : kind,profile:profile.value,start:start.value,end:end.value});
      for (const input of form.elements) if (['product_id','platform','group_by','site_group','window_days'].includes(input.name)) params.set(input.name,input.value);
      selection = Object.fromEntries(params); submit.disabled = true; article.setAttribute('aria-busy','true'); status.textContent = '读取中…';
      if(kind==='cohort'){
        const archived=archives.get(groupKey(selection));
        if(archived){for(const key of [...params.keys()])params.delete(key);params.set('mode','hermes');params.set('structure','cohort');params.set('id',archived);}
      }
      try {
        const response = await request(endpoint + '?' + params, {signal:abort.signal,credentials:'same-origin',headers:{Accept:'application/json'}});
        if (!response.ok) throw new Error('http');
        const d = await response.json(); if (token !== epoch) return;
        if(kind==='cohort'&&/^[a-f0-9]{64}$/.test(d.archive_id||''))archives.set(groupKey(selection),d.archive_id);
        if(kind==='discount')for(const item of d.available_profiles||[]){const code=typeof item==='string'?item:item.code,label=typeof item==='string'?item:item.label;if(!/^[A-Z0-9_]{1,24}$/.test(code||'')||[...profile.options].some(o=>o.value===code))continue;const option=el('option',label||code);option.value=code;profile.append(option);}
        if (d.monitor && (!uncertain || groupKey(selection)===uncertainKey)) { uncertain = false; uncertainKey=''; for (const action of actions) action.disabled = false; }
        const labels = {pending:'查询已排队或读取中，稍后按相同条件查询',queued:'查询排队中',disabled:'当前查询能力未启用',unavailable:'来源暂不可用，请稍后重试',failed:'读取失败，请重试',available:'读取完成',partial:'部分数据，覆盖不完整'};
        status.textContent = labels[d.status] || '响应状态未知，未展示为成功';
        body.append(el('p', `${profile.value === 'ALL' ? '全局' : profile.value} · ${start.value} 至 ${end.value} · ${kind === 'discount' ? 'ES 导出范围（不等同主站）' : kind === 'cohort' ? form.elements.site_group.selectedOptions[0].textContent : 'MMOEXP 主站'}`));
        if (['available','partial'].includes(d.status)) { render(body,d); result = d; hermes.disabled = typeof options.onHermes !== 'function' || !/^[A-Za-z0-9_-]{1,128}$/.test(d.evidence_id || ''); if (!d.evidence_id) body.append(el('p','本次结果尚未取得归档证据编号，暂不能交给 Hermes。','hint')); }
        if (d.reason) body.append(el('p', d.reason));
        if (d.period) facts(body,{period:d.period, source:d.source, captured_at:d.captured_at});
      } catch (error) { if (token === epoch && error.name !== 'AbortError') { status.textContent = '读取失败，请重试'; body.replaceChildren(); } }
      finally { if (token === epoch) { submit.disabled = false; article.removeAttribute('aria-busy'); } }
    });
    if (kind === 'cohort') {
      const toolbar = el('div',null,'fc-actions'); article.append(toolbar);
      for (const [action,label] of [['create','创建观察组'],['refresh','刷新观察'],['pause','暂停追踪'],['resume','恢复追踪'],['cancel','取消追踪']]) {
        const button = el('button',label,'ghostbtn'); button.type='button'; toolbar.append(button); actions.push(button);
        button.addEventListener('click',async()=>{
          if (uncertain || writing || !form.reportValidity()) return;
          if (start.value > end.value) {status.textContent='开始日期不能晚于结束日期';return;}
          invalidate(); const token=epoch; writing=true; for (const input of form.elements) input.disabled=true; for(const b of actions)b.disabled=true;
          const payload={kind:'hermes_cohort_observation',action,profile:profile.value,start:start.value,end:end.value,platform:form.elements.platform.value,site_group:form.elements.site_group.value,window_days:Number(form.elements.window_days.value)};
          selection={...payload}; status.textContent='正在更新观察任务…'; article.setAttribute('aria-busy','true');
          try {
            const response=await (options.writeFetch || request)(endpoint,{method:'POST',credentials:'same-origin',redirect:'error',signal:win.AbortSignal.timeout(20000),headers:{'Content-Type':'application/json','X-FS-Advisor-Action':'submit'},body:JSON.stringify(payload)});
            const d=await response.json(); if(token!==epoch)return;
            if(/^[a-f0-9]{64}$/.test(d.archive_id||''))archives.set(groupKey(selection),d.archive_id);
            if(!response.ok){if(response.status>=500)uncertain=true;throw Error('cohort_action_rejected');}
            status.textContent='观察任务状态已返回';renderCohort(body,d);result=d;hermes.disabled=typeof options.onHermes!=='function'||!/^[A-Za-z0-9_-]{1,128}$/.test(d.evidence_id||'');
          }catch(error){if(error.message!=='cohort_action_rejected')uncertain=true;if(uncertain)uncertainKey=groupKey(payload); status.textContent=uncertain?'更新结果待核对，请先查询相同条件的任务状态，勿重复提交。':'操作未获准，请检查权限、条件与当前任务状态。';}
          finally {writing=false;for(const input of form.elements)input.disabled=false;for(const b of actions)b.disabled=uncertain;article.removeAttribute('aria-busy');}
        });
      }
    }
    panels.push({invalidate});
  }
  return {dispose() { for (const panel of panels) panel.invalidate(); section.remove(); }};
}

export function hermesHandoffURL({kind,selection,data}) {
  if (!['product_orders','discount','cohort'].includes(kind) || !/^[A-Za-z0-9_-]{1,128}$/.test(data?.evidence_id || '')) throw Error('query_evidence_required');
  const params = new URLSearchParams({report_kind:'investigation',data_kind:kind,data_evidence:data.evidence_id});
  for (const key of ['start','end','profile','product_id','model_id','platform','group_by','site_group','window_days']) if (selection[key]) params.set(key,selection[key]);
  return '/dashboard/fs-home/brain/index.html?' + params;
}

export function mountBusinessDataWorkspace(scope, state, navigate, denied) {
  const doc = scope.root.ownerDocument;
  const target = doc.createElement('section'); scope.root.append(target);
  const button = doc.createElement('button'); button.type = 'button'; button.className = 'ghostbtn'; button.textContent = '查询工具 · 数据专区';
  // Business renderNav replaces sideNav and FC view hides it; keep the entry outside that owned subtree.
  const toolbar=doc.createElement('nav');toolbar.className='fc-actions';toolbar.setAttribute('aria-label','数据专区查询工具');toolbar.append(button);
  (scope.root.querySelector('.native-body') || scope.root).prepend(toolbar);
  button.addEventListener('click',()=>{const heading=target.querySelector('h2');heading?.scrollIntoView({block:'center'});heading?.focus({preventScroll:true});});
  const yesterday = new Date(Date.now()+8*3600000-86400000).toISOString().slice(0,10);
  // Scope fetch remains read-only; only this fixed authorized observation endpoint accepts POST.
  const writeFetch=async(url,options)=>{
    if(url!=='/dashboard/fs-home/advisor.json'||options.method!=='POST')throw Error('observation_endpoint_only');
    const response=await doc.defaultView.fetch(url,{...options,signal:doc.defaultView.AbortSignal.any([scope.signal,options.signal])});
    if(response.status===401)denied?.(response.status);
    return response;
  };
  const widget = mountDataWorkspace(target,{fetch:scope.fetch,writeFetch,start:state.b_start||yesterday,end:state.b_end||yesterday,onHermes:payload=>navigate(hermesHandoffURL(payload))});
  target.querySelector('h2').tabIndex = -1;
  scope.signal.addEventListener('abort',()=>{widget.dispose();toolbar.remove();target.remove();},{once:true});
  return widget;
}
