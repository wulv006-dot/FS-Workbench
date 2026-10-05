(function(){'use strict';const key='fs-business-theme',media=matchMedia('(prefers-color-scheme: dark)');let mode;
function apply(){try{mode=localStorage.getItem(key);}catch{}const dark=mode==='dark'||(!mode&&media.matches);document.documentElement.dataset.theme=dark?'dark':'light';const b=document.getElementById('business-theme-toggle');if(b){b.textContent=dark?'浅色主题':'深色主题';b.setAttribute('aria-label',b.textContent);}}
apply();addEventListener('storage',e=>{if(e.key===key)apply();});media.addEventListener('change',apply);
addEventListener('DOMContentLoaded',()=>{const b=document.createElement('button');b.id='business-theme-toggle';b.type='button';b.onclick=()=>{try{localStorage.setItem(key,document.documentElement.dataset.theme==='dark'?'light':'dark');}catch{}apply();};document.body.append(b);apply();});
})();
