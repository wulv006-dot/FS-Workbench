const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),assets=path.join(root,'frontend/assets');
const google=fs.readFileSync(path.join(assets,'google.js'),'utf8');
for(const source of [fs.readFileSync(path.join(assets,'legacy-business.js'),'utf8'),google.slice(google.indexOf('/* Duplicate business'),google.indexOf("'use strict';"))]){
 const window={},document={createElement:tag=>({tag})},panel={replaceChildren(...nodes){this.nodes=nodes}};
 vm.runInNewContext(source,{window,document,fetch(){throw Error('old_snapshot_request')}});
 window.MMOEXPBusiness.mount(panel);assert.equal(panel.nodes.at(-1).href,'/dashboard/analytics/?mode=business');
 window.MMOEXPBusiness.refresh();window.MMOEXPBusiness.unmount();
}
assert(!google.includes("BASE+'current.json'"));
const routes=fs.readFileSync(path.join(root,'frontend/candidate/formal.conf'),'utf8');
for(const url of ['/dashboard/index.html','/s/wulv/fc27-ops/','/dashboard/marketing/business-module.js'])assert(routes.includes('location = '+url+' {'));
assert(routes.includes('auth_request /__fc27_verify;'));assert(google.includes('MMOEXPMarketing'));
console.log('Legacy business consumers use the native entry; original FC gate and Google source are retained.');
