"""Pure, hash-pinned production-source adaptation. No CLI or filesystem writes."""
import ast
import hashlib

RANGE_SHA256 = 'ac0c9ff2465f6824879f69d00f07bf24e909f5fb9ee76c00e79cb9c510d67b10'
PAGE_SHA256 = '7827b3f3b04da8bfd3b608b808a3ddf971fa81e416684c67fb2ad9ac3390615a'

RANGE_ANCHOR = """    live_query=private_live_body(raw)
    def run_scoped(operation,timeout):
     def checked():
      next_status,next_actor=verify_live_session(cookie)
      if next_status!=200 or next_actor!=actor:raise PermissionError('session_changed')
      return operation()
     return LIVE_ADMIN.run(checked,timeout)
    status,data=get_live_orders(live_query,actor,run_source=run_scoped);self.reply(status,data)
"""
RANGE_REPLACEMENT = """    def run_scoped(operation,timeout):
     def checked():
      next_status,next_actor=verify_live_session(cookie)
      if next_status!=200 or next_actor!=actor:raise PermissionError('session_changed')
      return operation()
     return LIVE_ADMIN.run(checked,timeout)
    body=json.loads(raw.decode('utf8'))
    if isinstance(body,dict) and body.get('kind') in ('order_email_export_page','order_email_export_options'):
     from admin_order_email_export import parse_page_body,page_get
     from admin_email_export_source import options_get
     def unique(pairs):
      value={}
      for key,item in pairs:
       if key in value:raise ValueError('duplicate_field')
       value[key]=item
      return value
     body=json.loads(raw.decode('utf8'),object_pairs_hook=unique)
     kind=body.pop('kind')
     if kind=='order_email_export_options':
      status,data=options_get(body,actor,run_source=run_scoped);self.reply(status,data)
     else:
      export_request=parse_page_body(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf8'))
      status,data=page_get(export_request,actor,run_source=run_scoped);self.reply(status,data)
    else:
     live_query=private_live_body(raw)
     status,data=get_live_orders(live_query,actor,run_source=run_scoped);self.reply(status,data)
"""
PAGE_ANCHOR = """    widget = mountDataWorkspace(root, {
      fetch: read, writeFetch: write, start: yesterday, end: yesterday,
"""
PAGE_REPLACEMENT = """    const orderEmailFetch = (url, options = {}) => {
      const target = new URL(url, location.href);
      if (target.href !== new URL('/dashboard/users/live-orders.json', location.origin).href || options.method !== 'POST') throw Error('order_email_endpoint_only');
      const body = JSON.parse(options.body);
      if (!body || typeof body !== 'object' || Array.isArray(body) || (Object.hasOwn(body, 'kind') && body.kind !== 'order_email_export_options')) throw Error('invalid_export_request');
      return fetch(url, {...options, body: JSON.stringify({...body, kind: body.kind || 'order_email_export_page'}),
        credentials: 'same-origin', redirect: 'error', cache: 'no-store', signal: scopedSignal(options.signal)}).then(response => {
        if (response.status === 401 || response.status === 403) deny(response.status);
        return response;
      });
    };
    widget = mountDataWorkspace(root, {
      orderEmailExport: {endpoint: '/dashboard/users/live-orders.json', paged: true, fetch: orderEmailFetch},
      fetch: read, writeFetch: write, start: yesterday, end: yesterday,
"""


def _replace(source, expected_hash, anchor, replacement):
    if not isinstance(source, bytes) or hashlib.sha256(source).hexdigest() != expected_hash:
        raise ValueError('production_source_hash_mismatch')
    text = source.decode('utf8')
    if text.count(anchor) != 1:
        raise ValueError('production_anchor_not_unique')
    return text.replace(anchor, replacement, 1).encode('utf8')


def prepare(range_source, page_source):
    """Return candidate bytes keyed by basename; caller owns any local staging."""
    backend = _replace(range_source, RANGE_SHA256, RANGE_ANCHOR, RANGE_REPLACEMENT)
    page = _replace(page_source, PAGE_SHA256, PAGE_ANCHOR, PAGE_REPLACEMENT)
    ast.parse(backend)
    return {'range_api.py': backend, 'page.js': page}
