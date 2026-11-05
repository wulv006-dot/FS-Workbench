const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'fs-seo-nav-'));
try{
 const source=path.resolve(__dirname,'../navigation-experience');
 for(const name of ['build.cjs','prepare-current.cjs','hubnav.live.js','nav.live.js','navigation-experience.js','navigation-experience.css'])fs.copyFileSync(path.join(source,name),path.join(temp,name));
 const before=JSON.parse(fs.readFileSync(path.join(temp,'hubnav.live.js'),'utf8').match(/const BUILTIN=(.*);\r?\n/)[1]);
 const reg=structuredClone(before),section=reg.sections.find(s=>s.id==='analytics');
 section.ids.push('seo');reg.tools.push({id:'seo',label:'SEO监控台',path:'/dashboard/analytics/seo/',requiredGroup:'dashboard',section:'analytics'});
 const registry=path.join(temp,'navigation.json');fs.writeFileSync(registry,'\ufeff'+JSON.stringify(reg));
 const {prepare,targets}=require(path.join(temp,'prepare-current.cjs'));
 execFileSync(process.execPath,[path.join(temp,'build.cjs')]);
 const baseline=path.join(temp,'baseline');fs.mkdirSync(baseline);
 const sha=raw=>require('node:crypto').createHash('sha256').update(raw).digest('hex');
 const files=Object.entries(targets).map(([candidate,target])=>{
  const raw=Buffer.from(candidate.endsWith('.js')?fs.readFileSync(path.join(temp,'candidate',candidate),'utf8').replace(/\r\n/g,'\n').replace(/\n/g,'\r\n'):'<script src="/__hub/nav.js?v=old"></script>\r\nKEEP BUSINESS CONTENT\r\n');
  fs.writeFileSync(path.join(baseline,candidate),raw);return {candidate,target,beforeSha256:sha(raw),sha256:sha(raw)};
 });
 const manifest=path.join(temp,'manifest.json');fs.writeFileSync(manifest,JSON.stringify({scope:'traffic-source-tabs-ui-finish-20261019',businessWrites:false,timersChanged:false,files}));
 const output=path.join(temp,'release'),result=prepare(baseline,manifest,registry,output);assert.equal(result.files,16);
 for(const name of ['hubnav.js','nav.js']){
  const old=fs.readFileSync(path.join(baseline,name),'utf8'),next=fs.readFileSync(path.join(output,'candidate',name),'utf8');
  assert.equal(next.replace(/const registry=.*;\r?\n/,''),old.replace(/const registry=.*;\r?\n/,''));
 }
 assert(fs.readFileSync(path.join(output,'candidate','home.html'),'utf8').endsWith('KEEP BUSINESS CONTENT\r\n'));
 fs.appendFileSync(path.join(baseline,'home.html'),'drift');
 assert.throws(()=>prepare(baseline,manifest,registry,path.join(temp,'bad')),/captured source drift/);
 execFileSync(process.execPath,[path.join(temp,'build.cjs'),registry]);
 for(const name of ['hubnav.js','nav.js']){
  const compiled=fs.readFileSync(path.join(temp,'candidate',name),'utf8');
  assert.deepEqual(JSON.parse(compiled.match(/const registry=(.*);\r?\n/)[1]),reg);
  assert(compiled.includes('fs-nav-account-ready'));
 }
 assert.deepEqual(JSON.parse(fs.readFileSync(path.join(temp,'hubnav.live.js'),'utf8').match(/const BUILTIN=(.*);\r?\n/)[1]),before);
 console.log('PASS: captured navigation registry, exact 16-file scope, preserved bytes, cache references and drift rejection');
}finally{fs.rmSync(temp,{recursive:true,force:true});}

