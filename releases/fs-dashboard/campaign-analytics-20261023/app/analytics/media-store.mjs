import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {atomic} from './store.mjs';
import {canonical,digest,fail} from '../runtime/snapshot.mjs';
import {mediaLimits,mediaId,mediaReferences} from '../runtime/media-contract.mjs';
export {mediaLimits,mediaId,mediaReferences} from '../runtime/media-contract.mjs';

const types={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'};
function durableDirectories(roots){
 const parents=new Set();
 for(const root of roots){
  if(fs.existsSync(root)&&fs.lstatSync(root).isSymbolicLink())fail('INVALID_MEDIA_PATH');
  fs.mkdirSync(root,{recursive:true,mode:0o700});
  // Sync the directory entries as well as the files. Include the ancestor chain
  // on replay after an interrupted mkdir/sync, when a prior call's new entries
  // can already exist in memory without having reached durable storage.
  for(let current=path.resolve(root);;current=path.dirname(current)){parents.add(current);if(path.dirname(current)===current)break;}
 }
 if(process.platform!=='win32')for(const parent of [...parents].sort((a,b)=>b.length-a.length)){
  const fd=fs.openSync(parent,'r');try{fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
 }
}
function binary(file,bytes,mode){const temp=file+'.'+randomUUID()+'.tmp',fd=fs.openSync(temp,'wx',mode);try{fs.writeFileSync(fd,bytes);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}try{fs.renameSync(temp,file);}finally{if(fs.existsSync(temp))fs.unlinkSync(temp);}if(process.platform!=='win32'){const root=fs.openSync(path.dirname(file),'r');try{fs.fsyncSync(root);}finally{fs.closeSync(root);}}}
function dimensions(width,height){if(!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width>mediaLimits.dimension||height>mediaLimits.dimension||width*height>mediaLimits.pixels)fail('IMAGE_DIMENSIONS_INVALID');return {width,height};}
const crcTable=Array.from({length:256},(_,n)=>{for(let i=0;i<8;i++)n=n&1?0xedb88320^(n>>>1):n>>>1;return n>>>0;});
const crc32=bytes=>{let c=0xffffffff;for(const b of bytes)c=crcTable[(c^b)&255]^(c>>>8);return (c^0xffffffff)>>>0;};
export function inspectImage(bytes,mime){
 if(!Buffer.isBuffer(bytes)||!bytes.length||bytes.length>mediaLimits.fileBytes)fail('IMAGE_SIZE_INVALID');
 if(!types[mime])fail('IMAGE_TYPE_INVALID');let size;
 if(mime==='image/png'){
  if(!bytes.subarray(0,8).equals(Buffer.from('89504e470d0a1a0a','hex')))fail('IMAGE_STRUCTURE_INVALID');
  let offset=8,ended=false,data=false,count=0;
  while(offset+12<=bytes.length){
   if(++count>10000)fail('IMAGE_STRUCTURE_INVALID');const length=bytes.readUInt32BE(offset),end=offset+12+length;
   if(end>bytes.length)fail('IMAGE_STRUCTURE_INVALID');const kind=bytes.toString('ascii',offset+4,offset+8);
   if(!/^[A-Za-z]{4}$/.test(kind)||crc32(bytes.subarray(offset+4,end-4))!==bytes.readUInt32BE(end-4))fail('IMAGE_STRUCTURE_INVALID');
   if(count===1){if(kind!=='IHDR'||length!==13||![0,2,3,4,6].includes(bytes[offset+17])||![1,2,4,8,16].includes(bytes[offset+16])||bytes[offset+18]!==0||bytes[offset+19]!==0||bytes[offset+20]>1)fail('IMAGE_STRUCTURE_INVALID');size=dimensions(bytes.readUInt32BE(offset+8),bytes.readUInt32BE(offset+12));}
   else if(kind==='IHDR')fail('IMAGE_STRUCTURE_INVALID');
   if(kind==='IDAT')data=true;if(kind==='IEND'){if(length!==0||end!==bytes.length)fail('IMAGE_STRUCTURE_INVALID');ended=true;break;}offset=end;
  }
  if(!ended||!data||!size)fail('IMAGE_STRUCTURE_INVALID');
 }else if(mime==='image/jpeg'){
  if(bytes.length<12||bytes[0]!==255||bytes[1]!==216||bytes.at(-2)!==255||bytes.at(-1)!==217)fail('IMAGE_STRUCTURE_INVALID');
  let offset=2,scan=false;
  while(offset+4<=bytes.length){
   if(bytes[offset++]!==255)fail('IMAGE_STRUCTURE_INVALID');while(bytes[offset]===255)offset++;const marker=bytes[offset++];
   if(marker===0||marker===216||marker===217)fail('IMAGE_STRUCTURE_INVALID');const length=bytes.readUInt16BE(offset);
   if(length<2||offset+length>bytes.length-2)fail('IMAGE_STRUCTURE_INVALID');
   if([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(marker)){if(length<8)fail('IMAGE_STRUCTURE_INVALID');size=dimensions(bytes.readUInt16BE(offset+5),bytes.readUInt16BE(offset+3));}
   if(marker===218){scan=true;break;}offset+=length;
  }
  if(!size||!scan)fail('IMAGE_STRUCTURE_INVALID');
 }else{
  if(bytes.length<20||bytes.toString('ascii',0,4)!=='RIFF'||bytes.toString('ascii',8,12)!=='WEBP'||bytes.readUInt32LE(4)+8!==bytes.length)fail('IMAGE_STRUCTURE_INVALID');
  let offset=12,count=0,image=false,canvas;
  while(offset+8<=bytes.length){
   if(++count>10000)fail('IMAGE_STRUCTURE_INVALID');const kind=bytes.toString('ascii',offset,offset+4),length=bytes.readUInt32LE(offset+4),start=offset+8,end=start+length;
   if(end+(length%2)>bytes.length||['ANIM','ANMF'].includes(kind))fail('IMAGE_STRUCTURE_INVALID');
   if(kind==='VP8X'){if(length!==10)fail('IMAGE_STRUCTURE_INVALID');canvas=dimensions(bytes.readUIntLE(start+4,3)+1,bytes.readUIntLE(start+7,3)+1);}
   if(kind==='VP8 '){if(image||length<10||!bytes.subarray(start+3,start+6).equals(Buffer.from([157,1,42])))fail('IMAGE_STRUCTURE_INVALID');size=dimensions(bytes.readUInt16LE(start+6)&16383,bytes.readUInt16LE(start+8)&16383);image=true;}
   if(kind==='VP8L'){if(image||length<5||bytes[start]!==47)fail('IMAGE_STRUCTURE_INVALID');const bits=bytes.readUInt32LE(start+1);size=dimensions((bits&16383)+1,((bits>>>14)&16383)+1);image=true;}
   offset=end+(length%2);
  }
  if(!image||offset!==bytes.length||canvas&&(canvas.width!==size.width||canvas.height!==size.height))fail('IMAGE_STRUCTURE_INVALID');
 }
 return {sha256:digest(bytes),mime,bytes:bytes.length,...size};
}
export function makeMediaStore({dir,publicDir,operationsDir}){
 const blobs=path.join(dir,'blobs'),meta=path.join(dir,'metadata');
 function safeFile(root,name){if(!mediaId(name))fail('INVALID_MEDIA_ID');if(fs.existsSync(root)&&fs.lstatSync(root).isSymbolicLink())fail('INVALID_MEDIA_PATH');const file=path.join(root,name);if(fs.existsSync(file)&&(!fs.lstatSync(file).isFile()||fs.lstatSync(file).isSymbolicLink()))fail('INVALID_MEDIA_PATH');return file;}
 function metadata(assetId){const file=safeFile(meta,assetId);if(!fs.existsSync(file))fail('MEDIA_NOT_FOUND',404);const value=JSON.parse(fs.readFileSync(file,'utf8'));if(value.asset_id!==assetId||value.sha256!==assetId.split('.')[0]||types[value.mime]!==assetId.split('.')[1])fail('MEDIA_UNCONFIRMED');return value;}
 function read(assetId,published=false){const info=metadata(assetId),file=safeFile(published?path.join(publicDir,'assets'):blobs,assetId);if(!fs.existsSync(file))fail('MEDIA_NOT_FOUND',404);const bytes=fs.readFileSync(file);if(bytes.length!==info.bytes||digest(bytes)!==info.sha256)fail('MEDIA_UNCONFIRMED');return {info,bytes};}
 function confirm(assetId,expected){try{if(canonical(read(assetId).info)!==canonical(expected))fail('MEDIA_UNCONFIRMED');}catch{fail('MEDIA_UNCONFIRMED');}}
 return {
  metadata,read,
  stage(operationId,bytes,mime,user){
   if(!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(operationId||''))fail('INVALID_OPERATION_ID');
   const info=inspectImage(bytes,mime),asset_id=info.sha256+'.'+types[mime],hash=digest(canonical({kind:'media-upload',mime,sha256:info.sha256})),receipt=path.join(operationsDir,operationId+'.json');
   if(fs.existsSync(operationsDir)&&fs.lstatSync(operationsDir).isSymbolicLink()||fs.existsSync(receipt)&&(!fs.lstatSync(receipt).isFile()||fs.lstatSync(receipt).isSymbolicLink()))fail('INVALID_MEDIA_PATH');
   const value={asset_id,...info},result={asset:value,preview_url:'api/center/assets/'+asset_id,english_review:'operator_preview_required'};
   if(fs.existsSync(receipt)){
    let prior;try{prior=JSON.parse(fs.readFileSync(receipt));}catch{fail('MEDIA_UNCONFIRMED');}
    if(prior.hash!==hash)fail('REQUEST_CONFLICT',409);
    if(prior.kind!=='media-upload'||canonical(prior.result)!==canonical(result))fail('MEDIA_UNCONFIRMED');
    confirm(asset_id,value);return prior.result;
   }
   durableDirectories([dir,blobs,meta,operationsDir]);
   const target=safeFile(blobs,asset_id);let total=0;for(const name of fs.readdirSync(blobs)){if(/^[a-f0-9]{64}\.(png|jpg|webp)\.[a-f0-9-]{36}\.tmp$/.test(name))continue;if(!mediaId(name))fail('INVALID_MEDIA_PATH');total+=fs.statSync(safeFile(blobs,name)).size;}
   if(!fs.existsSync(target)&&total+bytes.length>mediaLimits.totalBytes)fail('MEDIA_STORAGE_LIMIT',413);
   if(!fs.existsSync(target))binary(target,bytes,0o600);
   else if(digest(fs.readFileSync(target))!==info.sha256)fail('MEDIA_UNCONFIRMED');
   if(!fs.existsSync(safeFile(meta,asset_id)))atomic(safeFile(meta,asset_id),value);
   confirm(asset_id,value);
   atomic(receipt,{hash,result,kind:'media-upload',user,recorded_at:new Date().toISOString()});return result;
  },
  manifest(draft){return Object.fromEntries(mediaReferences(draft).map(key=>[key,metadata(key)]));},
  publish(manifest){for(const assetId of Object.keys(manifest)){
   const {info,bytes}=read(assetId);if(canonical(info)!==canonical(manifest[assetId]))fail('MEDIA_UNCONFIRMED');
   const root=path.join(publicDir,'assets');if(fs.existsSync(root)&&fs.lstatSync(root).isSymbolicLink())fail('INVALID_MEDIA_PATH');fs.mkdirSync(root,{recursive:true,mode:0o755});fs.chmodSync(root,0o755);
   const target=safeFile(root,assetId);if(!fs.existsSync(target))binary(target,bytes,0o600);else if(digest(fs.readFileSync(target))!==info.sha256)fail('MEDIA_UNCONFIRMED');fs.chmodSync(target,0o644);
  }}
 };
}
