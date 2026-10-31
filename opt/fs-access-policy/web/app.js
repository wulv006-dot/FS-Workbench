/* FS 访问控制 IAM · 控制台前端
   零依赖、零外网。对外地址是 /__auth/access/，API 走 ./api/*；
   nginx 把这个前缀内部改写到后端的 /iam/，所以这里一律用相对路径。 */
(function () {
  'use strict';

  var API = './api/';
  var S = {
    view: 'members',
    data: null,
    role: null,      // 当前编辑的角色名
    draft: null,     // { resource: { action: true } }
    dirty: false,
    member: null,    // 抽屉里的成员
    isAdmin: false   // 来自 session.admin，决定抽屉里给不给「修改密码」
  };

  var $ = function (id) { return document.getElementById(id); };
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)FS_IAM_CSRF=([^;]+)/);
    return m ? m[1] : '';
  }
  function toast(msg, kind) {
    var el = $('toast');
    el.textContent = msg;
    el.className = 'toast ' + (kind || '');
    el.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.hidden = true; }, 3200);
  }

  function api(path, opts) {
    opts = opts || {};
    var conf = { method: opts.method || 'GET', credentials: 'same-origin', headers: {} };
    if (conf.method === 'POST') {
      conf.headers['Content-Type'] = 'application/json';
      conf.headers['X-CSRF-Token'] = csrf();
      conf.body = JSON.stringify(opts.body || {});
    }
    return fetch(API + path, conf).then(function (r) {
      return r.json().catch(function () { return { error: '服务器返回异常（HTTP ' + r.status + '）' }; })
        .then(function (j) {
          if (!r.ok) {
            var err = new Error(j.error || ('HTTP ' + r.status));
            err.payload = j;
            throw err;
          }
          return j;
        });
    });
  }

  /* ------------------------------------------------------------ 载入 */
  function load() {
    return api('overview').then(function (d) {
      S.data = d;
      $('who').textContent = d.policy.actor + (d.members.some(function (m) { return m.subject === d.policy.actor && m.admin; }) ? ' · 管理员' : '');
      $('nav-members').textContent = d.members.length;
      $('nav-roles').textContent = d.policy.roles.length;
      // 侧栏底部只放「一眼要看得到」的信息：版本、修订、谁什么时候改的。
      // 路径很长，单行省略 + title 兜完整值，否则会把侧栏底部顶成三四行。
      var fullPath = String(d.meta.path || '');
      var shortPath = fullPath.replace(/^\/opt\/auth-portal\/data\//, '');
      var stamp = String(d.meta.updatedAt || '').replace('T', ' ');
      if (stamp.length >= 16) stamp = stamp.slice(5, 16);
      var fullRev = String(d.meta.revision || '');
      $('side-foot').innerHTML =
        '策略版本 <b>#' + esc(d.meta.generation) + '</b> · 修订 <b class="mono" title="' + esc(fullRev) + '">' +
        esc(fullRev.slice(0, 8)) + '</b><br>' +
        '更新 <b>' + esc(stamp || '—') + '</b> · ' + esc(d.meta.updatedBy || '—') +
        '<span class="fp" title="' + esc(fullPath) + '">' + esc(shortPath) + '</span>';
      if (d.degraded) {
        S.degraded = d.degraded;
      }
      if (!S.role || !d.policy.roles.some(function (r) { return r.name === S.role; })) {
        S.role = (d.policy.roles[0] || {}).name;
        resetDraft();
      }
      $('loading') && $('loading').remove();
      render();
    }).catch(function (e) {
      $('main').innerHTML = '<div class="notice">载入失败：' + esc(e.message) +
        '。若提示未登录，请回到 <a href="../access/">门户登录页</a> 重新登录。</div>';
    });
  }

  function roleByName(name) {
    var list = (S.data && S.data.policy.roles) || [];
    for (var i = 0; i < list.length; i++) if (list[i].name === name) return list[i];
    return null;
  }

  function resetDraft() {
    var role = roleByName(S.role);
    S.draft = {};
    if (!role) return;
    (S.data.catalog || []).forEach(function (sec) {
      sec.resources.forEach(function (res) { S.draft[res.id] = {}; });
    });
    if (role.super) {
      Object.keys(S.draft).forEach(function (rid) {
        S.draft[rid] = { view: 1, edit: 1, execute: 1, deploy: 1, manage: 1 };
      });
    } else {
      (role.rules || []).forEach(function (rule) {
        var targets = rule.resources.indexOf('*') >= 0 ? Object.keys(S.draft) : rule.resources;
        targets.forEach(function (rid) {
          if (!S.draft[rid]) return;
          var acts = rule.actions.indexOf('*') >= 0 ? ['view', 'edit', 'execute', 'deploy', 'manage'] : rule.actions;
          acts.forEach(function (a) { S.draft[rid][a] = 1; });
        });
      });
    }
    S.dirty = false;
  }

  /* ------------------------------------------------------------ 渲染 */
  function render() {
    var main = $('main');
    main.dataset.view = S.view;
    document.querySelectorAll('.nav-item').forEach(function (b) {
      b.classList.toggle('active', b.dataset.view === S.view);
    });
    var banner = S.degraded
      ? '<div class="notice">策略引擎处于降级状态：' + esc(S.degraded) + '，当前按改造前的旧规则判定。</div>'
      : '';
    if (S.view === 'members') main.innerHTML = banner + viewMembers();
    else if (S.view === 'registration') {
      window.FSRegistration.requests(main);
      return;
    }
    else if (S.view === 'roles') main.innerHTML = banner + viewRoles();
    else if (S.view === 'check') main.innerHTML = banner + viewCheck();
    else main.innerHTML = banner + viewAudit();
    bind();
    if (S.view === 'audit') loadAudit();
  }

  function statCard(k, v, sub) {
    return '<div class="stat"><div class="k">' + esc(k) + '</div><div class="v">' + esc(v) +
      (sub ? '<small>' + esc(sub) + '</small>' : '') + '</div></div>';
  }

  function viewMembers() {
    var d = S.data, admins = d.members.filter(function (m) { return m.admin; }).length;
    var reg = d.members.filter(function (m) { return m.kind === 'registered'; }).length;
    var none = d.members.filter(function (m) { return !m.roles.length; }).length;
    var rows = d.members.map(function (m) {
      var tags = m.roles.length
        ? m.roles.map(function (r) {
            var role = roleByName(r) || { super: false, label: r };
            return '<span class="tag ' + (role.super ? 'super' : 'brand') + '">' + esc(role.label || r) + '</span>';
          }).join('')
        : '<span class="tag bad">未分配角色</span>';
      var login = m.lastLogin
        ? '<span class="dim">' + esc(m.lastLogin.at.slice(5)) + '</span><br><span class="dim mono">' + esc(m.lastLogin.ip) + '</span>'
        : '<span class="dim">—</span>';
      return '<tr>' +
        '<td><div class="name">' + esc(m.name) + '</div><div class="dim mono">' + esc(m.subject) + '</div></td>' +
        '<td><span class="tag">' + esc(m.source) + '</span>' + (m.kind === 'native' ? '<div class="dim">' + esc(m.groups.join(' / ')) + '</div>' : '') + '</td>' +
        '<td>' + tags + '</td>' +
        '<td>' + (m.enabled ? '<span class="tag ok">启用</span>' : '<span class="tag bad">停用</span>') + '</td>' +
        '<td><span class="dim">可读 ' + m.accessCount + ' 个资源' +
          (m.writable.length ? '，可写 ' + m.writable.length + ' 个' : '') + '</span></td>' +
        '<td>' + login + '</td>' +
        '<td style="text-align:right"><button class="btn sm" data-member="' + esc(m.subject) + '">管理</button></td>' +
        '</tr>';
    }).join('');

    return '' +
      '<div class="page-head"><div><div class="eyebrow">MEMBER</div><h1>成员管理</h1>' +
      '<p>成员来自门户统一登录（内置账号）与注册审批（注册账号）。点「管理」分配<b>角色</b>，也可以直接设新密码。</p></div>' +
      '</div>' +
      '<div class="stats">' + statCard('成员总数', d.members.length) + statCard('管理员', admins) +
      statCard('可授权角色', d.policy.roles.length) + statCard('未分配角色', none, '人') +
      (reg ? statCard('注册账号', reg) : '') + '</div>' +
      '<div class="card"><div class="card-head"><div><h2>成员列表</h2>' +
      '<div class="sub">「可写」= 该成员在多少个资源上拿到了改数据 / 执行 / 部署 / 授权</div></div>' +
      '<div class="actions"><button class="btn sm" id="btn-refresh">刷新</button></div></div>' +
      '<div class="card-body"><table><thead><tr><th>账号</th><th>来源</th><th>角色</th><th>状态</th>' +
      '<th>权限范围</th><th>最近登录</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></div></div>';
  }

  function viewRoles() {
    var d = S.data, role = roleByName(S.role);
    var list = d.policy.roles.map(function (r) {
      return '<button class="role-item' + (r.name === S.role ? ' on' : '') + '" data-role="' + esc(r.name) + '">' +
        '<span class="rn">' + esc(r.label || r.name) +
        (r.super ? ' <span class="tag super">超级</span>' : '') +
        (r.builtin ? ' <span class="tag">内置</span>' : '') + '</span>' +
        '<span class="rd">' + esc(r.desc || '—') + '</span>' +
        '<span class="rm">' + r.members.length + ' 名成员</span></button>';
    }).join('');

    return '' +
      '<div class="page-head"><div><div class="eyebrow">ROLE &amp; POLICY</div><h1>角色与策略</h1>' +
      '<p>按工作区分配：球类运营、RPG 运营、营销运营等。成员可兼任多个工作区；平台管理与部署单独授权。</p></div>' +
      '<div class="actions"><button class="btn" id="btn-new-role">新建角色</button></div></div>' +
      '<div class="roles-grid">' +
      '<div class="role-list">' + list + '</div>' +
      '<div class="card">' + (role ? matrixHtml(role) : '<div class="empty">还没有角色</div>') + '</div>' +
      '</div>';
  }

  function matrixHtml(role) {
    var cols = S.data.actions, cat = S.data.catalog;
    var head = '<tr><th style="min-width:210px">资源</th>' + cols.map(function (a) {
      return '<th style="text-align:center;width:74px">' + esc(a.label) + '</th>';
    }).join('') + '<th style="width:80px"></th></tr>';

    var body = cat.map(function (sec) {
      var inner = sec.resources.map(function (res) {
        var cells = cols.map(function (a) {
          var on = !!(S.draft[res.id] && S.draft[res.id][a.id]);
          var fixed = role.super;
          return '<td class="c"><input class="chk" type="checkbox" data-res="' + esc(res.id) +
            '" data-act="' + esc(a.id) + '"' + (on ? ' checked' : '') +
            (fixed ? ' disabled' : '') + '></td>';
        }).join('');
        return '<tr><td class="rname">' + esc(res.label) + '<span class="rid mono">' + esc(res.id) + '</span></td>' +
          cells + '<td></td></tr>';
      }).join('');
      return '<tr class="sec-row"><td colspan="' + (cols.length + 2) + '">' + esc(sec.label) + '</td></tr>' + inner;
    }).join('');

    var members = role.members.length
      ? role.members.map(function (m) { return '<span class="tag">' + esc(m) + '</span>'; }).join('')
      : '<span class="dim">还没有成员使用这个角色</span>';

    return '' +
      '<div class="card-head"><div><h2>' + esc(role.label || role.name) +
      (role.super ? ' <span class="tag super">超级角色</span>' : '') + '</h2>' +
      '<div class="sub mono">' + esc(role.name) + ' · ' + esc(role.desc || '无说明') + '</div></div>' +
      '<div class="actions">' +
      (role.super ? '' : '<button class="btn sm" id="btn-del-role">删除角色</button>') +
      '<button class="btn primary sm" id="btn-save-role" disabled>保存</button></div></div>' +
      (role.super
        ? '<div class="notice" style="margin:14px">这是超级角色：拥有全部资源与全部动作，不能降级。它能做的唯一一件事是「把管理员身份分给别人」，所以请谨慎授予。</div>'
        : '<div class="matrix-tools">' +
          '<span class="hint">快捷：</span>' +
          '<button class="btn sm" data-quick="view">全部只读</button>' +
          '<button class="btn sm" data-quick="rw">可读可改</button>' +
          '<button class="btn sm" data-quick="rwx">可读可改可跑</button>' +
          '<span class="sep"></span>' +
          '<button class="btn sm" data-quick="none">清空</button>' +
          '<span class="sep"></span><span class="hint" id="dirty-hint">未修改</span>' +
          '</div>') +
      '<div class="matrix"><table><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>' +
      '<div class="kv"><dt>使用成员</dt><dd>' + members + '</dd></div>';
  }

  function viewCheck() {
    var opts = S.data.members.map(function (m) {
      return '<option value="' + esc(m.subject) + '">' + esc(m.name) + (m.admin ? '（管理员）' : '') + '</option>';
    }).join('');
    return '' +
      '<div class="page-head"><div><div class="eyebrow">SIMULATOR</div><h1>权限自检</h1>' +
      '<p>给一条真实请求，看看系统到底会不会放行、走的是哪条规则。排障时先来这里。</p></div></div>' +
      '<div class="card"><form class="check-form" id="check-form">' +
      '<label class="fld">成员<select id="ck-subject">' + opts + '</select></label>' +
      '<label class="fld">方法<select id="ck-method"><option>GET</option><option>POST</option><option>PATCH</option><option>PUT</option><option>DELETE</option></select></label>' +
      '<label class="fld">路径<input id="ck-uri" value="/d4/api/price" placeholder="/d4/api/price"></label>' +
      '<label class="fld">通道<select id="ck-group"><option value="">普通</option><option value="deploy">部署</option></select></label>' +
      '<button class="btn primary" type="submit">判定</button>' +
      '</form><div id="ck-result"></div></div>';
  }

  function viewAudit() {
    return '' +
      '<div class="page-head"><div><div class="eyebrow">AUDIT</div><h1>授权变更审计</h1>' +
      '<p>每一次角色与绑定的改动都会留痕：谁、什么时候、把谁从什么改成了什么。</p></div>' +
      '<div class="actions"><button class="btn sm" id="btn-refresh-audit">刷新</button></div></div>' +
      '<div class="card"><div class="card-body timeline" id="audit-list"><div class="empty">载入中…</div></div></div>';
  }

  function loadAudit() {
    api('audit?limit=150').then(function (d) {
      var el = $('audit-list');
      if (!el) return;
      if (!d.entries.length) { el.innerHTML = '<div class="empty">还没有授权变更记录</div>'; return; }
      el.innerHTML = d.entries.map(function (e) {
        var chg = (e.changes || []).map(function (c) {
          if (c.op === 'member.roles') return '<span class="chg"><b>' + esc(c.subject) + '</b> ' +
            esc((c.from || []).join(',') || '无') + ' → ' + esc((c.to || []).join(',') || '无') + '</span>';
          if (c.op === 'role.update') return '<span class="chg">角色改动 <b>' + esc(c.role) + '</b></span>';
          if (c.op === 'role.add') return '<span class="chg">新增角色 <b>' + esc(c.role) + '</b></span>';
          if (c.op === 'role.remove') return '<span class="chg">删除角色 <b>' + esc(c.role) + '</b></span>';
          return '<span class="chg">' + esc(JSON.stringify(c)) + '</span>';
        }).join('');
        return '<div class="tl-item"><div class="tl-time">' + esc(e.at) + '</div><div class="tl-main">' +
          '<div class="tl-title">' + esc(e.actor || '?') + ' · ' + esc(e.note || e.kind) + '</div>' +
          '<div class="tl-sub">策略版本 #' + esc(e.generation) + ' · 修订 <span class="mono">' + esc(e.revision) + '</span></div>' +
          (chg ? '<div class="tl-changes">' + chg + '</div>' : '') +
          '</div></div>';
      }).join('');
    }).catch(function (e) {
      var el = $('audit-list');
      if (el) el.innerHTML = '<div class="empty">载入失败：' + esc(e.message) + '</div>';
    });
  }

  /* ------------------------------------------------------------ 交互 */
  function bind() {
    document.querySelectorAll('[data-role]').forEach(function (b) {
      b.onclick = function () {
        if (S.dirty && !confirm('当前角色还没保存，切换会丢失改动，继续？')) return;
        S.role = b.dataset.role; resetDraft(); render();
      };
    });
    document.querySelectorAll('[data-member]').forEach(function (b) {
      b.onclick = function () { openMember(b.dataset.member); };
    });
    var rf = $('btn-refresh');
    if (rf) rf.onclick = function () { load(); };
    var ra = $('btn-refresh-audit');
    if (ra) ra.onclick = loadAudit;
    var nr = $('btn-new-role');
    if (nr) nr.onclick = function () { $('role-dialog').showModal(); };
    var sr = $('btn-save-role');
    if (sr) sr.onclick = saveRole;
    var dr = $('btn-del-role');
    if (dr) dr.onclick = deleteRole;

    document.querySelectorAll('.matrix .chk').forEach(function (c) {
      c.onchange = function () {
        var rid = c.dataset.res, act = c.dataset.act;
        S.draft[rid] = S.draft[rid] || {};
        if (c.checked) S.draft[rid][act] = 1; else delete S.draft[rid][act];
        S.dirty = true;
        var hint = $('dirty-hint'); if (hint) hint.textContent = '有未保存改动';
        var btn = $('btn-save-role'); if (btn) btn.disabled = false;
      };
    });

    document.querySelectorAll('[data-quick]').forEach(function (b) {
      b.onclick = function () {
        var mode = b.dataset.quick;
        Object.keys(S.draft).forEach(function (rid) {
          if (mode === 'none') { S.draft[rid] = {}; return; }
          if (rid === 'identity') { S.draft[rid] = { view: 1 }; return; }
          var acts = { view: 1 };
          if (mode !== 'view') acts.edit = 1;
          if (mode === 'rwx') acts.execute = 1;
          S.draft[rid] = acts;
        });
        S.dirty = true;
        render();
        var btn = $('btn-save-role'); if (btn) btn.disabled = false;
      };
    });

    var cf = $('check-form');
    if (cf) cf.onsubmit = function (ev) { ev.preventDefault(); runCheck(); };
  }

  function draftRules() {
    var groups = {};
    Object.keys(S.draft).forEach(function (rid) {
      var acts = Object.keys(S.draft[rid] || {}).sort();
      if (!acts.length) return;
      var key = acts.join(',');
      (groups[key] = groups[key] || []).push(rid);
    });
    return Object.keys(groups).map(function (k) {
      return { resources: groups[k].sort(), actions: k.split(',') };
    });
  }

  function saveRole() {
    var role = roleByName(S.role);
    if (!role) return;
    var btn = $('btn-save-role');
    btn.disabled = true; btn.textContent = '保存中…';
    api('role/save', {
      method: 'POST',
      body: {
        name: role.name, label: role.label, desc: role.desc,
        super: !!role.super, rules: draftRules(), revision: S.data.meta.revision
      }
    }).then(function () {
      toast('已保存「' + (role.label || role.name) + '」的权限', 'ok');
      return load();
    }).catch(function (e) {
      toast(e.message, 'bad');
      btn.disabled = false; btn.textContent = '保存';
    });
  }

  function deleteRole() {
    var role = roleByName(S.role);
    if (!role) return;
    if (!confirm('删除角色「' + (role.label || role.name) + '」？这个操作会写进审计。')) return;
    api('role/delete', { method: 'POST', body: { name: role.name, revision: S.data.meta.revision } })
      .then(function () { toast('角色已删除', 'ok'); S.role = null; return load(); })
      .catch(function (e) { toast(e.message, 'bad'); });
  }

  function openMember(subject) {
    var m = null;
    S.data.members.forEach(function (x) { if (x.subject === subject) m = x; });
    if (!m) return;
    S.member = m;
    $('drawer-title').textContent = m.name;
    $('drawer-sub').textContent = m.source + ' · ' + m.subject + (m.lastLogin ? ' · 最近登录 ' + m.lastLogin.at : '');
    $('drawer-hint').textContent = '按工作区选择运营角色，可同时负责多个工作区；只读账号选择只读访客';
    var roles = S.data.policy.roles.slice().sort(function (a, b) {
      return (b.super ? 1 : 0) - (a.super ? 1 : 0) || b.rules.length - a.rules.length;
    });
    var isSelf = m.name === S.data.policy.actor;
    // 改密码是独立动作：不需要原密码、不需要二次确认、不填原因 —— 填新密码点更新即可。
    // 放在抽屉最上方：角色列表有 9 项、约 600px 高，放下面就得先滚到底才看得见。
    var pw = S.isAdmin
      ? '<div class="pw-block">' +
          '<div class="pw-head"><b>修改密码</b><span class="hint">仅管理员</span></div>' +
          '<div class="pw-row">' +
            '<input type="password" id="pw-input" autocomplete="new-password" maxlength="128" placeholder="新密码，至少 12 位">' +
            '<button class="btn primary" id="pw-save" type="button">更新密码</button>' +
          '</div>' +
          '<p class="pw-hint">不需要原密码。更新后该账号已登录的会话立即失效' +
          (isSelf ? '，<b>包括你自己 —— 需要用新密码重新登录</b>' : '') + '。</p>' +
        '</div>'
      : '';
    var writableTags = m.writable.length > 6
      ? m.writable.slice(0, 6).map(function (r) {
          return '<span class="tag warn">' + esc(r) + '</span>';
        }).join('') + '<span class="tag">等 ' + m.writable.length + ' 个</span>'
      : m.writable.map(function (r) {
          return '<span class="tag warn">' + esc(r) + '</span>';
        }).join('');
    var extra = (m.extraGrants || []).length
      ? '<div class="notice"><label><input type="checkbox" id="keep-extra-grants" checked> 保留原有补充授权</label><p class="hint">' +
        esc(m.extraGrants.map(function(g){return g.resources.map(function(id){var r=S.data.resources.find(function(x){return x.id===id;});return r?r.label:id;}).join('、')+'：'+g.actions.map(function(a){var x=S.data.actions.find(function(x){return x.id===a;});return x?x.label:a;}).join('、');}).join('；')) +
        '。取消勾选并保存后，仅按所选角色授权。</p></div>' : '';
    $('drawer-body').innerHTML = pw + extra +
        '<div class="matrix-mini">' + (m.writable.length
          ? '<span class="hint">当前可写：</span>' + writableTags
          : '<span class="hint">当前没有任何写权限</span>') + '</div>' +
        '<div class="role-pick">' + roles.map(function (r) {
          var on = m.roles.indexOf(r.name) >= 0;
          return '<label class="' + (on ? 'on' : '') + '">' +
            '<input type="checkbox" class="chk" value="' + esc(r.name) + '"' + (on ? ' checked' : '') + '>' +
            '<span><span class="rt">' + esc(r.label || r.name) +
            (r.super ? ' <span class="tag super">超级</span>' : '') + '</span>' +
            '<span class="rs">' + esc(r.summary) + '</span></span></label>';
        }).join('') + '</div>';
    document.querySelectorAll('#drawer-body .chk').forEach(function (c) {
      c.onchange = function () { c.closest('label').classList.toggle('on', c.checked); };
    });
    var pwBtn = $('pw-save');
    if (pwBtn) {
      var pwInput = $('pw-input');
      pwBtn.onclick = function () { setPassword(m, pwInput, pwBtn); };
      pwInput.onkeydown = function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); setPassword(m, pwInput, pwBtn); }
      };
    }
    $('drawer').hidden = false;
    $('scrim').hidden = false;
  }

  function setPassword(m, input, btn) {
    var v = input.value;
    // 12 位的下限不是产品偏好：底层 password_hash / password_matches 都硬校验
    // 12–128，短于此会写进一个连自己都验不过的哈希，账号当场被锁死。
    if (v.length < 12) { input.focus(); toast('新密码至少 12 位', 'bad'); return; }
    if (v.length > 128) { toast('新密码最多 128 位', 'bad'); return; }
    btn.disabled = true; btn.textContent = '更新中…';
    api('member/password', { method: 'POST', body: { subject: m.kind === 'native' ? 'native:' + m.name : m.subject, password: v } })
      .then(function (r) {
        input.value = '';
        if (r.selfChanged) {
          toast('密码已更新，你的登录已失效，请用新密码重新登录', 'ok');
          setTimeout(function () { window.location.href = './'; }, 1400);
          return;
        }
        toast('「' + m.name + '」的密码已更新', 'ok');
        btn.disabled = false; btn.textContent = '更新密码';
      })
      .catch(function (e) {
        btn.disabled = false; btn.textContent = '更新密码';
        toast(e.message, 'bad');
      });
  }

  function closeDrawer() {
    $('drawer').hidden = true;
    $('scrim').hidden = true;
    S.member = null;
  }

  function saveMember() {
    var m = S.member;
    if (!m) return;
    var picked = [];
    document.querySelectorAll('#drawer-body .chk').forEach(function (c) {
      if (c.checked) picked.push(c.value);
    });
    api('member/roles', {
      method: 'POST',
      body: { subject: m.subject, roles: picked, revision: S.data.meta.revision,
        keep_extra_grants: !$('keep-extra-grants') || $('keep-extra-grants').checked }
    }).then(function () {
      toast('已更新「' + m.name + '」的角色', 'ok');
      closeDrawer();
      return load();
    }).catch(function (e) { toast(e.message, 'bad'); });
  }

  function runCheck() {
    var q = 'explain?subject=' + encodeURIComponent($('ck-subject').value) +
      '&method=' + encodeURIComponent($('ck-method').value) +
      '&uri=' + encodeURIComponent($('ck-uri').value) +
      '&group=' + encodeURIComponent($('ck-group').value);
    api(q).then(function (d) {
      var v = d.decision;
      var allow = v.code === 200;
      // 决策链不再是纯装饰的六个空标签，每一步都带上真实值 —— 排障时能直接顺着读下来。
      var chain = [
        ['成员', v.subject || '—'],
        ['角色', (v.roles || []).join(' + ') || '未绑定'],
        ['规则', (v.matched || []).join('、') || '无'],
        ['资源', v.resource || '—'],
        ['动作', v.action || '—'],
        ['结论', String(v.code)]
      ];
      var hits = (v.matched || []).join('、') || '无';
      $('ck-result').innerHTML =
        '<div class="verdict"><div class="big ' + (allow ? 'allow' : 'deny') + '">' +
        (allow ? '放行' : (v.code === 401 ? '未登录' : '拒绝')) + '</div>' +
        '<div><div style="font-size:15px;font-weight:600">' +
        (allow ? '这条请求会被放行' : '这条请求会被拦住') + '</div>' +
        '<div class="dim" style="margin-top:4px">' + esc(v.reason) + '</div></div></div>' +
        '<dl class="kv">' +
        '<dt>成员</dt><dd>' + esc(v.subject || '—') + '</dd>' +
        '<dt>绑定角色</dt><dd>' + ((v.roles || []).map(function (r) { return '<span class="tag brand">' + esc(r) + '</span>'; }).join('') || '<span class="dim">无</span>') + '</dd>' +
        '<dt>命中规则</dt><dd class="mono">' + esc(hits) + '</dd>' +
        '<dt>解析资源</dt><dd>' + esc(v.resourceLabel || v.resource) + ' <span class="dim mono">' + esc(v.resource) + '</span></dd>' +
        '<dt>所需动作</dt><dd>' + esc(v.actionLabel || v.action) + ' <span class="dim mono">' + esc(v.action) + '</span></dd>' +
        '<dt>状态码</dt><dd class="mono">' + esc(v.code) + '</dd>' +
        '</dl>' +
        '<div class="pathbar">' + chain.map(function (p, i) {
          return '<span class="step' + (i === chain.length - 1 ? ' on' : '') + '"><b>' + esc(p[0]) + '</b>' +
            esc(p[1]) + '</span>' + (i < chain.length - 1 ? '<span class="arrow">›</span>' : '');
        }).join('') + '</div>';
    }).catch(function (e) {
      $('ck-result').innerHTML = '<div class="empty">判定失败：' + esc(e.message) + '</div>';
    });
  }

  /* ------------------------------------------------------------ 启动 */
  document.querySelectorAll('.nav-item').forEach(function (b) {
    b.onclick = function () { S.view = b.dataset.view; render(); };
  });
  $('drawer-close').onclick = closeDrawer;
  $('drawer-cancel').onclick = closeDrawer;
  $('drawer-save').onclick = saveMember;
  $('scrim').onclick = closeDrawer;
  $('role-form').addEventListener('submit', function (ev) {
    var btn = ev.submitter;
    if (!btn || btn.value !== 'ok') return;
    ev.preventDefault();
    var name = $('role-name').value.trim();
    api('role/save', {
      method: 'POST',
      body: {
        name: name, label: $('role-label').value.trim(), desc: $('role-desc').value.trim(),
        super: false, rules: [{ resources: ['*'], actions: ['view'] }],
        revision: S.data.meta.revision
      }
    }).then(function () {
      $('role-dialog').close();
      S.role = name; S.view = 'roles';
      toast('角色已创建，请勾选它被允许的资源', 'ok');
      return load();
    }).catch(function (e) { toast(e.message, 'bad'); });
  });
  /* ------------------------------------------------------------ 共用全站导航
     和 /dashboard/ 下所有页面用同一份脚本、同一份清单（唯一真源 /var/www/hub/hubnav.js），
     不再自己画一套顶栏/侧栏。只在确认已登录且是管理员之后挂：
     这个 URL 同时是全站未登录的登录落点，不能给匿名访问者摆出整条导航。
     版本号与 nginx 里 sub_filter 注入的那个保持一致，共用浏览器缓存。 */
  var HUBNAV_SRC = '/__hub/hubnav.js?v=hermes-nav-20261020-v2';
  function mountSharedNav() {
    if (window.__fsIamHubNav) return;
    window.__fsIamHubNav = true;
    var s = document.createElement('script');
    s.src = HUBNAV_SRC;
    document.body.appendChild(s);
  }

  /* ------------------------------------------------------------ 登录 / 启动 */
  function showLogin() {
    var q = {};
    window.location.search.replace(/^\?/, '').split('&').forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf('=');
      var k = i < 0 ? kv : kv.slice(0, i);
      q[decodeURIComponent(k)] = i < 0 ? '' : decodeURIComponent(kv.slice(i + 1).replace(/\+/g, ' '));
    });

    // next 只接受站内绝对路径，杜绝 //evil.com、/\evil.com 这类外跳。
    var nxt = q.next || '';
    if (!/^\/[^\/\\]/.test(nxt)) nxt = '/__auth/access/';

    $('login-next').value = nxt;
    $('login-view').hidden = false;
    $('app-view').hidden = true;

    var map = {
      noperm: '这个账号没有访问「账号与权限」的权限，请换一个有管理员权限的账号登录。',
      expired: '登录状态已过期，请重新登录。',
      bad: '账号或密码不正确，请重试。',
      locked: '尝试次数过多，该账号已被临时锁定，请稍后再试。',
      csrf: '请求格式不正确，请重新提交。',
      badreq: '请求格式不正确，请重新提交。'
    };
    var box = $('login-msg');
    if (q.err && map[q.err]) { box.textContent = map[q.err]; box.className = 'login-msg bad'; box.hidden = false; }
    else if (q.msg) { box.textContent = q.msg; box.className = 'login-msg ok'; box.hidden = false; }
    else { box.hidden = true; }
    window.FSRegistration.account();
  }

  function boot() {
    api('session').then(function (s) {
      // 服务端已挡住非管理员，这里只是兜底：没有 user 或 admin=false 就回登录卡。
      if (!s || !s.user || !s.admin) return showLogin();
      S.isAdmin = !!s.admin;
      $('login-view').hidden = true;
      $('app-view').hidden = false;
      mountSharedNav();
      load();
    }).catch(function (e) {
      var j = e.payload || {};
      if (j.detail && j.detail.code === 403) {
        // 已登录但没权限：不要把登录框再摆出来制造「我明明登录了」的错觉。
        return showLogin();
      }
      showLogin();
    });
  }

  window.addEventListener('beforeunload', function (ev) {
    if (S.dirty) { ev.preventDefault(); ev.returnValue = ''; }
  });

  boot();
})();
