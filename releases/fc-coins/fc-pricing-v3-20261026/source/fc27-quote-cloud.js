// Retired page adapter: current pricing runs only through the V3 coordinator.
(() => {
  'use strict';
  const notice=document.createElement('p');notice.className='panel';
  const link=document.createElement('a');link.href='/dashboard/fc27-coins.html';
  link.textContent='旧改价页面已退役，打开当前 FC27 自动定价台';notice.append(link);
  document.body.prepend(notice);
})();
