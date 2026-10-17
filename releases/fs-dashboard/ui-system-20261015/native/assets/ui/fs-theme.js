/* One resolver for native, legacy and Shadow DOM consumers. No business requests. */
(function(){
 'use strict';
 if(window.FSTheme)return;
 const key='fs-navigation-theme',media=matchMedia('(prefers-color-scheme: dark)');
 const valid=v=>['light','dark','system'].includes(v);
 let preference='light';
 try{const saved=localStorage.getItem(key);if(valid(saved))preference=saved;}catch{}
 const requested=new URL(location.href).searchParams.get('theme');if(valid(requested))preference=requested;
 function apply(value,persist=false){
  if(!valid(value))return;preference=value;
  const resolved=value==='system'?(media.matches?'dark':'light'):value;
  const html=document.documentElement;html.dataset.theme=resolved;html.dataset.fsTheme=resolved;
  document.querySelectorAll('.native-content').forEach(host=>{host.dataset.theme=resolved;host.dataset.fsTheme=resolved;});
  document.querySelectorAll('select[data-fs-theme-control],select#theme').forEach(s=>s.value=value);
  if(persist)try{localStorage.setItem(key,value);}catch{}
  document.dispatchEvent(new CustomEvent('fs-theme-change',{detail:{preference:value,resolved}}));
 }
 window.FSTheme=Object.freeze({set:(v)=>apply(v,true),get:()=>preference,resolve:()=>document.documentElement.dataset.fsTheme});
 media.addEventListener('change',()=>{if(preference==='system')apply(preference);});
 addEventListener('storage',e=>{if(e.key===key)apply(valid(e.newValue)?e.newValue:'light');});
 apply(preference);
 new MutationObserver(()=>{const value=document.documentElement.dataset.theme;if(['light','dark'].includes(value)&&value!==document.documentElement.dataset.fsTheme)apply(value,true);}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
})();
