const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const targets={
 'hubnav.js':'/var/www/hub/hubnav.js','nav.js':'/var/www/hub/nav.js',
 'z-main.conf':'/etc/nginx/conf.d/iggm-web.conf','zz-formal.conf':'/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',
 'home.html':'/var/www/dashboard/fs-home/index.html','analytics.html':'/var/www/dashboard/modules/analytics/index.html',
 'hermes.html':'/var/www/dashboard/modules/hermes/index.html','sports.html':'/var/www/dashboard/modules/sports/index.html',
 'arpg.html':'/var/www/dashboard/modules/arpg/index.html','bots.html':'/var/www/dashboard/modules/bots/index.html',
 'collaboration.html':'/var/www/dashboard/modules/collaboration/index.html','about.html':'/var/www/dashboard/modules/about/index.html',
 'report.html':'/var/www/dashboard/fs-home/brain/index.html','conversation.html':'/var/www/dashboard/fs-home/hermes/conversation/index.html',
 'tasks.html':'/var/www/dashboard/tasks/index.html','fc-coins.html':'/var/www/dashboard/fc27-coins.html'
};
const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const readJSON=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
function prepare(baseline,manifestPath,registryPath,output){
 assert(!fs.existsSync(output),'new output directory required');
 const manifest=readJSON(manifestPath),registry=readJSON(registryPath);
 assert.equal(manifest.scope,'traffic-source-tabs-ui-finish-20261019');
 assert.equal(manifest.businessWrites,false);assert.equal(manifest.timersChanged,false);
 assert.deepEqual(manifest.files.map(f=>f.candidate).sort(),Object.keys(targets).sort());
 assert.equal(registry.tools.filter(t=>t.id==='seo'&&t.path==='/dashboard/analytics/seo/').length,1);
 assert(registry.sections.find(s=>s.id==='analytics').ids.includes('seo'));
 const current=new Map();
 for(const row of manifest.files){
  assert.equal(row.target,targets[row.candidate]);
  const raw=fs.readFileSync(path.join(baseline,row.candidate));
  assert.equal(sha(raw),row.beforeSha256,'captured source drift');current.set(row.candidate,raw);
 }
 const source=__dirname,normalized=text=>text.replace(/\r\n/g,'\n');
 execFileSync(process.execPath,[path.join(source,'build.cjs')]);
 for(const name of ['hubnav.js','nav.js'])assert.equal(normalized(current.get(name).toString()),normalized(fs.readFileSync(path.join(source,'candidate',name),'utf8')),'current navigation differs from maintained source');
 execFileSync(process.execPath,[path.join(source,'build.cjs'),path.resolve(registryPath)]);
 const version='navigation-seo-20261105-'+sha(Buffer.from(JSON.stringify(registry))).slice(0,12),files=[],refs={};
 fs.mkdirSync(path.join(output,'candidate'),{recursive:true});
 for(const row of manifest.files){
  const before=current.get(row.candidate),text=before.toString();let after;
  if(['hubnav.js','nav.js'].includes(row.candidate)){
   const compiled=fs.readFileSync(path.join(source,'candidate',row.candidate),'utf8'),pattern=/const registry=(.*);\r?\n/;
   const old=text.match(pattern),next=compiled.match(pattern);assert(old&&next);
   assert.deepEqual(JSON.parse(next[1]),registry);
   after=text.replace('const registry='+old[1]+';','const registry='+next[1]+';');
   assert.equal(normalized(after),normalized(compiled),'unexpected navigation code change');
  }else{
   let count=0;after=text.replace(/((?:hubnav|nav)\.js\?v=)[A-Za-z0-9_-]+/g,(_,prefix)=>{count++;return prefix+version;});
   assert(count>0,'missing navigation cache reference');refs[row.candidate]=count;
  }
  const raw=Buffer.from(after);assert(!raw.equals(before),'unchanged release target');
  fs.writeFileSync(path.join(output,'candidate',row.candidate),raw);
  files.push({...row,sha256:sha(raw)});
 }
 const raw=Buffer.from(JSON.stringify({...manifest,files},null,2)+'\n');fs.writeFileSync(path.join(output,'manifest.json'),raw);
 fs.writeFileSync(path.join(output,'targets.json'),JSON.stringify(targets,null,2)+'\n');
 return {version,files:files.length,manifest_sha256:sha(raw),references:refs};
}
module.exports={prepare,targets};
if(require.main===module)console.log(JSON.stringify(prepare(...process.argv.slice(2))));
