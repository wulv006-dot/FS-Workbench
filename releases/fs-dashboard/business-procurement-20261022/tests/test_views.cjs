const {spawnSync}=require('node:child_process'),path=require('node:path'),assert=require('node:assert/strict');
for(const variant of ['business.js','home-business.js','legacy-business.js']){
 const r=spawnSync(process.execPath,[path.join(__dirname,'test_view.cjs'),variant],{stdio:'inherit',timeout:9000});
 assert.equal(r.status,0,'metric-renderer browser regression failed: '+variant);
}
