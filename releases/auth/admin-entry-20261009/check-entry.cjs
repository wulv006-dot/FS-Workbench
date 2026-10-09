const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const shell=fs.readFileSync(__dirname+'/source/shell.js','utf8');
const manage={hidden:true};
const fn=shell.match(/function accountNavigation\(user\)\{[^\n]+\}/)[0];
const ctx={document:{querySelector:s=>{assert.equal(s,'.account-management');return manage;}}};
vm.createContext(ctx);vm.runInContext(fn,ctx);
for(const [user,hidden] of [[null,true],[{role:'readonly'},true],[{role:'editor'},true],[{role:''},true],[{role:'admin'},false]]){
 ctx.user=user;vm.runInContext('accountNavigation(user)',ctx);assert.equal(manage.hidden,hidden);
}
ctx.user=null;vm.runInContext('accountNavigation(user)',ctx);assert.equal(manage.hidden,true);
assert(shell.includes("link('账号与权限管理','/__auth/access/','account-management')"));
assert.equal(shell.match(/identity=next;accountNavigation\(next\);/g).length,3);
assert(shell.includes('identity=null;accountNavigation(null);'));
assert(fs.readFileSync(__dirname+'/source/runtime.js','utf8').includes("role:v.headers.get('X-Auth-Role')||''"));
console.log('10 admin-entry assertions passed (role, expiry, refresh, canonical URL)');
