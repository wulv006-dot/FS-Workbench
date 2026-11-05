const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const FORMAL='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf';
const names=['index.html','seo.css','app.mjs','model.mjs','ai.mjs','fs-tokens.css','fs-theme.js'];
const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const readJSON=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
function prepare(repo,baselinePath,formalPath,output){
 assert(!fs.existsSync(output),'new output directory required');
 const baseline=readJSON(baselinePath),formal=fs.readFileSync(formalPath);assert.equal(sha(formal),baseline.target_hashes[FORMAL],'formal source drift');
 const original=formal.toString(),start='# >>> FS SEO daily >>>',end='# <<< FS SEO daily <<<';assert(Buffer.from(original).equals(formal),'UTF-8 formal required');
 assert.equal(original.split(start).length,2);assert.equal(original.split(end).length,2);const a=original.indexOf(start),b=original.indexOf(end)+end.length;assert(b>a);
 const block=original.slice(a,b),aliases=[...block.matchAll(/alias (\/var\/lib\/fs-navigation-formal-static\/seo-(?:daily|ui)-[a-f0-9]{16}\/([^;]+));/g)];
 assert.deepEqual(aliases.map(m=>m[2]).sort(),[...names].sort(),'exact seven SEO aliases required');
 const assets=new Map(names.map(name=>[name,fs.readFileSync(path.join(repo,name==='fs-tokens.css'?'ui-system/tokens/'+name:name==='fs-theme.js'?'ui-system/adapters/'+name:'ui-system/modules/seo/'+name))]));
 for(const name of ['ai.mjs','fs-tokens.css','fs-theme.js'])assert.equal(sha(assets.get(name)),baseline.target_hashes[aliases.find(m=>m[2]===name)[1]],'unchanged shared asset drift');
 const hash=crypto.createHash('sha256');for(const [name,raw] of assets)hash.update(name+'\0').update(raw);const version='seo-ui-'+hash.digest('hex').slice(0,16),targets={},files=[];
 fs.mkdirSync(path.join(output,'candidate/ui'),{recursive:true});
 for(const [name,raw] of assets){const candidate='ui/'+name,target='/var/lib/fs-navigation-formal-static/'+version+'/'+name;targets[candidate]=target;fs.writeFileSync(path.join(output,'candidate',candidate),raw);files.push({candidate,target,beforeSha256:null,sha256:sha(raw)});}
 let replacement=block;for(const match of aliases)replacement=replacement.replace(match[0],'alias /var/lib/fs-navigation-formal-static/'+version+'/'+match[2]+';');
 const routes=Buffer.from(original.slice(0,a)+replacement+original.slice(b));fs.writeFileSync(path.join(output,'candidate/routes.conf'),routes);targets['routes.conf']=FORMAL;files.push({candidate:'routes.conf',target:FORMAL,beforeSha256:sha(formal),sha256:sha(routes)});
 const unchangedRequired=[...baseline.unchangedRequired];
 for(const target of ['/etc/fs-seo/config.json','/etc/systemd/system/fs-seo-web.service','/etc/systemd/system/fs-seo-daily.service','/etc/systemd/system/fs-seo-daily.timer']){const hash=baseline.target_hashes[target];assert(/^[a-f0-9]{64}$/.test(hash),'existing SEO controls must be pinned');unchangedRequired.push({path:target,sha256:hash});}
 const manifest={schemaVersion:1,scope:'traffic-source-tabs-ui-finish-20261019',releaseReady:true,businessWrites:false,timersChanged:false,runtimeRequired:{'nginx.service':{ActiveState:'active'},'fs-marketing-range.service':{ActiveState:'active'}},unchangedRequired,files};
 const raw=Buffer.from(JSON.stringify(manifest,null,2)+'\n');fs.writeFileSync(path.join(output,'manifest.json'),raw);fs.writeFileSync(path.join(output,'targets.json'),JSON.stringify(targets,null,2)+'\n');return {version,files:files.length,manifest_sha256:sha(raw)};
}
module.exports={prepare};
if(require.main===module)console.log(JSON.stringify(prepare(path.resolve(__dirname,'../../..'),...process.argv.slice(2))));
