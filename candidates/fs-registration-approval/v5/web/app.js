'use strict';
let csrf = '', cursor = 0;
const $ = id => document.getElementById(id);
async function api(path, form) {
  const options = {credentials:'same-origin', headers:{}};
  if (form !== undefined) Object.assign(options, {method:'POST', body:JSON.stringify(form), headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}});
  const response = await fetch('./api/' + path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '暂不可用，请刷新');
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
  try { await api(id, Object.fromEntries(new FormData(form))); form.reset(); await boot(); message(id === 'register' ? '注册成功，申请待审批。请登录查看进度。' : '状态已更新'); }
  catch (error) { message(error.message); }
  finally { button.disabled = false; }
});
$('theme').addEventListener('click', () => document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
$('logout').addEventListener('click', async () => { try { await api('logout', {}); await boot(); message('已退出申请账号；原门户账号请在原门户退出。'); } catch(e) { message(e.message); } });
async function requests(after=0) {
  const data = await api('requests?after=' + after); $('requests').replaceChildren();
  for (const row of data.items) {
    const card = document.createElement('article'); card.className = 'about-card';
    const title = document.createElement('h3'); title.textContent = row.name + ' · ' + row.status;
    const info = document.createElement('p'); info.textContent = row.team + ' / ' + row.purpose + ' / ' + row.id;
    card.append(title, info);
    for (const action of row.status === 'pending' ? ['approve','reject'] : row.status === 'approved' ? ['revoke'] : []) {
      const button = document.createElement('button'); button.className='button'; button.type='button';
      button.textContent={approve:'批准全局只读',reject:'拒绝',revoke:'撤销授权'}[action];
      button.addEventListener('click', async () => {
        const reason = prompt('请填写人工核实结果或审批原因'); if (!reason) return;
        button.disabled = true;
        try { const body = {request_id:row.id,version:row.version,reason}; if (action !== 'revoke') body.action = action;
          await api(action === 'revoke' ? 'revoke' : 'decision', body); await requests(after); message('审批状态已更新');
        } catch(e) { message(e.message); } finally { button.disabled=false; }
      }); card.append(button);
    }
    $('requests').append(card);
  }
  cursor = data.items.at(-1)?.cursor || after; $('more').hidden = data.items.length !== 50;
}
$('refresh').addEventListener('click', () => requests().catch(e => message(e.message)));
$('more').addEventListener('click', () => requests(cursor).catch(e => message(e.message)));
$('audit-button').addEventListener('click', async () => {
  try { const data = await api('audit'); $('audit').replaceChildren();
    for (const item of data.items) { const line=document.createElement('p'); line.textContent=[item.id,new Date(item.at*1000).toISOString(),item.actor,item.action,item.request_id,item.reason].join(' · '); $('audit').append(line); }
    message('显示最早50条审计；完整审计通过接口分页读取');
  } catch(e) { message(e.message); }
});
boot().catch(e => message(e.message));
