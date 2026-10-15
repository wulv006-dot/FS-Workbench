const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(__dirname+'/../adapters/hubnav.js','utf8');
const fn=src.match(/function matches\(path\)\{[^\n]+\}/)[0];
function check(current,path){const u=new URL(current),c={URL,location:u};vm.runInNewContext(fn,c);return c.matches(path)}
assert(!check('https://fs.test/dashboard/fs-home/brain/index.html','/dashboard/fs-home/brain/index.html?report_kind=weekly#reports'));
assert(check('https://fs.test/dashboard/fs-home/brain/index.html?report_kind=weekly#reports','/dashboard/fs-home/brain/index.html?report_kind=weekly#reports'));
assert(!check('https://fs.test/dashboard/fs-home/brain/index.html?report_kind=daily#reports','/dashboard/fs-home/brain/index.html?report_kind=weekly#reports'));
assert(check('https://fs.test/dashboard/management/fc27.html','/dashboard/management/'));
assert(!check('https://fs.test/dashboard/analytics/','/dashboard/management/'));
console.log('navigation query-aware selection: 5 cases PASS');
