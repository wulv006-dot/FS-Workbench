"""Read a detail page already opened by the existing guarded Order reader.

No browser connection, navigation, credential access or source-wide crawler.
The existing reader owns actual-link validation and the collector lock.
"""
import re

DETAIL = re.compile(r'^/order/admin_order/look/id/[0-9]{1,12}\.html$')
DETAIL_DOM = r'''() => {
  const table=[...document.querySelectorAll('table')].find(t=>
    [...t.querySelectorAll('th')].map(x=>x.textContent.trim()).join('|')==='日志ID|生成时间|操作人|订单状态|内容');
  const logRows=table?[...table.querySelectorAll('tr')].slice(1):[];
  const itemRows=[...document.querySelectorAll('tr.jq-each-cg[data-gid][data-aid][data-cid]')];
  return {origin:location.origin,path:location.pathname,
    login:!!document.querySelector('input[type=password]'),found:!!table,
    item_count:itemRows.length,event_count:logRows.length,
    items:itemRows.slice(0,20).map(e=>Object.fromEntries(
      ['gid','aid','cid','pid','qty','used','unit','currency'].map(k=>[k,e.getAttribute('data-'+k)]))),
    events:logRows.slice(0,100).map(tr=>{const c=[...tr.querySelectorAll('td')];
      return c.length===5?{id:c[0].textContent.trim(),time:c[1].textContent.trim(),status:c[3].textContent.trim()}:null;}).filter(Boolean)};
}'''


def read_open_detail(page, expected_path):
    if not isinstance(expected_path,str) or not DETAIL.fullmatch(expected_path):
        raise ValueError('detail_path_contract')
    value=page.evaluate(DETAIL_DOM)
    if value.get('origin')!='https://order.p2pah.cn' or value.get('path')!=expected_path or value.get('login') or not value.get('found'):
        raise ValueError('detail_scope_contract')
    return {k:value[k] for k in ('items','events','item_count','event_count')}
