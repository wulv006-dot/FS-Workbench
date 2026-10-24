const {spawnSync}=require('node:child_process'),path=require('node:path'),assert=require('node:assert/strict');
for(const name of ['business.js','home-business.js','legacy-business.js']){
 const r=spawnSync(process.execPath,[path.join(__dirname,'test_browser.cjs')],{env:{...process.env,RS_VARIANT:name},stdio:'inherit'});assert.equal(r.status,0,name);
}
