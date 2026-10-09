// Native DOM with source-local globals. One active renderer owns all listeners and requests.
export function lifecycle(host, changed, denied){
 const root=host.attachShadow({mode:'open'}),controller=new AbortController(),events=new EventTarget();
 const timers=new Set(),frames=new Set(),observers=new Set(),urls=new Set(),mediaListeners=[];
 let active=true;
 const guard=fn=>(...args)=>{if(active)return fn(...args);};
 const listen=(target,type,fn,options={})=>target.addEventListener(type,guard(fn),{...(typeof options==='boolean'?{capture:options}:options),signal:controller.signal});
 const addEventListener=(type,fn,options)=>listen(type.startsWith('fs-')?events:window,type,fn,options);
 const setTimeout=(fn,ms,...args)=>{const id=window.setTimeout(()=>{timers.delete(id);if(active)fn(...args);},ms);timers.add(id);return id;};
 const setInterval=(fn,ms,...args)=>{const id=window.setInterval(guard(()=>fn(...args)),ms);timers.add(id);return id;};
 const clear=(id)=>{timers.delete(id);window.clearTimeout(id);window.clearInterval(id);};
 const requestAnimationFrame=fn=>{const id=window.requestAnimationFrame(t=>{frames.delete(id);if(active)fn(t);});frames.add(id);return id;};
 const cancelAnimationFrame=id=>{frames.delete(id);window.cancelAnimationFrame(id);};
 const Observer=Base=>class extends Base{constructor(fn){super(guard(fn));observers.add(this);}};
 const fetch=async(input,options={})=>{
  if(!active)throw new DOMException('Unmounted','AbortError');
  const url=new URL(typeof input==='string'?input:input.url,location.href);
  if(url.origin!==location.origin||(options.method&&options.method!=='GET'&&options.method!=='HEAD'))throw Error('Readonly same-origin only');
  const response=await protectedRead(url,{...options,signal:options.signal?AbortSignal.any([controller.signal,options.signal]):controller.signal},guard(denied));
  if(!active)throw new DOMException('Unmounted','AbortError');
  if(response.status===401||response.status===403){denied(response.status);controller.abort();throw Error('session_denied');}
  return response;
 };
 const matchMedia=query=>{const m=window.matchMedia(query);return new Proxy(m,{get(target,key){if(key==='addEventListener')return(type,fn)=>{const g=guard(fn);target.addEventListener(type,g);mediaListeners.push(()=>target.removeEventListener(type,g));};const v=Reflect.get(target,key,target);return typeof v==='function'?v.bind(target):v;}});};
 const document=new Proxy(window.document,{get(target,key){
  if(key==='documentElement')return host;if(key==='body')return root.querySelector('.native-body');if(key==='head')return root;
  if(key==='getElementById')return id=>root.getElementById(id);
  if(key==='querySelector')return s=>root.querySelector(s);if(key==='querySelectorAll')return s=>root.querySelectorAll(s);
  if(key==='activeElement')return root.activeElement;if(key==='addEventListener')return(type,fn,opt)=>listen(root,type,fn,opt);
  const v=Reflect.get(target,key,target);return typeof v==='function'?v.bind(target):v;
 }});
 const LocalURL=class extends URL{static createObjectURL(blob){const url=URL.createObjectURL(blob);urls.add(url);return url;}static revokeObjectURL(url){urls.delete(url);URL.revokeObjectURL(url);}};
 const locals={document,fetch,URL:LocalURL,setTimeout,setInterval,clearTimeout:clear,clearInterval:clear,requestAnimationFrame,cancelAnimationFrame,MutationObserver:Observer(window.MutationObserver),ResizeObserver:Observer(window.ResizeObserver),addEventListener,matchMedia};
 const localWindow=new Proxy({}, {get(target,key){
  if(key in target)return target[key];if(key in locals)return locals[key];
  if(key==='dispatchEvent')return e=>events.dispatchEvent(e);
  const v=window[key];return typeof v==='function'?v.bind(window):v;
 },set(target,key,value){target[key]=value;return true;}});
 return {...locals,window:localWindow,root,changed,signal:controller.signal,active:()=>active,profit:{},destroy(){
  active=false;controller.abort();for(const id of timers)clear(id);for(const id of frames)cancelAnimationFrame(id);
  for(const o of observers)o.disconnect();for(const off of mediaListeners)off();for(const url of urls)URL.revokeObjectURL(url);host.remove();
 }};
}

// WN-P2-01: classify protected-read failures with the existing native verifier.
// Network/503 failures remain ordinary errors while a valid session can retain stale data.
const permissionError=status=>Object.assign(Error('session_denied'),{status});
const redirected=r=>r.type==='opaqueredirect'||(r.status>=300&&r.status<400)||r.redirected;
async function nativeIdentity(signal){
 const opts={credentials:'same-origin',cache:'no-store',redirect:'manual',signal:signal||AbortSignal.timeout(15000)};
 const v=await window.fetch('/__auth/verify',opts);
 if(v.status===401||v.status===403)throw permissionError(v.status);
 if(redirected(v))throw permissionError(401);
 if(!v.ok)throw Error('native_verify_unavailable');
 const groups=(v.headers.get('X-Auth-Groups')||'').split(',').filter(Boolean);
 if(!groups.includes('dashboard'))throw permissionError(403);
 return {name:v.headers.get('X-Auth-User')||'当前账号',groups,role:v.headers.get('X-Auth-Role')||''};
}
export async function sessionIdentity(signal){return nativeIdentity(signal);}
export async function protectedRead(input,options={},denied=()=>{},expectedType='application/json'){
 const confirm=async original=>{
  try{await nativeIdentity(options.signal);}
  catch(e){if(e.status){denied(e.status);throw e;}throw original;}
  throw original;
 };
 let r;
 try{r=await window.fetch(input,{...options,credentials:'same-origin',cache:'no-store',redirect:'manual'});}
 catch(e){if(e.name==='AbortError')throw e;return confirm(e);}
 if(r.status===401||r.status===403){denied(r.status);throw permissionError(r.status);}
 if(redirected(r))return confirm(Error('protected_read_redirected'));
 const url=new URL(String(input),location.href);
 // Let the exact-range contract handle bounded busy replies, never authentication failures.
 const rangeReply=url.origin===location.origin&&url.pathname==='/dashboard/fs-home/range.json'&&expectedType==='application/json'&&[429,503].includes(r.status);
 if(!r.ok&&!rangeReply)return confirm(Error('protected_read_failed_'+r.status));
 const type=r.headers.get('content-type')||'';
 if(!type.includes(expectedType))return confirm(Error('protected_read_content_type'));
 if(type.includes('text/html')){
  const url=new URL(r.url||String(input),location.href);
  if(url.pathname.startsWith('/__auth/login'))return confirm(Error('protected_login_html'));
  // A login form returned with status 200 is checked, never treated as native data.
  const text=await r.clone().text();
  if(/<form\b[^>]*action=["'](?:[^"']*\/__auth\/login)/i.test(text))return confirm(Error('protected_login_html'));
 }
 return r;
}

// Capability discovery must not turn a path-specific denial into session revocation.
// Access checks control entry activation; the catalogue can retain locked feature descriptions.
export async function moduleAvailable(input,expectedType='text/html'){
 const url=new URL(String(input),location.href);
 if(url.origin!==location.origin)throw Error('Readonly same-origin module probe required');
 const options={method:'HEAD',credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(15000)};
 let response;
 try{response=await window.fetch(url,options);if([404,405,501].includes(response.status))response=await window.fetch(url,{...options,method:'GET'});}
 catch{return false;}
 if(response.status===401||response.status===403||redirected(response)){
  // A valid session can still be denied this individual module. Retain no response
  // nor its response; a verifier outage is also unavailable, never authorization.
  try{await nativeIdentity();}
  catch(error){if(error.status)throw error;return false;}
  return false;
 }
 return response.ok&&(response.headers.get('content-type')||'').includes(expectedType);
}
