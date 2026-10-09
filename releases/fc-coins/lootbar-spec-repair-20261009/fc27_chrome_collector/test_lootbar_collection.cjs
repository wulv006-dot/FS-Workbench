'use strict';

// Offline regression tests for the self-contained chrome.scripting Lootbar reader.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('fc27_chrome_collector/background.js', 'utf8');
let checks = 0;

class Element {
  constructor(tagName, {classes = [], text = null, visible = true, href = '', decoration = 'none', children = []} = {}) {
    this.tagName = tagName.toUpperCase();
    this.classes = new Set(classes);
    this.rawText = text;
    this.visible = visible;
    this.href = href;
    this.decoration = decoration;
    this.children = children;
    for (const child of children) child.parent = this;
  }
  get innerText() {
    return this.rawText == null ? this.children.map(child => child.innerText).filter(Boolean).join(' ') : this.rawText;
  }
  getClientRects() { return this.visible ? [{}] : []; }
  contains(other) { return this.children.some(child => child === other || child.contains(other)); }
  querySelectorAll(selector) {
    const all = [];
    const visit = node => { for (const child of node.children) { all.push(child); visit(child); } };
    visit(this);
    return all.filter(node => matches(node, selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function matches(node, selector) {
  if (selector === '*') return true;
  if (selector === 'a.on') return node.tagName === 'A' && node.classes.has('on');
  if (selector === '.coin-listitem') return node.classes.has('coin-listitem');
  if (selector === '.con-name') return node.classes.has('con-name');
  if (selector === '.discount-price') return node.classes.has('discount-price');
  if (selector === '.gift-num') return node.classes.has('gift-num');
  return false;
}

function buildCard(scenario, readNumber) {
  const children = [new Element('span', {classes:['con-name'], text:scenario.specName || '100K Safe Coins'})];
  const label = scenario.platformLabel || 'PS4/5';
  const platformCurrent = scenario.platformPrices?.[label];
  const finalCurrent = platformCurrent || (scenario.coupon ? (scenario.currentPrice || '$15.04') : (scenario.currentPrice || '$15.99'));
  const current = new Element('span', {classes:['discount-price'], text:finalCurrent});
  const hasDiscountText = Object.prototype.hasOwnProperty.call(scenario, 'discountText');
  const discountText = hasDiscountText ? scenario.discountText : (scenario.coupon ? '-$0.95' : null);
  const badges = [discountText, scenario.extraDiscount].filter(value => value != null)
    .map(value => new Element('span', {classes:['coupon-amount'], text:value}));
  if (scenario.aggregateCouponWrapper) {
    const wrapper = new Element('div', {classes:['item-discount'], children:[current,...badges]});
    children.push(new Element('div', {classes:['coin-listitem-con'], children:[wrapper]}));
  } else {
    children.push(current);
    children.push(...badges);
  }

  if (scenario.coupon || scenario.strikeValues?.length) {
    const values = scenario.strikeValues || [scenario.originalPrice || '$15.99'];
    for (const value of values) {
      const decoration = scenario.computedStrike ? 'line-through' : 'none';
      if (scenario.splitStrike) {
        const raw = value.replace('$','');
        children.push(new Element(scenario.computedStrike ? 'span' : 'del', {decoration,children:[
          new Element('span',{text:'$',decoration}),new Element('span',{text:raw,decoration})]}));
      } else children.push(new Element(scenario.computedStrike ? 'span' : 'del', {text:value,decoration}));
    }
  }
  if (!scenario.omitGift && !(scenario.delayGift && readNumber < 3))
    children.push(new Element('span', {classes:['gift-num'], text:scenario.giftText || '+5K'}));
  return new Element('div', {classes:['coin-listitem'], children});
}

function makeHarness(scenario = {}) {
  let nextTab = 0;
  const tabs = new Map();
  const removed = [];
  const updates = [];
  const listeners = [];
  const readCounts = new Map();
  const scriptResults = [];
  const chrome = {
    runtime: {
      onMessage: {addListener(listener) { listeners.push(listener); }},
      getURL: path => `chrome-extension://offline/${path}`
    },
    tabs: {
      async create({url}) { const id = ++nextTab; tabs.set(id, {id,url,reads:0}); return {id}; },
      async remove(id) { removed.push(id); tabs.delete(id); },
      async update(id, options) { updates.push({id,options}); return tabs.get(id); }
    },
    scripting: {
      async executeScript({target,func}) {
        const tab = tabs.get(target.tabId);
        tab.reads++;
        readCounts.set(tab.id, tab.reads);
        if (scenario.failReadAt === tab.reads) throw new Error('mocked injection error');
        const label = new URL(tab.url).searchParams.get('platform') === 'xbox' ? 'Xbox' :
          new URL(tab.url).searchParams.get('platform') === 'pc' ? 'PC' : 'PS4/5';
        const account = new Element('a', {classes:['c-nav-userinfo-avatar-wrap'], href:'/account', text:'', visible:scenario.loggedIn !== false});
        const rootNodes = [
          new Element('a', {classes:['on'], text:label}),
          new Element('button', {classes:['c-nav-prefer'], text:scenario.currency || 'EN / USD'}),
          account,
          buildCard({...scenario,platformLabel:label}, tab.reads)
        ];
        if (scenario.duplicateSpec) rootNodes.push(buildCard({...scenario,platformLabel:label}, tab.reads));
        const document = {
          querySelectorAll(selector) { return rootNodes.filter(node => matches(node, selector)); },
          querySelector(selector) {
            if (selector === "a[href='/account'].c-nav-userinfo-avatar-wrap") return account;
            if (selector === 'button.c-nav-prefer') return rootNodes[1];
            return null;
          }
        };
        const getComputedStyle = node => {
          let cursor = node, struck = false;
          while (cursor) { if (cursor.decoration === 'line-through') { struck = true; break; } cursor = cursor.parent; }
          return {display:node.visible?'block':'none',visibility:'visible',textDecorationLine:struck?'line-through':node.decoration};
        };
        const result = vm.runInNewContext(`(${func.toString()})()`, {document,getComputedStyle});
        scriptResults.push(result);
        return [{result}];
      }
    },
    storage: {session:{async get(){return {}},async set(){},async remove(){}}}
  };
  let context;
  context = vm.createContext({chrome,importScripts(path){
    if (path === 'local_collector.js')
      vm.runInContext(fs.readFileSync('fc27_chrome_collector/local_collector.js','utf8'),context,{filename:path});
  },setTimeout(callback){queueMicrotask(callback);return 1;}});
  vm.runInContext(source, context, {filename:'background.js'});
  async function collect() {
    return new Promise(resolve => {
      let keepAlive;
      for (const listener of listeners) {
        keepAlive = listener({type:'FC27_LOOTBAR_COLLECT'}, {}, resolve);
        if (keepAlive === true) break;
      }
      assert.equal(keepAlive, true);
    });
  }
  return {collect,tabs,removed,updates,readCounts,scriptResults,context};
}

async function success(scenario, platform = 'PS') {
  const harness = makeHarness(scenario);
  const result = await harness.collect();
  assert.equal(result.error, undefined, `${result.error}; last reads: ${JSON.stringify(harness.scriptResults.slice(-3))}`);
  const offer = result.offers[platform];
  assert.ok(offer, `missing ${platform} result`);
  checks++;
  return {offer,harness};
}

async function failure(scenario, pattern) {
  const harness = makeHarness(scenario);
  const result = await harness.collect();
  assert.match(result.error || '', pattern);
  assert.equal(harness.removed.length, 0, 'failed Lootbar pages must stay open');
  assert.equal(harness.tabs.size, 3, 'each failed platform page must be preserved');
  assert.equal(harness.updates.length, 1, 'one failed platform page is focused for review');
  assert.match(result.error, /失败的 Lootbar 页面已保留/);
  checks += 4;
  return {result,harness};
}

(async () => {
  const normal = await success({});
  assert.equal(normal.offer.usd_price,'15.99');
  assert.equal(normal.offer.bonus_k,'5');
  assert.equal(normal.harness.removed.length,3);
  checks += 3;

  // The current price, coupon badge and struck-through pre-coupon price share
  // nested card ancestors. Only the coupon amount node is treated as evidence.
  const coupon = await success({coupon:true,aggregateCouponWrapper:true});
  assert.equal(coupon.offer.usd_price,'15.99');
  assert.equal(coupon.offer.observed_coupon_price,'15.04');
  assert.equal(coupon.offer.excluded_coupon_discount,'0.95');
  assert.equal(coupon.offer.status,'已排除账号新客优惠券价');
  checks += 4;

  const delayed = await success({delayGift:true});
  assert.equal(delayed.offer.bonus_k,'5');
  assert.ok([...delayed.harness.removed].length===3);
  assert.ok([...delayed.harness.readCounts.values()].every(reads => reads >= 5));
  checks += 3;

  const computedStrike = await success({coupon:true,aggregateCouponWrapper:true,computedStrike:true});
  assert.equal(computedStrike.offer.usd_price,'15.99');
  checks++;

  const inheritedSplitStrike = await success({coupon:true,aggregateCouponWrapper:true,
    computedStrike:true,splitStrike:true});
  assert.equal(inheritedSplitStrike.offer.usd_price,'15.99');
  checks++;

  const groupedMoney = await success({coupon:true,aggregateCouponWrapper:true,
    originalPrice:'$1,234.56',currentPrice:'$1,233.61',discountText:'-$0.95'});
  assert.equal(groupedMoney.offer.usd_price,'1234.56');
  assert.equal(groupedMoney.offer.observed_coupon_price,'1233.61');
  checks += 2;

  const platforms = makeHarness({platformPrices:{'PS4/5':'$15.99','Xbox':'$16.49','PC':'$17.99'}});
  const platformResult = await platforms.collect();
  assert.equal(platformResult.offers.PS.usd_price,'15.99');
  assert.equal(platformResult.offers.XBOX.usd_price,'16.49');
  assert.equal(platformResult.offers.PC.usd_price,'17.99');
  checks += 3;

  const interrupted = await success({failReadAt:3});
  assert.ok([...interrupted.harness.readCounts.values()].every(reads => reads >= 6));
  checks++;

  await failure({coupon:true,aggregateCouponWrapper:true,strikeValues:['$15.99','$16.99']},/划线原价不唯一/);
  await failure({coupon:true,aggregateCouponWrapper:true,discountText:'-$0.95',extraDiscount:'-$0.50'},/减免金额不唯一/);
  await failure({coupon:true,aggregateCouponWrapper:true,discountText:null},/减免金额未显示/);
  await failure({coupon:true,aggregateCouponWrapper:true,discountText:'-$1.00'},/对不上/);
  await failure({currency:'EN / EUR'},/币种未核实为 USD/);
  await failure({omitGift:true},/赠送量未显示，未按 0 处理/);
  const uniqueSpec = await success();
  assert.equal(uniqueSpec.harness.scriptResults.at(-1).tierCandidateCount, 1);
  assert.equal(uniqueSpec.harness.scriptResults.at(-1).visibleCardCount, 1);
  const duplicateSpec = makeHarness({duplicateSpec:true});
  assert.match((await duplicateSpec.collect()).error, /商品规格重复/);
  assert.equal(duplicateSpec.scriptResults.at(-1).tierCandidateCount, 2);
  const missingSpec = makeHarness({specName:'Unrecognized spec'});
  assert.match((await missingSpec.collect()).error, /商品规格未识别/);
  assert.equal(missingSpec.scriptResults.at(-1).tierCandidateCount, 0);
  checks += 6;
  const localFailure = makeHarness();
  const settled = [];
  await assert.rejects(localFailure.context.collectLootbarTargets(async target => {
    await Promise.resolve();
    settled.push(target.platform);
    if (target.platform === 'PS') throw Object.assign(new Error('PS 页面失败'), {lootbarTabId:73});
    return {platform:target.platform};
  }), /PS 页面失败.*失败的 Lootbar 页面已保留 1 个/);
  assert.deepEqual([...settled].sort(), ['PC','PS','XBOX']);
  assert.equal(localFailure.updates.length, 1);
  assert.equal(localFailure.updates[0].id, 73);
  assert.equal(localFailure.updates[0].options.active, true);
  checks += 2;

  console.log(`Lootbar collector offline regressions: ${checks} passed.`);
})().catch(error=>{console.error(error);process.exitCode=1});
