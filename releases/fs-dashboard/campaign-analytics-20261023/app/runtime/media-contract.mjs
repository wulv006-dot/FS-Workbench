export const mediaLimits=Object.freeze({fileBytes:5*1024*1024,totalBytes:50*1024*1024,dimension:8192,pixels:32000000});
export const mediaId=value=>typeof value==='string'&&/^[a-f0-9]{64}\.(?:png|jpg|webp)$/.test(value);
const error=code=>{throw Object.assign(new Error(code),{code,status:400});};
const record=value=>value&&typeof value==='object'&&!Array.isArray(value);
export function projectMedia(media){
 if(!record(media)||Object.keys(media).some(k=>!['hero_desktop','hero_mobile','share','cards'].includes(k)))error('INVALID_MEDIA_SLOT');
 const reference=ref=>{
  if(!record(ref)||Object.keys(ref).some(k=>!['asset_id','alt','public_english_confirmed'].includes(k))||!mediaId(ref.asset_id)||typeof ref.alt!=='string'||ref.alt.length>200||/[<>\u0000-\u001f]/u.test(ref.alt)||/\p{Script=Han}/u.test(ref.alt)||ref.public_english_confirmed!==true)error('PUBLIC_MEDIA_REVIEW_REQUIRED');
  return {asset_id:ref.asset_id,alt:ref.alt,public_english_confirmed:true};
 };
 const result={};for(const slot of ['hero_desktop','hero_mobile','share'])if(Object.hasOwn(media,slot))result[slot]=reference(media[slot]);
 if(Object.hasOwn(media,'cards')){if(!record(media.cards)||Object.keys(media.cards).length>500)error('INVALID_MEDIA_SLOT');result.cards=Object.fromEntries(Object.entries(media.cards).map(([key,ref])=>{if(!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(key))error('INVALID_MEDIA_SLOT');return [key,reference(ref)];}));}
 return result;
}
export function mediaReferences(draft){const refs=[];for(const page of draft.pages||[]){if(!Object.hasOwn(page,'media'))continue;const media=projectMedia(page.media);for(const slot of ['hero_desktop','hero_mobile','share'])if(media[slot])refs.push(media[slot].asset_id);for(const ref of Object.values(media.cards||{}))refs.push(ref.asset_id);}return [...new Set(refs)];}
export function pageMedia(pages,prefix){
 if(typeof prefix!=='string'||!/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(prefix))error('INVALID_MEDIA_PREFIX');
 const ref=value=>({...value,url:prefix+'media/'+value.asset_id});
 return Object.fromEntries(pages.filter(p=>Object.hasOwn(p,'media')).map(p=>{const m=projectMedia(p.media),out={};for(const slot of ['hero_desktop','hero_mobile','share'])if(m[slot])out[slot]=ref(m[slot]);if(m.cards)out.cards=Object.fromEntries(Object.entries(m.cards).map(([k,v])=>[k,ref(v)]));return [p.page_id,out];}));
}
export function projectMediaManifest(input){
 if(!record(input)||Object.keys(input).length>1500)error('INVALID_MEDIA_MANIFEST');
 return Object.fromEntries(Object.entries(input).map(([key,m])=>{
  if(!mediaId(key)||!record(m)||Object.keys(m).some(k=>!['asset_id','sha256','mime','bytes','width','height'].includes(k))||m.asset_id!==key||m.sha256!==key.split('.')[0]||({'image/png':'png','image/jpeg':'jpg','image/webp':'webp'})[m.mime]!==key.split('.')[1]
   ||!Number.isInteger(m.bytes)||m.bytes<1||m.bytes>mediaLimits.fileBytes||![m.width,m.height].every(n=>Number.isInteger(n)&&n>0&&n<=mediaLimits.dimension)||m.width*m.height>mediaLimits.pixels)error('INVALID_MEDIA_MANIFEST');
  return [key,{asset_id:key,sha256:m.sha256,mime:m.mime,bytes:m.bytes,width:m.width,height:m.height}];
 }));
}
