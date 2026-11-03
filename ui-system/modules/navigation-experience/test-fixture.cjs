const fs=require('fs'),p=require('path');
const file=p.join(__dirname,'fixture.html');
let html=fs.readFileSync(file,'utf8');
const test=`<button id="race-test">模拟旧导航延迟覆盖</button><output id="race-result"></output><script>
document.getElementById('race-test').onclick=()=>{
 const before=document.querySelector('#hubNav .hn-search');
 for(const key of ['analytics','brain','activities']){
  const g=document.querySelector('[data-key="'+key+'"]'),old=document.createElement('section');
  old.className='hn-group';old.innerHTML='<a class="hn-heading">旧导航</a><a class="hn-tool">重复入口</a>';
  g.querySelector('.hn-row').replaceWith(old);
 }
 setTimeout(()=>{
  const groups=[...document.querySelectorAll('#hubNav .hn-tree > .hn-group')];
  const okay=groups.length===8&&!document.querySelector('.hn-group .hn-group')&&groups.every(g=>g.querySelector('.hn-expander'));
  document.getElementById('race-result').textContent=okay?'PASS：延迟覆盖后8个分组完整，无重复，收纳按钮保留':'FAIL';
 },50);
};</script>`;
html=html.replace('</body>',test+'</body>');fs.writeFileSync(file,html);
