'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto'),{execFileSync}=require('child_process');
const ROOT='/opt/mmoexp-guardbot',STAGE=ROOT+'/privacy-stage-20261111',BACKUP=ROOT+'/backups/privacy-20261111';
const KEY='/etc/mmoexp-guardbot/data.key',DROP='/etc/systemd/system/mmoexp-guardbot.service.d/privacy-storage.conf';
const active=['index.js','d4-guard-extension.js','public-welcome.js','welcome-navigation.js'];
const added=['secure-storage.js','privacy.js','privacy-admin.js'];
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function run(...args){return execFileSync(args[0],args.slice(1),{encoding:'utf8',stdio:['ignore','pipe','pipe']});}
function recoveryCode(name,text){
 text=text.replace("require('fs')","require('./secure-storage')");
 if(name==='index.js'){
  text=text.replace('function main() {',"function main() {\n  require('./privacy').installConsole();\n  require('./secure-storage').verify();");
  text=text.replace('} catch (e) { /* 首次运行没有白名单文件是正常的 */ }',"} catch (e) { if(e.code!=='ENOENT')throw e; }");
 }
 return text;
}
function rollback(){
 const manifest=JSON.parse(require(ROOT+'/secure-storage').readFileSync(BACKUP+'/manifest.json','utf8'));
 run('systemctl','stop','mmoexp-guardbot');
 for(const name of active)fs.copyFileSync(BACKUP+'/recovery/'+name,ROOT+'/'+name);
 const store=require(ROOT+'/secure-storage');store.migrate();store.verify();
 run('systemctl','daemon-reload');run('systemctl','start','mmoexp-guardbot');
 console.log(JSON.stringify({status:'recovery-started',encryptionRetained:true,currentDataPreserved:true,privacySelfService:false,supportAndAdminDeletionRemain:true,baseline:manifest.baseline}));
}
function install(){
 const lock=ROOT+'/.privacy-deploy.lock';const fd=fs.openSync(lock,'wx',0o600);fs.closeSync(fd);
 let stopped=false;
 try{
  if(fs.existsSync(BACKUP+'/manifest.json'))throw Error('Release backup already exists; inspect current state before retrying');
  fs.mkdirSync(BACKUP+'/original',{recursive:true,mode:0o700});fs.mkdirSync(BACKUP+'/recovery',{recursive:true,mode:0o700});
  const manifest={createdAt:new Date().toISOString(),baseline:{},installed:{},dataPlaintextHashes:{},keyFile:KEY};
  for(const name of [...active,...added]){
   run('/usr/local/bin/node','--check',STAGE+'/'+name);
   manifest.installed[name]=hash(fs.readFileSync(STAGE+'/'+name));
  }
  for(const name of active){
   const bytes=fs.readFileSync(ROOT+'/'+name);manifest.baseline[name]=hash(bytes);
   fs.writeFileSync(BACKUP+'/original/'+name,bytes,{mode:0o600});
   fs.writeFileSync(BACKUP+'/recovery/'+name,recoveryCode(name,bytes.toString('utf8')),{mode:0o600});
   run('/usr/local/bin/node','--check',BACKUP+'/recovery/'+name);
  }
  fs.mkdirSync(path.dirname(KEY),{recursive:true,mode:0o700});fs.chmodSync(path.dirname(KEY),0o700);
  if(!fs.existsSync(KEY))fs.writeFileSync(KEY,crypto.randomBytes(32),{flag:'wx',mode:0o600});fs.chmodSync(KEY,0o600);
  {const fd=fs.openSync(KEY,'r');fs.fsyncSync(fd);fs.closeSync(fd);const dd=fs.openSync(path.dirname(KEY),'r');fs.fsyncSync(dd);fs.closeSync(dd);}
  process.env.GUARD_PRIVACY_KEY_FILE=KEY;process.env.GUARD_PRIVACY_ENFORCE='1';
  // Only source has been backed up so far. Stop the writer before snapshotting any live state.
  run('systemctl','stop','mmoexp-guardbot');stopped=true;
  for(const name of [...active,...added])fs.copyFileSync(STAGE+'/'+name,ROOT+'/'+name);
  const store=require(ROOT+'/secure-storage');
  const data=['config.json','whitelist.json','d4-guard.json','welcome-config.json','welcome-games.json','action-ledger.jsonl','d4-action-ledger.jsonl','welcome-state/welcome-panel.json','welcome-state/welcome-delivery.jsonl'];
  for(const rel of data){
   const file=ROOT+'/'+rel;if(!fs.existsSync(file))continue;
   const bytes=fs.readFileSync(file);manifest.dataPlaintextHashes[rel]=hash(bytes);
   const dest=BACKUP+'/data/'+rel;fs.mkdirSync(path.dirname(dest),{recursive:true,mode:0o700});
   fs.writeFileSync(dest,store.encode(bytes),{mode:0o600});
  }
  const result=store.migrate();
  for(const [rel,expected] of Object.entries(manifest.dataPlaintextHashes))if(hash(store.readFileSync(ROOT+'/'+rel))!==expected)throw Error('Migration changed a data payload');
  fs.chmodSync(ROOT,0o700);
  fs.mkdirSync(path.dirname(DROP),{recursive:true});
  if(fs.existsSync(DROP))throw Error('Unexpected existing privacy service override');
  fs.writeFileSync(DROP,'[Service]\nEnvironment=GUARD_PRIVACY_KEY_FILE='+KEY+'\nEnvironment=GUARD_PRIVACY_ENFORCE=1\nUMask=0077\n',{mode:0o644});
  fs.writeFileSync(BACKUP+'/manifest.json',JSON.stringify(manifest,null,2),{mode:0o600});
  // The manifest itself contains no payload, but still uses the same encrypted data convention.
  store.migrate();const verified=store.verify();
  run('systemctl','daemon-reload');run('systemctl','start','mmoexp-guardbot');stopped=false;
  console.log(JSON.stringify({status:'started',migration:result,verification:verified,activePayloadsUnchanged:true,backup:BACKUP,rollback:'GUARD_PRIVACY_KEY_FILE='+KEY+' GUARD_PRIVACY_ENFORCE=1 node /opt/mmoexp-privacy-release-20261111.cjs rollback'}));
 }catch(error){
  if(stopped){
   try{
    const storage=require(ROOT+'/secure-storage');storage.migrate();storage.verify();
    for(const name of active)fs.copyFileSync(BACKUP+'/recovery/'+name,ROOT+'/'+name);
    if(!fs.existsSync(DROP)){fs.mkdirSync(path.dirname(DROP),{recursive:true});fs.writeFileSync(DROP,'[Service]\nEnvironment=GUARD_PRIVACY_KEY_FILE='+KEY+'\nEnvironment=GUARD_PRIVACY_ENFORCE=1\nUMask=0077\n');}
    run('systemctl','daemon-reload');run('systemctl','start','mmoexp-guardbot');
    console.error('Release failed; encrypted compatibility recovery started');
   }catch{console.error('Release failed; service left stopped to protect encrypted data. Repair locally.');}
  }
  throw error;
 }finally{fs.unlinkSync(lock);}
}
try{
 if(process.argv[2]==='install')install();else if(process.argv[2]==='rollback')rollback();else throw Error('Use install or rollback');
}catch(error){console.error('Privacy release error:',error.code||'CHECK_FAILED',/^(Release|Migration|Unexpected)/.test(error.message)?error.message:'Inspect locally; payload details suppressed');process.exitCode=1;}
