const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {prepare}=require('./prepare-ui.cjs'),repo=path.resolve(__dirname,'../../..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'fs-seo-ui-'));
const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
try{
 const old='/var/lib/fs-navigation-formal-static/seo-daily-0000000000000000/',names=['index.html','seo.css','app.mjs','model.mjs','ai.mjs','fs-tokens.css','fs-theme.js'];
 const formal=Buffer.from('# Keep other modules\r\n# >>> FS SEO daily >>>\r\n'+names.map(n=>'alias '+old+n+';\r\n').join('')+'proxy_pass http://127.0.0.1:8957;\r\n# <<< FS SEO daily <<<\r\n# Keep later routes\r\n');
 const target='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',hashes={[target]:sha(formal)};
 for(const name of ['ai.mjs','fs-tokens.css','fs-theme.js'])hashes[old+name]=sha(fs.readFileSync(path.join(repo,name==='fs-tokens.css'?'ui-system/tokens/'+name:name==='fs-theme.js'?'ui-system/adapters/'+name:'ui-system/modules/seo/'+name)));
 for(const p of ['/etc/fs-seo/config.json','/etc/systemd/system/fs-seo-web.service','/etc/systemd/system/fs-seo-daily.service','/etc/systemd/system/fs-seo-daily.timer'])hashes[p]='1'.repeat(64);
 const base=path.join(temp,'baseline.json'),input=path.join(temp,'formal.conf'),out=path.join(temp,'release');fs.writeFileSync(base,JSON.stringify({target_hashes:hashes,unchangedRequired:[]}));fs.writeFileSync(input,formal);
 const result=prepare(repo,base,input,out),manifest=JSON.parse(fs.readFileSync(path.join(out,'manifest.json'))),routes=fs.readFileSync(path.join(out,'candidate/routes.conf'),'utf8');
 assert.equal(result.files,8);assert.equal(manifest.files.filter(f=>f.target.startsWith('/var/lib/fs-navigation-formal-static/seo-ui-')).length,7);
 assert(manifest.files.every(f=>f.target.startsWith('/var/lib/fs-navigation-formal-static/seo-ui-')||f.target===target));
 assert.equal(manifest.unchangedRequired.length,4);assert(routes.startsWith('# Keep other modules\r\n'));assert(routes.endsWith('# Keep later routes\r\n'));assert(routes.includes('proxy_pass http://127.0.0.1:8957;\r\n'));
 assert(!manifest.files.some(f=>f.target.includes('/opt/')||f.target.includes('/systemd/')));
 fs.appendFileSync(input,'drift');assert.throws(()=>prepare(repo,base,input,path.join(temp,'bad')),/formal source drift/);
 console.log('PASS: UI-only eight targets, unchanged backend controls, seven aliases, other routes and drift rejection');
}finally{assert.equal(path.dirname(path.resolve(temp)),path.resolve(os.tmpdir()));fs.rmSync(temp,{recursive:true,force:true});}
