'use strict';
// One-time, explicitly authorized syslog migration. Raw bytes are preserved inside authenticated encryption.
const fs=require('fs'),path=require('path'),crypto=require('crypto'),zlib=require('zlib');
const {pipeline}=require('stream/promises'),{once}=require('events'),{execFileSync}=require('child_process');
const ROOT=process.env.TEXT_LOG_ROOT||'/var/log';
const DEST=process.env.TEXT_LOG_DEST||'/var/lib/mmoexp-privacy-archive/20261111/text-logs';
const BOT=process.env.TEXT_BOT_ROOT||'/opt/mmoexp-guardbot';
const KEY=process.env.TEXT_ARCHIVE_KEY_FILE||'/etc/mmoexp-guardbot/journal-archive.key';
const manifestFile=path.join(DEST,'manifest.json'),botFile=path.join(BOT,'legacy-system-events.jsonl');
const storage=require(path.join(BOT,'secure-storage'));
const MAGIC=Buffer.from('MMOEXPTEXTLOG1\n'),migrationId='syslog-privacy-20261111';
const rotatedName='messages.privacy-20261111';
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
async function fileHash(file){const h=crypto.createHash('sha256');for await(const chunk of fs.createReadStream(file))h.update(chunk);return h.digest('hex');}
function allowed(name){return /^messages-\d{8}$/.test(name)||name===rotatedName;}
function isBot(line){return /\[(D4-GUARD|SELFCHECK)\]/.test(line)||line.includes('/opt/mmoexp-guardbot/')||(line.includes('user=')&&(line.includes('brand=')||line.includes('处置失败')));}
async function* rawLines(file){
 let rest=Buffer.alloc(0),offset=0;
 for await(const chunk of fs.createReadStream(file)){
  rest=Buffer.concat([rest,chunk]);let start=0,end;
  while((end=rest.indexOf(10,start))!==-1){const raw=rest.subarray(start,end+1);yield {offset,raw};offset+=raw.length;start=end+1;}
  rest=Buffer.from(rest.subarray(start));
 }
 if(rest.length)yield {offset,raw:rest};
}
function timestamp(line,mtime){
 const m=line.match(/^(\w{3}\s+\d+\s+\d+:\d+:\d+)/);if(!m)throw Error('Unknown bot log timestamp');
 let year=new Date(mtime).getUTCFullYear(),stamp=Date.parse(m[1]+' '+year+' +0800');
 if(stamp>mtime+86400000)stamp=Date.parse(m[1]+' '+(--year)+' +0800');
 if(!Number.isFinite(stamp))throw Error('Unknown bot log timestamp');return stamp;
}
async function rotate(){
 if(process.env.TEXT_LOG_FIXTURE==='1')return;
 if(ROOT!=='/var/log')throw Error('Unexpected production log root');
 const active=path.join(ROOT,'messages'),target=path.join(ROOT,rotatedName),old=fs.lstatSync(active);
 if(!old.isFile()||old.isSymbolicLink()||fs.existsSync(target))throw Error('Cannot safely rotate current log');
 fs.renameSync(active,target);
 execFileSync('systemctl',['kill','--kill-who=main','--signal=SIGHUP','rsyslog.service']);
 const pid=String(execFileSync('systemctl',['show','rsyslog.service','-p','MainPID'],{encoding:'utf8'})).trim().split('=')[1];
 if(!/^\d+$/.test(pid)||pid==='0')throw Error('Cannot confirm syslog process');
 for(let n=0;n<100;n++){
  let open=false;
  for(const fd of fs.readdirSync('/proc/'+pid+'/fd')){try{if(fs.statSync('/proc/'+pid+'/fd/'+fd).ino===old.ino)open=true;}catch{}}
  if(fs.existsSync(active)&&fs.statSync(active).ino!==old.ino&&!open)return;
  await new Promise(r=>setTimeout(r,100));
 }
 throw Error('Current log rotation not confirmed; all old files retained');
}
async function verify(m,strict=m.status==='prepared'){
 const botText=storage.readFileSync(botFile,'utf8');
 if(strict&&hash(Buffer.from(botText))!==m.botCombinedSha256)throw Error('Bot archive changed before cleanup');
 const botRows=botText.split('\n').filter(Boolean).map(JSON.parse).filter(r=>r.migrationId===migrationId);
 const s=fs.statSync(m.otherFile),fd=fs.openSync(m.otherFile,'r'),head=Buffer.alloc(MAGIC.length+12),tag=Buffer.alloc(16);
 fs.readSync(fd,head,0,head.length,0);fs.readSync(fd,tag,0,16,s.size-16);fs.closeSync(fd);
 if(!head.subarray(0,MAGIC.length).equals(MAGIC))throw Error('Invalid archive header');
 const decipher=crypto.createDecipheriv('aes-256-gcm',fs.readFileSync(KEY),head.subarray(MAGIC.length));decipher.setAAD(MAGIC);decipher.setAuthTag(tag);
 const unzip=zlib.createGunzip(),pending=pipeline(fs.createReadStream(m.otherFile,{start:head.length,end:s.size-17}),decipher,unzip);
 const hashes=new Map(m.sources.map(s=>[s.name,{hash:crypto.createHash('sha256'),bytes:0,next:0}]));
 // Merge source offsets, retaining only a small number of bot rows in memory.
 const remaining=botRows.slice().sort((a,b)=>(a.name<b.name?-1:a.name>b.name?1:0)||a.offset-b.offset);let otherCount=0,botCount=0;
 function add(row){const item=hashes.get(row.name);if(!item||row.offset!==item.next)throw Error('Archive source offset mismatch');const raw=Buffer.from(row.raw,'base64');item.hash.update(raw);item.bytes+=raw.length;item.next+=raw.length;}
 async function accept(row){
  if(strict)while(remaining.length&&(remaining[0].name<row.name||(remaining[0].name===row.name&&remaining[0].offset<row.offset))){add(remaining.shift());botCount++;}
  if(isBot(Buffer.from(row.raw,'base64').toString('utf8')))throw Error('Bot record leaked to other-service archive');
  if(strict)add(row);otherCount++;
 }
 let rest='';
 for await(const chunk of unzip){rest+=chunk.toString('utf8');let at;while((at=rest.indexOf('\n'))!==-1){const line=rest.slice(0,at);rest=rest.slice(at+1);if(line)await accept(JSON.parse(line));}}
 await pending;if(rest)throw Error('Incomplete archive record');
 if(strict){while(remaining.length){add(remaining.shift());botCount++;}for(const source of m.sources){const got=hashes.get(source.name);if(got.bytes!==source.size||got.hash.digest('hex')!==source.sha256)throw Error('Archive raw source verification failed');}if(botCount!==m.botCount)throw Error('Bot count mismatch');}
 if(otherCount!==m.otherCount)throw Error('Other count mismatch');return true;
}
async function prepare(){
 if(fs.existsSync(manifestFile))throw Error('Archive manifest already exists');
 fs.mkdirSync(DEST,{recursive:true,mode:0o700});fs.chmodSync(DEST,0o700);
 const key=fs.readFileSync(KEY);if(key.length!==32)throw Error('Invalid archive key');
 await rotate();
 const sources=[];
 for(const name of fs.readdirSync(ROOT).filter(allowed).sort()){
  const file=path.join(ROOT,name),s=fs.lstatSync(file);if(!s.isFile()||s.isSymbolicLink())throw Error('Unexpected log source');
  sources.push({name,file,size:s.size,ino:s.ino,mtimeMs:s.mtimeMs,sha256:await fileHash(file)});
 }
 if(!sources.length)throw Error('No rotated text logs');
 const otherFile=path.join(DEST,'other-services.jsonl.gz.enc'),iv=crypto.randomBytes(12);
 fs.writeFileSync(otherFile,Buffer.concat([MAGIC,iv]),{flag:'wx',mode:0o600});
 const zip=zlib.createGzip({level:1}),cipher=crypto.createCipheriv('aes-256-gcm',key,iv);cipher.setAAD(MAGIC);
 const pending=pipeline(zip,cipher,fs.createWriteStream(otherFile,{flags:'a',mode:0o600}));
 const bot=[];let sourceCount=0,otherCount=0;
 for(const source of sources)for await(const {offset,raw} of rawLines(source.file)){
  const row={name:source.name,offset,raw:raw.toString('base64')},line=raw.toString('utf8');sourceCount++;
  if(isBot(line))bot.push({...row,migrationId,MESSAGE:line,at:timestamp(line,source.mtimeMs)});
  else{otherCount++;if(!zip.write(JSON.stringify(row)+'\n'))await once(zip,'drain');}
 }
 zip.end();await pending;fs.appendFileSync(otherFile,cipher.getAuthTag());
 const before=fs.existsSync(botFile)?storage.readFileSync(botFile,'utf8'):'';
 if(before.includes('"migrationId":"'+migrationId+'"'))throw Error('Bot text migration already present');
 const combined=before+(before&&!before.endsWith('\n')?'\n':'')+bot.map(r=>JSON.stringify(r)).join('\n')+(bot.length?'\n':'');
 storage.writeFileSync(botFile,combined);
 const m={version:1,status:'prepared',createdAt:new Date().toISOString(),format:'source filename and byte offset plus base64 original line bytes',sources,otherFile,sourceCount,otherCount,botCount:bot.length,botCombinedSha256:hash(Buffer.from(combined))};
 fs.writeFileSync(manifestFile,JSON.stringify(m,null,2),{flag:'wx',mode:0o600});
 for(const f of [otherFile,manifestFile,KEY,DEST]){const fd=fs.openSync(f,'r');fs.fsyncSync(fd);fs.closeSync(fd);}
 await verify(m);console.log(JSON.stringify({status:'verified',sourceFiles:sources.length,sourceCount,botCount:bot.length,otherCount,archiveBytes:fs.statSync(otherFile).size,originalsRetained:true}));
}
async function cleanup(){
 const m=JSON.parse(fs.readFileSync(manifestFile,'utf8'));if(m.status!=='prepared')throw Error('Archive not prepared');await verify(m);
 for(const source of m.sources){const resolved=path.resolve(source.file),s=fs.lstatSync(resolved);if(path.dirname(resolved)!==path.resolve(ROOT)||!allowed(path.basename(resolved))||s.isSymbolicLink()||!s.isFile()||s.ino!==source.ino||s.size!==source.size||await fileHash(resolved)!==source.sha256)throw Error('Source changed or outside allowed scope; no cleanup');}
 for(const source of m.sources)fs.unlinkSync(source.file);
 m.status='cleaned';m.cleanedAt=new Date().toISOString();fs.writeFileSync(manifestFile,JSON.stringify(m,null,2),{mode:0o600});
 console.log(JSON.stringify({status:'cleaned',sourceFiles:m.sources.length,sourceCount:m.sourceCount,botCount:m.botCount,otherCount:m.otherCount,currentLogUntouched:true}));
}
if(require.main===module)(async()=>{const cmd=process.argv[2];if(cmd==='prepare')await prepare();else if(cmd==='cleanup')await cleanup();else if(cmd==='verify'){await verify(JSON.parse(fs.readFileSync(manifestFile,'utf8')));console.log('Encrypted text log archive verified');}else throw Error('Use prepare, verify or cleanup');})().catch(()=>{console.error('Text log migration failed; inspect manifest. No raw data printed.');process.exitCode=1;});
