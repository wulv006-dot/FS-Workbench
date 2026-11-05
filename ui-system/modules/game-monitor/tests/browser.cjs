const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const {chromium}=require('playwright');
const output=process.argv[2];
if(!output)throw Error('Pass candidate directory containing operations.html and daily.json');
let browser,server;
(async()=>{
 const daily=JSON.parse(fs.readFileSync(path.join(output,'daily.json'),'utf8').replace(/^\uFEFF/,''));
 let dailyFails=false,supplementary=false;
 const supplemental=JSON.parse(fs.readFileSync(path.join(output,'intelligence.json'),'utf8').replace(/^\uFEFF/,''));
 server=http.createServer((req,res)=>{
  if(req.url.split('?')[0]==='/operations.html'){res.setHeader('Content-Type','text/html;charset=utf-8');return res.end(fs.readFileSync(path.join(output,'operations.html')));}
  if(req.url==='/daily.json'){res.setHeader('Content-Type','application/json');if(dailyFails){res.statusCode=503;return res.end('{}');}return res.end(JSON.stringify(daily));}
  if(supplementary&&req.url==='/intelligence.json'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(supplemental));}
  if(supplementary&&req.url==='/intelligence.status.json'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({schema_version:1,status:'failed',reason:'test_source_failure',attempted_at:new Date(Date.parse(supplemental.collected_at)+1000).toISOString()}));}
  if(req.url==='/index.html'){res.setHeader('Content-Type','text/html');return res.end('<!doctype html><html lang="zh-CN"><title>原工作区路由检查</title><body>原页面在生产仍由原发布器维护。</body></html>');}
  res.statusCode=404;res.end('{}');
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
 const check=(name,ok)=>{assert.ok(ok,name);checks.push(name);};
 await page.goto('http://127.0.0.1:'+server.address().port+'/operations.html');
 await page.waitForFunction(()=>!document.querySelector('#refresh-button').disabled);
 check('existing feed accepted despite absent supplemental endpoints',!(await page.locator('#snapshot-time').textContent()).includes('尚无'));
 check('all 29 games available in page dropdown',await page.locator('#game-filter option').count()===30);
 check('game dropdown stays inside main content',await page.locator('main #game-filter').count()===1);
 check('no game navigation sidebar replaces the shared workbench nav',await page.locator('#sidebar,#game-list').count()===0);
 check('partial source reads explicit',(await page.locator('#source-state').textContent()).includes('intelligence'));
 const count=await page.locator('.queue-open').count();check('source-backed action rows exist',count>0);
 const option=await page.locator('#game-filter option').nth(1).getAttribute('value');
 await page.locator('#game-filter').selectOption(option);
 check('dropdown filters game without navigating away',new URLSearchParams(new URL(page.url()).hash.slice(1)).get('game')===option);
 await page.reload();await page.waitForFunction(()=>!document.querySelector('#refresh-button').disabled);
 check('game dropdown selection survives refresh',await page.locator('#game-filter').inputValue()===option);
 await page.locator('#game-filter').selectOption('all');
 await page.screenshot({path:path.join(output,'operations-desktop.png')});
 await page.getByRole('button',{name:'切换暗色主题',exact:true}).click();
 check('shared FS theme adapter',await page.evaluate(()=>localStorage.getItem('fs-navigation-theme'))==='dark');
 await page.screenshot({path:path.join(output,'operations-dark.png')});
 await page.getByRole('button',{name:'切换浅色主题',exact:true}).click();
 dailyFails=true;await page.getByRole('button',{name:'刷新数据',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#refresh-button').disabled);
 check('failed refresh preserves prior action rows',await page.locator('.queue-open').count()===count);
 check('failed refresh explicitly marks daily',(await page.locator('#source-state').textContent()).includes('daily'));
 dailyFails=false;
 supplementary=true;await page.getByRole('button',{name:'刷新数据',exact:true}).click();
 await page.waitForFunction(()=>!document.querySelector('#refresh-button').disabled);
 check('latest collector failure visible with old 200 snapshot',(await page.locator('#source-state').textContent()).includes('intelligence采集失败'));
 await page.getByRole('tab',{name:'来源与提醒',exact:true}).click();
 check('old source values marked as retained after failure',await page.getByText('本轮失败，保留旧值',{exact:true}).count()>0);
 await page.getByRole('tab',{name:'游戏日程',exact:true}).click();
 await page.getByRole('button',{name:'月历',exact:true}).click();
 await page.locator('#calendar-month').fill('2026-11');
 check('month grid renders actual month',await page.locator('.calendar-day>span').count()===30);
 await page.getByRole('tab',{name:'竞品行情',exact:true}).click();
 check('no fake live price',await page.getByRole('heading',{name:'当前页面尚未接回可比报价接口'}).isVisible());
 check('existing price control entry retained',await page.getByRole('link',{name:'打开 FC 金币控制台'}).getAttribute('href')==='/dashboard/fc27-coins.html');
 await page.getByRole('tab',{name:'资料与工具',exact:true}).click();
 check('legacy workspace remains at original current entry',await page.locator('.legacy-frame').getAttribute('src')==='index.html');
 await page.getByRole('tab',{name:'行动清单',exact:true}).click();
 await page.locator('.queue-open').first().click();
 await page.getByRole('button',{name:'关注此变化',exact:true}).click();
 await page.locator('#only-watch').check();check('local watch filter',await page.locator('.queue-open').count()===1);
 await page.getByRole('button',{name:'提醒文案预览',exact:true}).click();
 check('preview does not claim delivery',(await page.locator('#detail-body').textContent()).includes('没有发送消息'));
 await page.keyboard.press('Escape');check('native dialog dismisses',await page.locator('#detail-dialog').evaluate(e=>!e.open));
 await page.locator('#only-watch').uncheck();
 for(const width of [320,375,768,1280,1920]){
  await page.setViewportSize({width,height:900});
  for(const tab of ['行动清单','游戏日程','游戏资讯','竞品行情','需求信号','来源与提醒','资料与工具']){
   await page.getByRole('tab',{name:tab,exact:true}).click();
   check('no overflow '+width+' '+tab,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
 }
 await page.setViewportSize({width:390,height:844});await page.getByRole('tab',{name:'行动清单',exact:true}).click();
 await page.screenshot({path:path.join(output,'operations-mobile.png'),fullPage:true});
 check('no browser errors',errors.length===0);
 fs.writeFileSync(path.join(output,'browser-verification.json'),JSON.stringify({passed:checks.length,checks,errors,scope:'new UI with existing public game feed; supplemental endpoint 404 and legacy route wiring tested'},null,2));
 console.log(JSON.stringify({passed:checks.length,errors}));
 await browser.close();await new Promise(resolve=>server.close(resolve));
})().catch(async error=>{console.error(error);if(browser)await browser.close();if(server)server.close();process.exitCode=1;});
