(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const money = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? '待核' : `$${Number(value).toFixed(digits)}`;
  const time = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '未取得';
  function cell(tag, text) { const n = document.createElement(tag); n.textContent = text; return n; }
  function row(body, values) { const tr = document.createElement('tr'); values.forEach(v => tr.append(cell('td', v))); body.append(tr); }
  const simLabel = value => ({not_comparable_capture_span:'来源采价相隔超过5分钟，未模拟',partial:'可比来源不完整',complete:'同轮可比',not_evaluated:'未模拟'}[value] || '未完成模拟');
  function render(data) {
    const latest = data.latest_observed;
    const failed = data.service?.ActiveState === 'failed';
    const latestFailed = data.latest_attempt && data.latest_attempt.status !== 'observed';
    $('reference-summary').textContent = `已记录 ${data.observed_count} 次成功采样 / ${data.window_count} 次记录；其中 ${data.comparable_count} 次可作同轮模拟。${failed || latestFailed ? '最近跟随采样未完成，请核查原工单。' : data.service?.ActiveState==='unknown' ? '采样服务状态未能取证。' : '跟随原自然周期采样。'}${data.read_failures ? `有 ${data.read_failures} 份记录未能读取。` : ''}`;
    $('reference-meta').textContent = latest ? `最近采样 ${time(latest.completed_at)}；原工单 ${latest.run_id}。${simLabel(latest.simulation_status)}。` : '还没有成功采样，不能判断价格趋势。';
    const market = $('reference-market'); market.replaceChildren();
    const cards = $('reference-prices'); cards.replaceChildren();
    for (const platform of ['PS', 'XBOX', 'PC']) {
      const offer = latest?.itemd2r?.find(o => o.platform === platform && o.status === 'valid');
      const card = cell('div', ''); card.className = 'monitor-price-card';
      card.append(cell('strong', `ItemD2R · ${platform}`));
      const price = cell('div', money(offer?.gross_usd)); price.className = 'monitor-card-value'; card.append(price);
      card.append(cell('p', offer ? `${offer.purchase_k}K + ${offer.bonus_k}K · ${money(offer.effective_usd_per_k,4)}/K` : '采价缺失'));
      card.append(cell('p', `采价 ${time(offer?.captured_at)}`));
      card.append(cell('p', offer && Date.now()-Date.parse(offer.captured_at)>900000 ? '历史样本：采价已超过15分钟' : '独立观察样本'));
      cards.append(card);
      for (const source of ['Lootbar','U7Buy','ItemD2R','IGGM','U4GM']) {
        const value = latest?.market?.find(o => o.platform === platform && o.source === source);
        row(market, [platform, source, source==='Lootbar'?'核心':(['U7Buy','ItemD2R'].includes(source)?'第二梯队':'第三梯队'),
          value?.status==='valid'?money(value.gross_usd):'缺失', value?.status==='valid'?`${value.purchase_k} / ${value.bonus_k}`:'待核',
          money(value?.effective_usd_per_k,4), time(value?.captured_at)]);
      }
    }
    const eld=data.eldorado||latest?.eldorado;
    for(const platform of ['PS','XBOX','PC']) {
      const observation=eld?.platforms?.find(o=>o.platform===platform);
      const card=cell('div','');card.className='monitor-price-card';card.append(cell('strong',`ELD · ${platform} · C2C`));
      const price=cell('div',money(observation?.lowest_observed_100k_usd));price.className='monitor-card-value';card.append(price);
      card.append(cell('p',observation?.status==='observed'?`100K起购量合格展示低价 · 仅首屏${observation.observed_sellers}卖家 / ${observation.eligible_100k_sellers}符合数量`:'未取得本轮卖家数据'));
      card.append(cell('p',`采价 ${time(observation?.captured_at)} · 生产直接权重0`));
      card.append(cell('p',eld?.kind==='user_requested_initial_public_observation'?'首次公开校准，独立于自然周期样本':`原自然工单 ${eld?.run_id||'未取得'}${eld?.reason?' · '+eld.reason:''}`));
      card.append(cell('p','交付方式与结算费用未逐卖家核实，不作为可执行售价或全站最低价。'));
      if(observation?.captured_at&&Date.now()-Date.parse(observation.captured_at)>900000)card.append(cell('p','历史观察：采价已超过15分钟'));
      if(observation?.offers?.length){const details=document.createElement('details');details.append(cell('summary','卖家 / 起购量 / 库存 / 单价 / 信誉'));
        for(const offer of observation.offers)details.append(cell('p',`${offer.seller} · 起购${offer.minimum_k}K · 库存${offer.stock_k}K · ${money(offer.displayed_usd_per_k,5)}/K · ${offer.rating_pct}% / ${offer.reviews}评 · ${offer.delivery_time}${offer.quantity_eligible_100k?'':' · 不符合100K起购量'}`));
        card.append(details);
      }
      cards.append(card);
    }
    const simulations = $('reference-simulations'); simulations.replaceChildren();
    for (const s of latest?.weighted || []) row(simulations, [s.platform, `${Number(s.anchor_weight)*100}%`, money(s.weighted_unit,4),
      s.delta_vs_lootbar_pct==null?'待核':`${Number(s.delta_vs_lootbar_pct).toFixed(2)}%`,
      [...(s.unavailable_sources || []),...(s.storefront_comparable===false?['本店价格不可比']:[])].join('、') || '无']);
    if (!simulations.children.length) row(simulations, ['暂无合格同轮样本', '—', '—', '—', simLabel(latest?.simulation_status)]);
    const history = $('reference-history'); history.replaceChildren();
    for (const s of data.history || []) row(history, [time(s.completed_at || s.started_at),
      ...['PS','XBOX','PC'].map(p=>money(s.itemd2r?.find(o=>o.platform===p)?.gross_usd)),
      s.status==='observed'?simLabel(s.simulation_status):'采样未完成 / 失败', s.run_id]);
    if (!history.children.length) row(history, ['暂无记录', '—','—','—','等待原自然周期','—']);
  }
  let loading = false;
  async function refresh() {
    if (loading) return;
    loading = true; $('reference-refresh').disabled = true; $('reference-observer').setAttribute('aria-busy','true');
    const controller = new AbortController(); const timer = setTimeout(()=>controller.abort(),8000);
    try {
      const response = await fetch('/api/fc27/cloud/reference-observer',{credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if (!response.ok) throw Error(response.status===401||response.status===403?'登录权限不可用':`读取失败（${response.status}）`);
      render(await response.json()); $('reference-error').textContent='';
    } catch (error) {
      $('reference-error').textContent=`观察数据读取失败：${error.name==='AbortError'?'请求超时':error.message}。下方若有记录为上次读数，请勿当作最新价格。`;
    } finally { clearTimeout(timer); loading=false; $('reference-refresh').disabled=false; $('reference-observer').setAttribute('aria-busy','false'); }
  }
  $('reference-refresh').addEventListener('click',refresh);
  $('refresh').addEventListener('click',refresh);
  setInterval(()=>{if(!document.hidden)refresh();},60000); refresh();
})();
