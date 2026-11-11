'use strict';
const fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto'),assert=require('assert/strict');
const {spawnSync}=require('child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'guard-journal-test-'));
const journal=path.join(root,'journal'),dir=path.join(journal,'machine'),dest=path.join(root,'encrypted-archive'),bot=path.join(root,'bot'),key=path.join(root,'key');
fs.mkdirSync(dir,{recursive:true});fs.mkdirSync(bot);fs.writeFileSync(key,crypto.randomBytes(32),{mode:0o600});fs.chmodSync(key,0o600);
const source=path.join(dir,'system@fixture.journal'),active=path.join(dir,'system.journal');
fs.writeFileSync(source,'fabricated immutable journal');fs.writeFileSync(active,'fabricated active journal');
fs.writeFileSync(path.join(bot,'secure-storage.js'),`module.exports=require(${JSON.stringify(path.resolve(__dirname,'../../../opt/mmoexp-guardbot/secure-storage'))}).createStorage({root:__dirname,keyFile:${JSON.stringify(key)},enforce:true});`);
const helper=path.join(root,'journalctl-fixture');
fs.writeFileSync(helper,`#!/usr/bin/env node\nif(process.argv.some(a=>a.startsWith('--file='))){console.log(JSON.stringify({_SYSTEMD_UNIT:'mmoexp-guardbot.service',MESSAGE:'user=111111111111111111 fabricated name',__REALTIME_TIMESTAMP:'1794355200000000'}));console.log(JSON.stringify({_SYSTEMD_UNIT:'other.service',MESSAGE:'fabricated unrelated record',__REALTIME_TIMESTAMP:'1794355200000001'}));}\n`,{mode:0o700});fs.chmodSync(helper,0o700);
const env={...process.env,JOURNAL_ROOT:journal,JOURNAL_DEST:dest,JOURNAL_ARCHIVE_KEY_FILE:path.join(root,'other-key'),JOURNALCTL_BIN:helper,JOURNAL_BOT_ROOT:bot};
const run=cmd=>spawnSync(process.execPath,[path.join(__dirname,'archive-journals.cjs'),cmd],{env,encoding:'utf8'});
function check(name,condition){assert(condition,name);console.log('PASS '+name);}
try{
 let r=run('prepare');check('archive prepares and verifies both categories',r.status===0);
 const manifestPath=path.join(dest,'manifest.json'),original=fs.readFileSync(manifestPath),m=JSON.parse(original);
 check('all source records accounted for',m.sourceCount===2&&m.botCount===1&&m.otherCount===1);
 fs.writeFileSync(source,'source changed after archive');r=run('cleanup');check('changed source blocks cleanup',r.status!==0&&fs.existsSync(source));fs.writeFileSync(source,'fabricated immutable journal');
 const ciphertext=fs.readFileSync(m.otherFile),damaged=Buffer.from(ciphertext);damaged[damaged.length-1]^=1;fs.writeFileSync(m.otherFile,damaged);r=run('cleanup');check('tampered archive blocks cleanup',r.status!==0&&fs.existsSync(source));fs.writeFileSync(m.otherFile,ciphertext);
 const outside=path.join(root,'outside@fixture.journal');fs.writeFileSync(outside,'outside file');m.sources.push({file:outside,size:12,ino:fs.statSync(outside).ino,sha256:crypto.createHash('sha256').update('outside file').digest('hex')});fs.writeFileSync(manifestPath,JSON.stringify(m));r=run('cleanup');check('outside-root source is never removed',r.status!==0&&fs.existsSync(outside)&&fs.existsSync(source));fs.writeFileSync(manifestPath,original);
 r=run('cleanup');check('only verified rotated files are removed',r.status===0&&!fs.existsSync(source)&&fs.existsSync(active));
 require(path.join(bot,'secure-storage')).eraseSubject('111111111111111111');
 r=run('verify');check('later bot deletion preserves unrelated archive verification',r.status===0);
 console.log(JSON.stringify({suite:'journal-archive',assertions:7,status:'passed',fixture:'fabricated journal records only'}));
}finally{fs.rmSync(root,{recursive:true,force:true});}
