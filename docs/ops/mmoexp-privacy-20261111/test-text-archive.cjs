'use strict';
const fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto'),assert=require('assert/strict'),{spawnSync}=require('child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'guard-text-test-')),logs=path.join(root,'logs'),bot=path.join(root,'bot'),dest=path.join(root,'archive'),key=path.join(root,'key');
fs.mkdirSync(logs);fs.mkdirSync(bot);fs.writeFileSync(key,crypto.randomBytes(32),{mode:0o600});fs.chmodSync(key,0o600);
const storageModule=process.env.STORAGE_SOURCE||(fs.existsSync(path.join(__dirname,'source','secure-storage.js'))?path.join(__dirname,'source','secure-storage.js'):path.resolve(__dirname,'../../../opt/mmoexp-guardbot/secure-storage.js'));
fs.writeFileSync(path.join(bot,'secure-storage.js'),`module.exports=require(${JSON.stringify(storageModule)}).createStorage({root:__dirname,keyFile:${JSON.stringify(key)},enforce:true});`);
const source=path.join(logs,'messages-20261108'),active=path.join(logs,'messages');
const bytes=Buffer.concat([Buffer.from('Nov  6 10:00:00 fixture other: unrelated record\nNov  6 10:01:00 fixture node: [SELFCHECK] user=fabricated (111111111111111111)\n'),Buffer.from([255,254,0,10]),Buffer.from('Nov  6 10:02:00 fixture other: no final newline')]);
fs.writeFileSync(source,bytes);fs.writeFileSync(active,'active current log untouched');
const env={...process.env,TEXT_LOG_ROOT:logs,TEXT_LOG_DEST:dest,TEXT_BOT_ROOT:bot,TEXT_ARCHIVE_KEY_FILE:key,TEXT_LOG_FIXTURE:'1'};
const run=cmd=>spawnSync(process.execPath,[path.join(__dirname,'archive-text-logs.cjs'),cmd],{env,encoding:'utf8'});
let checks=0;function check(name,condition){assert(condition,name);checks++;console.log('PASS '+name);}
try{
 let r=run('prepare');check('raw source byte roundtrip including invalid UTF8 and unterminated line',r.status===0);
 const mf=path.join(dest,'manifest.json'),original=fs.readFileSync(mf),m=JSON.parse(original);
 check('all records accounted for and no plaintext export',m.sourceCount===4&&m.botCount===1&&m.otherCount===3&&fs.readdirSync(dest).sort().join(',')==='manifest.json,other-services.jsonl.gz.enc');
 const storage=require(path.join(bot,'secure-storage'));check('bot record has deletion identifier and original retention timestamp',storage.readFileSync(path.join(bot,'legacy-system-events.jsonl'),'utf8').includes('111111111111111111')&&JSON.parse(storage.readFileSync(path.join(bot,'legacy-system-events.jsonl'),'utf8')).at===Date.parse('2026-11-06T10:01:00+08:00'));
 fs.appendFileSync(source,'changed');r=run('cleanup');check('changed source blocks cleanup',r.status!==0&&fs.existsSync(source));fs.writeFileSync(source,bytes);
 const cipher=fs.readFileSync(m.otherFile),bad=Buffer.from(cipher);bad[bad.length-1]^=1;fs.writeFileSync(m.otherFile,bad);r=run('cleanup');check('corrupted archive blocks cleanup',r.status!==0&&fs.existsSync(source));fs.writeFileSync(m.otherFile,cipher);
 const outside=path.join(root,'messages-20261101');fs.writeFileSync(outside,'outside');m.sources.push({name:path.basename(outside),file:outside,size:7,ino:fs.statSync(outside).ino,sha256:crypto.createHash('sha256').update('outside').digest('hex')});fs.writeFileSync(mf,JSON.stringify(m));r=run('cleanup');check('outside source cannot be removed',r.status!==0&&fs.existsSync(outside)&&fs.existsSync(source));fs.writeFileSync(mf,original);
 r=run('cleanup');check('only verified rotated sources are removed',r.status===0&&!fs.existsSync(source)&&fs.readFileSync(active,'utf8')==='active current log untouched');
 storage.eraseSubject('111111111111111111');r=run('verify');check('other-service verification survives legitimate bot deletion',r.status===0&&!storage.readFileSync(path.join(bot,'legacy-system-events.jsonl'),'utf8').includes('111111111111111111'));
 console.log(JSON.stringify({suite:'text-archive',assertions:checks,status:'passed',fixture:'fabricated logs only'}));
}finally{fs.rmSync(root,{recursive:true,force:true});}
