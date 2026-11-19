const {
  chromium
}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const dir=__dirname,nav=fs.readFileSync(path.join(dir,'candidate','nav.js'),'utf8'),hub=fs.readFileSync(path.join(dir,'candidate','hubnav.js'),'utf8');
const browserPath=process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const ui='/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/';
const registry=JSON.parse(hub.split('const registry=')[1].split(';\n')[0]);
(async()=>{
  const browser=await chromium.launch({
    headless:true,executablePath:browserPath
  });
  try{
    const context=await browser.newContext();
    let html='';
    const hits=[];
    await context.route('**/*',async route=>{
      const req=route.request(),u=new URL(req.url());
      hits.push(u.pathname);
      if(u.hostname!=='fs.test')return route.abort();
      if(u.pathname==='/__auth/verify')return route.fulfill({
        status:200,headers:{
          'X-Auth-User':'fixture','X-Auth-Role':'user','X-Auth-Groups':'dashboard'
        }
      });
      if(u.pathname==='/dashboard/fs-home/navigation.json')return route.fulfill({
        status:200,contentType:'application/json',body:JSON.stringify(registry)
      });
      if(req.resourceType()==='document')return route.fulfill({
        status:200,contentType:'text/html',body:html
      });
      if(u.pathname.endsWith('.css'))return route.fulfill({
        status:200,contentType:'text/css',body:''
      });
      if(u.pathname.endsWith('fs-theme.js'))return route.fulfill({
        status:200,contentType:'application/javascript',body:'window.FSTheme={get:()=>"light",set:()=>{}};'
      });
      return route.fulfill({
        status:404,body:''
      });
    });
    const page=await context.newPage();
    html=`<!doctype html><html><head><link rel="stylesheet" href="${ui}fs-tokens.css"><link rel="stylesheet" href="${ui}fs-ui.css"><script src="${ui}fs-theme.js"></script></head><body><main>test</main></body></html>`;
    await page.goto('http://fs.test/dashboard/analytics/campaigns/analytics/weekly.html');
    await page.addScriptTag({
      content:hub
    });
    assert.equal(await page.locator('#hubNav a[href="/dashboard/modules/sports/fc-project-review/"]').count(),1);
    await page.waitForTimeout(100);
    assert.equal(await page.locator('#hubNav a[href="/dashboard/modules/sports/fc-project-review/"]').count(),1);
    let data=await page.evaluate(({
      ui
    })=>({
      nav:document.querySelectorAll('#hubNav').length,weekly:document.querySelectorAll('#hubNav a[href="/dashboard/analytics/campaigns/analytics/weekly.html"]').length,tokens:[...document.querySelectorAll('link[rel="stylesheet"]')].filter(n=>n.href===new URL(ui+'fs-tokens.css',location.href).href).length,ui:[...document.querySelectorAll('link[rel="stylesheet"]')].filter(n=>n.href===new URL(ui+'fs-ui.css',location.href).href).length,theme:[...document.scripts].filter(n=>n.src===new URL(ui+'fs-theme.js',location.href).href).length,group:document.querySelectorAll('#hubNav .hn-tree > .hn-group').length
    }),{
      ui
    });
    assert.deepEqual(data,{
      nav:1,weekly:1,tokens:1,ui:1,theme:1,group:9
    });
    await page.addScriptTag({
      content:hub
    });
    await page.waitForTimeout(50);
    assert.equal(await page.locator('#hubNav').count(),1);
    assert.equal(await page.locator('link[href$="fs-tokens.css"]').count(),1);
    console.log('dynamic + existing CSS/theme + duplicate hubnav: PASS');
    html='<!doctype html><html><head></head><body><nav id="hubNav"><a class="hn-brand" href="/dashboard/">FS</a><section class="hn-group"><a class="hn-heading" href="/dashboard/analytics/campaigns/analytics/">活动</a></section></nav><button id="hubNavToggle"></button><button id="hubNavScrim" hidden></button><main>test</main></body></html>';
    await page.goto('http://fs.test/dashboard/modules/arpg/');
    await page.addScriptTag({
      content:nav
    });
    await page.waitForTimeout(100);
    assert.equal(await page.locator('#hubNav a[href="/dashboard/analytics/campaigns/analytics/weekly.html"]').count(),1);
    const before=await page.locator('#hubNav .hn-group').count();
    await page.addScriptTag({
      content:nav
    });
    await page.waitForTimeout(50);
    assert.equal(await page.locator('#hubNav .hn-group').count(),before);
    assert.equal(await page.locator('#hubNav').count(),1);
    console.log('static nav + weekly + duplicate nav: PASS');
  }finally{
    await browser.close();
  }
})().catch(e=>{
  console.error(e);
  process.exitCode=1
});
