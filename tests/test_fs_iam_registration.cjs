const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const root = path.join(__dirname, '../opt/fs-access-policy/web');

(async () => {
  const server = http.createServer((req, res) => {
    const filename = path.basename(new URL(req.url, 'http://localhost').pathname) || 'index.html';
    if (!['index.html', 'app.js', 'app.css', 'registration.js'].includes(filename)) { res.writeHead(404).end(); return; }
    res.setHeader('Content-Type', filename.endsWith('.js') ? 'text/javascript' : filename.endsWith('.css') ? 'text/css' : 'text/html');
    res.end(fs.readFileSync(path.join(root, filename)));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch(process.platform === 'win32' ? {
    executablePath: process.env.FS_TEST_BROWSER || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
  } : {});
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    let account = {role:'guest'}, mode = 'ok', calls = [];
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== origin) return route.abort();
      if (!url.pathname.includes('/api/')) return route.continue();
      calls.push({path:url.pathname, method:request.method(), body:request.postDataJSON()});
      let data = {}, status = 200;
      const operation = url.pathname.split('/').pop();
      if (url.pathname === '/api/session') data = {user:'',admin:false};
      else if (operation === 'bootstrap') data = {csrf:'fixture-csrf',account};
      else if (operation === 'register' && mode === 'unknown') { status=503; data={error:'fixture unavailable'}; }
      else if (operation === 'register') data = {request_id:'fixture-request',state:'pending'};
      else if (operation === 'native-login') { status=401; data={error:'invalid credentials'}; }
      else if (operation === 'login') {
        account={id:'fixture-user',name:'test_user',state:'pending',request:{id:'fixture-request',reason:''}};
        data={csrf:'fixture-csrf',account};
      } else if (operation === 'requests') data={items:[{id:'fixture-request',version:0,status:'pending',name:'test_user',team:'QA',purpose:'fixture only',cursor:1}]};
      else if (operation === 'decision') { status=409; data={error:'申请已变化，请刷新后重试'}; }
      else if (operation === 'audit') data={items:[]};
      await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(origin + '/index.html');
    await page.getByRole('button', {name:'没有账号？注册账号'}).click();
    await page.getByLabel('账号（必填）', {exact:true}).fill('test_user');
    await page.getByLabel('密码（必填）', {exact:true}).fill('synthetic-password-42');
    await page.getByLabel('团队（必填）', {exact:true}).fill('QA');
    await page.getByLabel('申请用途（必填）', {exact:true}).fill('fixture only');
    await page.getByRole('button', {name:'注册并提交申请'}).click();
    await page.getByText('注册成功，申请待审批。请登录查看进度。', {exact:true}).waitFor();
    const registration = calls.find(c => c.path.endsWith('/register'));
    assert.deepEqual(registration.body, {username:'test_user',password:'synthetic-password-42',team:'QA',purpose:'fixture only'});
    assert.equal(registration.method, 'POST');
    await page.getByLabel('注册账号',{exact:true}).fill('test_user');
    await page.locator('#registration-login-form input[name=password]').fill('synthetic-password-42');
    await page.getByRole('button', {name:'登录并查看申请',exact:true}).click();
    await page.getByRole('heading', {name:'test_user · 待审批'}).waitFor();
    assert.equal(await page.getByText('申请编号：fixture-request', {exact:true}).count(), 1);
    assert(!calls.some(c => /decision|requests/.test(c.path)), 'pending account must not call admin APIs');

    account={role:'guest'}; mode='unknown'; calls=[];
    await page.reload();
    await page.getByRole('button', {name:'没有账号？注册账号'}).click();
    await page.getByLabel('账号（必填）', {exact:true}).fill('test_user');
    await page.getByLabel('密码（必填）', {exact:true}).fill('synthetic-password-42');
    await page.getByLabel('团队（必填）', {exact:true}).fill('QA');
    await page.getByLabel('申请用途（必填）', {exact:true}).fill('fixture only');
    await page.getByRole('button', {name:'注册并提交申请'}).click();
    await page.getByText(/结果待核对，请刷新查看申请或审计/).waitFor();
    assert(await page.getByRole('button', {name:'注册并提交申请'}).isDisabled());
    assert.equal(calls.filter(c=>c.path.endsWith('/register')).length, 1, 'unknown write must not retry');

    mode='ok'; calls=[];
    await page.reload();
    await page.locator('#login-form').waitFor({state:'visible'});
    assert.equal(await page.locator('#login-form').getAttribute('action'), '../login');
    assert(await page.locator('#login-form input[name=remember]').isChecked());
    assert.equal(await page.locator('#login-form').evaluate(form => {
      const event=new Event('submit',{cancelable:true}); form.dispatchEvent(event); return event.defaultPrevented;
    }), false, 'native login must retain its original form and remember duration');
    await page.evaluate(() => {
      document.getElementById('login-view').hidden=true;
      document.getElementById('app-view').hidden=false;
      const main=document.getElementById('main'); main.dataset.view='registration';
      return window.FSRegistration.requests(main);
    });
    await page.locator('.registration-table tbody tr').filter({hasText:'test_user'}).waitFor();
    await page.getByRole('searchbox').fill('test_user');
    assert.equal(await page.locator('.registration-table tbody tr:visible').count(), 1);
    await page.locator('.registration-filter').selectOption('pending');
    await page.getByLabel('选择 test_user').check();
    await page.getByRole('button', {name:'通过选中申请'}).click();
    await page.getByText(/申请已变化，请刷新后重试/).waitFor();
    const decision=calls.find(c=>c.path.endsWith('/decision'));
    assert.deepEqual(decision.body,{request_id:'fixture-request',version:0,reason:'一键通过（默认全局只读）',action:'approve'});
    assert.equal(calls.filter(c=>c.path.endsWith('/decision')).length,1);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed:true,flows:['registration','pending login','unknown write no retry','approval CAS conflict'],productionWrites:0}));
  } finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode=1; });
