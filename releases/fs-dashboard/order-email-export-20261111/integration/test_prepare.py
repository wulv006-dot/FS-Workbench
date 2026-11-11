"""Offline integration: execute candidate Handler AST and production page with stubs."""
import ast
import datetime
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import prepare

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = ROOT / 'releases/fs-dashboard/tiered-data-access-20261101/source'
sys.path.insert(0, str(SOURCE))
import admin_order_email_export as exporter
from admin_live_dispatch import private_body_params
import os


def candidates():
    return prepare.prepare((HERE/'fixtures/range_api.py').read_bytes(), (HERE/'fixtures/page.js').read_bytes())


class Backend(unittest.TestCase):
    def request(self, body, sessions=None, headers=None):
        tree = ast.parse(candidates()['range_api.py'])
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        method = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == 'do_POST')
        cls = ast.ClassDef(name='Handler', bases=[], keywords=[], body=[method], decorator_list=[])
        calls = []
        sessions = iter(sessions or [(200, 'real-actor')] * 3)
        def private(raw):
            value = private_body_params(raw)
            if 'kind' in value: raise ValueError('unknown_field')
            calls.append(('normal', raw))
            return value
        def get(query, actor, run_source):
            return run_source(lambda: (calls.append(('source', actor)) or (206, {'actor': actor})), 10)
        def page(request, actor, run_source):
            calls.append(('export', request, actor))
            return get(request, actor, run_source)
        ns = dict(urlsplit=urlsplit, re=re, json=json, LIVE_ADMIN=types.SimpleNamespace(run=lambda op, timeout: op()),
                  verify_live_session=lambda cookie: next(sessions), private_live_body=private, get_live_orders=get)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<candidate>', 'exec'), ns)
        obj = ns['Handler']()
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        obj.path = '/users/live-orders'
        obj.headers = {'Content-Type':'application/json', 'Content-Length':str(len(raw)), 'Sec-Fetch-Site':'same-origin', 'Cookie':'synthetic', 'X-Auth-User':'forged'}
        obj.headers.update(headers or {})
        obj.rfile = io.BytesIO(raw)
        obj.connection = types.SimpleNamespace(settimeout=lambda timeout: None)
        replies = []
        obj.reply = lambda *args: replies.append(args)
        # Real parser, stub only the source call; no customers or credentials.
        with patch.object(exporter, 'page_get', page):
            obj.do_POST()
        return replies[-1], calls

    def export_body(self):
        day = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=2)
        return dict(kind='order_email_export_page', site_id='266', game_id='833', start=day.isoformat(), end_exclusive=(day+datetime.timedelta(days=1)).isoformat())

    def test_normal_unchanged_and_actor_not_header(self):
        raw = b'{"site_id":"266","game_id":"833","start":"2026-11-09","end_exclusive":"2026-11-10","customer_email":"synthetic@example.invalid"}'
        reply, calls = self.request(raw)
        self.assertEqual(reply, (206, {'actor':'real-actor'}))
        self.assertIn(('normal', raw), calls)
        self.assertNotIn('export', [c[0] for c in calls])

    def test_export_real_parser_and_scoped_actor(self):
        reply, calls = self.request(self.export_body())
        self.assertEqual(reply[0], 206)
        export = next(c for c in calls if c[0] == 'export')
        self.assertNotIn('kind', export[1])
        self.assertEqual(export[2], 'real-actor')

    def test_revoked_and_changed_actor_never_reads_source(self):
        for session in [(403, None), (200, 'other')]:
            reply, calls = self.request(self.export_body(), [(200, 'real-actor'), session])
            self.assertEqual(reply[0], 503)
            self.assertNotIn('source', [c[0] for c in calls])

    def test_session_denied_before_body(self):
        for code in [401,403,429,503]:
            reply, calls = self.request(b'bad json', [(code,None)])
            self.assertEqual(reply[0], code)
            self.assertEqual(calls, [])

    def test_invalid_export_unknown_fields_duplicate_and_json(self):
        body = self.export_body()
        for raw in [b'bad', b'[]', json.dumps(dict(body, actor='forged')).encode(), json.dumps(dict(body, filters={'status':'paid'})).encode(), json.dumps(body).replace('"site_id": "266"', '"site_id":"266","site_id":"267"').encode(), json.dumps(dict(body, kind='unknown')).encode()]:
            reply, calls = self.request(raw)
            self.assertEqual(reply[0], 422, raw)
            self.assertNotIn('source', [c[0] for c in calls])

    def test_existing_http_guards(self):
        for headers, code in [({'Sec-Fetch-Site':'cross-site'},403), ({'Content-Type':'text/plain'},415), ({'Content-Length':'4097'},413), ({'Content-Length':'4096'},422), ({'Transfer-Encoding':'chunked'},415)]:
            reply, calls = self.request(self.export_body(), headers=headers)
            self.assertEqual(reply[0], code)
            self.assertFalse(calls)

    def test_hash_and_anchor_guards(self):
        with self.assertRaisesRegex(ValueError, 'hash_mismatch'):
            prepare.prepare(b'changed', (HERE/'fixtures/page.js').read_bytes())
        with self.assertRaisesRegex(ValueError, 'anchor_not_unique'):
            prepare._replace(b'x x', __import__('hashlib').sha256(b'x x').hexdigest(), 'x', 'y')
        self.assertEqual(candidates(), candidates())


class Frontend(unittest.TestCase):
    def test_production_page_mount_wrapper_and_deny(self):
        page = candidates()['page.js'].decode()
        # Only replace module import/load and start trigger; execute all real page functions.
        page = page[page.index(chr(10))+1:].replace('await import(moduleURL.href)', '({mountDataWorkspace:globalThis.mountDataWorkspace})')
        page = page.rsplit('start();', 1)[0]
        page = page.replace("else show('工具页暂时无法加载，请刷新后重试。', true);", 'else throw error;')
        script = r'''
const vm = require('node:vm'), assert = require('node:assert/strict');
const nodes = new Map(); let mounted, disposed=0, requests=[];
const node = () => ({dataset:{},hidden:false,value:'',textContent:'',addEventListener(){},attachShadow(){return {append(link){link.onload();}}}});
for (const id of ['page-status','workspace-host','theme']) nodes.set(id,node());
const sandbox = {AbortController,AbortSignal,URL,Date,Map,JSON,Error,DOMException,console,
 document:{getElementById:id=>nodes.get(id),createElement:node,addEventListener(){},documentElement:{dataset:{}},body:{dataset:{moduleUrl:'/dashboard/workspace-assets/workspace-native-20261006-123456abcdef/data-workspace.js'}}},
 window:{addEventListener(){}},location:{origin:'https://example.invalid',href:'https://example.invalid/dashboard/'},
 sessionIdentity:async()=>({name:'real',role:'admin'}),protectedRead:()=>{},
 mountDataWorkspace:(root,options)=>{mounted=options;return {dispose(){disposed++;}}},
 fetch:async(url,options)=>{requests.push({url,options});return {status:sandbox.code||206}}};
vm.createContext(sandbox); vm.runInContext(PAGE,sandbox);
(async()=>{
 await vm.runInContext('start()',sandbox);
 assert(mounted); const cfg=mounted.orderEmailExport;
 assert.equal(cfg.endpoint,'/dashboard/users/live-orders.json'); assert.equal(cfg.paged,true);
 assert.equal(JSON.stringify(cfg.games),JSON.stringify([{value:'833',label:'FC26'},{value:'1327',label:'FC27'}]));
 assert.equal(cfg.sites[0].value,'266');
 for(const [url,options] of [['/evil',{method:'POST',body:'{}'}],[cfg.endpoint,{method:'GET'}],[cfg.endpoint,{method:'POST',body:'[]'}],[cfg.endpoint,{method:'POST',body:'{"kind":"bad"}'}]]) {
  assert.throws(()=>cfg.fetch(url,options));
 }
 assert.equal(requests.length,0);
 const signal=new AbortController().signal;
 await cfg.fetch(cfg.endpoint,{method:'POST',body:'{"game_id":"833"}',signal,credentials:'omit',redirect:'follow'});
 const req=requests[0];assert.equal(req.options.credentials,'same-origin');assert.equal(req.options.redirect,'error');assert.equal(req.options.cache,'no-store');
 assert.equal(JSON.parse(req.options.body).kind,'order_email_export_page'); assert.equal(JSON.parse(req.options.body).game_id,'833');
 assert.notEqual(req.options.signal,signal);
 sandbox.code=401;await cfg.fetch(cfg.endpoint,{method:'POST',body:'{}'});
 assert.equal(disposed,1);assert.equal(nodes.get('workspace-host').hidden,true);
 assert.equal(vm.runInContext('identity',sandbox),null);assert.equal(vm.runInContext('widget',sandbox),null);
 assert.equal(vm.runInContext('controller.signal.aborted',sandbox),true);
 await vm.runInContext('deny(403)',sandbox);assert.equal(nodes.get('page-status').dataset.state,'error');
 assert.throws(()=>mounted.writeFetch('/evil',{method:'POST'}));
 console.log('page mount + wrapper + 401/403 cleanup passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''.replace('PAGE', json.dumps(page))
        for denied in (401, 403):
            result = subprocess.run([os.environ.get('NODE_BINARY', 'node'), '-e', script.replace('sandbox.code=401', 'sandbox.code=' + str(denied))], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
