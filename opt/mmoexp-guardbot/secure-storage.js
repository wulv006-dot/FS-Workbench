'use strict';
// Explicit adapter for this bot's JSON documents and JSONL records. Never patches Node's global fs.
const raw = require('fs');
const path = require('path');
const crypto = require('crypto');
const MAGIC = 'MMOEXPENC1\n';
const AAD = Buffer.from('MMOEXP_BOT:at-rest:v1');
const DAY = 86400000;
function createStorage({root = __dirname, keyFile = process.env.GUARD_PRIVACY_KEY_FILE,
  enforce = process.env.GUARD_PRIVACY_ENFORCE === '1', now = () => Date.now()} = {}) {
  root = path.resolve(root);
  let key;
  function getKey() {
    if (!key) {
      if (!keyFile) throw Error('Privacy encryption key is not configured');
      const stat = raw.statSync(keyFile);
      if (process.platform !== 'win32' && (stat.mode & 0o077)) throw Error('Privacy key permissions must be 0600');
      key = raw.readFileSync(keyFile);
      if (key.length !== 32) throw Error('Privacy key must contain exactly 32 bytes');
    }
    return key;
  }
  function sensitive(file) {
    if (typeof file !== 'string' && !Buffer.isBuffer(file)) return false;
    const full = path.resolve(String(file));
    const rel = path.relative(root, full);
    if (rel.startsWith('..' + path.sep) || path.isAbsolute(rel)) return false;
    if (rel.split(path.sep).some(p => ['node_modules', '.git'].includes(p))) return false;
    const name = path.basename(full);
    return /\.json(?:l)?(?:$|[.\-])/i.test(name) && !['package.json', 'package-lock.json'].includes(name);
  }
  function decode(data, allowPlain = false) {
    const text = Buffer.isBuffer(data) ? data.toString('utf8') : String(data);
    if (!text.startsWith(MAGIC)) {
      if (enforce && !allowPlain) throw Error('Unencrypted API data refused');
      return Buffer.from(text);
    }
    const box = JSON.parse(text.slice(MAGIC.length));
    if (box.v !== 1) throw Error('Unsupported encrypted data version');
    const nonce = Buffer.from(box.iv, 'base64'), tag = Buffer.from(box.tag, 'base64');
    if (nonce.length !== 12 || tag.length !== 16) throw Error('Invalid encrypted data envelope');
    const decipher = crypto.createDecipheriv('aes-256-gcm', getKey(), nonce);
    decipher.setAAD(AAD); decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(Buffer.from(box.data, 'base64')), decipher.final()]);
  }
  function encode(data) {
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', getKey(), iv);
    cipher.setAAD(AAD);
    const encrypted = Buffer.concat([cipher.update(Buffer.isBuffer(data) ? data : Buffer.from(String(data))), cipher.final()]);
    return MAGIC + JSON.stringify({v:1, iv:iv.toString('base64'), tag:cipher.getAuthTag().toString('base64'), data:encrypted.toString('base64')}) + '\n';
  }
  function atomic(file, data) {
    const temp = file + '.privacy-tmp-' + crypto.randomBytes(8).toString('hex');
    let fd;
    try {
      fd = raw.openSync(temp, 'wx', 0o600);
      raw.writeFileSync(fd, data); raw.fsyncSync(fd); raw.closeSync(fd); fd = undefined;
      raw.renameSync(temp, file); raw.chmodSync(file, 0o600);
      if(process.platform!=='win32') { const dirfd=raw.openSync(path.dirname(file),'r');try{raw.fsyncSync(dirfd);}finally{raw.closeSync(dirfd);} }
    } finally {
      if (fd !== undefined) raw.closeSync(fd);
      if (raw.existsSync(temp)) raw.unlinkSync(temp);
    }
  }
  function readFileSync(file, options) {
    if (!sensitive(file)) return raw.readFileSync(file, options);
    const data = decode(raw.readFileSync(file));
    const encoding = typeof options === 'string' ? options : options?.encoding;
    return encoding ? data.toString(encoding) : data;
  }
  function writeFileSync(file, data, options) {
    if (!sensitive(file)) return raw.writeFileSync(file, data, options);
    atomic(String(file), encode(data));
  }
  function appendFileSync(file, data, options) {
    if (!sensitive(file)) return raw.appendFileSync(file, data, options);
    const previous = raw.existsSync(file) ? readFileSync(file) : Buffer.alloc(0);
    const next = Buffer.concat([previous, Buffer.isBuffer(data) ? data : Buffer.from(String(data))]);
    writeFileSync(file, next);
  }
  function paths() {
    const found=[];
    function walk(dir) {
      for (const entry of raw.readdirSync(dir, {withFileTypes:true})) {
        if (entry.isSymbolicLink() || ['node_modules','.git'].includes(entry.name)) continue;
        const file=path.join(dir,entry.name);
        if(entry.isDirectory()) walk(file); else if(entry.isFile() && sensitive(file)) found.push(file);
      }
    }
    walk(root); return found;
  }
  function migrate() {
    getKey(); let changed=0;
    for(const file of paths()) {
      const bytes=raw.readFileSync(file);
      if(bytes.toString('utf8').startsWith(MAGIC)) { decode(bytes); raw.chmodSync(file,0o600); continue; }
      const stat=raw.statSync(file);
      atomic(file,encode(bytes)); raw.utimesSync(file,stat.atime,stat.mtime); changed++;
    }
    return {encryptedFiles:paths().length,migratedFiles:changed};
  }
  function subjectRecord(value,id) {
    return value && typeof value==='object' && !Array.isArray(value) &&
      ([value.userId,value.user_id,value.id,value.author?.id,value.user?.id].includes(id) ||
       (typeof value.key==='string' && value.key.startsWith(id+':')));
  }
  function eraseValue(value,id) {
    if(subjectRecord(value,id)) return undefined;
    if(Array.isArray(value)) return value.map(v=>eraseValue(v,id)).filter(v=>v!==undefined);
    if(value && typeof value==='object') {
      const out={};
      for(const [k,v] of Object.entries(value)) {
        if(k===id) continue;
        const next=eraseValue(v,id); if(next!==undefined) out[k]=next;
      }
      return out;
    }
    if(typeof value==='string') {
      if(value===id) return undefined;
      return value.split(id).join('[deleted]');
    }
    return value;
  }
  function eraseSubject(id) {
    if(!/^\d{15,25}$/.test(id)) throw Error('Invalid Discord user ID');
    // Validate every file first. Never acknowledge success after only a partial parse.
    const plan=[];
    for(const file of paths()) {
      const before=readFileSync(file,'utf8');
      if(!before.includes(id)) continue;
      let after;
      if(/\.jsonl$/.test(file)) {
        // A diagnostic string can contain a name alongside the ID: remove the whole associated row.
        after=before.split('\n').filter(Boolean).filter(line=>!line.includes(id)).map(l=>JSON.stringify(JSON.parse(l))).join('\n');
        if(after)after+='\n';
      } else {
        const erased=eraseValue(JSON.parse(before),id);
        after=JSON.stringify(erased===undefined ? {_privacyErased:true} : erased,null,2)+'\n';
      }
      if(after.includes(id)) throw Error('Deletion verification failed');
      plan.push({file,after});
    }
    for(const item of plan) writeFileSync(item.file,item.after);
    for(const file of paths()) if(readFileSync(file,'utf8').includes(id)) throw Error('Deletion verification failed');
    return {updatedFiles:plan.length,verified:true};
  }
  function prune() {
    let removedRecords=0;
    for(const file of paths()) {
      const rel=path.relative(root,file);
      if(!/\.jsonl$/.test(file) && (/^(backups|stage[^\\/]*)[\\/]/.test(rel)||/\.json[.\-]/.test(path.basename(file)))) {
        if(raw.statSync(file).mtimeMs<=now()-30*DAY) {
          writeFileSync(file,JSON.stringify({_privacyExpired:true})+'\n');
        }
        continue;
      }
      if(!/\.jsonl$/.test(file))continue;
      const before=readFileSync(file,'utf8').split('\n').filter(Boolean).map(JSON.parse);
      const days=/^(runtime|legacy-system)-events\.jsonl$/.test(path.basename(file)) ? 7 : 30;
      const after=before.filter(row=>{
        const stamp=row.__REALTIME_TIMESTAMP ? Number(row.__REALTIME_TIMESTAMP)/1000 : typeof row.at==='number' ? row.at : Date.parse(row.ts || row.at || '');
        return Number.isFinite(stamp) && stamp>now()-days*DAY;
      });
      removedRecords+=before.length-after.length;
      if(after.length!==before.length)writeFileSync(file,after.map(r=>JSON.stringify(r)).join('\n')+(after.length?'\n':''));
    }
    return {removedRecords};
  }
  function verify() {
    let count=0;
    for(const file of paths()) {
      const bytes=raw.readFileSync(file);
      if(!bytes.toString('utf8').startsWith(MAGIC))throw Error('Unencrypted data file detected');
      decode(bytes); count++;
    }
    return {encryptedFiles:count,cipher:'AES-256-GCM',verified:true};
  }
  return {...raw,readFileSync,writeFileSync,appendFileSync,paths,migrate,prune,verify,eraseSubject,
    encode,decode,sensitive,root,keyFile};
}
const instance=createStorage();
module.exports=Object.assign(instance,{createStorage,MAGIC,DAY});
