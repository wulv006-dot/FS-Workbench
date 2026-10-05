/* IGGM 抓取工具 Web 版 · 前端逻辑（零外部依赖） */
(function () {
  var CATS = [];
  var GAME = '';
  var SITE = '';
  var WHO = localStorage.getItem('iggm_who') || '';

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  var SITES = { iggm: 'IGGM', aoeah: 'AOEAH', u4gm: 'U4GM' };
  function siteBadge(s) {
    var n = SITES[s] || (s || '?');
    return '<span class="sitebadge site-' + esc(s || 'x') + '">' + esc(n) + '</span>';
  }

  async function api(url, opts) {
    var o = opts || {};
    o.headers = o.headers || { 'Content-Type': 'application/json' };
    var r = await fetch(url, o);
    if (r.status === 401) { location.reload(); return null; }
    return r.json();
  }

  var STATUS = { queued: '排队中', running: '抓取中', done: '已完成', failed: '失败', cancelled: '已中止' };

  function elapsed(t) {
    if (!t.created) return '';
    var a = new Date(t.created.replace(' ', 'T')).getTime();
    var b = t.finished ? new Date(t.finished.replace(' ', 'T')).getTime() : Date.now();
    var s = Math.max(0, Math.round((b - a) / 1000));
    return s < 60 ? s + 's' : Math.floor(s / 60) + 'm' + ('0' + (s % 60)).slice(-2) + 's';
  }

  function whoOf(t) { return t.submitter ? esc(t.submitter) : '<span class="anon">匿名</span>'; }

  /* ---------------- 我的名字 ---------------- */
  $('who').value = WHO;
  $('who').oninput = function () {
    WHO = $('who').value.trim();
    localStorage.setItem('iggm_who', WHO);
  };

  /* ---------------- 解析品类 ---------------- */
  $('btnDiscover').onclick = async function () {
    var url = $('url').value.trim();
    if (!url) { $('discoverErr').textContent = '请先填 URL'; return; }
    var btn = this;
    btn.disabled = true; btn.textContent = '解析中…';
    $('discoverErr').textContent = '';
    var res = await api('/api/discover', { method: 'POST', body: JSON.stringify({ url: url }) });
    btn.disabled = false; btn.textContent = '解析品类';
    if (!res || !res.ok) {
      $('discoverErr').textContent = (res && res.error) || '解析失败，请检查 URL 或稍后重试';
      return;
    }
    CATS = res.categories || [];
    GAME = res.game || '';
    SITE = res.site || '';
    $('gameName').textContent = GAME;
    $('siteBadge').textContent = SITES[SITE] || SITE || '?';
    $('siteBadge').className = 'sitebadge site-' + (SITE || 'x');
    renderCats();
    $('cateBox').style.display = '';
  };

  function renderCats() {
    var box = $('cates');
    box.innerHTML = '';
    CATS.forEach(function (u) {
      var name = u.replace(/\/+$/, '').split('/').pop();
      var label = document.createElement('label');
      label.className = 'cate sel';
      var cb = document.createElement('input');
      cb.type = 'checkbox'; cb.value = u; cb.checked = true;
      cb.onchange = function () { label.className = cb.checked ? 'cate sel' : 'cate'; };
      label.appendChild(cb);
      label.appendChild(document.createTextNode(name));
      box.appendChild(label);
    });
    $('cateCount').textContent = '共 ' + CATS.length + ' 个品类';
  }

  function setAll(v) {
    document.querySelectorAll('#cates input').forEach(function (i) {
      i.checked = v;
      i.parentNode.className = v ? 'cate sel' : 'cate';
    });
  }
  $('btnAll').onclick = function () { setAll(true); };
  $('btnNone').onclick = function () { setAll(false); };

  /* ---------------- 提交任务 ---------------- */
  $('btnStart').onclick = async function () {
    var sel = [];
    document.querySelectorAll('#cates input:checked').forEach(function (i) { sel.push(i.value); });
    if (!sel.length) { alert('至少勾选一个品类'); return; }
    var btn = this;
    btn.disabled = true;
    var res = await api('/api/scrape', {
      method: 'POST',
      body: JSON.stringify({
        url: $('url').value.trim(), categories: sel,
        game: GAME, submitter: WHO, site: SITE
      })
    });
    btn.disabled = false;
    if (!res || !res.ok) { alert((res && res.error) || '提交失败'); return; }
    poll();
  };

  /* ---------------- 停止 / 日志 ---------------- */
  async function stopTask(id, name) {
    if (!confirm('确定停止「' + name + '」？已抓到的数据仍会导出。')) return;
    await api('/api/cancel', { method: 'POST', body: JSON.stringify({ task_id: id }) });
    poll();
  }

  function openLogs(id) {
    $('mask').classList.add('show');
    $('logBox').textContent = '加载中…';
    api('/api/logs?task_id=' + id).then(function (r) {
      $('logBox').textContent = (r && r.ok)
        ? ((r.logs || []).join('\n') || '（暂无日志）')
        : '加载失败';
    });
  }
  $('btnCloseLog').onclick = function () { $('mask').classList.remove('show'); };
  $('mask').onclick = function (e) {
    if (e.target.id === 'mask') $('mask').classList.remove('show');
  };

  /* ---------------- 队列渲染 ---------------- */
  function renderQueue(res) {
    var running = null, waiting = [];
    (res.active || []).forEach(function (t) {
      if (t.status === 'running') running = t; else waiting.push(t);
    });
    waiting.sort(function (a, b) { return a.queue_pos - b.queue_pos; });

    $('qStat').textContent = running
      ? '抓取中 · 排队 ' + waiting.length
      : (waiting.length ? '排队 ' + waiting.length : '空闲');
    $('qStat').className = 'pill' + (running ? ' on' : '');

    var box = $('qRunning');
    if (!running) {
      box.innerHTML = '';
    } else {
      box.innerHTML =
        '<div class="qitem run">' +
        '<div class="qhead">' +
        '<span class="qbadge now">正在抓取</span>' +
        siteBadge(running.site) +
        '<span class="gname">' + esc(running.game || gameSlug(running.url)) + '</span>' +
        '<span class="qmeta">' + (running.categories || []).length + ' 个品类 · 提交人 ' + whoOf(running) + '</span>' +
        '<span class="spacer" style="flex:1"></span>' +
        '<span class="qtime">' + elapsed(running) + '</span>' +
        '</div>' +
        '<div class="pbar' + (running.status === 'failed' ? ' fail' : '') + '"><div style="width:' + (running.progress || 0) + '%"></div></div>' +
        '<div class="prow">' +
        '<span class="detail">' + esc(running.detail || '—') + '</span>' +
        '<span class="pct">' + (running.progress || 0) + '%</span>' +
        '</div>' +
        '<div class="row" style="margin-top:8px">' +
        '<button class="small danger" data-stop="' + esc(running.id) + '" data-name="' + esc(running.game || gameSlug(running.url)) + '">停止</button> ' +
        '<button class="small" data-logs="' + esc(running.id) + '">日志</button>' +
        '<span class="hint" style="margin:0 0 0 8px">已抓 ' + (running.rows || 0) + ' 行 · 任务 ' + esc(running.id) + '</span>' +
        '</div></div>';
    }

    var w = $('qWaiting');
    if (!waiting.length) {
      w.innerHTML = '';
    } else {
      w.innerHTML = '<div class="qtitle">排队中（' + waiting.length + '）</div>' +
        waiting.map(function (t) {
          return '<div class="qitem">' +
            '<span class="qbadge">#' + t.queue_pos + '</span>' +
            siteBadge(t.site) +
            '<span class="gname sm">' + esc(t.game || gameSlug(t.url)) + '</span>' +
            '<span class="qmeta">' + (t.categories || []).length + ' 个品类 · 提交人 ' + whoOf(t) + '</span>' +
            '<span class="spacer" style="flex:1"></span>' +
            '<span class="qtime">已等待 ' + elapsed(t) + '</span>' +
            '<button class="small danger" data-stop="' + esc(t.id) + '" data-name="' + esc(t.game || gameSlug(t.url)) + '">取消</button>' +
            '</div>';
        }).join('');
    }

    $('qEmpty').style.display = (running || waiting.length) ? 'none' : '';

    document.querySelectorAll('[data-stop]').forEach(function (b) {
      b.onclick = function () { stopTask(b.getAttribute('data-stop'), b.getAttribute('data-name')); };
    });
    document.querySelectorAll('[data-logs]').forEach(function (b) {
      b.onclick = function () { openLogs(b.getAttribute('data-logs')); };
    });
  }

  function gameSlug(url) {
    return (url || '').replace(/\/+$/, '').split('/').pop() || '—';
  }

  /* ---------------- 历史表格 ---------------- */
  function renderTable(res) {
    var map = {};
    (res.history || []).forEach(function (t) { map[t.id] = t; });
    var list = Object.keys(map).map(function (k) { return map[k]; })
      .sort(function (a, b) { return (b.created || '').localeCompare(a.created || ''); });

    $('emptyTip').style.display = list.length ? 'none' : '';
    $('taskRows').innerHTML = list.map(function (t) {
      var st = STATUS[t.status] || t.status;
      var canDownload = (t.status === 'done' || t.status === 'cancelled') && t.file;
      var canStop = (t.status === 'queued' || t.status === 'running');
      var name = t.game || gameSlug(t.url);
      return '<tr>' +
        '<td>' + siteBadge(t.site) + ' <span class="gname sm">' + esc(name) + '</span>' +
        '<div class="qmeta">' + esc(t.detail || '') + '</div></td>' +
        '<td>' + whoOf(t) + '</td>' +
        '<td class="mono">' + (t.categories || []).length + ' 个</td>' +
        '<td><span class="tag ' + esc(t.status) + '">' + esc(st) + '</span></td>' +
        '<td><div class="mini"><div style="width:' + (t.progress || 0) + '%"></div></div>' +
        '<span style="font-size:11px;color:var(--sub)">' + (t.progress || 0) + '%</span></td>' +
        '<td class="mono">' + (t.rows || 0) + '</td>' +
        '<td class="mono">' + esc(t.created) + '</td>' +
        '<td>' +
        (canDownload ? '<a href="/download/' + esc(t.id) + '"><button class="small">下载 CSV</button></a> ' : '') +
        '<button class="small" data-logs2="' + esc(t.id) + '">日志</button> ' +
        (canStop ? '<button class="small danger" data-stop2="' + esc(t.id) + '" data-name="' + esc(name) + '">停止</button>' : '') +
        '</td></tr>';
    }).join('');

    document.querySelectorAll('#taskRows [data-logs2]').forEach(function (b) {
      b.onclick = function () { openLogs(b.getAttribute('data-logs2')); };
    });
    document.querySelectorAll('#taskRows [data-stop2][data-name]').forEach(function (b) {
      b.onclick = function () { stopTask(b.getAttribute('data-stop2'), b.getAttribute('data-name')); };
    });
  }

  /* ---------------- 轮询 ---------------- */
  async function poll() {
    var res = await api('/api/state');
    if (!res || !res.ok) return;
    renderQueue(res);
    renderTable(res);
  }

  poll();
  setInterval(poll, 1000);
})();
