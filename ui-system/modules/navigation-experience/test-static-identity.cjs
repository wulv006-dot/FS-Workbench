const { chromium } = require('playwright');
const fs=require('fs'),assert=require('assert/strict');
const nav=fs.readFileSync(__dirname+'/candidate/nav.js','utf8');
(async()=>{
  const b=await chromium.launch({
    headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
  });
  try{
    for(const test of ['denied','offline','nondeploy','deploy']){
      const c=await b.newContext();
      await c.route('**/*',async r=>{
        const u=new URL(r.request().url());
        if(u.pathname==='/__auth/verify'){
          if(test==='offline')return r.abort();
          if(test==='denied')return r.fulfill({
            status:403
          });
          await new Promise(x=>setTimeout(x,250));
          return r.fulfill({
            status:200,headers:{
              'X-Auth-User':'NEW_ACCOUNT','X-Auth-Role':'user','X-Auth-Groups':test==='deploy'?'deploy':'rpg'
            }
          });
        }
        if(r.request().resourceType()==='document')return r.fulfill({
          status:200,contentType:'text/html',body:'<!doctype html><body><nav id="hubNav"><a class="hn-brand" href="/dashboard/">FS</a><section class="hn-group"><a class="hn-heading" href="/dashboard/modules/collaboration/">协作</a><a data-requires-group="deploy" href="/deploy/">Deploy</a></section><span data-fs-user>OLD_ACCOUNT</span></nav><button id="hubNavToggle"></button></body>'
        });
        return r.fulfill({
          status:404
        });
      });
      const p=await c.newPage();
      await p.goto('http://fs.test/d4/');
      await p.addScriptTag({
        content:nav
      });
      assert(!(await p.locator('body').innerText()).includes('OLD_ACCOUNT'));
      assert.equal(await p.locator('[data-requires-group="deploy"]:visible').count(),0);
      await p.waitForTimeout(400);
      if(test==='denied')assert.equal(await p.locator('#hubNav').isVisible(),false);
      if(test==='deploy'){
        assert.equal(await p.locator('[data-requires-group="deploy"][href="/deploy/"]').count(),1);
        assert.equal(await p.locator('html.fs-nav-awaiting-identity').count(),0);
      }
      if(test==='nondeploy'||test==='offline')assert.equal(await p.locator('[data-requires-group="deploy"]:visible').count(),0);
      await c.close();
      console.log('static '+test+' PASS');
    }
  }finally{
    await b.close();
  }
})().catch(e=>{
  console.error(e);
  process.exitCode=1
});
