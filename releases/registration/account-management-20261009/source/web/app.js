'use strict';
let csrf = '', cursor = 0, busy = false, rows = [], selected = new Set();
const $ = id => document.getElementById(id);
async function api(path, form) {
  const options = {credentials:'same-origin', headers:{}};
  if (form !== undefined) Object.assign(options, {method:'POST', body:JSON.stringify(form), headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}});
  let response, data;
  try { response = await fetch('./api/' + path, options); data = await response.json(); }
  catch { throw new Error('�����жϻ���Ӧ�쳣����ˢ�º˶�״̬���ٲ���'); }
  if (!response.ok) {
    const text = response.status === 401 && ['login','native-login'].includes(path) ? '�˺Ż����������������ԡ�' : data.error || '�ݲ����ã���ˢ��';
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
    const labels = {pending:'���������ɲ鿴���ܺ�����״̬',readonly:'����׼��ȫ��ֻ��',rejected:'�����Ѿܾ�',revoked:'��Ȩ�ѳ���'};
    $('state').textContent = a.name + ' �� ' + labels[a.state];
    $('request').textContent = '�����ţ�' + a.request.id + ' �� ״̬��' + a.request.status + (a.request.reason ? ' �� ����˵����' + a.request.reason : '');
    $('apply').hidden = !['rejected','revoked'].includes(a.state); $('approved').hidden = a.state !== 'readonly';
  }
  if (admin) await requests();
}
for (const id of ['register','login','native-login','apply']) $(id).addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
  const feedback = form.querySelector('[role="alert"]'); feedback.textContent = ''; message('');
  try { await api(id, Object.fromEntries(new FormData(form))); form.reset(); await boot(); message(id === 'register' ? 'ע��ɹ�����������������¼�鿴���ȡ�' : '״̬�Ѹ���'); }
  catch (error) {
    feedback.textContent = error.message; message(error.message);
    (feedback.getClientRects().length ? feedback : $('message')).scrollIntoView({block:'nearest'});
  }
  finally { button.disabled = false; }
});
$('theme').addEventListener('click', () => document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
$('logout').addEventListener('click', async () => { try { await api('logout', {}); await boot(); message('���˳�����ǰ�Ự��ʧЧ��'); } catch(e) { message(e.message); } });
async function requests(after=0) {
  const data = await api('requests?after=' + after); rows = data.items; selected.clear(); $('select-all').checked = false; $('requests').replaceChildren();
  for (const row of data.items) {
    const card = document.createElement('article'); card.className = 'about-card';
    const title = document.createElement('h3'); title.textContent = row.name + ' �� ' + ({pending:'������',approved:'ȫ��ֻ��',rejected:'�Ѿܾ�',revoked:'�ѳ���'}[row.status] || row.status);
    const info = document.createElement('p'); info.textContent = row.team + ' / ' + row.purpose + ' / ' + row.id;
    card.append(title, info);
    if (['pending','approved'].includes(row.status)) {
      const label = document.createElement('label'), check = document.createElement('input'); check.type = 'checkbox'; check.dataset.request = row.id; check.disabled = busy;
      const name = document.createElement('span'); name.textContent = 'ѡ�� ' + row.name;
      check.addEventListener('change', () => { check.checked ? selected.add(row.id) : selected.delete(row.id); selection(); });
      label.className = 'account-select'; label.append(check,name); card.prepend(label);
    }
    for (const action of row.status === 'pending' ? ['approve','reject'] : row.status === 'approved' ? ['revoke'] : []) {
      const button = document.createElement('button'); button.className='button'; button.type='button';
      button.textContent={approve:'��׼ȫ��ֻ��',reject:'�ܾ�',revoke:'������Ȩ'}[action];
      button.disabled = busy;
      button.addEventListener('click', async () => {
        if (busy) return;
        const reason = prompt('����д�˹���ʵ���������ԭ��'); if (!reason) return;
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
  $('selection').textContent = '��ǰҳ��ѡ ' + items.length + ' ���˺�';
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
  if (!reason || reason.length > 240) { message('����д1�C240������ԭ��'); return; }
  const label = {approve:'��׼ȫ��ֻ��',reject:'�ܾ�����',revoke:'������Ȩ'}[action];
  if (!confirm(label + '��' + items.length + '���˺�\n' + items.map(row => row.name).join('��') + '\nԭ��' + reason)) return;
  working(true); $('results').replaceChildren(); let succeeded = 0, failed = 0, unknown = false;
  try {
    for (const row of items) {
      const line = document.createElement('p'); $('results').append(line);
      const body = {request_id:row.id,version:row.version,reason}; if (action !== 'revoke') body.action = action;
      try { await api(action === 'revoke' ? 'revoke' : 'decision', body); line.textContent = row.name + '��' + label + '�ɹ�'; succeeded++; }
      catch (e) {
        if (!e.status || e.status >= 500) { line.textContent = row.name + '��������˶ԣ���ֹͣ������������ˢ�����벢��������ƣ���Ҫֱ�����ԡ�'; unknown = true; break; }
        line.textContent = row.name + '��δ��� �� ' + e.message; failed++;
        if ([401,403,429].includes(e.status)) break;
      }
    }
    message('����� ' + succeeded + ' / ' + items.length + '��ʧ�� ' + failed + (unknown ? '�����ڴ��˶Խ��' : succeeded + failed < items.length ? '������δִ��' : ''));
    try { await requests(after); } catch (e) { message('������¼�ѱ��������б�ˢ��ʧ�ܣ�' + e.message); }
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
    for (const item of data.items) { const line=document.createElement('p'); line.textContent=[item.id,new Date(item.at*1000).toISOString(),item.actor,item.action,item.request_id,item.reason].join(' �� '); $('audit').append(line); }
    message('��ʾ����50����ƣ��������ͨ���ӿڷ�ҳ��ȡ');
  } catch(e) { message(e.message); }
});
boot().catch(e => message(e.message));
