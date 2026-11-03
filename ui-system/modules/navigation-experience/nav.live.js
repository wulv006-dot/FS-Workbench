/* FS 首屏外壳 nav.js —— 静态导航挂好之后只做「增强」，不再重建导航。
   2026-10-19：替代原先「探测完所有入口权限才渲染导航」的做法，首屏不再抖动。
   有 #hubNav 时 hubnav.js 会在第一行直接返回，不会重复 24 次 HEAD 探测。 */
(function () {
  'use strict';

  // Keep the shared Hermes hierarchy consistent on existing static workspace shells.
  // Compile all shared submenus from the same registry as static pages and hubnav.
  var sharedGroups = {"analytics": "<section class=\"hn-group\"><a class=\"hn-heading\" href=\"/dashboard/modules/analytics/\"><span class=\"hn-icon\">▥</span><span>数据分析</span></a><a class=\"hn-tool\" href=\"/dashboard/analytics/?mode=business\">数据看板</a><a class=\"hn-tool\" href=\"/dashboard/channel-effects/\">渠道效果看板</a><a class=\"hn-tool\" href=\"/dashboard/users/\">用户分析</a><a class=\"hn-tool\" href=\"/dashboard/data-tools/\">数据分析工具</a><a class=\"hn-tool\" href=\"/dashboard/fs-home/brain/index.html?report_kind=weekly#reports\">运营报告</a><a class=\"hn-tool\" href=\"/dashboard/management/\">经营管理台</a><a class=\"hn-tool\" href=\"/dashboard/game-monitor/\">游戏监控台</a></section>", "brain": "<section class=\"hn-group\"><a class=\"hn-heading\" href=\"/dashboard/modules/hermes/\"><span class=\"hn-icon\">◈</span><span>Hermes 智体</span></a><a class=\"hn-tool\" href=\"/dashboard/fs-home/brain/index.html\">智体决策报告</a><a class=\"hn-tool\" href=\"/dashboard/fs-home/hermes/conversation/\">持续对话</a><a class=\"hn-tool\" href=\"/dashboard/fs-home/hermes/customer-tracking/\">智体客单追踪</a></section>", "activities": "<section class=\"hn-group\"><a class=\"hn-heading\" href=\"/dashboard/analytics/campaigns/analytics/\"><span class=\"hn-icon\">◫</span><span>主站活动区</span></a><a class=\"hn-tool\" href=\"/dashboard/analytics/campaigns/analytics/\">活动转化分析</a><a class=\"hn-tool\" href=\"/dashboard/analytics/campaigns/analytics/products.html\">商品编辑与预览</a></section>"};
  Object.keys(sharedGroups).forEach(function(id){
    var paths={analytics:'/dashboard/modules/analytics/',brain:'/dashboard/modules/hermes/',activities:"/dashboard/analytics/campaigns/analytics/"};
    var heading=document.querySelector('#hubNav .hn-heading[href="'+paths[id]+'"]');
    var box=document.createElement('div');box.innerHTML=sharedGroups[id];var next=box.firstElementChild;
    if(heading)heading.parentElement.replaceWith(next);
    else if(id==='activities'){var sports=document.querySelector('#hubNav .hn-heading[href="/dashboard/modules/sports/"]');if(sports)sports.parentElement.before(next);}
  });

  var current=new URL(location.href),best=null,bestLength=-1;
  document.querySelectorAll('#hubNav a[aria-current]').forEach(function(a){a.removeAttribute('aria-current');});
  document.querySelectorAll('#hubNav .hn-home,#hubNav .hn-heading,#hubNav .hn-tool').forEach(function(a){
    var u=new URL(a.href,location.origin),exact=current.pathname===u.pathname;
    if(a.classList.contains('hn-home')&&!exact)return;
    if(!exact&&(!u.pathname.endsWith('/')||!current.pathname.startsWith(u.pathname)))return;
    if(Array.from(u.searchParams).some(function(p){return current.searchParams.get(p[0])!==p[1];}))return;
    var score=u.pathname.length+(a.classList.contains('hn-tool')?1:0);
    if(score>bestLength){best=a;bestLength=score;}
  });
  if(best){best.setAttribute('aria-current','page');var parent=best.closest('.hn-group');if(parent){var title=parent.querySelector('.hn-heading');if(title!==best)title.setAttribute('aria-current','true');}}

  var KEY = 'fs-navigation-theme';
  var media = matchMedia('(prefers-color-scheme: dark)');

  /* 1) 主题：head 里的内联脚本已按 localStorage 定好首屏，这里只负责下拉框联动 */
  function resolve(pref) { return pref === 'system' ? (media.matches ? 'dark' : 'light') : pref; }
  function apply(pref, persist) {
    var value = ['light', 'dark', 'system'].indexOf(pref) >= 0 ? pref : 'light';
    var resolved = resolve(value);
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.fsTheme = resolved;
    document.querySelectorAll('select[data-fs-theme-control],select#theme').forEach(function (s) { s.value = value; });
    if (persist) { try { localStorage.setItem(KEY, value); } catch (e) {} }
    document.dispatchEvent(new CustomEvent('fs-theme-change', { detail: { preference: value, resolved: resolved } }));
  }
  var saved = 'light';
  try { saved = localStorage.getItem(KEY) || 'light'; } catch (e) {}
  apply(saved, false);
  document.querySelectorAll('select[data-fs-theme-control],select#theme').forEach(function (s) {
    s.value = saved;
    s.addEventListener('change', function () { apply(s.value, true); });
  });
  media.addEventListener('change', function () {
    var pref = 'light';
    try { pref = localStorage.getItem(KEY) || 'light'; } catch (e) {}
    if (pref === 'system') apply('system', false);
  });

  /* 2) 移动端抽屉 */
  var nav = document.getElementById('hubNav');
  var toggle = document.getElementById('hubNavToggle');
  var scrim = document.getElementById('hubNavScrim');
  function closeNav() {
    if (!nav) return;
    nav.classList.remove('open');
    if (scrim) scrim.hidden = true;
    if (toggle) toggle.setAttribute('aria-expanded', 'false');
  }
  if (toggle && nav) {
    nav.hidden = false;
    if (innerWidth < 900) { /* 由 CSS 处理位移，保持 DOM 可见以便过渡 */ }
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      if (scrim) scrim.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
    });
    if (scrim) scrim.addEventListener('click', function () { closeNav(); toggle.focus(); });
    addEventListener('keydown', function (e) { if (e.key === 'Escape') closeNav(); });
    addEventListener('resize', function () { if (innerWidth >= 900) closeNav(); });
  }

  /* 3) 账号名：一次后台校验，只补文字，不动版式（不阻塞首屏） */
  var userSlot = document.querySelector('[data-fs-user]');
  if (userSlot) {
    fetch('/__auth/verify', { credentials: 'same-origin', cache: 'no-store', redirect: 'manual' })
      .then(function (r) {
        if (r.status !== 200 || r.redirected) return;
        var name = r.headers.get('X-Auth-User');
        var role = r.headers.get('X-Auth-Role');
        var groups = (r.headers.get('X-Auth-Groups') || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean);
        if (name) userSlot.textContent = name;
        var admin = document.querySelector('[data-fs-admin]');
        if (admin && role === 'admin') admin.hidden = false;
        if (groups.indexOf('deploy') < 0) {
          document.querySelectorAll('[data-requires-group="deploy"]').forEach(function (el) {
            el.dataset.access = 'locked';
            el.setAttribute('aria-disabled', 'true');
            el.removeAttribute('href');
            el.title = '当前账号无 deploy 组权限';
          });
        }
      })
      .catch(function () {});
  }

  /* 4) 首页两枚快捷卡：shell.js 重建工作区网格时会被清掉，这里补回（原先由 hubnav 的 MutationObserver 负责） */
  var grid = document.getElementById('workspaces');
  if (grid && document.body.dataset.page === 'home') {
    var shortcuts = [
      { id: 'management', icon: '◎', title: '经营管理台', desc: '三组进度 · 健康度责任到人 · 目标沙盘与经营决策', path: '/dashboard/management/' },
      { id: 'game-monitor', icon: '◷', title: '游戏监控台', desc: '全球新游上线 · 版本赛季 · 开服节点一屏追踪', path: '/dashboard/game-monitor/' }
    ];
    var placing = false;
    function place() {
      if (placing) return;
      placing = true;
      try {
        var after = grid.querySelector('.workspace-card.arpg');
        if (!after) return;
        shortcuts.forEach(function (s) {
          if (grid.querySelector('[data-fs-shortcut="' + s.id + '"]')) return;
          var card = document.createElement('article');
          card.className = 'workspace-card ' + s.id;
          card.dataset.fsShortcut = s.id;
          var a = document.createElement('a');
          a.className = 'workspace-main';
          a.href = s.path;
          a.innerHTML = '<span class="workspace-icon">' + s.icon + '</span><h3>' + s.title + '</h3><p>' + s.desc +
            '</p><span class="entry">进入工作区 →</span>';
          card.appendChild(a);
          after.after(card);
          after = card;
        });
      } finally { placing = false; }
    }
    place();
    new MutationObserver(place).observe(grid, { childList: true });
  }

  /* 5) 切页预热：悬停即预渲染同站工作区，点下去几乎瞬开 */
  if (HTMLScriptElement.supports && HTMLScriptElement.supports('speculationrules')) {
    try {
      var rules = {
        prerender: [{ where: { href_matches: '/dashboard/modules/*' }, eagerness: 'moderate' }],
        prefetch: [{ where: { href_matches: '/dashboard/*' }, eagerness: 'moderate' }]
      };
      var s = document.createElement('script');
      s.type = 'speculationrules';
      s.textContent = JSON.stringify(rules);
      document.head.appendChild(s);
    } catch (e) {}
  }
})();
