#!/usr/bin/env node
/*
 * FC27 金币工作台 —— 竞品卡片栅格「4 列 × 3 行」契约测试（离线、零依赖、零网络）
 *
 * 不变量（页面口径）：一行 = 一个区服（PS / XBOX / PC），一列 = 一家竞品
 * （Lootbar / IGGM / U4GM / U7Buy）。本轮哪家没采到，就补一张「暂未获取」
 * 占位卡，而不是把后面的卡片顶上来 —— 所以**任何**一轮采集都必须渲染
 * PLATFORMS × 固定来源数 = 3 × 4 = 12 张卡，且每个区服恰好 4 张。
 *
 * 做法：把候选 JS 里真正的渲染块原样抽出来，在最小沙箱里执行，
 * 断言渲染结果；对同一份逻辑跑三种输入（9 条 / 12 条 / 0 条）。
 * 抽取用的是**精确锚点**，源码一改测试立刻报错（不会静默变松）。
 */
'use strict';

const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', 'source', 'fc27-quote-cloud.js');
const FIX = n => path.join(__dirname, 'fixtures', 'competitors-' + n + '.json');

const SITES = ['Lootbar', 'IGGM', 'U4GM', 'U7Buy'];
const PLATFORMS = ['PS', 'XBOX', 'PC'];
const EXPECT_CARDS = SITES.length * PLATFORMS.length; // 12

const failures = [];
function ok(cond, label) {
  if (!cond) failures.push(label);
  console.log((cond ? '  PASS  ' : '  FAIL  ') + label);
}

// ── 从源码抽取渲染块（精确锚点，抽不到即失败）──────────────────────────────
const src = fs.readFileSync(SRC, 'utf8');

function sliceBetween(from, to, label) {
  const i = src.indexOf(from);
  if (i < 0) throw new Error('锚点缺失(起点) ' + label);
  const j = src.indexOf(to, i + from.length);
  if (j < 0) throw new Error('锚点缺失(终点) ' + label);
  return src.slice(i, j);
}
function braceBlock(marker) {
  const i = src.indexOf(marker);
  if (i < 0) throw new Error('缺函数: ' + marker);
  let depth = 0, seen = false;
  for (let k = i; k < src.length; k++) {
    const c = src[k];
    if (c === '{') { depth++; seen = true; }
    else if (c === '}') { depth--; if (seen && depth === 0) return src.slice(i, k + 1); }
  }
  throw new Error('函数未闭合: ' + marker);
}

const preamble = [
  sliceBetween('const PLATFORMS=', 'const $=id=>', 'PLATFORMS'),
  sliceBetween('const esc=', 'function decimal4', 'esc/fmt'),
  braceBlock('function decimal4('),
  braceBlock('function activityTime('),
].join('\n');

const tail = src.slice(src.indexOf('const offers=collection?.competitors||[];'));
const cutStart = tail.indexOf('尚无完整采集');
const cutEnd = tail.indexOf("</div>';", cutStart);
if (src.indexOf('const offers=collection?.competitors||[];') < 0 || cutStart < 0 || cutEnd < 0) {
  throw new Error('渲染块锚点缺失');
}
const renderBlock = tail.slice(0, cutEnd + "</div>';".length)
  .replace("$('monitor-competitors').innerHTML=", 'const __html=');

const factory = new Function('collection', preamble + '\n' + renderBlock + '\nreturn __html;');

// ── 断言工具 ────────────────────────────────────────────────────────────────
function render(competitors) {
  const html = factory({ competitors });
  const cards = (html.match(/<article class="monitor-competitor-card/g) || []).length;
  const missing = (html.match(/monitor-competitor-card missing/g) || []).length;
  const order = [];
  for (const m of html.matchAll(/<strong>([^<]+)<\/strong><span class="tag">([^<]+)<\/span>/g)) {
    order.push(m[2] + '/' + m[1]);
  }
  return { html, cards, missing, order };
}

function checkGrid(label, competitors, expectMissing) {
  console.log('\n[' + label + ']  输入 ' + competitors.length + ' 条竞品');
  const { cards, missing, order } = render(competitors);

  ok(cards === EXPECT_CARDS, '卡片总数 = ' + EXPECT_CARDS + '（实际 ' + cards + '）');
  ok(missing === expectMissing, '占位卡数 = ' + expectMissing + '（实际 ' + missing + '）');

  for (const p of PLATFORMS) {
    const n = order.filter(x => x.startsWith(p + '/')).length;
    ok(n === SITES.length, p + ' 区服卡片数 = ' + SITES.length + '（实际 ' + n + '）');
  }
  // 列序必须固定：每行的第 k 列恒为第 k 家竞品 —— 缺项不得让后面的卡顶上来。
  let columnsStable = order.length === EXPECT_CARDS;
  for (let i = 0; i < order.length && columnsStable; i++) {
    const expect = PLATFORMS[Math.floor(i / SITES.length)] + '/' + SITES[i % SITES.length];
    if (order[i] !== expect) columnsStable = false;
  }
  ok(columnsStable, '列序固定为 ' + SITES.join(' / ') + '，缺项不位移');
  return order;
}

// ── 场景 1：本轮真实数据（IGGM 未采到 → 9 条 / 3 张占位）──────────────────
const realRaw = JSON.parse(fs.readFileSync(FIX(9), 'utf8'));
checkGrid('真实 9 条', realRaw.competitors, EXPECT_CARDS - realRaw.competitors.length);

// ── 场景 2：四家全到（12 条 / 0 张占位）────────────────────────────────────
const fullRaw = JSON.parse(fs.readFileSync(FIX(12), 'utf8'));
checkGrid('合成 12 条', fullRaw.competitors, 0);

// ── 场景 3：只有一家到（3 条 / 9 张占位）───────────────────────────────────
const one = SITES.slice(0, 1);
const onlyLootbar = PLATFORMS.map(p => ({ platform: p, source: one[0] }));
checkGrid('仅 Lootbar 到', onlyLootbar, EXPECT_CARDS - 3);

// ── 场景 4：本轮零采集 → 走「尚无完整采集」分支，不得生成任何卡片 ───────────
console.log('\n[零采集]');
{
  const { html, cards, missing } = render([]);
  ok(cards === 0 && missing === 0, '不渲染任何竞品卡（实际 ' + cards + '）');
  ok(html.indexOf('尚无完整采集') >= 0, '显示「尚无完整采集」提示');
}

// ── 场景 5：出现固定四家之外的新来源 → 追加为第 5 列，前四列不动 ─────────────
console.log('\n[多出未知来源]');
{
  const extra = [{ platform: 'PS', source: 'NewShop' }];
  const { cards, missing, order } = render(fullRaw.competitors.concat(extra));
  ok(cards === PLATFORMS.length * (SITES.length + 1), '卡片总数 = ' + (PLATFORMS.length * (SITES.length + 1)) + '（实际 ' + cards + '）');
  ok(missing === PLATFORMS.length - 1, '仅新来源缺 2 个区服 → 占位 2（实际 ' + missing + '）');
  let prefixStable = true;
  for (let i = 0; i < order.length && prefixStable; i++) {
    const col = i % (SITES.length + 1);
    if (col < SITES.length && order[i] !== PLATFORMS[Math.floor(i / (SITES.length + 1))] + '/' + SITES[col]) prefixStable = false;
  }
  ok(prefixStable, '前四列顺序不受新来源影响');
}

// ── 结果 ───────────────────────────────────────────────────────────────────
console.log('\n' + JSON.stringify({ total: 5, failures: failures.length, assertionFailures: failures }, null, 2));
if (failures.length) {
  console.error('\nFAILED: ' + failures.length + ' 项断言未通过');
  for (const f of failures) console.error('  - ' + f);
  process.exit(1);
}
console.log('\nCOMPETITOR_GRID_OK = true');
