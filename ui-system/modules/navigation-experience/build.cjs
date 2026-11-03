const fs=require('fs'),path=require('path');
const dir=__dirname;
const live=fs.readFileSync(path.join(dir,'hubnav.live.js'),'utf8');
const reg=JSON.parse(live.match(/const BUILTIN=(.*);\r?\n/)[1]);
const css=fs.readFileSync(path.join(dir,'navigation-experience.css'),'utf8');
const enhancement=fs.readFileSync(path.join(dir,'navigation-experience.js'),'utf8').replace('__FS_NAV_REGISTRY__',JSON.stringify(reg));
const style=`\n(function(){if(document.getElementById('fsNavExperienceStyle'))return;const s=document.createElement('style');s.id='fsNavExperienceStyle';s.textContent=${JSON.stringify(css)};document.head.append(s);})();\n`;
fs.mkdirSync(path.join(dir,'candidate'),{recursive:true});
const hub=live.replace('tree.replaceChildren(frag);',"tree.replaceChildren(frag);document.dispatchEvent(new CustomEvent('fs-nav-account-ready',{detail:{account:tree.querySelector('.hn-account')}}));");
fs.writeFileSync(path.join(dir,'candidate','hubnav.js'),hub+style+enhancement);
let nav=fs.readFileSync(path.join(dir,'nav.live.js'),'utf8');
// The shared renderer owns group structure and active state once mounted.
nav=nav.replace('  // Keep the shared Hermes hierarchy', '  if(!window.__fsNavExperience){\n  // Keep the shared Hermes hierarchy');
nav=nav.replace("  var KEY = 'fs-navigation-theme';", "  }\n  var KEY = 'fs-navigation-theme';");
// Do not prerender operational pages: their scripts can start data requests before a click.
nav=nav.slice(0,nav.indexOf('  /* 5)'))+'})();\n';
fs.writeFileSync(path.join(dir,'candidate','nav.js'),nav+style+enhancement);
fs.writeFileSync(path.join(dir,'candidate','navigation-experience.css'),css);
fs.writeFileSync(path.join(dir,'enhancement.compiled.js'),style+enhancement);
const groups=reg.sections.map(s=>`<section class="hn-group"><a class="hn-heading" href="${s.path}"><span class="hn-icon">${s.icon}</span><span>${s.title}</span></a></section>`).join('');
const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>导航交互验收</title><link rel="stylesheet" href="/navigation-experience.css"><style>body{font:15px system-ui;background:#edf2f3;color:#21383d;margin:0}main{padding:40px;max-width:1100px}h1{font-size:34px}article{padding:25px;background:white;border:1px solid #dbe6e6;border-radius:14px;margin:20px 0}#hubNavToggle,#hubNavScrim{display:none}</style><body class="fs-unified-navigation"><nav id="hubNav"><a class="hn-brand" href="/dashboard/">FS · MMOEXP</a>${groups}<div class="hn-account"><a href="/__auth/status">导航测试账号</a></div></nav><button id="hubNavToggle" aria-controls="hubNav">导航</button><button id="hubNavScrim" hidden>关闭导航</button><main><p>交互验收 · 本地预览</p><h1>让每次切换，都轻一点。</h1><article><h2>工作区导航</h2><p>测试分组收纳、快捷搜索、紧凑模式、键盘和移动端。这里没有业务数据与操作接口。</p></article><article><h2>一致的操作体验</h2><p>导航保持稳定，业务页面独立加载。支持浏览器前进、后退和在新标签页打开。</p></article></main><script src="/enhancement.compiled.js"></script></body></html>`;
fs.writeFileSync(path.join(dir,'fixture.html'),html);
console.log('Built candidate and local interaction fixture.');
