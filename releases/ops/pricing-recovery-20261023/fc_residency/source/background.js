const BASE = 'https://www.lootbar.com/game-coins/fc27';
importScripts('local_collector.js');
const TARGETS = [
  {platform: 'PS', url: BASE, label: 'PS4/5'},
  {platform: 'XBOX', url: BASE + '?platform=xbox', label: 'Xbox'},
  {platform: 'PC', url: BASE + '?platform=pc', label: 'PC'}
];

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function readVisibleOffer() {
  const visible = el => {
    if (!el) return false;
    const style = typeof getComputedStyle === 'function' ? getComputedStyle(el) : null;
    if (style && (style.display === 'none' || style.visibility === 'hidden')) return false;
    return typeof el.getClientRects !== 'function' || el.getClientRects().length > 0;
  };
  const text = el => String(el?.innerText || '').replace(/\s+/g, ' ').trim();
  const visibleAll = (root, selector) => [...root.querySelectorAll(selector)].filter(visible);
  const amountPattern = '(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d{1,6})?';
  const dollarPattern = new RegExp('\\$\\s*(' + amountPattern + ')(?![\\d,.])', 'g');
  const parseAmount = raw => {
    const value = String(raw || '').replaceAll(',', '');
    if (!/^\d+(?:\.\d{1,6})?$/.test(value) || !Number.isFinite(Number(value)) || Number(value) <= 0)
      return null;
    return value;
  };
  const toCents = raw => {
    const value = String(raw || '').replaceAll(',', '');
    const match = value.match(/^(\d+)(?:\.(\d{1,2}))?$/);
    if (!match) return null;
    return BigInt(match[1]) * 100n + BigInt((match[2] || '').padEnd(2, '0'));
  };
  const selected = visibleAll(document, 'a.on').map(text).filter(Boolean);
  const accountLink = document.querySelector("a[href='/account'].c-nav-userinfo-avatar-wrap");
  const loggedIn = visible(accountLink);
  const currencyButton = document.querySelector('button.c-nav-prefer');
  const currencyLabel = visible(currencyButton) ? text(currencyButton) : '';
  const currencyState = !currencyLabel ? 'missing' :
    !/\bEN\b/i.test(currencyLabel) ? 'language' :
      !/\bUSD\b/i.test(currencyLabel) ? 'currency' : 'ready';

  const cards = visibleAll(document, '.coin-listitem');
  const tiers = cards.map(card => {
    const nameNode = card.querySelector('.con-name');
    const name = visible(nameNode) ? text(nameNode) : '';
    const match = name.match(/^(\d+(?:\.\d{1,6})?)\s*(K|M)\s+Safe Coins$/i);
    if (!match) return null;
    const amount = Number(match[1]);
    const baseK = amount * (match[2].toUpperCase() === 'M' ? 1000 : 1);
    return Number.isFinite(baseK) && baseK > 0 ? {card, baseK} : null;
  }).filter(Boolean);
  const oneHundredK = tiers.filter(tier => tier.baseK === 100);
  const chosen = oneHundredK.length === 1 ? oneHundredK[0] :
    oneHundredK.length > 1 ? null : tiers.sort((a, b) => a.baseK - b.baseK)[0];
  const tierState = oneHundredK.length > 1 ? 'multiple' : chosen ? 'ready' : 'missing';

  let currentPrice = null, priceState = 'missing', currentPriceNode = null;
  let gift = null, giftState = 'missing';
  let couponState = 'none', observedCouponPrice = null, excludedCouponDiscount = null;
  let reconstruction = {method:'direct_no_coupon', exact:true, precision:'USD_cent'};
  if (chosen) {
    const priceNodes = visibleAll(chosen.card, '.discount-price');
    if (priceNodes.length > 1) priceState = 'multiple';
    else if (priceNodes.length === 1) {
      currentPriceNode = priceNodes[0];
      const priceText = text(currentPriceNode);
      const symbolCount = (priceText.match(/\$/g) || []).length;
      const match = priceText.match(/^\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,6})?)\s*$/);
      if (symbolCount > 1) priceState = 'multiple';
      else if (!match) priceState = priceText.includes('$') ? 'format' : 'missing';
      else {
        currentPrice = parseAmount(match[1]);
        priceState = currentPrice ? 'ready' : 'format';
      }
    }

    const giftNodes = visibleAll(chosen.card, '.gift-num');
    if (giftNodes.length > 1) giftState = 'multiple';
    else if (giftNodes.length === 1) {
      const giftText = text(giftNodes[0]);
      const match = giftText.match(/^\+\s*(\d+(?:\.\d{1,6})?)\s*K$/i);
      if (!giftText) giftState = 'missing';
      else if (!match || !Number.isFinite(Number(match[1])) || Number(match[1]) < 0) giftState = 'format';
      else { gift = String(Number(match[1])); giftState = 'ready'; }
    }

    const descendants = visibleAll(chosen.card, '*');
    const isInsidePrice = node => priceNodes.some(priceNode =>
      priceNode === node || priceNode.contains?.(node));
    const nestedSameText = candidates => candidates.filter(candidate =>
      !candidates.some(other => other.node !== candidate.node &&
        other.node.contains?.(candidate.node) && other.value === candidate.value));
    const containsPrice = node => priceNodes.some(priceNode =>
      node !== priceNode && node.contains?.(priceNode));
    const evidenceNodes = descendants.filter(node => !isInsidePrice(node) && !containsPrice(node));
    const couponCues = evidenceNodes.filter(node =>
      /coupon|new\s+(?:user|customer)|first\s+purchase|newbie|新客|新人|优惠券/i.test(text(node)));
    const negativeNodes = evidenceNodes.filter(node => /[-−]\s*\$/.test(text(node)));
    const minimalNegativeNodes = negativeNodes.filter(node =>
      !negativeNodes.some(other => other !== node && node.contains?.(other)));
    const couponCandidates = [];
    const advertisedAmount = node => {
      for (let current = node; current && current !== chosen.card; current = current.parentElement)
        if (/up\s+to|maximum|\bmax\b|\bcap\b/i.test(text(current))) return true;
      return false;
    };
    let malformedCouponAmount = false;
    for (const node of minimalNegativeNodes) {
      const nodeText = text(node);
      const dollarCount = (nodeText.match(/\$/g) || []).length;
      const tokens = [...nodeText.matchAll(dollarPattern)];
      const negativeTokens = [...nodeText.matchAll(new RegExp('[-−]\\s*\\$\\s*(' + amountPattern + ')(?![\\d,.])', 'g'))];
      if (/[-−]\s*\$/.test(nodeText) && (dollarCount !== 1 || tokens.length !== 1 || negativeTokens.length !== 1))
        malformedCouponAmount = true;
      if (dollarCount === 1 && tokens.length === 1 && negativeTokens.length === 1 && !advertisedAmount(node)) {
        couponCandidates.push({node, value:negativeTokens[0][1]});
      }
    }
    const coupons = nestedSameText(couponCandidates);
    const strikeNodes = evidenceNodes.filter(node => {
      const tag = String(node.tagName || '').toLowerCase();
      const style = typeof getComputedStyle === 'function' ? getComputedStyle(node) : null;
      return tag === 'del' || tag === 's' ||
        /(^|\s)line-through(\s|$)/i.test(style?.textDecorationLine || '');
    });
    const hasCoupon = coupons.length > 0 || malformedCouponAmount || couponCues.length > 0 || strikeNodes.length > 0;
    if (hasCoupon) {
      if (malformedCouponAmount) couponState = 'discount_format';
      else if (coupons.length > 1) couponState = 'discount_multiple';
      else if (!coupons.length) couponState = 'discount_missing';
      else if (priceState !== 'ready') couponState = 'waiting_price';
      else {
        const discount = coupons[0].value;
        const discountCents = toCents(discount);
        if (discountCents == null) couponState = 'discount_precision';
        else {
          const strikeCandidates = [];
          const malformedStrikeNodes = [];
          for (const node of strikeNodes) {
            const nodeText = text(node);
            const dollarCount = (nodeText.match(/\$/g) || []).length;
            const tokens = [...nodeText.matchAll(dollarPattern)];
            if (dollarCount && (dollarCount !== 1 || tokens.length !== 1)) malformedStrikeNodes.push(node);
            else if (dollarCount === 1 && tokens.length === 1)
              strikeCandidates.push({node, value:tokens[0][1]});
          }
          // Keep a full parent amount when styling is inherited and the DOM
          // splits its currency symbol and digits into separate descendants.
          const malformedStrike = malformedStrikeNodes.some(node =>
            !strikeCandidates.some(candidate => candidate.node !== node && candidate.node.contains?.(node)));
          const strikes = nestedSameText(strikeCandidates);
          if (malformedStrike) couponState = 'original_format';
          else if (strikes.length > 1) couponState = 'original_multiple';
          else if (!strikes.length) {
            const currentCents = toCents(currentPrice);
            if (currentCents == null || discountCents <= 0n) couponState = 'cent_precision';
            else {
              const originalCents = currentCents + discountCents;
              observedCouponPrice = currentPrice;
              excludedCouponDiscount = discount;
              currentPrice = String(originalCents / 100n) + '.' + String(originalCents % 100n).padStart(2,'0');
              couponState = 'excluded';
              reconstruction = {method:'derived_actual_discount', exact:true, precision:'USD_cent',
                paid_usd:observedCouponPrice, discount_usd:discount};
            }
          }
          else {
            const original = parseAmount(strikes[0].value);
            const currentCents = toCents(currentPrice);
            const originalCents = original == null ? null : toCents(original);
            if (currentCents == null || originalCents == null) couponState = 'cent_precision';
            else if (originalCents - currentCents !== discountCents || discountCents <= 0n)
              couponState = 'relation_mismatch';
            else {
              couponState = 'excluded';
              observedCouponPrice = currentPrice;
              excludedCouponDiscount = discount;
              currentPrice = original;
              reconstruction = {method:'direct_strike', exact:true, precision:'USD_cent',
                paid_usd:observedCouponPrice, discount_usd:discount};
            }
          }
        }
      }
    }
  }

  return {selected, loggedIn, currencyLabel, currencyState, tierState,
    tierCandidateCount:oneHundredK.length, visibleCardCount:cards.length,
    baseK:chosen?.baseK, priceState, usdPrice:currentPrice, giftState, bonusK:gift,
    couponState, observedCouponPrice, excludedCouponDiscount, reconstruction};
}

async function collectOne(target) {
  const tab = await chrome.tabs.create({url: target.url, active: false});
  let preserveTab = false;
  try {
    let observed, previousSignature = '', stableReads = 0;
    for (let attempt = 0; attempt < 40; attempt++) {
      await delay(500);
      try {
        const result = await chrome.scripting.executeScript({target: {tabId: tab.id},
          func: readVisibleOffer});
        observed = result[0]?.result;
      } catch (_) {
        observed = undefined;
        previousSignature = '';
        stableReads = 0;
        continue;
      }
      const complete = observed?.selected?.length === 1 && observed.selected[0] === target.label &&
        observed.loggedIn && observed.currencyState === 'ready' && observed.tierState === 'ready' &&
        observed.priceState === 'ready' && observed.giftState === 'ready' &&
        ['none','excluded'].includes(observed.couponState) && observed.baseK && observed.usdPrice;
      if (!complete) { previousSignature = ''; stableReads = 0; continue; }
      const signature = JSON.stringify({selected:observed.selected,baseK:observed.baseK,
        usdPrice:observed.usdPrice,bonusK:observed.bonusK,couponState:observed.couponState,
        observedCouponPrice:observed.observedCouponPrice,
        excludedCouponDiscount:observed.excludedCouponDiscount});
      stableReads = signature === previousSignature ? stableReads + 1 : 1;
      previousSignature = signature;
      if (stableReads >= 3) break;
    }
    const complete = observed?.selected?.length === 1 && observed.selected[0] === target.label &&
      observed.loggedIn && observed.currencyState === 'ready' && observed.tierState === 'ready' &&
      observed.priceState === 'ready' && observed.giftState === 'ready' &&
      ['none','excluded'].includes(observed.couponState) && observed.baseK && observed.usdPrice &&
      stableReads >= 3;
    if (!complete) {
      let reason;
      const fieldsReady = observed?.selected?.length === 1 && observed.selected[0] === target.label &&
        observed.loggedIn && observed.currencyState === 'ready' && observed.tierState === 'ready' &&
        observed.priceState === 'ready' && observed.giftState === 'ready' &&
        ['none','excluded'].includes(observed.couponState) && observed.baseK && observed.usdPrice;
      if (fieldsReady && stableReads < 3) reason = '报价信息未能连续稳定读取，请刷新后重试';
      else if (!observed) reason = 'Lootbar 页面未完成加载或结构未能读取';
      else if (!observed?.selected?.includes(target.label) || observed.selected.length !== 1)
        reason = `${target.platform} 平台选择未唯一核实`;
      else if (!observed.loggedIn) reason = 'Lootbar 当前 Chrome 登录状态未就绪';
      else if (observed.currencyState === 'language') reason = 'Lootbar 页面语言未核实，请切换至 EN / USD';
      else if (observed.currencyState !== 'ready') reason = 'Lootbar 币种未核实为 USD，请切换至 EN / USD';
      else if (observed.tierState === 'multiple') reason = '100K 商品规格重复，无法唯一核实';
      else if (observed.tierState !== 'ready') reason = 'Safe Coins 商品规格未识别，请确认 Lootbar 页面为英文';
      else if (observed.priceState === 'multiple') reason = '当前售价存在多个候选';
      else if (observed.priceState === 'format') reason = '当前售价格式不受支持';
      else if (observed.priceState !== 'ready') reason = '当前售价未显示';
      else if (observed.couponState === 'discount_multiple') reason = '账号优惠券减免金额不唯一';
      else if (observed.couponState === 'discount_missing') reason = '检测到账号优惠券，但减免金额未显示';
      else if (observed.couponState === 'discount_format') reason = '账号优惠券减免金额格式不清';
      else if (observed.couponState === 'original_multiple') reason = '账号优惠券对应的划线原价不唯一';
      else if (observed.couponState === 'original_missing') reason = '账号优惠券对应的可见划线原价缺失';
      else if (observed.couponState === 'original_format') reason = '账号优惠券对应的划线原价格式不清';
      else if (observed.couponState === 'relation_mismatch') reason = '券前原价、券后价格与减免金额对不上';
      else if (observed.couponState === 'discount_precision' || observed.couponState === 'cent_precision')
        reason = '账号优惠券金额无法精确到分核实';
      else if (observed.giftState === 'multiple') reason = '赠送量存在多个候选';
      else if (observed.giftState === 'format') reason = '赠送量格式不清，未按 0 处理';
      else reason = '赠送量未显示，未按 0 处理';
      preserveTab = true;
      const error = new Error(`${target.platform}：${reason}`);
      error.lootbarTabId = tab.id;
      throw error;
    }
    return {platform: target.platform, usd_price: observed.usdPrice,
      base_k: String(observed.baseK), bonus_k: observed.bonusK,
      ...(observed.couponState === 'excluded' ? {
        status:'已排除账号新客优惠券价', observed_coupon_price:observed.observedCouponPrice,
        excluded_coupon_discount:observed.excludedCouponDiscount
      } : {})};
  } catch (error) {
    preserveTab = true;
    if (!error.lootbarTabId) error.lootbarTabId = tab.id;
    throw error;
  } finally {
    if (!preserveTab) await chrome.tabs.remove(tab.id).catch(() => {});
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'FC27_LOOTBAR_COLLECT') return;
  Promise.allSettled(TARGETS.map(collectOne)).then(async results => {
    const failures = results.filter(result => result.status === 'rejected');
    if (failures.length) {
      const first = failures[0].reason;
      await chrome.tabs.update(first.lootbarTabId, {active:true}).catch(() => {});
      sendResponse({error: failures.map(result => String(result.reason?.message || result.reason)).join('；') +
        '。失败的 Lootbar 页面已保留在当前 Chrome 标签页供核对。'});
      return;
    }
    const rows = results.map(result => result.value);
    sendResponse({offers: Object.fromEntries(rows.map(({platform, ...offer}) => [platform, offer]))});
  }).catch(error => sendResponse({error: String(error.message || error)}));
  return true;
});

const previewLaunches = new Set();
chrome.runtime.onMessage.addListener((message,sender,sendResponse) => {
  if (message?.type !== 'FC27_REPRICE_PREVIEW' && message?.type !== 'FC27_REPRICE_INVALIDATE') return;
  const pageUrl = sender?.tab?.url || sender?.url || '';
  let parsed;
  try { parsed = new URL(pageUrl); }
  catch (_) { sendResponse({error:'预览来源不合法'}); return; }
  if (sender?.frameId !== 0 || !['http://47.85.224.112','http://47.253.252.55'].includes(parsed.origin) ||
      parsed.pathname !== '/dashboard/fc27-coins.html') {
    sendResponse({error:'仅接受报价页的预览请求'});
    return;
  }
  if(message.type==='FC27_REPRICE_INVALIDATE'){
    const token=String(message.token||'');
    if(!/^[0-9a-f-]{36}$/i.test(token)){sendResponse({error:'预览标记无效'});return}
    const key='fc27PendingPreview:'+token;
    chrome.storage.session.get(key).then(result=>{
      const entry=result[key];
      if(entry){entry.invalidated=true;entry.invalidatedAt=Date.now();return chrome.storage.session.set({[key]:entry})}
    }).then(()=>sendResponse({invalidated:true})).catch(error=>sendResponse({error:String(error?.message||error)}));
    return true;
  }
  const payload=message.payload;
  let serialized;
  try { serialized=JSON.stringify(payload); }
  catch (_) { sendResponse({error:'预览数据无法读取'}); return; }
  if (!payload || serialized.length>150000 || !payload.evidence || !payload.edits) {
    sendResponse({error:'预览数据缺失或过大'});
    return;
  }
  const launchKey=String(sender.tab.id)+':'+String(message.run_id||'');
  if (previewLaunches.has(launchKey)) {
    sendResponse({error:'本轮预览已经打开'});
    return;
  }
  previewLaunches.add(launchKey);
  const token=crypto.randomUUID();
  const storageKey='fc27PendingPreview:'+token;
  chrome.storage.session.set({[storageKey]:{payload,sourceTabId:sender.tab.id,sourceOrigin:parsed.origin,
    createdAt:Date.now(),invalidated:false,consumedBy:null}}).then(() =>
    chrome.tabs.create({url:chrome.runtime.getURL('repricing.html?request='+encodeURIComponent(token)),active:true})
  ).then(tab => {
    sendResponse({opened:true,tabId:tab.id,token});
    setTimeout(()=>previewLaunches.delete(launchKey),120000);
  }).catch(error => {
    previewLaunches.delete(launchKey);
    chrome.storage.session.remove(storageKey).catch(()=>{});
    sendResponse({error:String(error?.message||error)});
  });
  return true;
});
