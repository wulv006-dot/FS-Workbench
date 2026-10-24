const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../source/shell.js'),'utf8');
const expression=source.match(/const mode=(.*?);\$\('status'\)/)?.[1];assert.ok(expression);
const label=new Function('state','q','return '+expression);
assert.equal(label({mode:'business'},{b_profile:'RS'}),'RS · Admin所选范围 / Order发货统计利润');
assert.equal(label({mode:'business'},{b_profile:'FC27'}),'MMOEXP · Admin主站 / Order补充参考');
assert.equal(label({mode:'traffic'},{b_profile:'RS'}),'Google · 来源独立');
console.log('Parent status: RS source identity and original non-RS/traffic labels passed');
