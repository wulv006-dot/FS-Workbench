'use strict';
// Run locally on the bot host as its service account. Never prints data or key bytes.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const cmd=process.argv[2];
if(cmd==='init-key'){
  const file=process.env.GUARD_PRIVACY_KEY_FILE;
  if(!file)throw Error('GUARD_PRIVACY_KEY_FILE is required');
  fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o700});
  if(!fs.existsSync(file))fs.writeFileSync(file,crypto.randomBytes(32),{flag:'wx',mode:0o600});
  fs.chmodSync(file,0o600);console.log('Privacy key present; key bytes not displayed');
}else{
  const store=require('./secure-storage');
  if(cmd==='migrate')console.log(JSON.stringify(store.migrate()));
  else if(cmd==='verify')console.log(JSON.stringify(store.verify()));
  else if(cmd==='prune')console.log(JSON.stringify(store.prune()));
  else if(cmd==='erase')console.log(JSON.stringify(store.eraseSubject(process.argv[3])));
  else throw Error('Use init-key, migrate, verify, prune, or erase <verified-user-id>');
}
