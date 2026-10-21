// Offline fixtures are fictional; production readback is a separate acceptance.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const fixtures = JSON.parse(fs.readFileSync(path.join(__dirname, 'ui-fixtures.json')));
let access = 'admin';
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  res.setHeader('Cache-Control','no-store');
  if (url.pathname.endsWith('/data.json')) {
    res.setHeader('Content-Type','application/json');
    if (url.searchParams.get('q') === 'fixture-error') {res.writeHead(503);res.end('{}');return;}
    if (url.searchParams.get('q') === 'fixture-auth') {res.writeHead(403);res.end('{}');return;}
    if (url.searchParams.get('q') === 'fixture-busy') {res.writeHead(429);res.end('{}');return;}
    const key = url.searchParams.get('q') === 'fixture-test' ? 'test' : url.searchParams.get('q') === 'fixture-accounting' ? 'accounting' : url.searchParams.get('q') === 'fixture-pages' ? (url.searchParams.get('page') === '2' ? 'pages2' : 'pages1') : url.searchParams.get('q') ? 'empty' : url.searchParams.get('mode') === 'coupon' ? (url.searchParams.get('project') === '7' ? 'batch' : 'coupon') : (url.searchParams.get('project') === 'KOL' ? (url.searchParams.get('code')==='alpha' ? 'single' : 'kol') : 'code');
    if (key.startsWith('pages') || ['kol','single'].includes(key)) await new Promise(resolve => setTimeout(resolve, 500));
    res.end(JSON.stringify(fixtures[key]));return;
  }
  if (url.pathname.endsWith('runtime.js')) {
    res.setHeader('Content-Type','text/javascript');
    res.end(`export async function sessionIdentity(){return {name:'fixture',role:${JSON.stringify(access)}}}export async function protectedRead(u,o,deny){const r=await fetch(u,o);if([401,403].includes(r.status))deny(r.status);if(!r.ok)throw Error('protected_read_failed_'+r.status);return r}`);return;
  }
  if (url.pathname.endsWith('fs-theme.js')) {
    res.setHeader('Content-Type','text/javascript');res.end("window.FSTheme={get:()=>document.documentElement.dataset.fsTheme||'light',set:v=>{document.documentElement.dataset.fsTheme=v;dispatchEvent(new Event('fs-theme-change'))}};");return;
  }
  if (url.pathname.endsWith('.css') && !url.pathname.endsWith('/channel.css')) {
    res.setHeader('Content-Type','text/css');res.end(':root{--fs-font:system-ui;--fs-line:#ddd;--fs-text:#123;--fs-surface:#fff;--fs-bg:#eee}');return;
  }
  if (url.pathname.startsWith('/__hub/')) {res.setHeader('Content-Type','text/javascript');res.end('');return;}
  const name = url.pathname === '/dashboard/channel-effects/' ? 'index.html' : url.pathname.split('/').pop();
  if (!['index.html','channel.js','channel.css'].includes(name)) {res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type', {'.js':'text/javascript','.css':'text/css','.html':'text/html'}[path.extname(name)]);
  res.end(fs.readFileSync(path.join(root,'ui',name)));
});
(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    const failures = []; page.on('pageerror', error => failures.push(error.message));
    const url = `http://127.0.0.1:${server.address().port}/dashboard/channel-effects/`;
    await page.goto(url);
    await page.locator('#results').waitFor({state:'visible'});
    assert.match(await page.locator('#kpis').innerText(), /\$70.00/);
    assert.match(await page.locator('#projects').innerText(), /自然流量（对照）/);
    assert.match(await page.locator('#customers').innerText(), /新客/);
    assert.match(await page.locator('#customers').innerText(), /老客/);
    assert.match(await page.locator('#orders').innerText(), /新老客（ES）/);
    assert.match(await page.locator('#countries').innerText(), /美国（US）/);
    assert.match(await page.locator('#orders').innerText(), /美国（US）/);
    assert.equal(await page.locator('[name=country] option[value=US]').textContent(),'美国（US）');
    assert.equal(await page.locator('.table-wrapper').evaluateAll(nodes => nodes.every(n => n.tabIndex === 0 && n.getAttribute('role') === 'region' && n.getAttribute('aria-label'))),true);
    assert.equal(await page.locator('#orders img').count(),0);
    await page.locator('[name=q]').fill('fixture-pages'); await page.locator('button[type=submit]').click();
    await page.locator('#total').filter({hasText:'120'}).waitFor();
    const nextRequest = page.waitForRequest(req => req.url().includes('fixture-pages') && req.url().includes('page=1'));
    const nextResponse = page.waitForResponse(resp => resp.url().includes('fixture-pages') && resp.url().includes('page=1'));
    await page.locator('#next').focus();
    await nextRequest;
    assert.equal(await page.locator('#results').isVisible(),true);
    await nextResponse;
    await page.waitForTimeout(50);
    assert.equal(await page.locator('#next').evaluate(e => e === document.activeElement),true);
    await page.locator('#next').click();
    await page.locator('#page').filter({hasText:'2 / 3'}).waitFor();
    assert.equal(await page.locator('#orders tbody tr').count(),50);
    await page.locator('[name=q]').fill('fixture-busy'); await page.locator('button[type=submit]').click();
    await page.locator('#status').filter({hasText:'已有查询正在执行'}).waitFor();
    await page.locator('[name=q]').fill(''); await page.locator('button[type=submit]').click();
    await page.locator('#total').filter({hasText:'共 3 单'}).waitFor();
    const projectResponse=page.waitForResponse(resp=>resp.url().includes('project=KOL'));
    await page.locator('#projects').getByRole('button',{name:'KOL',exact:true}).click();
    assert.equal(await page.locator('#results').isVisible(),true);
    assert.equal(await page.locator('#results').getAttribute('aria-busy'),'true');
    assert.match(await page.locator('#kpis').innerText(),/\$70.00/);
    await projectResponse;
    await page.waitForFunction(() => document.querySelector('#kpis').textContent.includes('$30.00'));
    assert.match(await page.locator('#kpis').innerText(), /50.0%/);
    assert.equal(await page.locator('#projects tbody tr').count(),3);
    const codeResponse=page.waitForResponse(resp=>resp.url().includes('code=alpha'));
    await page.locator('#codes').getByRole('button',{name:/^Alpha/}).click();
    assert.equal(await page.locator('#results').isVisible(),true);
    assert.match(await page.locator('#kpis').innerText(),/\$30.00/);
    await codeResponse;
    await page.waitForFunction(()=>document.querySelector('#kpis').textContent.includes('$10.00'));
    assert.equal(await page.locator('#results').getAttribute('aria-busy'),'false');
    await page.locator('#reset').click();
    await page.waitForFunction(()=>document.querySelector('#kpis').textContent.includes('$70.00'));
    assert.equal(await page.locator('[name=project]').inputValue(),'');
    assert.equal(await page.locator('[name=code]').inputValue(),'');
    await page.locator('[name=q]').fill('fixture-accounting'); await page.locator('button[type=submit]').click();
    await page.locator('#orders').getByText(/fictional confirmed coupon/).waitFor();
    assert.match(await page.locator('#orders').innerText(),/欺诈单：待退款\/申诉/);
    assert.match(await page.locator('#kpis').innerText(),/100.0%/);
    assert.match(await page.locator('#coverage').innerText(),/成本未覆盖 0/);
    await page.locator('[name=q]').fill('fixture-test'); await page.locator('button[type=submit]').click();
    await page.locator('#orders').getByText(/测试单：不计经营指标/).waitFor();
    assert.match(await page.locator('#kpis').innerText(),/\$0.00/);
    assert.match(await page.locator('#orders').innerText(),/\$0.50/);
    assert.match(await page.locator('#total').innerText(),/共 1 单.*含 1 笔测试单/);
    assert.match(await page.locator('#coverage').innerText(),/已完成 0.*成本未覆盖 0.*排除测试 1/);
    assert.match(await page.locator('#status').innerText(),/仅含测试单/);
    await page.locator('#reset').click();
    await page.waitForFunction(()=>document.querySelector('#kpis').textContent.includes('$70.00'));
    await page.locator('[name=mode]').selectOption('coupon');
    await page.locator('#projects-title').filter({hasText:'优惠券模板'}).waitFor();
    assert.match(await page.locator('#kpis').innerText(), /\$10.00/);
    assert.equal(await page.locator('#projects tbody tr').count(),2);
    await page.locator('[name=project]').selectOption('7');
    await page.waitForFunction(() => document.querySelector('#codes').textContent.includes('one') && !document.querySelector('#codes').textContent.includes('two'));
    await page.locator('#theme').selectOption('dark');
    assert.equal(await page.locator('html').getAttribute('data-fs-theme'),'dark');
    await page.setViewportSize({width:375,height:812});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('[name=q]').fill('absent'); await page.locator('button[type=submit]').click();
    await page.locator('#orders .empty').waitFor();
    await page.locator('[name=q]').fill('fixture-error'); await page.locator('button[type=submit]').click();
    await page.locator('#status[data-state=error]').waitFor();
    assert.equal(await page.locator('#results').isVisible(),true);
    await page.locator('[name=q]').fill('fixture-auth'); await page.locator('button[type=submit]').click();
    await page.waitForFunction(() => document.querySelector('#status').textContent.includes('未获渠道效果看板授权'));
    assert.equal(await page.locator('#refresh').isDisabled(),true);
    const dates = await browser.newPage({timezoneId:'America/Los_Angeles'});
    await dates.clock.setFixedTime(new Date('2026-10-21T15:59:59Z'));
    await dates.goto(url); await dates.locator('#results').waitFor({state:'visible'});
    for (const [button,start,end] of [['昨日','2026-10-20','2026-10-20'],['近7天','2026-10-14','2026-10-20'],['近30天','2026-09-21','2026-10-20']]) {
      await dates.getByRole('button',{name:button,exact:true}).click();
      assert.equal(await dates.locator('[name=start]').inputValue(),start);
      assert.equal(await dates.locator('[name=end]').inputValue(),end);
    }
    await dates.clock.setFixedTime(new Date('2026-10-21T16:00:01Z'));
    await dates.getByRole('button',{name:'昨日',exact:true}).click();
    assert.equal(await dates.locator('[name=end]').inputValue(),'2026-10-21');
    await dates.clock.setFixedTime(new Date('2027-12-31T16:00:01Z'));
    await dates.getByRole('button',{name:'近7天',exact:true}).click();
    assert.equal(await dates.locator('[name=start]').inputValue(),'2027-12-25');
    assert.equal(await dates.locator('[name=end]').inputValue(),'2027-12-31');
    await dates.clock.setFixedTime(new Date('2028-03-01T00:00:00Z'));
    await dates.getByRole('button',{name:'近30天',exact:true}).click();
    assert.equal(await dates.locator('[name=start]').inputValue(),'2028-01-31');
    assert.equal(await dates.locator('[name=end]').inputValue(),'2028-02-29');
    await dates.close();
    access='reader';
    await page.goto(url); await page.locator('#status[data-state=error]').waitFor();
    assert.equal(await page.locator('#results').isVisible(),false);
    assert.deepEqual(failures,[]);
    console.log('channel UI: attribution, pagination during cost polling, stable focus, busy, coupon dedup/batch, theme, mobile, empty/error and role denial passed');
  } finally {await browser.close();server.close();}
})().catch(error => {console.error(error);server.close();process.exitCode=1;});
