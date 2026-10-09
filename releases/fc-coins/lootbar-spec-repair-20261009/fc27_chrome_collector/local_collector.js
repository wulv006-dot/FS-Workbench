// Every tab opened here belongs to the Chrome profile that clicked Collect.
const LOCAL_SITES = ['Lootbar', 'U4GM', 'IGGM', 'U7Buy'];
const LOCAL_PLATFORMS = ['PS', 'XBOX', 'PC'];
const LOCAL_URLS = {
  Lootbar: 'https://www.lootbar.com/game-coins/fc27',
  U4GM: 'https://www.u4gm.com/fc-27/coins',
  IGGM: 'https://www.iggm.com/ea-sports-fc/fc-27-coins',
  U7Buy: 'https://www.u7buy.com/fc27/coins',
  P2PAH: 'https://order.p2pah.cn/order/admin_delivery/index.html',
  FX: 'https://www.bankofchina.com/sourcedb/whpj/'
};
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const now = () => new Date().toISOString();

async function withTab(url, reader, active = false) {
  const tab = await chrome.tabs.create({url, active});
  let keep = false;
  try { return await reader(tab.id); }
  catch (error) { keep = error.message === 'P2PAH_LOGIN_REQUIRED'; throw error; }
  finally { if (!keep) await chrome.tabs.remove(tab.id).catch(() => {}); }
}

async function readUntil(tabId, func, args = [], good = x => !!x, attempts = 50) {
  let last;
  for (let i = 0; i < attempts; i++) {
    await pause(500);
    try {
      const result = await chrome.scripting.executeScript({target: {tabId}, func, args});
      last = result[0]?.result;
      if (good(last)) return last;
    } catch (_) { /* Navigation in progress. */ }
  }
  throw new Error('页面未完成加载或结构已变化：' + JSON.stringify(last).slice(0, 100));
}

function inspectP2PAH() {
  return {
    login: location.href.includes('login.html'),
    page: new URLSearchParams(location.search).get('page'),
    game: document.querySelector('#lot-game')?.value,
    product: document.querySelector('#lot-type')?.value,
    hasDataRows: [...document.querySelectorAll('tr')].some(tr => tr.querySelector('td')),
    empty: document.body?.innerText.includes('暂无数据') || false,
    rows: [...document.querySelectorAll('tr')].map(tr => {
      const c = [...tr.querySelectorAll('td')];
      const platform = c[6]?.innerText?.trim().match(/^FC\s*27\s*▶\s*(PS|XBOX|PC)$/i)?.[1];
      return platform ? {platform: platform.toUpperCase(), record_id: c[1]?.innerText.trim(),
        trade_at: c[5]?.innerText.trim(), cny_per_1k: c[9]?.innerText.trim()} : null;
    }).filter(Boolean)
  };
}

function shanghaiDate(days) {
  const date = new Date(Date.now() + days * 86400000);
  return new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric',
    month: '2-digit', day: '2-digit'}).format(date);
}

function costUrl(page) {
  const query = new URLSearchParams({gid:'1322',aid:'0',cid:'1',start: shanghaiDate(-7) + ' 00:00',
    end: shanghaiDate(1) + ' 00:00',show_ccy:'-1',genre:'0',status:'-1',op_id:'0',
    is_stock:'',keyword:'',sn:'',page:String(page)});
  return LOCAL_URLS.P2PAH + '?' + query;
}

async function collectCosts() {
  return withTab(costUrl(1), async tabId => {
    const found = {};
    for (let page = 1; page <= 15; page++) {
      if (page > 1) await chrome.tabs.update(tabId, {url: costUrl(page)});
      const data = await readUntil(tabId, inspectP2PAH, [], x => x?.login ||
        (x?.page===String(page) && x?.game==='1322' && x?.product==='1' &&
          (x.hasDataRows || x.empty)));
      if (data.login) {
        await chrome.tabs.update(tabId, {active: true});
        throw new Error('P2PAH_LOGIN_REQUIRED');
      }
      if (data.game !== '1322' || data.product !== '1') throw new Error('P2PAH FC27 / Game Coins 筛选未保持');
      for (const row of data.rows) {
        if (!found[row.platform] && /^\d+$/.test(row.record_id) &&
            Number.isFinite(Number(row.cny_per_1k)) && Number(row.cny_per_1k) > 0) {
          found[row.platform] = {game:'FC27',product:'Game Coins',...row,checked_at:now()};
        }
      }
      if (Object.keys(found).length === 3 || !data.hasDataRows) break;
    }
    return found;
  });
}

function inspectU4GM(label) {
  const quantities = [...document.querySelectorAll('[data-qty]')]
    .map(el => Number(el.getAttribute('data-qty'))).filter(n => Number.isInteger(n) && n > 0);
  if (!quantities.length) return null;
  const base = quantities.includes(100) ? 100 : Math.min(...quantities);
  document.querySelector(`[data-qty="${base}"]`)?.click();
  const selected = document.querySelector(`[data-qty="${base}"]`)?.classList.contains('btn-buy');
  const platform = [...document.querySelectorAll('*')].filter(el => el.childElementCount === 0 &&
    el.textContent.trim() === 'Platform').at(-1)?.parentElement?.innerText || '';
  const price = document.querySelector('.js-amount')?.innerText?.match(/[\d,.]+/)?.[0];
  return selected && platform.includes(label) && price ?
    {usd_price: price.replaceAll(',', ''), base_k:String(base),bonus_k:'0'} : null;
}

async function collectU4GM() {
  const urls = {PS:LOCAL_URLS.U4GM,XBOX:LOCAL_URLS.U4GM+'?server_code=xbox_one_series',
    PC:LOCAL_URLS.U4GM+'?server_code=pc'};
  const labels = {PS:'PS 4/5',XBOX:'Xbox One/Series',PC:'PC'};
  const found = {};
  for (const platform of LOCAL_PLATFORMS) {
    found[platform] = await withTab(urls[platform], async tabId => {
      const value = await readUntil(tabId, inspectU4GM, [labels[platform]]);
      return {...value,checked_at:now(),url:urls[platform],status:'交付方式待核实'};
    });
  }
  return found;
}

function inspectIGGM(device) {
  const selectedDevice = document.querySelector('li[data-device_id].active')?.getAttribute('data-device_id');
  const quantities = [...document.querySelectorAll('span[data-num]')]
    .map(el => Number(el.getAttribute('data-num'))).filter(n => Number.isInteger(n) && n > 0);
  if (!quantities.length) return {selectedDevice};
  const base = quantities.includes(100) ? 100 : Math.min(...quantities);
  const price = document.querySelector('.golds__price .true__price')?.getAttribute('lkr');
  const selectedQuantity = document.querySelector('span[data-num].active')?.getAttribute('data-num');
  return {selectedDevice,selectedQuantity,price,base};
}

function clickIGGM(selector) {
  document.querySelector(selector)?.click();
}

async function collectIGGM() {
  return withTab(LOCAL_URLS.IGGM, async tabId => {
    const found = {};
    for (const [platform,device] of [['PS','8'],['XBOX','10'],['PC','1']]) {
      await chrome.scripting.executeScript({target:{tabId},func:clickIGGM,
        args:[`li[data-device_id="${device}"]`]});
      const platformState = await readUntil(tabId, inspectIGGM, [device],
        value => value?.selectedDevice===device && Number.isInteger(value.base));
      const base = platformState.base;
      await pause(400);
      await chrome.scripting.executeScript({target:{tabId},func:clickIGGM,
        args:[`span[data-num="${base}"]`]});
      await readUntil(tabId, inspectIGGM, [device],
        value => value?.selectedDevice===device && value?.selectedQuantity===String(base) && !!value.price);
      await pause(400);
      const state = await readUntil(tabId, inspectIGGM, [device],
        value => value?.selectedDevice===device && value?.selectedQuantity===String(base) && !!value.price);
      const value = {usd_price:state.price,base_k:String(base),bonus_k:'0'};
      found[platform] = {...value,checked_at:now(),url:LOCAL_URLS.IGGM,status:'Comfort Trade'};
    }
    return found;
  });
}

function inspectU7Buy(label) {
  const control = [...document.querySelectorAll('.radio-select')]
    .find(el => el.textContent.trim() === label);
  if (!control?.classList.contains('active')) return null;
  const names = [...document.querySelectorAll('.coins-name')].map(el => el.innerText.trim());
  const tiers = names.map(name => {
    const match = name.match(new RegExp('^(\\d+(?:\\.\\d+)?)(K|M) Safe Coins '+label+'$', 'i'));
    return match ? {name,base: Number(match[1]) * (match[2].toUpperCase()==='M'?1000:1)} : null;
  }).filter(Boolean);
  if (!tiers.length) return null;
  const selected = tiers.find(t => t.base === 100) || tiers.sort((a,b) => a.base-b.base)[0];
  const card = [...document.querySelectorAll('.players-reactive-table-content-wrapper')]
    .find(el => [...el.querySelectorAll('.coins-name')].some(name => name.innerText.trim() === selected.name));
  const text = card?.innerText || '';
  const price = text.match(/([\d.]+)\s*USD/)?.[1];
  if (!price) return null;
  const bonus = text.match(/Newcomer\s*\+\s*(\d+)K/i)?.[1] || '0';
  return {usd_price:price,base_k:String(selected.base),bonus_k:bonus,
    conditional:bonus!=='0',comparable:bonus==='0',status:bonus!=='0'?
      '新客加赠，默认不参与常规价比较':'Comfort Trade'};
}

function clickU7Buy(label) {
  [...document.querySelectorAll('.radio-select')]
    .find(el => el.textContent.trim() === label)?.click();
}

async function collectU7Buy() {
  return withTab(LOCAL_URLS.U7Buy, async tabId => {
    const found = {};
    for (const [platform,label] of [['PS','PS4/PS5'],['XBOX','XBOX'],['PC','PC']]) {
      let value;
      for (let attempt=0;attempt<2;attempt++) {
        await chrome.scripting.executeScript({target:{tabId},func:clickU7Buy,args:[label]});
        try { value = await readUntil(tabId, inspectU7Buy, [label]); break; }
        catch (error) { if (attempt===1) throw new Error(platform+' 平台：'+error.message); }
      }
      found[platform] = {...value,checked_at:now(),url:LOCAL_URLS.U7Buy};
    }
    return found;
  });
}

function inspectFX() {
  const row = [...document.querySelectorAll('tr')].find(tr =>
    tr.querySelector('td')?.innerText.trim() === '美元');
  const cells = row ? [...row.querySelectorAll('td')].map(el => el.innerText.trim()) : [];
  const rate = Number(cells[5]) / 100;
  return Number.isFinite(rate) && rate > 0 ?
    {cny_per_usd:String(rate),published_at:cells[6],checked_at:new Date().toISOString(),url:location.href} : null;
}

async function collectFX() {
  return withTab(LOCAL_URLS.FX, tabId => readUntil(tabId, inspectFX));
}

async function collectLootbarTargets(collector = collectOne) {
  const results = await Promise.allSettled(TARGETS.map(collector));
  const failures = results.filter(result => result.status === 'rejected');
  if (failures.length) {
    const reasons = failures.map(result => result.reason);
    const firstPage = reasons.find(error => Number.isInteger(error?.lootbarTabId));
    if (firstPage) await chrome.tabs.update(firstPage.lootbarTabId, {active:true}).catch(() => {});
    const preserved = reasons.filter(error => Number.isInteger(error?.lootbarTabId)).length;
    const detail = reasons.map(error => String(error?.message || error)).join('；');
    const followUp = preserved
      ? `失败的 Lootbar 页面已保留 ${preserved} 个在当前 Chrome 标签页供核对。`
      : '请检查 Lootbar 页面是否能打开后重试。';
    throw new Error(`${detail}。${followUp}`);
  }
  return results.map(result => result.value);
}

async function localCollect() {
  const evidence = {game:'FC27',product:'Game Coins',checked_at:null,cost_url:LOCAL_URLS.P2PAH,
    policy:{base_lootbar_reduction_pct:'0.5',shared_gap_weight:'0.15',
      unconfirmed_gap_weight:'0.05',
      max_lootbar_reduction_pct:'8',minimum_gross_margin_pct:'10'},costs:{},
    offers:{PS:{},XBOX:{},PC:{}},fx:null};
  const errors = [];
  try { evidence.costs = await collectCosts(); }
  catch (error) {
    if (error.message === 'P2PAH_LOGIN_REQUIRED') throw error;
    errors.push('P2PAH：'+error.message);
  }
  for (const [site,collect] of [['Lootbar',async () => {
    const rows = await collectLootbarTargets();
    return Object.fromEntries(rows.map(({platform,...offer}) => [platform,{...offer,
      checked_at:now(),url:LOCAL_URLS.Lootbar,status:offer.status||'登录后价 / 可选 Comfort Trade'}]));
  }],['U4GM',collectU4GM],['IGGM',collectIGGM],['U7Buy',collectU7Buy]]) {
    try {
      const found = await collect();
      for (const [platform,offer] of Object.entries(found)) evidence.offers[platform][site] = offer;
    } catch (error) { errors.push(site+'：'+error.message); }
  }
  try { evidence.fx = await collectFX(); }
  catch (error) { errors.push('中国银行汇率：'+error.message); }
  evidence.checked_at = now();
  return {evidence,errors};
}

chrome.runtime.onMessage.addListener((message,_sender,sendResponse) => {
  if (message?.type !== 'FC27_LOCAL_COLLECT') return;
  localCollect().then(sendResponse).catch(error => sendResponse({error:error.message}));
  return true;
});
