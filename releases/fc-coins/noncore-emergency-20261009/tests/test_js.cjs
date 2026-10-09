'use strict';
const assert = require('node:assert/strict');
const Logic = require('../source/repricing_logic.js');
const Original = require('./legacy_repricing_logic.js');
const now = Date.parse('2026-10-09T03:00:00Z');
const stamp = new Date(now - 60000).toISOString();
let checks = 0;
const same = (actual, expected) => { assert.deepEqual(actual, expected); checks++; };
const rejects = payload => { assert.throws(() => Logic.buildPreview(payload, now)); checks++; };

function payload(ownPrice = '30.00') {
  const evidence = {game:'FC27', product:'Game Coins', checked_at:stamp,
    fx:{cny_per_usd:'5', checked_at:stamp}, costs:{}, offers:{},
    storefront:{status:'ok', rows:{}}};
  for (const platform of Object.keys(Logic.PLATFORMS)) {
    evidence.costs[platform] = {game:'FC27', product:'Game Coins', cny_per_1k:'0.5',
      record_id:'12345', trade_at:stamp, checked_at:stamp};
    evidence.offers[platform] = Object.fromEntries(Object.entries({Lootbar:'20.00', U4GM:'18.00', IGGM:'19.00', U7Buy:'17.00'})
      .map(([site, usd_price]) => [site,{usd_price, base_k:'100', bonus_k:'0', comparable:true,
        checked_at:stamp, url:`https://${site.toLowerCase()}.example/item`}]));
    evidence.storefront.rows[platform] = {platform, status:'ok', base_k:'100', bonus_k:'5',
      package_usd:ownPrice, checked_at:stamp};
  }
  return {evidence, edits:{minimum_gross_margin_pct:'10'}};
}
function missing(site) {
  const value = payload();
  for (const platform of Object.keys(Logic.PLATFORMS)) delete value.evidence.offers[platform][site];
  return value;
}
function originalShape(result) {
  return {...result, rows:result.rows.map(({unavailable_sources, reference_sources, ...row})=>row)};
}

for (const own of ['30.00','16.00','14.00','12.00']) {
  const value = payload(own);
  same(originalShape(Logic.recompute(value.evidence, value.edits)), Original.recompute(value.evidence, value.edits));
  same(Logic.buildPreview(value, now), Original.buildPreview(value, now));
}
for (const [site, reference, target] of [['IGGM','U4GM','0.1800'],['U4GM','IGGM','0.1900']]) {
  const value = missing(site);
  const result = Logic.recompute(value.evidence, value.edits);
  same(result.rows.map(row=>row.proposal), [target,target,target]);
  for (const row of result.rows) {
    same(row.missing, []);
    same(row.unavailable_sources, [site]);
    same(row.reference_sources, [reference]);
    same(row.offers.length, 4);
    same(row.offers.find(offer=>offer.site===site).usd_price, undefined);
  }
  same(Logic.buildPreview(value, now).targets.map(row=>row.quote), [target,target,target]);
}
same(Logic.buildPreview(missing('U7Buy'), now).targets.map(row=>row.quote), ['0.1850','0.1850','0.1850']);
const noReferences = missing('IGGM');
for (const platform of Object.keys(Logic.PLATFORMS)) delete noReferences.evidence.offers[platform].U4GM;
same(Logic.buildPreview(noReferences, now).targets.map(row=>row.quote), ['0.1800','0.1800','0.1800']);
same(Logic.recompute(noReferences.evidence, noReferences.edits).rows.map(row=>row.reference_sources), [['U7Buy'],['U7Buy'],['U7Buy']]);
for (const platform of Object.keys(Logic.PLATFORMS)) noReferences.evidence.offers[platform].U7Buy.usd_price = '19.50';
same(Logic.buildPreview(noReferences, now).targets.map(row=>row.quote), ['0.1950','0.1950','0.1950']);
for (const mutate of [
  value=>delete value.evidence.offers.PS.U7Buy,
  value=>delete value.evidence.offers.PS.Lootbar,
  value=>value.evidence.offers.PS.U7Buy.checked_at = new Date(now-3600001).toISOString(),
  value=>value.evidence.offers.PS.U7Buy.checked_at = new Date(now+120000).toISOString(),
  value=>value.evidence.offers.PS.U7Buy.usd_price = 'NaN',
  value=>value.evidence.offers.PS.U7Buy.usd_price = '19.501',
  value=>value.evidence.offers.PS.U7Buy.base_k = '99',
  value=>value.evidence.offers.PS.U7Buy.bonus_k = '101',
  value=>value.evidence.offers.PS.U7Buy.currency = 'CNY',
  value=>value.evidence.offers.PS.U7Buy.comparable = false,
  value=>value.evidence.offers.PS.U4GM = {usd_price:'invalid'}
]) {
  const value = structuredClone(noReferences); mutate(value); rejects(value);
}
rejects(missing('Lootbar'));
for (const mutate of [
  value=>value.evidence.offers.PS.U4GM.checked_at = new Date(now-3600001).toISOString(),
  value=>value.evidence.offers.PS.U4GM.checked_at = new Date(now+120000).toISOString(),
  value=>value.evidence.offers.PS.U4GM.usd_price = '',
  value=>value.evidence.offers.PS.U4GM.usd_price = 'NaN',
  value=>value.evidence.offers.PS.U4GM.usd_price = '18.001',
  value=>value.evidence.offers.PS.U4GM.base_k = '99',
  value=>value.evidence.offers.PS.U4GM.bonus_k = '101',
  value=>value.evidence.offers.PS.U4GM.currency = 'CNY',
  value=>value.evidence.offers.PS.U4GM.comparable = false,
  value=>value.evidence.offers.PS.U7Buy.checked_at = new Date(now-3600001).toISOString(),
  value=>value.evidence.costs.PS.checked_at = new Date(now-3600001).toISOString(),
  value=>value.evidence.storefront.rows.PS.checked_at = new Date(now-3600001).toISOString(),
  value=>delete value.evidence.storefront.rows.PS
]) {
  const value = missing('IGGM'); mutate(value); rejects(value);
}
const tampered = missing('IGGM');
tampered.result = {rows:[{platform:'PS',proposal:'99.9999'}]};
same(Logic.buildPreview(tampered, now).targets[0].quote, '0.1800');
same(Logic.buildPreview(tampered, now).targets[0].quote === tampered.result.rows[0].proposal, false);
const legacy = missing('IGGM'); delete legacy.evidence.storefront;
same(Logic.recompute(legacy.evidence, legacy.edits), Original.recompute(legacy.evidence, legacy.edits));
rejects(legacy);
console.log(JSON.stringify({checks, passed:true, scope:'isolated JavaScript recompute and preview; no browser or writes'}));
