(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const seedRegion = window.REGION_RELEASES;
  const labels = {release:'新作发售',season:'赛季',update:'更新',server:'新服',maintenance:'维护',delay:'延期',announcement:'公告'};
  let latest = null, latestStatus = null, latestSeo = null, seoError = false, history = false, active = null, stopped = false, refreshError = false;
  function seoCards() {
    let section = $('fsSeoNews');
    if (!section) {
      section = document.createElement('section'); section.id = 'fsSeoNews';
      section.className = 'fs-seo-news';
      $('fcGrid').after(section);
    }
    section.hidden = history;
    const outdated = latestSeo && Date.now() > Date.parse(latestSeo.stale_after);
    section.innerHTML = `<h2 class="section-title">MMOEXP News <small>主站 SEO 资讯</small></h2><p>${latestSeo ? `采集 ${esc(new Date(latestSeo.collected_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))}（北京） · ${latestSeo.documents.length} 篇 · ${latestSeo.coverage.game_keys.length} 款游戏${seoError || outdated ? ' · 本轮未更新，保留上次结果' : latestSeo.status === 'partial' ? ' · 部分文章未读取成功' : ''}` : '等待夜间采集结果'}。本站编辑内容与官方公告分开列示；新闻发布日期不作为活动倒计时。</p><div class="fs-daily-grid">${(latestSeo?.documents || []).map(row => `<article class="fs-daily-item"><div class="fs-daily-label">主站 SEO 资讯 · ${esc(row.profiles?.join(' / ') || row.game_keys.join(' / '))}</div><h3>${esc(row.title_zh || "中文标题待整理")}</h3><p>${esc(row.summary_zh || "原文已采集，中文摘要暂未生成。")}</p><p>新闻发布：${esc(row.published_at)}</p><details><summary>原文与来源</summary><p>${esc(row.title)}</p><p>${esc(row.summary)}</p><a href="${esc(row.source_url)}" target="_blank" rel="noopener noreferrer">阅读 MMOEXP 原文 ↗</a></details></article>`).join('')}</div><details><summary>采集范围与版本</summary><p>从主站新闻索引选取近期文章，优先兼顾不同游戏；这是有数量上限的资讯样本。${esc(latestSeo?.version || '')}</p></details>`;
  }
  function validateSeo(value) {
    if (value?.contract !== 'mmoexp-seo-news-v1' || value.source_kind !== 'mmoexp_seo' || !/^mmoexp-news-[a-f0-9]{20}$/.test(value.version || '') || !Array.isArray(value.documents) || value.documents.length > 12 || !Number.isFinite(Date.parse(value.collected_at)) || !Number.isFinite(Date.parse(value.stale_after)) || !Array.isArray(value.coverage?.game_keys)) throw Error('invalid_seo_news');
    for (const row of value.documents) {
      const url = new URL(row.source_url);
      if (url.origin !== 'https://www.mmoexp.com' || !/^\/News\/[a-z0-9][a-z0-9-]*\.html$/.test(url.pathname) || url.search || url.hash || url.username || url.password || row.source_kind !== 'mmoexp_seo' || row.event_date !== null || row.event_time !== null || !validDate(row.published_at) || typeof row.title !== 'string' || row.title.length > 240 || typeof row.summary !== 'string' || row.summary.length > 360 || !Array.isArray(row.game_keys) || ['title_zh','summary_zh'].some(k=>row[k] !== undefined && (typeof row[k] !== 'string' || row[k].length > (k==='title_zh'?160:420))) || row.profiles !== undefined && !Array.isArray(row.profiles)) throw Error('invalid_seo_article');
    }
    return value;
  }
  function validDate(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(value || '') && Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0,10) === value;
  }
  function validate(value) {
    if (value?.schema_version !== 1 || value.status !== 'succeeded' || !/^game-intel-[a-f0-9]{20}$/.test(value.version || '') || !Array.isArray(value.events) || value.events.length > 180 || !Number.isFinite(Date.parse(value.collected_at)) || !Number.isFinite(Date.parse(value.stale_after)) || !value.coverage || !Array.isArray(value.source_status)) throw Error('invalid_daily');
    for (const e of value.events) {
      for (const key of ['event_id','game_key','game_name','title','summary','evidence','source_id','source_url','collected_at']) if (typeof e[key] !== 'string' || e[key].length > 1000) throw Error('invalid_event');
      if (!Object.prototype.hasOwnProperty.call(labels,e.kind) || e.event_date !== null && !validDate(e.event_date) || e.event_time !== null && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(e.event_time) || e.timezone !== null && !/^UTC(?:[+-](?:0\d|1[0-4]):[0-5]\d)?$/.test(e.timezone)) throw Error('invalid_event_date');
      const url = new URL(e.source_url);
      if (url.protocol !== 'https:' || url.username || url.password) throw Error('invalid_source');
    }
    return value;
  }
  function updateStatus() {
    if (!$('fsDailyStatus')) return;
    const outdated = latest && Date.now() > Date.parse(latest.stale_after);
    const failed = latestStatus && latestStatus.status !== 'succeeded';
    $('fsHistoryToggle').textContent = history ? '返回每日情报' : '查看原包历史资料';
    $('fsDailyStatus').textContent = history
      ? '历史资料模式 · 原包事件与经营建议未重新核实；此处倒计时不属于每日采集结果。'
      : !latest ? '暂无已验证的每日情报版本；活跃预警与倒计时保持空白。原包仅可作为历史资料查看。'
      : `${outdated || failed || refreshError ? '⚠ 过期或本轮未完成，保留上一成功版本 · ' : '每日官方情报 · '}最近成功 ${new Date(latest.collected_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}（北京） · 每日00:05准备情报`;
    const c = latest?.coverage;
    $('fsDailyCoverage').textContent = c
      ? `官方入口可读映射 ${c.covered_games?.length || 0}/${c.total_games} 款；本批有证据事件覆盖 ${c.event_covered_games?.length || 0} 款。${Number.isInteger(c.reject_count) && c.reject_count > 0 ? `另有 ${c.reject_count} 条未通过证据校验，已排除；本批为部分结果。` : ''}缺口：${(c.missing_games || []).join('、') || '无入口缺口'}。${c.source_documents_omitted ? `本批容量限制省略 ${c.source_documents_omitted} 份文档。` : ''}只有明确日期、时间及偏移才生成小时倒计时；游戏资料与评级仍沿用原包。`
      : '尚未取得成功版本的来源覆盖结果。';
    const list = $('fsDailySources'); list.replaceChildren();
    for (const row of latest?.source_status || []) {
      const li = document.createElement('li');
      li.textContent = `${row.source_id} · ${row.status === 'available' ? `可读，${row.documents}份资料` : row.status === 'no_recent_documents' ? '无可解析的近期文档' : '读取失败'}${row.reason ? ' · '+row.reason : ''}`;
      list.append(li);
    }
    document.body.dataset.dailyState = history ? 'history' : latest ? 'live' : 'empty';
  }
  function dailyCards(snapshot) {
    $('fcMeta').textContent = '每日官方情报与AI整理 · 发布日期与事件时间分开列示';
    $('fcBriefCount').textContent = latest ? snapshot.events.length + ' 条节点' : '待确认';
    const grid = $('fcGrid');
    grid.innerHTML = snapshot.events.length ? snapshot.events.map(e => {
      const when = e.event_date ? e.event_date + (e.event_time ? ' '+e.event_time : '') + (e.timezone ? ' '+e.timezone : ' · 时区未注明') : '事件日期待确认，不生成倒计时';
      return `<article class="fs-daily-item"><div class="fs-daily-label">${esc(e.game_name)} · ${esc(labels[e.kind])}${e.carried_forward?' · 沿用已验证节点':''}</div><h3>${esc(e.title)}</h3><p>${esc(e.summary)}</p><p><b>事件：</b>${esc(when)}</p><p><b>新闻发布：</b>${esc(e.published_at || '来源未注明')}<br><b>采集：</b>${esc(e.collected_at)}</p><details><summary>官方原文证据</summary><blockquote>${esc(e.evidence)}</blockquote><a href="${esc(e.source_url)}" target="_blank" rel="noopener noreferrer">查看官方来源</a></details></article>`;
    }).join('') : latest ? '<p class="fs-daily-item">本批官方来源未提取出可验证的新节点；请结合来源覆盖缺口查看。</p>' : '<p class="fs-daily-item">尚无可用采集结果，暂无法判断预警与新节点。</p>';
    grid.classList.add('fs-daily-grid');
  }
  function apply() {
    if (history) {
      window.fsApplyGameDaily(null); window.REGION_RELEASES = seedRegion;
      $('fcGrid')?.classList.remove('fs-daily-grid');
    } else {
      const snapshot = latest || {events:[],collected_at:null};
      window.fsApplyGameDaily(snapshot,latestSeo);
      window.REGION_RELEASES = {
        collection_available:!!latest, updated: snapshot.collected_at || '尚未成功', window:'官方发布节点', regions:['范围未注明'], sources:{}, notes:[],
        items:snapshot.events.map(e=>({daily_verified:true,event_time:e.event_time,timezone:e.timezone,title:e.title,name_en:e.game_name,publisher:e.source_id,platform:'来源详见原文',regions:['范围未注明'],type:labels[e.kind],date:e.event_date || '待确认',ip_tier:'待评估',biz_note:e.summary,source_url:e.source_url,source_name:'官方原文'}))
      };
      dailyCards(snapshot);
    }
    window.fsRenderGameRegion?.();
    if ($('rgUpdated')) $('rgUpdated').textContent = history ? '原包历史快照，未作为本次官方采集证据' : '每日官方来源 · 仅显示本批及保留的已验证节点；地区范围未注明时不推测';
    updateStatus();
    seoCards();
  }
  async function read(path, signal) {
    const response = await fetch(path, {credentials:'same-origin',cache:'no-store',redirect:'manual',signal});
    if ([401,403].includes(response.status) || response.redirected || response.type === 'opaqueredirect') { await window.fsVerifyGameSession(); throw Error('session_denied'); }
    if (!response.ok || !(response.headers.get('content-type') || '').includes('application/json')) throw Error('daily_unavailable');
    const text = await response.text();
    if (text.length > 500000) throw Error('daily_too_large');
    return JSON.parse(text);
  }
  async function refresh() {
    if (stopped || active || !await window.fsVerifyGameSession()) return;
    const user = window.fsGameSessionKey();
    const controller = new AbortController(); active = controller;
    const timeout = setTimeout(()=>controller.abort(),25000);
    try {
      const results = await Promise.allSettled([read('daily.json',controller.signal),read('daily.status.json',controller.signal),read('seo-news.json',controller.signal),read('seo-news.status.json',controller.signal)]);
      if (!await window.fsVerifyGameSession() || user !== window.fsGameSessionKey() || controller.signal.aborted || stopped) return;
      refreshError = results.slice(0,2).some(r=>r.status==='rejected');
      seoError = results[2].status === 'rejected' || results[3].status === 'rejected' || !['available','partial'].includes(results[3].value?.status);
      const previousSeoVersion = latestSeo?.version;
      if (results[2].status === 'fulfilled') { try { latestSeo = validateSeo(results[2].value); } catch { seoError = true; } }
      seoCards();
      if (results[1].status === 'fulfilled') latestStatus = results[1].value;
      let changed = latestSeo?.version !== previousSeoVersion;
      if (results[0].status === 'fulfilled') {
        const incoming = validate(results[0].value);
        changed ||= incoming.version !== latest?.version;
        latest = incoming;
      }
      if (changed && !history) apply();
      updateStatus();
    } catch { refreshError = true; updateStatus(); }
    finally { clearTimeout(timeout); active = null; }
  }
  $('fsHistoryToggle').addEventListener('click', () => { history = !history; apply(); });
  $('fcCollectBtn').textContent = 'ⓘ 每日采集说明';
  $('fcCollectBtn').addEventListener('click', () => { $('fsDailyStatus').scrollIntoView({behavior:'smooth',block:'center'}); });
  window.addEventListener('pagehide', () => { stopped = true; active?.abort(); });
  window.addEventListener('pageshow', () => { stopped = false; refresh(); });
  function start() {
    apply();
    window.FS_GAME_TIMERS.push(setInterval(refresh,300000));
    refresh();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',start,{once:true});
  else start();
})();
