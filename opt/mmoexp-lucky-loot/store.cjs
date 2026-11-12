'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
class Store {
 constructor(file,keyFile){
  this.file=file;this.key=fs.readFileSync(keyFile);if(this.key.length!==32)throw Error('Invalid data key');
  fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o700});
  this.data=fs.existsSync(file)?this.read():{v:1,campaigns:{},settings:{},audit:[]};
 }
 read(){const b=fs.readFileSync(this.file);if(b.subarray(0,4).toString()!=='LL01')throw Error('Encrypted state required');
  const d=crypto.createDecipheriv('aes-256-gcm',this.key,b.subarray(4,16));d.setAuthTag(b.subarray(16,32));
  return JSON.parse(Buffer.concat([d.update(b.subarray(32)),d.final()]).toString('utf8'));}
 save(next){const iv=crypto.randomBytes(12),c=crypto.createCipheriv('aes-256-gcm',this.key,iv);
  const cipher=Buffer.concat([c.update(JSON.stringify(next),'utf8'),c.final()]);
  const temp=this.file+'.tmp';let fd;
  try{fd=fs.openSync(temp,'w',0o600);fs.writeFileSync(fd,Buffer.concat([Buffer.from('LL01'),iv,c.getAuthTag(),cipher]));fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(temp,this.file);this.data=next;}
  finally{if(fd!==undefined)fs.closeSync(fd);}
 }
 update(fn){const next=structuredClone(this.data);const result=fn(next);this.save(next);return result;}
 audit(action,id){this.update(s=>{s.audit.push({at:Date.now(),action,id});s.audit=s.audit.filter(x=>x.at>Date.now()-7*86400000);});}
}
module.exports={Store};
