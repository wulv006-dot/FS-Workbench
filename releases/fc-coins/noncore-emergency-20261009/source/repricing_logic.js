(() => {
  'use strict';

  const PLATFORMS = Object.freeze({
    PS: Object.freeze({id: '21942', name: 'PS'}),
    XBOX: Object.freeze({id: '21944', name: 'XBOX'}),
    PC: Object.freeze({id: '21946', name: 'PC'})
  });
  const SITES = Object.freeze(['Lootbar', 'U4GM', 'IGGM', 'U7Buy']);
  const MAX_AGE_MS = 60 * 60 * 1000;
  const FIXED_MARGIN = '0.200000';
  const FIXED_RMB_RATE = '6.65';

  function fail(message) { throw new Error(message); }
  function decimal(value, label, places = 6) {
    const text = String(value ?? '').trim();
    if (!new RegExp(`^\\d+(?:\\.\\d{1,${places}})?$`).test(text) ||
        !Number.isFinite(Number(text)) || Number(text) <= 0)
      fail(`${label}缺失或格式不符`);
    return Number(text);
  }
  function parsedTime(value, label, now) {
    const time = Date.parse(value || '');
    if (!Number.isFinite(time) || time > now + 60_000 || now - time > MAX_AGE_MS)
      fail(`${label}缺失或已超过 60 分钟，请重新采集`);
    return time;
  }
  function fixed4(value, label) {
    const text = String(value ?? '').trim();
    if (!/^\d+\.\d{4}$/.test(text) || !Number.isFinite(Number(text)) || Number(text) <= 0)
      fail(`${label}必须是四位小数`);
    return text;
  }
  function costForQuote(quote) {
    const text = fixed4(quote, '建议价');
    const [whole, fraction] = text.split('.');
    const quoteUnits = BigInt(whole) * 10000n + BigInt(fraction);
    const micros = quoteUnits * 532n;
    const integer = micros / 1000000n;
    const decimalPart = String(micros % 1000000n).padStart(6, '0');
    return `${integer}.${decimalPart}`;
  }
  function requiresLowMarginConfirmation(target) {
    return Boolean(target?.marginBelowMinimum && !target?.quoteManual);
  }
  function unwrapInjectionResult(results, operation = '后台操作') {
    const injection = Array.isArray(results) ? results[0] : null;
    if (injection?.error) {
      const detail = String(injection.error.message || injection.error || '注入失败');
      fail(`${operation}脚本注入失败：${detail}`);
    }
    if (!injection || !Object.prototype.hasOwnProperty.call(injection, 'result') || injection.result === undefined)
      fail(`${operation}脚本未返回确认结果；后台页面可能已自动刷新，操作状态未确认`);
    return injection.result;
  }
  function canonicalMoney(value) {
    const text = String(value ?? '').trim();
    if (!/^\d+(?:\.\d{1,6})?$/.test(text) || !Number.isFinite(Number(text))) return null;
    const [integer, fraction = ''] = text.split('.');
    const normalizedInteger = integer.replace(/^0+(?=\d)/, '');
    const normalizedFraction = fraction.replace(/0+$/, '');
    return normalizedFraction ? `${normalizedInteger}.${normalizedFraction}` : normalizedInteger;
  }
  function sameMoney(a, b) {
    const left = canonicalMoney(a);
    return left !== null && left === canonicalMoney(b);
  }

  function normalizeDiscountRules(value) {
    const defaults={schema_version:1,bands:{at_least_40:{min_discount_pct:'0.00',max_discount_pct:'10.00'},
      '30_to_40':{min_discount_pct:'7.50',max_discount_pct:'7.50'},
      '20_to_30':{min_discount_pct:'5.00',max_discount_pct:'5.00'},
      below_20:{min_discount_pct:'0.00',max_discount_pct:'0.00'}}};
    if (value === undefined || value === null) return defaults;
    const exact=(object,keys)=>object!==null && typeof object==='object' && !Array.isArray(object) &&
      Object.keys(object).length===keys.length && keys.every(key=>Object.hasOwn(object,key));
    if (!exact(value,['schema_version','bands']) || value.schema_version!==1 ||
        !exact(value.bands,Object.keys(defaults.bands))) fail('降幅区间配置格式无效');
    const bands={};
    for (const name of Object.keys(defaults.bands)) {
      const row=value.bands[name];
      if (!exact(row,['min_discount_pct','max_discount_pct'])) fail('降幅区间配置格式无效');
      const numbers={};
      for (const key of ['min_discount_pct','max_discount_pct']) {
        const text=row[key];
        if (typeof text!=='string' || !/^[0-9]+(?:\.[0-9]{1,2})?$/.test(text) ||
            !Number.isFinite(Number(text)) || Number(text)<0 || Number(text)>10)
          fail('降幅须为0至10之间的百分比，最多两位小数');
        numbers[key]=Number(text);
      }
      if (numbers.min_discount_pct>numbers.max_discount_pct) fail('降幅下限不得大于上限');
      bands[name]=Object.fromEntries(Object.entries(numbers).map(([key,value])=>[key,value.toFixed(2)]));
    }
    return {schema_version:1,bands};
  }

  // Compare purchase margin bands exactly; displayed 30.00% may still be below 30%.
  function exactMarginBand(cost, fx, delivered, page) {
    const ratio = value => {
      const [mantissa, exponent='0'] = String(value).toLowerCase().split('e');
      const [whole, fraction=''] = mantissa.split('.');
      const shift = fraction.length-Number(exponent);
      return shift>=0 ? [BigInt(whole+fraction),10n**BigInt(shift)] :
        [BigInt(whole+fraction)*10n**BigInt(-shift),1n];
    };
    const [c,cd]=ratio(cost),[f,fd]=ratio(fx),[q,qd]=ratio(delivered),[p,pd]=ratio(page);
    for (const band of [40,30,20])
      if (c*q*fd*pd*100n <= f*p*cd*qd*BigInt(100-band)) return band;
    return 0;
  }

  function tieredPagePrice(lootbarPage, u4gmPage, iggmPage, costUsd, delivered, minimumMargin, beforeMargin,
    lootbarDelivered, u4gmDelivered, iggmDelivered, pricingRules, fallback=null) {
    const references = [[u4gmPage,u4gmDelivered],[iggmPage,iggmDelivered],...(fallback?[fallback]:[])]
      .filter(([page])=>page!==null);
    if (!references.length) fail('参考竞品报价缺失');
    const pageCents = [lootbarPage,...references.map(([page])=>page)].map(page=>{
      const cents=Math.round(page*100);
      if (!Number.isSafeInteger(cents) || Math.abs(page*100-cents)>1e-8)
        fail('竞品页面总价须精确到美分');
      return cents;
    });
    if ([delivered,lootbarDelivered,...references.map(([,quantity])=>quantity)].some(quantity=>
      !Number.isFinite(quantity) || quantity<=0 || quantity>200)) fail('商品含赠送金币数超出范围');
    const lootbarUnit=lootbarPage/lootbarDelivered;
    const gaps=references.map(([page,quantity])=>page/quantity)
      .map(unit=>Math.max(0,(lootbarUnit-unit)/lootbarUnit));
    const costCents = costUsd*delivered*100;
    const ceil = value => Math.ceil(value-1e-10);
    const minimumCents = ceil(costCents/(1-minimumMargin/100));
    const tier=beforeMargin>=40?'at_least_40':beforeMargin>=30?'30_to_40':
      beforeMargin>=20?'20_to_30':'below_20';
    const oldReduction=tier==='at_least_40'?Math.min(0.10,gaps.reduce((sum,gap)=>sum+gap,0)/gaps.length):
      tier==='30_to_40'?0.075:tier==='20_to_30'?0.05:0;
    const bounds=normalizeDiscountRules(pricingRules).bands[tier];
    const reduction=Math.min(Math.max(oldReduction,Number(bounds.min_discount_pct)/100),Number(bounds.max_discount_pct)/100);
    const preferred=ceil(lootbarUnit*(1-reduction)*100*100);
    const cents=Math.max(preferred,minimumCents);
    const page = cents/100;
    const margin = (1-costUsd*delivered/page)*100;
    const discount = (1-(page/100)/lootbarUnit)*100;
    const maxDiscount=Number(bounds.max_discount_pct);
    if (margin+1e-9 < minimumMargin || discount-1e-9 > maxDiscount)
      fail('分档价格边界校验失败');
    return {cents, tier, discount, requestedDiscount:reduction*100, profitFloorApplied:minimumCents>preferred};
  }

  // Keep this calculation in lockstep with calculate() in fc27_quote_browser.js.
  // The extension recomputes from evidence and edits because the dashboard is HTTP.
  function recompute(evidence, edits = {}) {
    const emergency = evidence.game==='FC27' && Boolean(evidence.storefront);
    const pricingRules=normalizeDiscountRules(edits.pricing_rules);
    const fx = decimal(evidence.fx?.cny_per_usd, '汇率');
    const marginText = String(edits.minimum_gross_margin_pct ?? '10');
    const minimumMargin = Number(marginText);
    if (!/^\d+(?:\.\d{1,6})?$/.test(marginText) || !Number.isFinite(minimumMargin) ||
        minimumMargin < 0 || minimumMargin >= 100) fail('最低毛利率缺失或无效');
    const rows = Object.keys(PLATFORMS).map(platform => {
      const raw = evidence.costs?.[platform] || {};
      const rawCost = raw.cny_per_1k ? decimal(raw.cny_per_1k, '原始成本') : null;
      const editedCost = edits.costs?.[platform];
      const cost = editedCost ? decimal(editedCost, '人工成本') : rawCost;
      const offers = [], missing = [], benchmark = [], unavailable = [];
      for (const site of SITES) {
        const source = evidence.offers?.[platform]?.[site] || {};
        const manual = edits.offers?.[platform]?.[site] || {};
        if (!source.usd_price && !manual.usd_price) {
          if (emergency && site!=='Lootbar' && !evidence.offers?.[platform]?.[site] && !Object.keys(manual).length)
            unavailable.push(site);
          else missing.push(site);
          offers.push({site, status:'缺数据', comparable:false});
          continue;
        }
        try {
          const price = decimal(manual.usd_price ?? source.usd_price, `${site} 售价`);
          const base = decimal(manual.base_k ?? source.base_k, `${site} 购买 K`);
          const bonusText = String(manual.bonus_k ?? source.bonus_k ?? '0');
          if (!/^(?:0|\d+(?:\.\d{1,6})?)$/.test(bonusText)) fail(`${site} 赠送 K 格式不符`);
          const bonus = Number(bonusText);
          const unit = price / (base + bonus);
          const comparable = Boolean(manual.comparable ?? source.comparable ?? !source.conditional);
          offers.push({site, usd_price:String(price), base_k:String(base), bonus_k:String(bonus),
            usd_per_1k:unit.toFixed(4), comparable, conditional:Boolean(source.conditional),
            manual:Object.keys(manual).length>0, url:source.url,
            status:Object.keys(manual).length?'人工修正':source.status||'已核对',
            checked_at:manual.checked_at||source.checked_at});
          if (comparable) benchmark.push({site, unit});
        } catch (_) {
          missing.push(site);
          offers.push({site,status:'价格或数量缺数据',comparable:false});
        }
      }
      const row = {platform,raw_cost_cny:rawCost==null?null:String(rawCost),
        cost_cny:cost==null?null:String(cost),cost_manual:Boolean(editedCost),
        cost_record_id:raw.record_id,cost_trade_at:raw.trade_at,offers,missing,proposal:null};
      const referenceSources = ['U4GM','IGGM'].filter(site=>benchmark.some(offer=>offer.site===site));
      if (emergency && !referenceSources.length && unavailable.includes('U4GM') && unavailable.includes('IGGM') &&
          benchmark.some(offer=>offer.site==='U7Buy')) referenceSources.push('U7Buy');
      if (emergency) Object.assign(row,{unavailable_sources:unavailable,reference_sources:referenceSources});
      if (cost==null) { row.status='缺成本'; return row; }
      if (missing.length || !benchmark.length) {
        row.status=missing.length?'缺竞品数据':'无可比竞品'; return row;
      }
      benchmark.sort((a,b)=>a.unit-b.unit||(a.site<b.site?-1:a.site>b.site?1:0));
      const lowest=benchmark[0];
      const floor=Number((Math.ceil((cost/fx/(1-minimumMargin/100)-1e-12)*10000)/10000).toFixed(4));
      const lootbar=benchmark.find(item=>item.site==='Lootbar');
      const u4gm=benchmark.find(item=>item.site==='U4GM');
      const iggm=benchmark.find(item=>item.site==='IGGM');
      if (!lootbar || (!u4gm && !(emergency && unavailable.includes('U4GM'))) ||
          (!iggm && !(emergency && unavailable.includes('IGGM'))) || !referenceSources.length) {
        row.status='核心竞品不可比'; return row;
      }
      const u4gmGap=u4gm?Math.max(0,(lootbar.unit-u4gm.unit)/lootbar.unit*100):null;
      const iggmGap=iggm?Math.max(0,(lootbar.unit-iggm.unit)/lootbar.unit*100):null;
      const own = evidence.storefront?.rows?.[platform];
      if (emergency && !own) fail(`${platform} 本轮 MMOEXP 页面售价证据缺失`);
      if (own) {
        const ownBase = decimal(own.base_k,'MMOEXP 购买 K');
        const ownBonus = Number(own.bonus_k);
        if (ownBase !== 100 || !Number.isFinite(ownBonus) || ownBonus < 0 || ownBonus > 100)
          fail('MMOEXP 100K 商品规格不符');
        const bySite = Object.fromEntries(offers.filter(offer=>offer.comparable).map(offer=>[offer.site,offer]));
        const pricingSites = ['Lootbar',...referenceSources];
        if (pricingSites.some(site=>Number(bySite[site]?.base_k)!==100)) {
          row.status='核心竞品规格不一致'; return row;
        }
        const lootbarPage = decimal(bySite.Lootbar.usd_price,'Lootbar 页面总价');
        const u4gmPage = u4gm?decimal(bySite.U4GM.usd_price,'U4GM 页面总价'):null;
        const iggmPage = iggm?decimal(bySite.IGGM.usd_price,'IGGM 页面总价'):null;
        const quantities=Object.fromEntries(pricingSites.map(site=>
          [site,100+Number(bySite[site].bonus_k)]));
        if (Object.values(quantities).some(quantity=>!Number.isFinite(quantity)||quantity<100||quantity>200)) {
          row.status='核心竞品赠送数量异常'; return row;
        }
        const delivered = ownBase+ownBonus;
        const costUsd = cost/fx;
        const beforePage = decimal(own.package_usd,'MMOEXP 当前页面总价');
        const beforeMargin = (1-costUsd*delivered/beforePage)*100;
        const picked = tieredPagePrice(lootbarPage,u4gmPage,iggmPage,costUsd,delivered,minimumMargin,exactMarginBand(cost,fx,delivered,beforePage),
          quantities.Lootbar,quantities.U4GM,quantities.IGGM,pricingRules,
          referenceSources.includes('U7Buy')?[decimal(bySite.U7Buy.usd_price,'U7Buy 页面总价'),quantities.U7Buy]:null);
        const floorCents = Math.ceil(costUsd*delivered*100/(1-minimumMargin/100)-1e-10);
        const floor = floorCents/10000;
        const auto = picked ? picked.cents/10000 : null;
        const manualQuote = edits.quotes?.[platform];
        const manual = manualQuote ? decimal(manualQuote,'人工建议价') : null;
        if (manual!==null && !/^\d+(?:\.\d{1,4})?$/.test(String(manualQuote)))
          fail('人工建议价最多四位小数');
        const proposed = manual!==null ? manual : auto!==null ? auto : floor;
        const page = proposed*100;
        const margin = (1-costUsd*delivered/page)*100;
        const blocked = manual===null && !picked;
        const blockedReason = blocked ? 'no_feasible_price_in_band' : null;
        const below = proposed<floor;
        const reduction = (1-(page/ownBase)/lootbar.unit)*100;
        const warning = manual!==null && below ? '人工建议价低于设定毛利率；已按人工审核价待确认发布。' :
          blocked ? '目标降幅与设置的最低毛利率无共同可行价；已暂停该平台自动改价，请人工审核。' :
          manual===null && picked?.profitFloorApplied ? `最低 ${String(minimumMargin)}% 毛利保护覆盖目标降幅 ${picked.requestedDiscount.toFixed(2)}%；实际采用降幅 ${reduction.toFixed(2)}%，标价 $${page.toFixed(2)}，赠送计入采购成本。` : '';
        Object.assign(row,{lowest_site:lowest.site,lowest_usd_per_1k:lowest.unit.toFixed(4),
          lootbar_usd_per_1k:lootbar.unit.toFixed(4),lootbar_page_usd:lootbarPage.toFixed(2),
          target_page_usd:blocked?null:page.toFixed(2),pricing_basis:'page_total_100k',
          pricing_quantity_basis:'own_base_competitor_delivered',
          requested_discount_pct:picked?picked.requestedDiscount.toFixed(2):null,
          profit_floor_applied:Boolean(manual===null && picked?.profitFloorApplied),
          pricing_tier:picked?.tier||null,own_bonus_k:String(ownBonus),
          pre_change_margin_pct:beforeMargin.toFixed(2),
          u4gm_gap_pct:u4gmGap===null?null:u4gmGap.toFixed(2),iggm_gap_pct:iggmGap===null?null:iggmGap.toFixed(2),
          lootbar_reduction_pct:blocked?null:reduction.toFixed(2),
          floor_usd_per_1k:floor.toFixed(4),auto_proposal:auto===null?null:auto.toFixed(4),
          proposal:proposed.toFixed(4),quote_manual:manual!==null,gross_margin_pct:margin.toFixed(2),
          pricing_mode:manual!==null?'manual':blocked?'tier_unavailable':'lootbar_anchor',
          benchmark_site:'Lootbar',minimum_gross_margin_pct:String(minimumMargin),
          margin_below_minimum:below,auto_blocked_reason:blockedReason,
          warning,status:manual!==null?'人工审核通过 · 待发布':blocked?
            '分档无可行自动价 · 待人工审核':'按 Lootbar 含赠送实际单价对标 · 待审核'});
        return row;
      }
      const reduction=Math.min(8,0.5+0.15*Math.min(u4gmGap,iggmGap)+0.05*Math.max(u4gmGap,iggmGap));
      const target=Number((Math.floor((lootbar.unit*(1-reduction/100)+1e-12)*10000)/10000).toFixed(4));
      const capFloor=Math.ceil(lootbar.unit*0.92*10000)/10000;
      const auto=Math.max(target,capFloor);
      const manualQuote=edits.quotes?.[platform];
      const proposed=manualQuote?decimal(manualQuote,'人工建议价'):auto;
      const below=proposed<floor;
      const warning=below?(manualQuote?'人工建议价低于设定毛利率；已按人工审核价待确认发布。':
        `Lootbar 基准下调 ${reduction.toFixed(2)}% 后仍未达设定毛利率，请逐项审核。`):'';
      const mode=manualQuote?'manual':below?'margin_warning':'lootbar_anchor';
      Object.assign(row,{lowest_site:lowest.site,lowest_usd_per_1k:lowest.unit.toFixed(4),
        lootbar_usd_per_1k:lootbar.unit.toFixed(4),u4gm_gap_pct:u4gmGap.toFixed(2),
        iggm_gap_pct:iggmGap.toFixed(2),lootbar_reduction_pct:reduction.toFixed(2),
        floor_usd_per_1k:floor.toFixed(4),auto_proposal:auto.toFixed(4),proposal:proposed.toFixed(4),
        quote_manual:Boolean(manualQuote),gross_margin_pct:((1-cost/fx/proposed)*100).toFixed(2),
        pricing_mode:mode,benchmark_site:'Lootbar',
        minimum_gross_margin_pct:String(minimumMargin),margin_below_minimum:below,warning,
        status:manualQuote?'人工审核通过 · 待发布':below?'低于设定毛利率 · 待审核':
          '按 Lootbar 对标 · 待审核'});
      return row;
    });
    if(evidence.game==='FC27'&&evidence.storefront){
      const ps=rows.find(row=>row.platform==='PS'),xbox=rows.find(row=>row.platform==='XBOX');
      if(xbox.pricing_basis==='page_total_100k'){
        xbox.independent_auto_proposal=xbox.auto_proposal;
        xbox.auto_price_source='PS';
        if(ps.missing.length||!ps.auto_proposal||ps.auto_blocked_reason){
          xbox.auto_proposal=null;
          if(!xbox.quote_manual)Object.assign(xbox,{auto_blocked_reason:'ps_auto_price_unavailable',
            target_page_usd:null,status:'PS 自动建议价不可用 · Xbox 暂不自动改价',
            warning:'PS 没有有效自动建议价，Xbox 本轮不执行自动改价。'});
        }else{
          xbox.auto_proposal=ps.auto_proposal;
          if(!xbox.quote_manual){
            const price=Number(ps.auto_proposal),delivered=100+Number(xbox.own_bonus_k),page=price*100;
            const margin=(1-Number(xbox.cost_cny)/fx*delivered/page)*100;
            const lootbar=xbox.offers.find(offer=>offer.site==='Lootbar');
            const unit=Number(lootbar.usd_price)/(Number(lootbar.base_k)+Number(lootbar.bonus_k));
            const below=price<Number(xbox.floor_usd_per_1k);
            Object.assign(xbox,{proposal:price.toFixed(4),target_page_usd:page.toFixed(2),
              gross_margin_pct:margin.toFixed(2),margin_below_minimum:below,
              lootbar_reduction_pct:((1-page/100/unit)*100).toFixed(2),
              auto_blocked_reason:null,pricing_mode:'ps_shared_market',pricing_tier:ps.pricing_tier,
              requested_discount_pct:ps.requested_discount_pct,profit_floor_applied:Boolean(ps.profit_floor_applied),
              benchmark_site:'PS',warning:below?'PS 建议价低于 Xbox 最低毛利要求，Xbox 本轮不执行自动改价。':ps.warning||'',
              status:below?'跟随 PS 建议价 · Xbox 毛利不足，自动改价拦截':'与 PS 统一自动售价 · 待审核'});
          }
        }
      }
    }
    return {checked_at:evidence.checked_at,fx:evidence.fx,minimum_gross_margin_pct:String(minimumMargin),rows};
  }

  function buildPreview(payload, now = Date.now()) {
    if (!payload || typeof payload !== 'object') fail('报价数据缺失');
    const evidence = payload.evidence;
    const edits = payload.edits || {};
    if (!evidence || evidence.game !== 'FC27' || evidence.product !== 'Game Coins')
      fail('本轮证据不是 FC27 / Game Coins');
    parsedTime(evidence.checked_at, '本轮采集时间', now);
    parsedTime(evidence.fx?.checked_at, '汇率采集时间', now);
    decimal(evidence.fx?.cny_per_usd, '本轮汇率');
    const result = recompute(evidence, edits);

    const targets = [];
    for (const platform of Object.keys(PLATFORMS)) {
      const sourceCost = evidence.costs?.[platform];
      if (!sourceCost || sourceCost.game !== 'FC27' || sourceCost.product !== 'Game Coins')
        fail(`${platform} 本轮采购成本缺失或商品不匹配`);
      decimal(sourceCost.cny_per_1k, `${platform} 本轮采购成本`);
      parsedTime(sourceCost.checked_at, `${platform} 成本采集时间`, now);
      if (!/^\d+$/.test(String(sourceCost.record_id ?? '')) || !sourceCost.trade_at)
        fail(`${platform} 成本来源记录不完整`);

      for (const site of SITES) {
        const offer = evidence.offers?.[platform]?.[site];
        if (!offer && evidence.storefront && site!=='Lootbar') continue;
        if (!offer) fail(`${platform} ${site} 竞品报价缺失`);
        if (offer.currency !== undefined && offer.currency !== 'USD') fail(`${platform} ${site} 竞品币种不符`);
        decimal(offer.usd_price, `${platform} ${site} 售价`);
        decimal(offer.base_k, `${platform} ${site} 购买量`);
        if (!/^(?:0|\d+(?:\.\d{1,6})?)$/.test(String(offer.bonus_k ?? '')))
          fail(`${platform} ${site} 赠送量缺失或格式不符`);
        parsedTime(offer.checked_at, `${platform} ${site} 采集时间`, now);
      }

      const rows = result.rows.filter(row => row?.platform === platform);
      if (rows.length !== 1) fail(`${platform} 报价结果重复或缺失`);
      const row = rows[0];
      if (row.status === '缺成本' || row.missing?.length || !Array.isArray(row.offers) ||
          row.offers.length !== SITES.length || !row.proposal)
        fail(`${platform} 报价存在缺项，停止改价`);
      if (!sameMoney(row.raw_cost_cny, sourceCost.cny_per_1k, 6))
        fail(`${platform} 当前计算引用的原始成本与本轮采集不一致`);
      const quote = fixed4(row.proposal, `${platform} 建议价`);
      if (row.pricing_basis === 'page_total_100k') {
        const own = evidence.storefront?.rows?.[platform];
        if (evidence.storefront?.status !== 'ok' || own?.status !== 'ok' ||
            own?.platform !== platform || Number(own?.base_k) !== 100)
          fail(`${platform} 本轮 MMOEXP 页面售价证据缺失`);
        parsedTime(own.checked_at, `${platform} 前台售价采集时间`, now);
        if (row.target_page_usd !== null &&
            !sameMoney(row.target_page_usd,(Number(quote)*100).toFixed(2)))
          fail(`${platform} 页面总价与后台目标价不一致`);
      }
      if (typeof row.margin_below_minimum !== 'boolean')
        fail(`${platform} 毛利状态缺失`);
      if (row.margin_below_minimum && !String(row.warning || '').trim())
        fail(`${platform} 低毛利警告缺失`);

      targets.push({
        platform,
        id: PLATFORMS[platform].id,
        quote,
        targetCost: costForQuote(quote),
        sourceCost: Number(sourceCost.cny_per_1k).toFixed(6),
        effectiveCost: Number(row.cost_cny).toFixed(6),
        costManual: Boolean(row.cost_manual),
        costEditReason: row.cost_manual ? String(edits.reason || '') : '',
        recordTradeAt: String(sourceCost.trade_at),
        checkedAt: evidence.checked_at,
        pricingMode: String(row.pricing_mode || ''),
        pricingBasis: String(row.pricing_basis || ''),
        targetPageUsd: row.target_page_usd,
        lootbarPageUsd: row.lootbar_page_usd,
        ownBonusK: row.own_bonus_k,
        autoBlockedReason: row.auto_blocked_reason,
        quoteManual: Boolean(row.quote_manual),
        marginBelowMinimum: row.margin_below_minimum,
        minimumGrossMargin: String(row.minimum_gross_margin_pct ?? result.minimum_gross_margin_pct ?? ''),
        actualGrossMargin: String(row.gross_margin_pct ?? ''),
        warning: String(row.warning || ''),
        offers: row.offers.map(offer=>({site:offer.site,usdPerK:offer.usd_per_1k,
          comparable:offer.comparable,conditional:offer.conditional,manual:offer.manual,
          checkedAt:offer.checked_at}))
      });
    }
    return {
      checkedAt: evidence.checked_at,
      fx: String(evidence.fx.cny_per_usd),
      minimumGrossMargin: String(result.minimum_gross_margin_pct ?? ''),
      targets
    };
  }

  function validateBackendSnapshot(snapshot, expectedTargets) {
    if (!snapshot || snapshot.origin !== 'https://order.p2pah.cn' ||
        snapshot.path !== '/game/admin_game_price/index.html')
      fail('当前页面不是 P2PAH 商品价格管理页');
    if (String(snapshot.queryGid) !== '1322' || String(snapshot.gameId) !== '1322')
      fail('当前页面 URL 和筛选项未同时确认 FC 27（商品 ID 1322）');
    if (Number(snapshot.exchangeRate) !== 6.65) fail('后台人民币汇率不是固定值 6.65');
    if (snapshot.allServerCount !== 1 || snapshot.websiteSelectCount !== 1 || snapshot.b2cCount !== 1)
      fail('后台所有区、地区或 B2C 控件缺失或重复');
    if (snapshot.allServerChecked !== false) fail('所有区选项必须保持未勾选');
    if (snapshot.selectedWebsites !== 0) fail('检测到已选地区选项；请全部取消后再继续');
    if (snapshot.b2cSelected !== true) fail('后台 B2C 选项未勾选，停止改价');
    if (snapshot.saveFormCount !== 1 || snapshot.saveFormAction !== '/game/admin_game_price/saveprice.html' ||
        snapshot.saveFormOrigin !== 'https://order.p2pah.cn' || snapshot.saveFormMethod !== 'get' ||
        snapshot.syncButtonCount !== 1)
      fail('后台保存或同步控件与已核验契约不符');
    if (!Array.isArray(snapshot.rows) || !Array.isArray(expectedTargets) ||
        snapshot.rows.length !== 3 || expectedTargets.length !== 3)
      fail('后台 FC 27 商品行必须恰好包含三个平台');
    const seenIds = new Set();
    for (const target of expectedTargets) {
      const matches = snapshot.rows.filter(row => row?.platform === target.platform &&
        row?.expectedPlatform === target.platform);
      if (matches.length !== 1) fail(`${target.platform} 后台商品行缺失或重复`);
      const row = matches[0];
      if (String(row.id) !== target.id || String(row.gameId) !== '1322' ||
          row.platform !== target.platform || seenIds.has(String(row.id)) ||
          row.platformSpan !== target.platform ||
          row.lirunlv == null || Number(row.lirunlv) !== 0.2)
        fail(`${target.platform} 平台 ID、商品或毛利率字段不匹配`);
      seenIds.add(String(row.id));
      if (!/^\d+\.\d{6}$/.test(String(row.costPrice || '')))
        fail(`${target.platform} 成本字段精度不符合预期`);
      decimal(row.b2c, `${target.platform} B2C 价格`, 6);
    }
    return true;
  }

  function sameBackendSnapshot(a, b, platforms) {
    if (!a || !b || a.origin !== b.origin || a.path !== b.path ||
        String(a.queryGid) !== String(b.queryGid) || String(a.gameId) !== String(b.gameId) ||
        Number(a.exchangeRate) !== Number(b.exchangeRate) ||
        a.allServerCount !== b.allServerCount || a.websiteSelectCount !== b.websiteSelectCount ||
        a.b2cCount !== b.b2cCount || a.saveFormCount !== b.saveFormCount ||
        a.saveFormAction !== b.saveFormAction || a.saveFormOrigin !== b.saveFormOrigin ||
        a.syncButtonCount !== b.syncButtonCount ||
        a.allServerChecked !== b.allServerChecked ||
        a.selectedWebsites !== b.selectedWebsites || a.b2cSelected !== b.b2cSelected)
      return false;
    return platforms.every(platform => {
      const before = a.rows?.find(row => row.platform === platform);
      const after = b.rows?.find(row => row.platform === platform);
      return before && after && before.id === after.id && before.gameId === after.gameId &&
        before.platform === after.platform && sameMoney(before.costPrice, after.costPrice) &&
        sameMoney(before.b2c, after.b2c) && Number(before.lirunlv) === Number(after.lirunlv);
    });
  }

  function verifyReadback(snapshot, targets, originals, operation = 'apply') {
    for (const target of targets) {
      const row = snapshot?.rows?.find(item => item.platform === target.platform);
      if (!row || row.id !== target.id) fail(`${target.platform} 回读平台 ID 不符`);
      const expectedCost = operation === 'restore' ? originals[target.platform].costPrice : target.targetCost;
      const expectedB2c = operation === 'restore' ? originals[target.platform].b2c : target.quote;
      if (!sameMoney(row.costPrice, expectedCost) || !sameMoney(row.b2c, expectedB2c))
        fail(`${target.platform} 回读成本或 B2C 价格不符`);
    }
    return true;
  }

  function selectedTargets(allTargets, selected) {
    if (!Array.isArray(selected) || !selected.length) fail('请至少选择一个平台');
    const selectedNames=new Set();
    return selected.map(item=>{
      const target=allTargets.find(row=>row.platform===item.platform);
      if (!target || target.id!==item.id || selectedNames.has(item.platform))
        fail('所选平台重复或与预览不一致');
      selectedNames.add(item.platform);
      return target;
    });
  }

  async function executeApply(adapter, allTargets, chosenTargets, initialSnapshot, originals) {
    const changed=[];
    let synced=false;
    try {
      validateBackendSnapshot(initialSnapshot,allTargets);
      const chosen=selectedTargets(allTargets,chosenTargets);
      const liveStart=await adapter.read();
      validateBackendSnapshot(liveStart,allTargets);
      if (!sameBackendSnapshot(initialSnapshot,liveStart,Object.keys(PLATFORMS)))
        fail('后台值已变化，请重新读取预览');
      for (const target of chosen) {
        if (typeof adapter.revalidateSources!=='function' ||
            !await adapter.revalidateSources(target)) fail('本轮证据重新校验失败，停止写入');
        const before=originals[target.platform];
        const live=await adapter.read();
        validateBackendSnapshot(live,allTargets);
        for (const allTarget of allTargets) {
          const liveRow=live.rows.find(item=>item.platform===allTarget.platform);
          const previous=originals[allTarget.platform];
          const alreadyChanged=changed.includes(allTarget.platform);
          const expectedCost=alreadyChanged?allTarget.targetCost:previous.costPrice;
          const b2cOkay=alreadyChanged?
          (sameMoney(liveRow.b2c,previous.b2c)||sameMoney(liveRow.b2c,allTarget.quote)):
            sameMoney(liveRow.b2c,previous.b2c);
          if (!sameMoney(liveRow.costPrice,expectedCost) || !b2cOkay)
            fail(`${allTarget.platform} 后台值在逐行提交前发生变化`);
        }
        const row=live.rows.find(item=>item.platform===target.platform);
        if (!before || !sameMoney(row.costPrice,before.costPrice) || !sameMoney(row.b2c,before.b2c))
          fail(`${target.platform} 后台原值与预览不一致`);
        try {
          await adapter.writeCost(target.platform,target.id,before.costPrice,target.targetCost);
          changed.push(target.platform);
        } catch (error) {
          const observed=await adapter.read().catch(()=>null);
          const current=observed?.rows?.find(item=>item.platform===target.platform);
          if (current && sameMoney(current.costPrice,target.targetCost) && !changed.includes(target.platform))
            changed.push(target.platform);
          throw error;
        }
      }
      const beforeSync=await adapter.read();
      validateBackendSnapshot(beforeSync,allTargets);
      for (const target of allTargets) {
        const row=beforeSync.rows.find(item=>item.platform===target.platform);
        const old=originals[target.platform];
        const isChosen=chosen.some(item=>item.platform===target.platform);
        const expectedCost=isChosen?target.targetCost:old.costPrice;
        const expectedB2c=isChosen?
          (sameMoney(row.b2c,old.b2c)||sameMoney(row.b2c,target.quote)):
          sameMoney(row.b2c,old.b2c);
        if (!sameMoney(row.costPrice,expectedCost) || !expectedB2c)
          fail(`${target.platform} 同步前成本或 B2C 原值发生变化`);
      }
      for (const target of chosen) {
        if (typeof adapter.revalidateSources!=='function' ||
            !await adapter.revalidateSources(target)) fail('同步前本轮证据已过期或发生变化');
      }
      const response=await adapter.sync();
      if (!response?.success || !response.message) fail('后台没有新的同步成功反馈');
      synced=true;
      await adapter.reload();
      const after=await adapter.read();
      validateBackendSnapshot(after,allTargets);
      verifyReadback(after,chosen,originals,'apply');
      for (const target of allTargets) {
        if (chosen.some(item=>item.platform===target.platform)) continue;
        const row=after.rows.find(item=>item.platform===target.platform);
        const old=originals[target.platform];
        if (!sameMoney(row.costPrice,old.costPrice)||!sameMoney(row.b2c,old.b2c))
          fail(`${target.platform} 未选平台在同步后发生变化`);
      }
      return {ok:true,changed,synced,message:String(response.message)};
    } catch (error) {
      return {ok:false,changed,synced,error:String(error?.message||error)};
    }
  }

  async function executeRestore(adapter, allTargets, chosenTargets, initialSnapshot, originals) {
    const restored=[];
    let synced=false;
    try {
      validateBackendSnapshot(initialSnapshot,allTargets);
      const chosen=selectedTargets(allTargets,chosenTargets);
      const liveStart=await adapter.read();
      validateBackendSnapshot(liveStart,allTargets);
      if (!sameBackendSnapshot(initialSnapshot,liveStart,Object.keys(PLATFORMS)))
        fail('后台值已变化，请重新读取后恢复');
      for (const target of chosen) {
        const row=initialSnapshot.rows.find(item=>item.platform===target.platform);
        const old=originals[target.platform];
        if (!old || (!sameMoney(row.costPrice,target.targetCost,6)&&
            !sameMoney(row.costPrice,old.costPrice,6)) ||
            (!sameMoney(row.b2c,old.b2c) && !sameMoney(row.b2c,target.quote)))
          fail(`${target.platform} 后台值已变化，无法安全恢复原值`);
      }
      for (const target of chosen) {
        const live=await adapter.read();
        validateBackendSnapshot(live,allTargets);
        for (const allTarget of allTargets) {
          const liveRow=live.rows.find(item=>item.platform===allTarget.platform);
          const oldAll=originals[allTarget.platform];
          const isChosen=chosen.some(item=>item.platform===allTarget.platform);
          const expectedCost=isChosen?(restored.includes(allTarget.platform)?oldAll.costPrice:allTarget.targetCost):
            initialSnapshot.rows.find(item=>item.platform===allTarget.platform).costPrice;
          if (!sameMoney(liveRow.costPrice,expectedCost,6))
            fail(`${allTarget.platform} 后台成本在恢复前发生变化`);
          if (isChosen && !sameMoney(liveRow.b2c,oldAll.b2c) &&
              !sameMoney(liveRow.b2c,allTarget.quote))
              fail(`${allTarget.platform} 后台 B2C 价格在恢复前发生变化`);
          if (!isChosen) {
            const before=initialSnapshot.rows.find(item=>item.platform===allTarget.platform);
            if (!sameMoney(liveRow.b2c,before.b2c))
              fail(`${allTarget.platform} 未选平台 B2C 值在恢复前发生变化`);
          }
        }
        const old=originals[target.platform];
        const liveTarget=live.rows.find(item=>item.platform===target.platform);
        if (sameMoney(liveTarget.costPrice,old.costPrice)) {
          restored.push(target.platform);
          continue;
        }
        try {
          await adapter.writeCost(target.platform,target.id,target.targetCost,old.costPrice);
          restored.push(target.platform);
        } catch (error) {
          const observed=await adapter.read().catch(()=>null);
          const current=observed?.rows?.find(item=>item.platform===target.platform);
          if (current && sameMoney(current.costPrice,old.costPrice) && !restored.includes(target.platform))
            restored.push(target.platform);
          throw error;
        }
      }
      const beforeSync=await adapter.read();
      validateBackendSnapshot(beforeSync,allTargets);
      for (const target of chosen) {
        const row=beforeSync.rows.find(item=>item.platform===target.platform);
        const old=originals[target.platform];
        if (!sameMoney(row.costPrice,old.costPrice,6) ||
            (!sameMoney(row.b2c,old.b2c) && !sameMoney(row.b2c,target.quote)))
          fail(`${target.platform} 恢复前值不符，已停止同步`);
      }
      for (const target of allTargets) {
        if (chosen.some(item=>item.platform===target.platform)) continue;
        const row=beforeSync.rows.find(item=>item.platform===target.platform);
        const before=initialSnapshot.rows.find(item=>item.platform===target.platform);
        if (!sameMoney(row.costPrice,before.costPrice) || !sameMoney(row.b2c,before.b2c))
          fail(`${target.platform} 未选平台在恢复同步前发生变化`);
      }
      const response=await adapter.sync();
      if (!response?.success || !response.message) fail('后台没有新的同步成功反馈');
      synced=true;
      await adapter.reload();
      const after=await adapter.read();
      validateBackendSnapshot(after,allTargets);
      verifyReadback(after,chosen,originals,'restore');
      for (const target of allTargets) {
        if (chosen.some(item=>item.platform===target.platform)) continue;
        const row=after.rows.find(item=>item.platform===target.platform);
        const before=initialSnapshot.rows.find(item=>item.platform===target.platform);
        if (!sameMoney(row.costPrice,before.costPrice)||!sameMoney(row.b2c,before.b2c))
          fail(`${target.platform} 未选平台在恢复后发生变化`);
      }
      return {ok:true,restored,synced,message:String(response.message)};
    } catch (error) {
      return {ok:false,restored,synced,error:String(error?.message||error)};
    }
  }

  const api = Object.freeze({
    PLATFORMS, SITES, MAX_AGE_MS, FIXED_MARGIN, FIXED_RMB_RATE,
    recompute, buildPreview, costForQuote, requiresLowMarginConfirmation, unwrapInjectionResult, validateBackendSnapshot, sameBackendSnapshot, verifyReadback,
    executeApply, executeRestore,
    sameMoney
  });
  globalThis.FC27RepricingLogic = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
