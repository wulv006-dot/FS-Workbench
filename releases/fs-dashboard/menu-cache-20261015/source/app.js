'use strict';
let csrf = '', cursor = 0, busy = false, rows = [], selected = new Set(), modules = [];
const $ = id => document.getElementById(id);
async function api(path, form) {
  const options = {credentials:'same-origin', headers:{}};
  if (form !== undefined) Object.assign(options, {method:'POST', body:JSON.stringify(form), headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}});
  let response, data;
  try { response = await fetch('./api/' + path, options); data = await response.json(); }
  catch { throw new Error('连接中断或响应异常，请刷新核对状态后再操作'); }
  if (!response.ok) {
    const text = response.status === 401 && ['login','native-login'].includes(path) ? '账号或密码错误，请检查后重试。' : data.error || '暂不可用，请刷新';
    const error = new Error(text); error.status = response.status; throw error;
  }
  if(form!==undefined){try{sessionStorage.removeItem('fs-menu-access-v1');localStorage.setItem('fs-menu-access-epoch',crypto.randomUUID());}catch{}}
  return data;
}
function message(text) { $('message').textContent = text; }
async function boot() {
  const data = await api('bootstrap'); csrf = data.csrf; modules = data.permission_modules || [];
  const a = data.account, registered = !!a.id, admin = a.role === 'admin';
  $('guest').hidden = a.role !== 'guest'; document.body.dataset.access = a.role; $('home').hidden = a.role === 'guest';
  $('account').hidden = !registered; $('admin').hidden = !admin;
  $('logout').hidden = a.role === 'guest';
  if (registered) {
    const labels = {pending:'待审批：可查看介绍和申请状态',readonly:'已批准：按模块授权',rejected:'申请已拒绝',revoked:'授权已撤销'};
    $('state').textContent = a.name + ' · ' + labels[a.state];
    $('request').textContent = '申请编号：' + a.request.id + ' · 状态：' + a.request.status + (a.request.reason ? ' · 审批说明：' + a.request.reason : '');
    $('apply').hidden = !['rejected','revoked'].includes(a.state); $('approved').hidden = a.state !== 'readonly';
    if (a.state === 'readonly' && a.permissions) {
      const allowed = modules.filter(m=>a.permissions.modules[m.id] !== 'none'); $('approved').replaceChildren();
      $('approved').textContent = allowed.length ? '已授权模块：' : '暂无业务模块授权，可联系管理员调整。';
      for(const m of allowed) { const link=document.createElement('a'); link.href=m.href; link.textContent=m.label+'（'+(a.permissions.modules[m.id]==='editor'?'本人任务可编辑':'只读')+'）'; $('approved').append(link,document.createTextNode('　')); }
    }
  }
  if (admin) await Promise.all([requests(), accounts()]);
}
for (const id of ['register','login','apply']) $(id).addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
  const feedback = form.querySelector('[role="alert"]'); feedback.textContent = ''; message('');
  try {
    const values = Object.fromEntries(new FormData(form));
    if (id === 'login') {
      try { await api('native-login', values); }
      catch (error) { if (error.status !== 401) throw error; await api('login', values); }
      window.location.assign('/dashboard/'); return;
    }
    await api(id, values); form.reset(); await boot();
    if (id === 'register') setGuestView(false);
    message(id === 'register' ? '注册成功，申请待审批。请登录进入工作台。' : '状态已更新');
  }
  catch (error) {
    feedback.textContent = error.message; message(error.message);
    (feedback.getClientRects().length ? feedback : $('message')).scrollIntoView({block:'nearest'});
  }
  finally { button.disabled = false; }
});
function setGuestView(register) { $('login-panel').hidden=register; $('register-panel').hidden=!register; (register?$('register'):$('login')).querySelector('input').focus(); }
$('open-register').addEventListener('click', event=>{event.preventDefault();setGuestView(true);});
$('back-login').addEventListener('click', event=>{event.preventDefault();setGuestView(false);});
$('theme').addEventListener('click', () => document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
$('logout').addEventListener('click', async () => { try { await api('logout', {}); await boot(); setGuestView(false); message('已退出，当前会话已失效。'); } catch(e) { message(e.message); } });
async function requests(after=0) {
  const data = await api('requests?after=' + after); rows = data.items; selected.clear(); $('select-all').checked = false; $('requests').replaceChildren();
  for (const row of data.items) {
    const card = document.createElement('article'); card.className = 'about-card';
    const title = document.createElement('h3'); title.textContent = row.name + ' · ' + ({pending:'待审批',approved:row.permissions?.version ? '按模块授权' : '全局只读',rejected:'已拒绝',revoked:'已撤销'}[row.status] || row.status);
    const info = document.createElement('p'); info.textContent = row.team + ' / ' + row.purpose + ' / ' + row.id;
    card.append(title, info);
    if (['pending','approved'].includes(row.status)) {
      const label = document.createElement('label'), check = document.createElement('input'); check.type = 'checkbox'; check.dataset.request = row.id; check.disabled = busy;
      const name = document.createElement('span'); name.textContent = '选择 ' + row.name;
      check.addEventListener('change', () => { check.checked ? selected.add(row.id) : selected.delete(row.id); selection(); });
      label.className = 'account-select'; label.append(check,name); card.prepend(label);
    }
    for (const action of row.status === 'pending' ? ['approve','reject'] : row.status === 'approved' ? ['revoke'] : []) {
      const button = document.createElement('button'); button.className='button'; button.type='button';
      button.textContent={approve:'批准全局只读',reject:'拒绝',revoke:'撤销授权'}[action];
      button.disabled = busy;
      button.addEventListener('click', async () => {
        if (busy) return;
        const reason = prompt('请填写人工核实结果或审批原因'); if (!reason) return;
        await decideRows([row], action, reason, after);
      }); card.append(button);
    }
    if (row.status === 'approved' && row.permissions && modules.length) permissionEditor(card,row);
    $('requests').append(card);
  }
  cursor = data.items.at(-1)?.cursor || after; $('more').hidden = data.items.length !== 50;
  selection();
}
function selection() {
  const items = rows.filter(row => selected.has(row.id));
  $('selection').textContent = '当前页已选 ' + items.length + ' 个账号';
  for (const action of ['approve','reject','revoke']) $('bulk-' + action).disabled = busy || !items.length || items.some(row => row.status !== (action === 'revoke' ? 'approved' : 'pending'));
  const count = rows.filter(row => ['pending','approved'].includes(row.status)).length;
  $('select-all').checked = count > 0 && items.length === count; $('select-all').indeterminate = items.length > 0 && items.length < count;
}
function working(value) {
  busy = value;
  for (const el of $('admin').querySelectorAll('button,input,textarea,select')) el.disabled = value;
  selection();
}
function permissionEditor(card, row) {
  const details = document.createElement('details'), summary = document.createElement('summary'); summary.textContent = '修改模块权限'; details.append(summary);
  const inputs = {};
  for (const module of modules) {
    const label = document.createElement('label'); label.textContent = module.label;
    const select = document.createElement('select'); select.dataset.module = module.id;
    for (const [value,text] of [['none','无访问'],['readonly','只读'],...(module.can_edit ? [['editor','可编辑：仅本人任务']] : [])]) {
      const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option);
    }
    select.value = row.permissions.modules[module.id]; select.disabled = busy; inputs[module.id] = select; label.append(select); details.append(label);
  }
  const note = document.createElement('p'); note.textContent = '编辑仅维护自己名下任务，不包含新增、删除、指派或成员管理。保存会注销该账号旧会话；开放编辑时还会登记执行人，以便管理员分配任务。'; details.append(note);
  const save = document.createElement('button'); save.type = 'button'; save.className = 'button'; save.textContent = '保存模块权限'; save.disabled = busy;
  save.addEventListener('click', async () => {
    if (busy) return;
    const reason = prompt('请填写权限调整原因'); if (!reason || !reason.trim() || reason.trim().length > 240) return;
    const permissions = Object.fromEntries(Object.entries(inputs).map(([id,input])=>[id,input.value]));
    if (!confirm('修改 ' + row.name + ' 的模块权限\n' + modules.map(m=>m.label+'：'+{none:'无访问',readonly:'只读',editor:'可编辑：仅本人任务'}[permissions[m.id]]).join('\n') + '\n原因：' + reason + '\n该账号须重新登录。')) return;
    working(true); $('results').replaceChildren(); const result = document.createElement('p'); $('results').append(result);
    try {
      const data = await api('permissions',{request_id:row.id,request_version:row.version,version:row.permissions.version,permissions,reason:reason.trim()});
      result.textContent = row.name + '：模块权限已保存，旧会话已注销。';
      if (data.member) {
        try { await syncMember(data.member); result.textContent += '执行人登记已核对。'; }
        catch(e) { result.textContent += '执行人登记未完成或待核对：' + e.message + '；权限保存已成功，重新开放编辑前先核对成员记录。'; }
      }
    } catch(e) { result.textContent = row.name + '：' + (!e.status || e.status >= 500 ? '结果待核对，请刷新并查审计，不要直接重试。' : '未保存 · ' + e.message); }
    finally { try { await requests(); } catch(e) { result.textContent += ' 列表刷新失败：' + e.message; } working(false); $('results').scrollIntoView({block:'nearest'}); }
  });
  details.append(save); card.append(details);
}
async function syncMember(member) {
  async function call(form) {
    const response = await fetch('/dashboard/tasks/api/members',{credentials:'same-origin',...(form ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(form)} : {})});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || '执行人登记失败'); return data;
  }
  const data = await call(), existing = data.members.find(row=>row.username===member.username);
  if (existing) { if (!existing.active) throw new Error('该执行人记录已停用，须由管理员核实'); return; }
  await call(member);
}
async function decideRows(items, action, reason, after=0) {
  reason = reason.trim();
  if (!reason || reason.length > 240) { message('请填写1–240字审批原因'); return; }
  const label = {approve:'批准全局只读',reject:'拒绝申请',revoke:'撤销授权'}[action];
  if (!confirm(label + '：' + items.length + '个账号\n' + items.map(row => row.name).join('、') + '\n原因：' + reason)) return;
  working(true); $('results').replaceChildren(); let succeeded = 0, failed = 0, unknown = false;
  try {
    for (const row of items) {
      const line = document.createElement('p'); $('results').append(line);
      const body = {request_id:row.id,version:row.version,reason}; if (action !== 'revoke') body.action = action;
      try { await api(action === 'revoke' ? 'revoke' : 'decision', body); line.textContent = row.name + '：' + label + '成功'; succeeded++; }
      catch (e) {
        if (!e.status || e.status >= 500) { line.textContent = row.name + '：结果待核对，已停止后续操作。请刷新申请并查审批审计，不要直接重试。'; unknown = true; break; }
        line.textContent = row.name + '：未完成 · ' + e.message; failed++;
        if ([401,403,429].includes(e.status)) break;
      }
    }
    message('已完成 ' + succeeded + ' / ' + items.length + '，失败 ' + failed + (unknown ? '；存在待核对结果' : succeeded + failed < items.length ? '；其余未执行' : ''));
    try { await requests(after); } catch (e) { message('操作记录已保留，但列表刷新失败：' + e.message); }
  } finally { working(false); $('results').scrollIntoView({block:'nearest'}); }
}
$('select-all').addEventListener('change', event => {
  for (const check of $('requests').querySelectorAll('input[data-request]')) { check.checked = event.target.checked; check.checked ? selected.add(check.dataset.request) : selected.delete(check.dataset.request); }
  selection();
});
for (const action of ['approve','reject','revoke']) $('bulk-' + action).addEventListener('click', () => {
  if (busy) return; const items = rows.filter(row => selected.has(row.id));
  if (!items.length || items.some(row => row.status !== (action === 'revoke' ? 'approved' : 'pending'))) return;
  decideRows(items, action, $('bulk-reason').value);
});
$('refresh').addEventListener('click', () => requests().catch(e => message(e.message)));
$('more').addEventListener('click', () => requests(cursor).catch(e => message(e.message)));
$('audit-button').addEventListener('click', async () => {
  try { const data = await api('audit'); $('audit').replaceChildren();
    for (const item of data.items) { const line=document.createElement('p'); let reason=item.reason;
      if(item.action==='permissions') { const record=JSON.parse(reason); reason=record.reason+' · '+Object.entries(record.modules).map(([id,mode])=>id+':'+mode).join('、'); }
      line.textContent=[item.id,new Date(item.at*1000).toISOString(),item.actor,item.action==='permissions'?'修改模块权限':item.action,item.request_id,reason].join(' · '); $('audit').append(line); }
    message('显示最早50条审计；完整审计通过接口分页读取');
  } catch(e) { message(e.message); }
});
function accountInput(form, labelText, name, type='text') {
  const label=document.createElement('label'), input=document.createElement('input');
  label.textContent=labelText; input.name=name; input.type=type; input.required=true; input.maxLength=type==='password'?128:240;
  if(type==='password') input.autocomplete=name==='admin_password'?'current-password':'new-password';
  label.append(input); form.append(label); return input;
}
async function accountSave(form, route, row, extra) {
  if(busy) return; busy=true;
  const values=Object.fromEntries(new FormData(form));
  const buttons=[...form.querySelectorAll('button')]; buttons.forEach(button=>button.disabled=true);
  try {
    const result=await api(route,{subject:row.subject,revision:row.revision,...values,...extra});
    form.reset();
    if(result.self_changed) { await boot(); message('本人账号已更新，旧会话已退出，请重新登录。'); }
    else { await accounts(); message('账号已更新，全部旧会话已失效。'); }
  } catch(error) { message(error.message); }
  finally { form.querySelectorAll('input[type="password"]').forEach(input=>input.value=''); buttons.forEach(button=>button.disabled=false); busy=false; }
}
async function accounts() {
  const data=await api('accounts'); $('all-accounts').replaceChildren();
  $('account-count').textContent='全部账号：'+data.items.length+' 个';
  for(const row of data.items) {
    const card=document.createElement('article'); card.className='about-card account-card';
    const title=document.createElement('h3'); title.textContent=row.name+' · '+(row.role==='admin'?'管理员':'普通账号')+' · '+(row.enabled?'已启用':'未启用');
    const source=document.createElement('p'); source.className='account-source'; source.textContent='账号来源：'+row.sources.map(value=>({portal:'统一门户',fc_legacy:'旧 FC 账号库',registration:'注册审批'}[value]||value)).join('、');
    card.append(title,source);
    if(row.state==='legacy_only') { const info=document.createElement('p'); info.textContent='此账号仅保留在旧库。先设置统一密码，再明确启用，才可进入工作台。'; card.append(info); }
    const passwordDetails=document.createElement('details'), passwordSummary=document.createElement('summary'); passwordSummary.textContent='修改密码'; passwordDetails.append(passwordSummary);
    const passwordForm=document.createElement('form'); passwordForm.className='account-controls';
    accountInput(passwordForm,'新密码（12–128 位）','new_password','password').minLength=12;
    accountInput(passwordForm,'再次输入新密码','confirm_password','password').minLength=12;
    accountInput(passwordForm,'你的管理员当前密码','admin_password','password'); accountInput(passwordForm,'修改原因','reason');
    const reset=document.createElement('button'); reset.type='submit'; reset.className='button'; reset.textContent='保存新密码'; passwordForm.append(reset);
    passwordForm.addEventListener('submit',event=>{event.preventDefault(); accountSave(passwordForm,'account-password',row,{});}); passwordDetails.append(passwordForm); card.append(passwordDetails);
    const permissionDetails=document.createElement('details'), permissionSummary=document.createElement('summary'); permissionSummary.textContent='调整访问权限'; permissionDetails.append(permissionSummary);
    const permissionForm=document.createElement('form'); permissionForm.className='account-controls';
    const enabledLabel=document.createElement('label'), enabled=document.createElement('input'); enabled.type='checkbox'; enabled.checked=row.enabled; enabledLabel.append(enabled,document.createTextNode('启用该账号')); permissionForm.append(enabledLabel);
    const selectors={};
    if(row.role==='admin') { const fixed=document.createElement('p'); fixed.textContent='管理员保留完整管理权限，停用操作必须保留至少一名可登录管理员。'; permissionForm.append(fixed); }
    else for(const module of modules) {
      const label=document.createElement('label'), select=document.createElement('select'); label.textContent=module.label;
      for(const [value,text] of [['none','无访问'],['readonly','只读'],...(module.can_edit?[['editor','本人任务可编辑']]:[])]) { const option=document.createElement('option'); option.value=value; option.textContent=text; select.append(option); }
      select.value=row.modules[module.id]; selectors[module.id]=select; label.append(select); permissionForm.append(label);
    }
    accountInput(permissionForm,'你的管理员当前密码','admin_password','password'); accountInput(permissionForm,'修改原因','reason');
    const save=document.createElement('button'); save.type='submit'; save.className='button'; save.textContent='保存访问权限'; permissionForm.append(save);
    permissionForm.addEventListener('submit',event=>{event.preventDefault(); const grants=row.role==='admin'?row.modules:Object.fromEntries(Object.entries(selectors).map(([key,select])=>[key,select.value])); accountSave(permissionForm,'account-permissions',row,{enabled:enabled.checked,modules:grants});}); permissionDetails.append(permissionForm); card.append(permissionDetails);
    $('all-accounts').append(card);
  }
}
$('accounts-refresh').addEventListener('click',()=>accounts().catch(error=>message(error.message)));
$('account-audit-button').addEventListener('click',async()=>{
  try { const data=await api('account-audit'); $('account-audit').replaceChildren();
    for(const item of data.items) { const line=document.createElement('p'); const reason=item.action==='permissions'?JSON.parse(item.reason).reason:item.reason; line.textContent=[new Date(item.at*1000).toLocaleString(),item.actor,item.action==='password'?'修改密码':'调整权限',item.subject,reason].join(' · '); $('account-audit').append(line); }
    message(data.items.length?'显示最早 50 条账号审计；完整记录保留并可分页读取。':'暂无账号修改记录。');
  } catch(error) { message(error.message); }
});
boot().catch(e => message(e.message));
