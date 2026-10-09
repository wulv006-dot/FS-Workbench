'use strict';
let csrf = '', cursor = 0, busy = false, rows = [], selected = new Set();
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
  return data;
}
function message(text) { $('message').textContent = text; }
async function boot() {
  const data = await api('bootstrap'); csrf = data.csrf;
  const a = data.account, registered = !!a.id, admin = a.role === 'admin';
  $('guest').hidden = registered || admin || a.role !== 'guest'; $('native-box').hidden = a.role !== 'guest';
  $('account').hidden = !registered; $('admin').hidden = !admin;
  $('logout').hidden = a.role === 'guest';
  if (registered) {
    const labels = {pending:'待审批：可查看介绍和申请状态',readonly:'已批准：全局只读',rejected:'申请已拒绝',revoked:'授权已撤销'};
    $('state').textContent = a.name + ' · ' + labels[a.state];
    $('request').textContent = '申请编号：' + a.request.id + ' · 状态：' + a.request.status + (a.request.reason ? ' · 审批说明：' + a.request.reason : '');
    $('apply').hidden = !['rejected','revoked'].includes(a.state); $('approved').hidden = a.state !== 'readonly';
  }
  if (admin) await requests();
}
for (const id of ['register','login','native-login','apply']) $(id).addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
  const feedback = form.querySelector('[role="alert"]'); feedback.textContent = ''; message('');
  try { await api(id, Object.fromEntries(new FormData(form))); form.reset(); await boot(); message(id === 'register' ? '注册成功，申请待审批。请登录查看进度。' : '状态已更新'); }
  catch (error) {
    feedback.textContent = error.message; message(error.message);
    (feedback.getClientRects().length ? feedback : $('message')).scrollIntoView({block:'nearest'});
  }
  finally { button.disabled = false; }
});
$('theme').addEventListener('click', () => document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
$('logout').addEventListener('click', async () => { try { await api('logout', {}); await boot(); message('已退出，当前会话已失效。'); } catch(e) { message(e.message); } });
async function requests(after=0) {
  const data = await api('requests?after=' + after); rows = data.items; selected.clear(); $('select-all').checked = false; $('requests').replaceChildren();
  for (const row of data.items) {
    const card = document.createElement('article'); card.className = 'about-card';
    const title = document.createElement('h3'); title.textContent = row.name + ' · ' + ({pending:'待审批',approved:'全局只读',rejected:'已拒绝',revoked:'已撤销'}[row.status] || row.status);
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
  for (const el of $('admin').querySelectorAll('button,input,textarea')) el.disabled = value;
  selection();
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
    for (const item of data.items) { const line=document.createElement('p'); line.textContent=[item.id,new Date(item.at*1000).toISOString(),item.actor,item.action,item.request_id,item.reason].join(' · '); $('audit').append(line); }
    message('显示最早50条审计；完整审计通过接口分页读取');
  } catch(e) { message(e.message); }
});
boot().catch(e => message(e.message));
