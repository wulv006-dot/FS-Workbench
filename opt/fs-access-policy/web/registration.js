/* 当前 IAM 界面复用原注册账本；权限、会话和审批仍由原运行时判断。 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var token = '', uncertain = false, busy = false;
  var labels = { pending: '待审批', readonly: '已批准', approved: '已批准', rejected: '已拒绝', revoked: '已撤销' };

  async function api(path, form) {
    if (form !== undefined && uncertain) throw new Error('上次结果待核对，请刷新并查看申请或审计记录');
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 20000);
    var options = { credentials: 'same-origin', signal: controller.signal, headers: {} };
    if (form !== undefined) {
      options.method = 'POST';
      options.headers = { 'Content-Type': 'application/json', 'X-CSRF-Token': token };
      options.body = JSON.stringify(form);
    }
    try {
      var response = await fetch('./api/registration/' + path, options);
      var data = await response.json();
      if (!response.ok) {
        var error = new Error(data.error || '请求失败');
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      if (form !== undefined && (!error.status || error.status >= 500)) {
        uncertain = true;
        throw new Error('结果待核对，请刷新查看申请或审计；注册可先尝试登录核对，不要直接重复提交');
      }
      throw error;
    } finally { clearTimeout(timer); }
  }

  async function bootstrap() {
    var data = await api('bootstrap');
    token = data.csrf;
    return data;
  }

  function message(text, bad) {
    var box = $('login-msg');
    box.textContent = text;
    box.className = 'login-msg ' + (bad ? 'bad' : 'ok');
    box.hidden = false;
    box.scrollIntoView({ block: 'nearest' });
  }

  function guest(register) {
    $('login-form').hidden = register;
    $('registration-view').hidden = !register;
    $('registration-account').hidden = true;
    $('registration-toggle').textContent = register ? '返回登录' : '没有账号？注册账号';
  }

  function button(text, action, parent) {
    var el = document.createElement('button');
    el.type = 'button'; el.className = 'btn'; el.textContent = text;
    el.addEventListener('click', action); parent.appendChild(el);
    return el;
  }

  async function account() {
    try {
      var data = await bootstrap(), a = data.account;
      $('registration-toggle').hidden = a.role !== 'guest';
      if (a.role === 'guest') return guest(false);
      $('login-form').hidden = true;
      $('registration-view').hidden = true;
      var box = $('registration-account');
      box.hidden = false; box.replaceChildren();
      var heading = document.createElement('h2');
      heading.textContent = a.name + (a.id ? ' · ' + (labels[a.state] || a.state) : ' · 已登录');
      box.appendChild(heading);
      var info = document.createElement('p');
      info.textContent = a.id ? '申请编号：' + a.request.id + (a.request.reason ? '\n审批说明：' + a.request.reason : '') : '当前账号可使用已获授权的业务模块。';
      box.appendChild(info);
      if (!a.id || a.state === 'readonly') {
        var link = document.createElement('a');
        link.href = '/dashboard/'; link.textContent = '返回平台'; box.appendChild(link);
      }
      button('刷新申请状态', account, box);
      button('退出账号', async function () {
        if (busy) return;
        busy = true;
        try { await api('logout', {}); window.location.assign('/__auth/access/'); }
        catch (e) { message(e.message, true); }
        finally { busy = false; }
      }, box);
      if (a.id && ['rejected', 'revoked'].indexOf(a.state) >= 0) {
        var form = document.createElement('form');
        form.method = 'post'; form.action = './api/registration/apply';
        var label = document.createElement('label');
        label.htmlFor = 'registration-reason'; label.textContent = '重新申请用途（必填）';
        var input = document.createElement('textarea');
        input.id = 'registration-reason'; input.name = 'purpose'; input.required = true; input.maxLength = 240;
        var submit = document.createElement('button');
        submit.type = 'submit'; submit.className = 'btn primary'; submit.textContent = '重新申请';
        form.append(label, input, submit); box.appendChild(form);
        form.addEventListener('submit', function (event) { submitForm(event, 'apply'); });
      }
    } catch (e) { message('申请状态读取失败：' + e.message + '。请刷新后核对。', true); }
  }

  async function submitForm(event, operation) {
    event.preventDefault();
    if (busy || uncertain) return;
    var form = event.currentTarget, submit = form.querySelector('button[type="submit"]');
    busy = true; submit.disabled = true;
    try {
      var values = Object.fromEntries(new FormData(form));
      if (operation === 'login') {
        values = { username: values.username, password: values.password };
        var result;
        try { result = await api('native-login', values); }
        catch (error) {
          if (error.status !== 401) throw error;
          result = await api('login', values);
        }
        if (!result.account.id || result.account.state === 'readonly') {
          window.location.assign($('login-next').value || '/dashboard/'); return;
        }
      } else { await api(operation, values); }
      form.reset();
      if (operation === 'register') {
        guest(false); message('注册成功，申请待审批。请登录查看进度。');
        $('login-form').querySelector('input[name="username"]').focus();
      } else { await account(); }
    } catch (e) { message(e.status === 401 && operation === 'login' ? '账号或密码错误，请检查后重试。' : e.message, true); }
    finally { busy = false; submit.disabled = uncertain; }
  }

  async function requests(main, after) {
    after = after || 0;
    main.innerHTML = '<h2>注册审批</h2><p role="status">正在读取申请…</p>';
    try {
      await bootstrap();
      var data = await api('requests?after=' + after);
      if (main.dataset.view !== 'registration') return;
      main.replaceChildren();
      var heading = document.createElement('h2'); heading.textContent = '注册审批'; main.appendChild(heading);
      var feedback = document.createElement('p'); feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
      var controls = document.createElement('div'); controls.className = 'registration-actions';
      var reasonLabel = document.createElement('label'); reasonLabel.htmlFor = 'registration-decision-reason'; reasonLabel.textContent = '审批原因（拒绝、撤销时必填）';
      var reason = document.createElement('textarea'); reason.id = 'registration-decision-reason'; reason.maxLength = 240;
      var selected = [];
      button('刷新申请', function () { if (!busy) requests(main, after); }, controls);
      main.append(controls, reasonLabel, reason, feedback);
      if (!data.items.length) feedback.textContent = '暂无注册申请。';
      data.items.forEach(function (row) {
        var card = document.createElement('article'); card.className = 'registration-row';
        var title = document.createElement('h3'); title.textContent = row.name + ' · ' + (labels[row.status] || row.status);
        var info = document.createElement('p'); info.textContent = row.team + ' / ' + row.purpose + '\n申请编号：' + row.id;
        card.append(title, info);
        if (['pending', 'approved'].indexOf(row.status) >= 0) {
          var label = document.createElement('label'), check = document.createElement('input');
          check.type = 'checkbox'; label.append(check, document.createTextNode('选择 ' + row.name)); card.prepend(label);
          selected.push({ row: row, check: check });
        }
        main.appendChild(card);
      });
      async function decide(action) {
        if (busy || uncertain) return;
        var items = selected.filter(function (x) { return x.check.checked; });
        if (!items.length) { feedback.textContent = '请先选择当前页的申请。'; return; }
        var text = reason.value.trim() || (action === 'approve' ? '一键通过（默认全局只读）' : '');
        if (!text) { feedback.textContent = '请填写审批原因。'; reason.focus(); return; }
        if (items.some(function (x) { return x.row.status !== (action === 'revoke' ? 'approved' : 'pending'); })) {
          feedback.textContent = '待审批和已批准账号请分开选择。'; return;
        }
        busy = true;
        document.querySelectorAll('.nav-item').forEach(function (el) { el.disabled = true; });
        main.querySelectorAll('button,input,textarea').forEach(function (el) { el.disabled = true; });
        var results = [];
        try {
          for (var item of items) {
            var row = item.row;
            var body = { request_id: row.id, version: row.version, reason: text };
            if (action !== 'revoke') body.action = action;
            try {
              await api(action === 'revoke' ? 'revoke' : 'decision', body);
              results.push(row.name + '：已完成');
            } catch (e) {
              results.push(row.name + '：' + e.message);
              if (!e.status || e.status >= 500 || [401, 403, 429].indexOf(e.status) >= 0) break;
            }
          }
        } finally {
          busy = false;
          document.querySelectorAll('.nav-item').forEach(function (el) { el.disabled = false; });
        }
        if (!uncertain) { await requests(main, after); }
        else { controls.querySelector('button').disabled = false; }
        var status = main.querySelector('[role="status"]');
        status.textContent = results.join('；') + '。已处理 ' + results.length + '/' + items.length + '，其余未执行。';
      }
      ['approve', 'reject', 'revoke'].forEach(function (action) {
        button({ approve: '通过选中申请', reject: '拒绝选中申请', revoke: '撤销选中授权' }[action], function () { decide(action); }, controls).disabled = uncertain;
      });
      if (data.items.length === 50) button('下一页', function () { if (!busy) requests(main, data.items[data.items.length - 1].cursor); }, controls);
      if (after) button('返回第一页', function () { if (!busy) requests(main, 0); }, controls);
      button('查看审批审计', async function () {
        try {
          var audit = await api('audit?after=0');
          feedback.textContent = audit.items.length ? audit.items.map(function (r) { return r.name + ' / ' + r.actor + ' / ' + r.action + ' / ' + r.reason; }).join('\n') : '暂无审批审计。';
        } catch (e) { feedback.textContent = e.message; }
      }, controls);
    } catch (e) {
      if (main.dataset.view !== 'registration') return;
      main.replaceChildren();
      var error = document.createElement('p'); error.setAttribute('role', 'status'); error.textContent = '读取失败：' + e.message; main.appendChild(error);
      button('重新读取', function () { if (!busy) requests(main, after); }, main);
    }
  }

  $('registration-toggle').addEventListener('click', function () {
    guest($('registration-view').hidden);
    ($('registration-view').hidden ? $('login-form') : $('registration-form')).querySelector('input[name="username"]').focus();
  });
  $('registration-form').addEventListener('submit', function (event) { submitForm(event, 'register'); });
  $('login-form').addEventListener('submit', function (event) { submitForm(event, 'login'); });
  window.FSRegistration = { account: account, requests: requests };
})();
