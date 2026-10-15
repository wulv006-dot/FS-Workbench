
const menuCacheSlot='fs-menu-access-v1',menuEpochSlot='fs-menu-access-epoch';
let menuIdentityKey=null;
function clearMenuCache(){menuIdentityKey=null;try{sessionStorage.removeItem(menuCacheSlot);}catch{}}
function rememberMenuIdentity(user){
 if(!user?.name){clearMenuCache();return;}
 try{
  const key=JSON.stringify([user.name,user.role||'', [...user.groups].sort(),localStorage.getItem(menuEpochSlot)]);
  const old=JSON.parse(sessionStorage.getItem(menuCacheSlot)||'null');
  if(old?.key!==key)sessionStorage.setItem(menuCacheSlot,JSON.stringify({key,paths:{}}));
  menuIdentityKey=key;
 }catch{clearMenuCache();}
}
async function menuAccess(path,type,probe){
 const key=menuIdentityKey,slot=JSON.stringify([path,type]);
 try{const cache=JSON.parse(sessionStorage.getItem(menuCacheSlot)||'null');if(key&&cache?.key===key&&cache.paths?.[slot]===true)return true;}catch{}
 const available=await probe();
 try{const cache=JSON.parse(sessionStorage.getItem(menuCacheSlot)||'null');if(available&&key&&menuIdentityKey===key&&cache?.key===key){cache.paths[slot]=true;sessionStorage.setItem(menuCacheSlot,JSON.stringify(cache));}}catch{}
 return available;
}
addEventListener('storage',event=>{if(event.key===menuEpochSlot||event.key===null)clearMenuCache();});
