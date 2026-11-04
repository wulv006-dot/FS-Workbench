const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'fs-seo-nav-'));
try{
 const source=path.resolve(__dirname,'../navigation-experience');
 for(const name of ['build.cjs','hubnav.live.js','nav.live.js','navigation-experience.js','navigation-experience.css'])fs.copyFileSync(path.join(source,name),path.join(temp,name));
 const before=JSON.parse(fs.readFileSync(path.join(temp,'hubnav.live.js'),'utf8').match(/const BUILTIN=(.*);\r?\n/)[1]);
 const reg=structuredClone(before),section=reg.sections.find(s=>s.id==='analytics');
 section.ids.push('seo');reg.tools.push({id:'seo',label:'SEO监控台',path:'/dashboard/analytics/seo/',requiredGroup:'dashboard',section:'analytics'});
 const registry=path.join(temp,'navigation.json');fs.writeFileSync(registry,'\ufeff'+JSON.stringify(reg));
 execFileSync(process.execPath,[path.join(temp,'build.cjs'),registry]);
 for(const name of ['hubnav.js','nav.js']){
  const compiled=fs.readFileSync(path.join(temp,'candidate',name),'utf8');
  assert.deepEqual(JSON.parse(compiled.match(/const registry=(.*);\r?\n/)[1]),reg);
  assert(compiled.includes('fs-nav-account-ready'));
 }
 assert.deepEqual(JSON.parse(fs.readFileSync(path.join(temp,'hubnav.live.js'),'utf8').match(/const BUILTIN=(.*);\r?\n/)[1]),before);
 console.log('PASS: both navigation renderers use captured registry and preserve historical input');
}finally{fs.rmSync(temp,{recursive:true,force:true});}
