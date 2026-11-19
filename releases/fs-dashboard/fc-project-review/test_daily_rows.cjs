'use strict';
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright-core');

(async () => {
  const week = {game:'FC27', scope:'all', start:'2026-11-16', end:'2026-11-18',
    kpi:{salesUsd:600, profitCny:60}, daily:[
      {date:'2026-11-16', salesUsd:100, profitCny:10, marginPct:10},
      {date:'2026-11-17', salesUsd:200, profitCny:20, marginPct:10},
      {date:'2026-11-18', salesUsd:300, profitCny:30, marginPct:10}]};
  const current = {...week, start:'2026-11-17', kpi:{salesUsd:0, profitCny:null}, daily:[
    {date:'2026-11-17', salesUsd:null, profitCny:null, marginPct:null},
    {date:'2026-11-18', salesUsd:0, profitCny:-5, marginPct:-10}]};
  const data = {asOf:'2026-11-18', defaultPeriod:current, packets:[week,current]};
  const html = execFileSync(process.env.PYTHON || 'python', ['-X','utf8','-B','-c',
    'import json,sys,package_dashboard; print(package_dashboard.build(json.load(sys.stdin)))'],
    {cwd:__dirname, input:JSON.stringify(data), encoding:'utf8', maxBuffer:4*1024*1024});
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_EXECUTABLE});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => route.abort());
    await page.setContent(html);
    const choose = packet => page.selectOption('#loaded-period',
      [packet.game,packet.scope,packet.start,packet.end].join('|'), {force:true});
    const rows = () => page.locator('#sales-trend tbody tr').allTextContents();
    for (let i = 0; i < 3; i++) {
      await choose(current);
      assert.deepEqual(await rows(), ['2026-11-17——', '2026-11-18$0.00-¥5.00']);
      assert.match(await page.locator('#overview-coverage').textContent(), /缺 1 \/ 2 天/);
      assert.match(await page.locator('#kpis').innerText(), /—/);
      await choose(week);
      assert.deepEqual(await rows(), ['2026-11-16$100.00¥10.00', '2026-11-17$200.00¥20.00', '2026-11-18$300.00¥30.00']);
    }
    assert.deepEqual(errors, []);
    console.log('PASS: overlapping periods preserve selected nulls, zero and negative values across repeated switches');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
