const http = require('http');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require('playwright');
assert(process.argv[2], 'provide a prepared candidate stage path');
const stage = path.resolve(process.argv[2]);
const manifest = JSON.parse(fs.readFileSync(path.join(stage, 'manifest.json'), 'utf8'));
const assets = manifest.files.filter(x => x.candidate.startsWith('a-shared/'));
const urls = Object.fromEntries(assets.map(x => {
  const part = x.target.split('/').slice(-2).join('/');
  return [path.basename(x.target), '/dashboard/workspace-assets/' + part];
}));
const counts = Object.fromEntries(assets.map(x => [path.basename(x.target), 0]));
const hub = fs.readFileSync(path.join(stage, 'candidate/b-shared/hubnav.js'));
const retiredAssets = [
  'workspace-native-20261006-ba0a83afd594/runtime.js',
  'workspace-native-20261006-ba0a83afd594/workspace.css',
  ...['fs-tokens.css', 'fs-ui.css', 'fs-theme.js', 'legacy.css'].map(
    name => 'workspace-native-20261006-561eda9b98e2/ui/' + name
  ),
];
for (const row of manifest.files.filter(x => x.candidate.startsWith('d-pages/'))) {
  const source = fs.readFileSync(path.join(stage, 'candidate', row.candidate), 'utf8');
  for (const oldURL of retiredAssets) {
    assert(!source.includes(oldURL), `${row.candidate} still loads ${oldURL}`);
  }
}

const page = `<!doctype html><html><head>
<link rel="stylesheet" href="${urls['workspace.css']}">
<link rel="stylesheet" href="${urls['fs-tokens.css']}">
<link rel="stylesheet" href="${urls['fs-ui.css']}">
<link rel="modulepreload" href="${urls['runtime.js']}">
<script defer src="${urls['fs-theme.js']}"></script>
</head><body><main>fixture</main><script src="/hub.js"></script></body></html>`;
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const asset = assets.find(x => urls[path.basename(x.target)] === pathname);
  if (asset) {
    counts[path.basename(asset.target)]++;
    if (!String(req.headers.cookie || '').includes('fixture=authorized')) {
      res.writeHead(401, { 'Cache-Control': 'no-store' });return res.end();
    }
    res.writeHead(200, {
      'Content-Type': pathname.endsWith('.css') ? 'text/css' : 'application/javascript',
      'Cache-Control': 'private, max-age=2592000, immutable',
    });
    return res.end(fs.readFileSync(path.join(stage, 'candidate', asset.candidate)));
  }
  if (pathname === '/hub.js') {res.writeHead(200, {'Content-Type':'application/javascript'});return res.end(hub);}
  if (pathname === '/__auth/verify') {res.writeHead(200, {'X-Auth-User':'fixture','X-Auth-Groups':'dashboard'});return res.end();}
  if (pathname.endsWith('navigation.json')) {res.writeHead(404);return res.end();}
  res.writeHead(200, {'Content-Type':'text/html'});res.end(page);
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
  try {
    const anonymous = await browser.newContext();
    const denied = await anonymous.request.get(base + urls['fs-tokens.css']);
    assert.equal(denied.status(), 401);
    await anonymous.close();
    counts['fs-tokens.css'] = 0;
    const context = await browser.newContext();
    await context.addCookies([{name:'fixture',value:'authorized',url:base}]);
    const p = await context.newPage();
    await p.goto(base + '/dashboard/one');
    await p.waitForTimeout(300);
    const first = {...counts};
    for (const name of Object.keys(counts)) assert.equal(first[name], 1, name + ' first visit');
    await p.goto(base + '/dashboard/two');
    await p.waitForTimeout(300);
    assert.deepEqual(counts, first);
    assert.equal(await p.locator('#hubNav').count(), 1);
    console.log(JSON.stringify({anonymousStatus:401, firstAssetRequests:first, secondAdditionalRequests:0, navCount:1}));
    await context.close();
  } finally {await browser.close();server.close();}
})().catch(error => {console.error(error);server.close();process.exitCode=1;});
