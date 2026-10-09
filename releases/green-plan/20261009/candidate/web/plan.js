'use strict';
document.getElementById('print').addEventListener('click',()=>window.print());
document.querySelectorAll('[data-week]').forEach(button=>{const link=document.createElement('a');link.href='index.html';link.textContent=button.textContent+' · 查看共享进展';button.replaceWith(link)});
