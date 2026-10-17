'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),repo=path.resolve(root,'../../..');
const template=fs.readFileSync(path.join(root,'source/report.template.html'),'utf8');
const tokens=fs.readFileSync(path.join(repo,'ui-system/tokens/fs-tokens.css'),'utf8');
const resolver=fs.readFileSync(path.join(repo,'ui-system/adapters/fs-theme.js'),'utf8');
assert(!template.includes('var(--fs-surface)-space'));assert(template.includes(tokens));assert(template.includes(resolver));
const original=fs.readFileSync(path.join(repo,'releases/fs-dashboard/hermes-learning-loop-20261016/baseline/report.template.html'),'utf8');
const before=original.match(/<script>([\s\S]*?)<\/script>/)[1];
assert(template.includes(before.replace(/\r\n/g,'\n').trim()),'existing report handlers remain unchanged apart from newline normalization');
const body='<section id="executive"><h1>经营报告测试</h1><p>收入 $29,273.54 · 435 单</p></section><details id="closed"><summary>折叠证据</summary><p>保留原始字段</p><details id="nested"><summary>嵌套证据</summary><p>原内容</p></details></details><details id="opened" open><summary>已展开行动</summary><p>负责人/复查/停止条件</p></details><figure class="chart"><button data-chart-tab="one" aria-pressed="true">金额</button><button data-chart-tab="two" aria-pressed="false">订单</button><div class="chart-panel" id="one"><svg viewBox="0 0 200 100"><text x="5" y="20">$29,273.54</text><rect x="0" y="40" width="100" height="20" fill="#f5eee1"/></svg></div><div class="chart-panel" id="two" hidden>435</div></figure>';
const preBody=body+'<details class="research-body" open><summary>长研究</summary><pre>'+('long_evidence_value_'.repeat(200))+'</pre></details>';
const html=content=>template.replace('@@TITLE@@','测试报告').replace('@@BODY@@',content).replace('@@FILENAME_JSON@@','"test.html"');
(async()=>{
 const browser=await chromium.launch({headless:true});let checks=0;
 const page=await browser.newPage({viewport:{width:1440,height:1000},colorScheme:'dark'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 // The standalone/Blob report cannot depend on localStorage availability.
 await page.setContent(html(preBody));
 assert.equal(await page.locator('html').getAttribute('data-fs-theme'),'light');checks++;
 await page.getByLabel('报告主题').selectOption('system');assert.equal(await page.locator('html').getAttribute('data-fs-theme'),'dark');checks++;
 assert.equal(await page.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(10, 20, 36)');
 assert.equal(await page.locator('main').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(18, 29, 49)');assert.equal(await page.locator('pre').evaluate(e=>getComputedStyle(e).whiteSpace),'pre-wrap');checks++;
 await page.emulateMedia({colorScheme:'light'});await page.waitForFunction(()=>document.documentElement.dataset.fsTheme==='light');assert.equal(await page.locator('html').getAttribute('data-fs-theme'),'light');checks++;
 await page.getByLabel('报告主题').selectOption('dark');await page.emulateMedia({colorScheme:'light'});assert.equal(await page.locator('html').getAttribute('data-fs-theme'),'dark');checks++;
 await page.getByRole('button',{name:'订单',exact:true}).click();assert.equal(await page.locator('#two').isVisible(),true);checks++;
 const originalOpen=await page.locator('details').evaluateAll(nodes=>nodes.map(n=>n.open));
 await page.evaluate(()=>{dispatchEvent(new Event('beforeprint'));dispatchEvent(new Event('beforeprint'));});
 assert((await page.locator('details').evaluateAll(nodes=>nodes.map(n=>n.open))).every(Boolean));checks++;
 await page.emulateMedia({media:'print'});
 assert.equal(await page.locator('main').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)');
 assert.equal(await page.locator('#two').isVisible(),true);assert.equal(await page.locator('#one').isVisible(),false);checks++;
 await page.evaluate(()=>{dispatchEvent(new Event('afterprint'));dispatchEvent(new Event('afterprint'));});
 assert.deepEqual(await page.locator('details').evaluateAll(nodes=>nodes.map(n=>n.open)),originalOpen);checks++;
 await page.emulateMedia({media:'screen'});assert.equal(await page.locator('html').getAttribute('data-fs-theme'),'dark');checks++;
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));checks++;
 await page.getByLabel('报告主题').focus();assert.equal(await page.getByLabel('报告主题').evaluate(e=>getComputedStyle(e).outlineStyle),'solid');checks++;
 // Optional private local real report: reuse body only, never commit its evidence.
 if(process.argv[2]){
  const report=fs.readFileSync(process.argv[2],'utf8'),main=report.match(/<main>([\s\S]*?)<\/main>/);assert(main);
  const baseline=await browser.newPage({viewport:{width:390,height:844}});
  await baseline.setContent(original.replace('@@TITLE@@','测试报告').replace('@@BODY@@',main[1]).replace('@@FILENAME_JSON@@','"test.html"'));
  const beforeWidth=await baseline.evaluate(()=>document.documentElement.scrollWidth);await baseline.close();
  await page.goto('about:blank');await page.setContent(html(main[1]));await page.getByLabel('报告主题').selectOption('dark');
  assert.equal(await page.locator('main').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(18, 29, 49)');
  const candidateWidth=await page.evaluate(()=>document.documentElement.scrollWidth);assert(candidateWidth<=beforeWidth);console.log(JSON.stringify({originalBodyWidth:beforeWidth,candidateBodyWidth:candidateWidth}));
  await page.evaluate(()=>dispatchEvent(new Event('beforeprint')));assert.equal(await page.locator('details:not([open])').count(),0);
  await page.evaluate(()=>dispatchEvent(new Event('afterprint')));
  if(process.argv[3])await page.screenshot({path:process.argv[3],fullPage:false});checks++;
 }
 assert.deepEqual(errors,[]);await browser.close();console.log(JSON.stringify({checks,errors,production_writes:0}));
})().catch(error=>{console.error(error);process.exit(1)});
