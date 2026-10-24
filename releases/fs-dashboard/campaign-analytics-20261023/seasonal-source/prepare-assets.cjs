const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const sharp = require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const root=path.resolve(__dirname,'../app/seasonal');
const docs=process.env.SEASONAL_ASSET_SOURCE;
if(!docs)throw new Error('SEASONAL_ASSET_SOURCE must identify the original creative source directory; existing accepted assets need no rebuild');
const input=JSON.parse(fs.readFileSync(path.join(docs,'IMAGEGEN-PROMPTS.json'),'utf8'));
const hash=buffer=>crypto.createHash('sha256').update(buffer).digest('hex');
(async()=>{
  fs.mkdirSync(path.join(docs,'creative-originals'),{recursive:true});
  const manifest=[];
  for(const asset of input.assets){
    const source=fs.readFileSync(asset.source);
    fs.copyFileSync(asset.source,path.join(docs,'creative-originals',asset.name+'.png'));
    // Keep the generated composition; only encode a smaller web format.
    const output=await sharp(source).webp({quality:86,effort:5}).toBuffer();
    fs.writeFileSync(path.join(root,'assets',asset.name+'.webp'),output);
    const meta=await sharp(output).metadata();
    manifest.push({name:asset.name,width:meta.width,height:meta.height,sourceSha256:hash(source),webSha256:hash(output),webBytes:output.length,webPath:'assets/'+asset.name+'.webp'});
  }
  fs.writeFileSync(path.join(docs,'ASSET-MANIFEST.json'),JSON.stringify({generatedAt:'2026-10-24',assets:manifest},null,2)+'\n');
  console.log(JSON.stringify({assets:manifest.length,totalWebBytes:manifest.reduce((sum,a)=>sum+a.webBytes,0)}));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
