'use strict';
// Authorized one-time migration of fixed, rotated journal files. No plaintext export is written to disk.
const fs=require('fs'),path=require('path'),crypto=require('crypto'),zlib=require('zlib');
const {spawn,execFileSync}=require('child_process'),readline=require('readline');
const {pipeline}=require('stream/promises');const {once}=require('events');
const ROOT=process.env.JOURNAL_ROOT||'/var/log/journal',DEST=process.env.JOURNAL_DEST||'/var/lib/mmoexp-privacy-archive/20261111';
const MANIFEST=path.join(DEST,'manifest.json');
const KEY=process.env.JOURNAL_ARCHIVE_KEY_FILE||'/etc/mmoexp-guardbot/journal-archive.key';
const JOURNALCTL=process.env.JOURNALCTL_BIN||'journalctl';
const MAGIC=Buffer.from('MMOEXPJOURNAL1\n');
const BOT_ROOT=process.env.JOURNAL_BOT_ROOT||'/opt/mmoexp-guardbot';
const storage=require(path.join(BOT_ROOT,'secure-storage'));
const botFile=path.join(BOT_ROOT,'legacy-system-events.jsonl');
function snapshotFiles(){
 const files=[];
 for(const dir of fs.readdirSync(ROOT,{withFileTypes:true})){
  if(!dir.isDirectory()||dir.isSymbolicLink())continue;
  const parent=path.join(ROOT,dir.name);
  for(const name of fs.readdirSync(parent)){
   if(!name.includes('@')||!name.endsWith('.journal'))continue;
   const f=path.resolve(parent,name),s=fs.lstatSync(f);
   if(!s.isFile()||s.isSymbolicLink())throw Error('Unexpected journal source');
   files.push({file:f,size:s.size,ino:s.ino});
  }
 }
 return files.sort((a,b)=>a.file.localeCompare(b.file));
}
async function fileHash(file){const hash=crypto.createHash('sha256');for await(const chunk of fs.createReadStream(file))hash.update(chunk);return hash.digest('hex');}
function isBot(row){return Object.values(row).some(v=>v==='mmoexp-guardbot.service') || String(row.MESSAGE||'').includes('/opt/mmoexp-guardbot/');}
async function prepare(){
 if(fs.existsSync(MANIFEST))throw Error('Archive manifest already exists; verify or clean up the existing archive instead of replacing it');
 fs.mkdirSync(DEST,{recursive:true,mode:0o700});fs.chmodSync(DEST,0o700);
 fs.mkdirSync(path.dirname(KEY),{recursive:true,mode:0o700});
 if(!fs.existsSync(KEY))fs.writeFileSync(KEY,crypto.randomBytes(32),{flag:'wx',mode:0o600});
 fs.chmodSync(KEY,0o600);{const fd=fs.openSync(KEY,'r');fs.fsyncSync(fd);fs.closeSync(fd);}const key=fs.readFileSync(KEY);if(key.length!==32)throw Error('Invalid archive key');
 // New bot output has already been sanitized before this command is used.
 if(process.env.JOURNALCTL_BIN){execFileSync(JOURNALCTL,['--sync']);execFileSync(JOURNALCTL,['--rotate']);}
 else {
  const current=[];
  for(const dir of fs.readdirSync(ROOT,{withFileTypes:true}))if(dir.isDirectory()){
   const file=path.join(ROOT,dir.name,'system.journal');if(fs.existsSync(file))current.push({file,ino:fs.statSync(file).ino});
  }
  // systemd 219 supports SIGUSR2 rotation; the newer --rotate / --sync CLI options are unavailable.
  execFileSync('systemctl',['kill','--kill-who=main','--signal=SIGUSR2','systemd-journald.service']);
  let rotated=false;
  for(let tries=0;tries<100;tries++){
   if(current.length && current.every(item=>fs.existsSync(item.file)&&fs.statSync(item.file).ino!==item.ino)){rotated=true;break;}
   await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!rotated)throw Error('Journal rotation was not confirmed; original files retained');
 }
 const sources=snapshotFiles();if(!sources.length)throw Error('No rotated journals found');
 for(const item of sources)item.sha256=await fileHash(item.file);
 const iv=crypto.randomBytes(12),outFile=path.join(DEST,'other-services.jsonl.gz.enc');
 fs.writeFileSync(outFile,Buffer.concat([MAGIC,iv]),{flag:'wx',mode:0o600});
 const zip=zlib.createGzip({level:1}),cipher=crypto.createCipheriv('aes-256-gcm',key,iv);cipher.setAAD(MAGIC);
 const output=fs.createWriteStream(outFile,{flags:'a',mode:0o600});
 const pending=pipeline(zip,cipher,output);
 const bot=[],hashBot=crypto.createHash('sha256'),hashOther=crypto.createHash('sha256');let botCount=0,otherCount=0,sourceCount=0;
 const child=spawn(JOURNALCTL,[...sources.map(s=>'--file='+s.file),'--no-pager','--all','--output=json'],{stdio:['ignore','pipe','pipe']});
 let errors='';child.stderr.on('data',chunk=>{errors+=chunk.toString();if(errors.length>100000)child.kill();});
 const completed=once(child,'close');
 try{
  for await(const line of readline.createInterface({input:child.stdout,crlfDelay:Infinity})){
   if(!line)continue;
   const row=JSON.parse(line),bytes=line+'\n';sourceCount++;
   if(isBot(row)){bot.push(bytes);hashBot.update(bytes);botCount++;}
   else {hashOther.update(bytes);otherCount++;if(!zip.write(bytes))await once(zip,'drain');}
  }
  const [exitCode]=await completed;
  if(exitCode!==0 || errors.trim())throw Error('Journal export reported a problem; original files retained');
  zip.end();await pending;fs.appendFileSync(outFile,cipher.getAuthTag());
  {const fd=fs.openSync(outFile,'r');fs.fsyncSync(fd);fs.closeSync(fd);}
  if(fs.existsSync(botFile))throw Error('Bot legacy archive already exists');
  storage.writeFileSync(botFile,bot.join(''));
  const manifest={version:1,status:'prepared',createdAt:new Date().toISOString(),format:'complete journalctl --all JSON records; original fields and cursors retained',sources,
   sourceCount,botCount,otherCount,botSha256:hashBot.digest('hex'),otherSha256:hashOther.digest('hex'),botFile,otherFile:outFile,archiveKeyFile:KEY};
  fs.writeFileSync(MANIFEST,JSON.stringify(manifest,null,2),{flag:'wx',mode:0o600});
  {const fd=fs.openSync(MANIFEST,'r');fs.fsyncSync(fd);fs.closeSync(fd);const dd=fs.openSync(DEST,'r');fs.fsyncSync(dd);fs.closeSync(dd);}
  await verify(manifest);
  console.log(JSON.stringify({status:'verified',sourceFiles:sources.length,sourceEntries:sourceCount,botEntries:botCount,otherEntries:otherCount,encryptedArchiveBytes:fs.statSync(outFile).size,originalFilesRetained:true}));
 }catch(e){child.kill();zip.destroy();throw e;}
}
async function verify(m){
 const bot=storage.readFileSync(m.botFile);
 if(crypto.createHash('sha256').update(bot).digest('hex')!==m.botSha256)throw Error('Bot archive verification failed');
 const key=fs.readFileSync(KEY),stat=fs.statSync(m.otherFile),fd=fs.openSync(m.otherFile,'r');
 const head=Buffer.alloc(MAGIC.length+12),tag=Buffer.alloc(16);fs.readSync(fd,head,0,head.length,0);fs.readSync(fd,tag,0,16,stat.size-16);fs.closeSync(fd);
 if(!head.subarray(0,MAGIC.length).equals(MAGIC))throw Error('Invalid archive header');
 const decipher=crypto.createDecipheriv('aes-256-gcm',key,head.subarray(MAGIC.length));decipher.setAAD(MAGIC);decipher.setAuthTag(tag);
 const input=fs.createReadStream(m.otherFile,{start:head.length,end:stat.size-17}),unzip=zlib.createGunzip();
 const flow=pipeline(input,decipher,unzip);let count=0;const hash=crypto.createHash('sha256');
 for await(const chunk of unzip){hash.update(chunk);let i=-1;while((i=chunk.indexOf(10,i+1))!==-1)count++;}
 await flow;
 if(count!==m.otherCount || hash.digest('hex')!==m.otherSha256)throw Error('Other-service archive verification failed');
 if(m.sourceCount!==m.botCount+m.otherCount)throw Error('Archive record count mismatch');
 return true;
}
async function cleanup(){
 const m=JSON.parse(fs.readFileSync(MANIFEST,'utf8'));
 if(m.status!=='prepared')throw Error('Archive is not in prepared state');
 await verify(m);
 // Check every source before any removal. Only exact immutable, rotated files are eligible.
 for(const source of m.sources){
  const f=path.resolve(source.file),rel=path.relative(ROOT,f),name=path.basename(f),s=fs.lstatSync(f);
  if(rel.startsWith('..')||path.isAbsolute(rel)||!name.includes('@')||!name.endsWith('.journal')||s.isSymbolicLink()||!s.isFile()||s.ino!==source.ino||s.size!==source.size||await fileHash(f)!==source.sha256)throw Error('Journal source changed; no cleanup performed');
 }
 for(const source of m.sources)fs.unlinkSync(source.file);
 m.status='cleaned';m.cleanedAt=new Date().toISOString();fs.writeFileSync(MANIFEST,JSON.stringify(m,null,2),{mode:0o600});
 console.log(JSON.stringify({status:'cleaned',archivedFiles:m.sources.length,sourceEntries:m.sourceCount,botEntries:m.botCount,otherEntries:m.otherCount,allArchivesVerified:true,currentJournalUntouched:true}));
}
(async()=>{if(process.argv[2]==='prepare')await prepare();else if(process.argv[2]==='cleanup')await cleanup();else if(process.argv[2]==='verify'){await verify(JSON.parse(fs.readFileSync(MANIFEST,'utf8')));console.log('Encrypted journal archives verified');}else throw Error('Use prepare, verify or cleanup');})().catch(error=>{console.error('Journal migration failed; original sources retained unless manifest says cleaned.',error.code||'CHECK_FAILED',/^(Journal|Archive|Bot|Other|Invalid|Unexpected|No rotated|Encrypted|Bot legacy)/.test(error.message)?error.message:'Inspect locally; raw details suppressed');process.exitCode=1;});
