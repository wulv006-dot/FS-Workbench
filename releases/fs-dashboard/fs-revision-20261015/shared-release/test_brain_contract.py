"""Run real brain requests through the frozen nginx mapping and range Handler.

Only the Hermes business operation is stubbed: no paid model call or write occurs.
"""
import ast
import io
import json
from pathlib import Path
import re
import subprocess
import types
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class BrainContract(unittest.TestCase):
    def test_browser_requests_reach_actual_hermes_handler(self):
        # Exercise the shipped JS functions/form handler; do not reimplement URLs.
        javascript = r"""
const fs=require('fs'),vm=require('vm');const source=fs.readFileSync(process.argv[1],'utf8');
const calls=[],elements=new Map(),job={id:'a'.repeat(32),state:'COMPLETED',body:{start:'2026-10-05',end:'2026-10-11',question:'contract test'}};
function element(){return {value:'',classList:{add(){},remove(){},toggle(){}},append(){},replaceChildren(){},click(){},remove(){},scrollIntoView(){}};}
const document={hidden:true,body:element(),getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},createElement:element};
const context={document,location:{search:''},URLSearchParams,AbortSignal,Date,Map,Set,Blob,crypto:{randomUUID:()=> '12345678-1234-1234-1234-123456789abc'},
URL:{createObjectURL:()=> 'blob:contract',revokeObjectURL(){}},setTimeout:()=>1,clearTimeout(){},
fetch:async(url,options)=>{calls.push({url,options});let body={...job};if(url.includes('artifact='))body={content:JSON.stringify({model_generated:true,summary:'stored original',actions:[]}),mime:'text/html',filename:'report.html'};
return {ok:true,headers:{get:()=> 'application/json'},json:async()=>body};}};
vm.createContext(context);
const end=source.indexOf("  $('report-kind').value=reportKind;");if(end<0)throw Error('brain initialization boundary changed');
vm.runInContext(source.slice(0,end)+"globalThis.contract={request,select,report,submit:$('investigate').onsubmit};})();",context);
(async()=>{await context.contract.request('?mode=hermes');await context.contract.select(job.id);
await context.contract.report(job,'html');await context.contract.report(job,'boss',true);
for(const [id,value] of Object.entries({start:'2026-10-05',end:'2026-10-11',question:'contract test',mode:'investigation'}))document.getElementById(id).value=value;
await context.contract.submit({preventDefault(){}});console.log(JSON.stringify(calls));})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result = subprocess.run(['node', '-e', javascript, str(ROOT/'brain/brain.js')], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = json.loads(result.stdout)
        conf = (ROOT/'frontend-release/stage/candidate/formal.conf').read_text('utf-8')
        # Load the actual backend class AST without importing collectors/starting jobs.
        tree = ast.parse((ROOT/'analytics/candidate/range_api.py').read_text('utf-8'))
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        observations = []
        def get(params, user):
            observations.append(('GET', params))
            self.assertEqual(params.get('mode'), ['hermes'])
            self.assertLessEqual(set(params), {'mode', 'id', 'artifact'})
            if 'artifact' in params:self.assertIn(params['artifact'][0], {'json', 'html', 'boss'})
            return 200, {'contract': 'hermes'}
        def post(body, user, headers):
            observations.append(('POST', body))
            self.assertEqual(set(body), {'kind', 'request_id', 'start', 'end', 'question', 'mode'})
            self.assertEqual(body['kind'], 'hermes_report')
            self.assertRegex(body['request_id'], r'^brain_weekly_[a-f0-9]{32}$')
            self.assertEqual(body['mode'], 'investigation')
            self.assertEqual(headers['X-FS-Advisor-Action'], 'submit')
            self.assertEqual(headers['Sec-Fetch-Site'], 'same-origin')
            return 202, {'contract': 'hermes'}
        namespace = dict(BaseHTTPRequestHandler=object, urlsplit=urlsplit, parse_qs=parse_qs, re=re, json=json,
                         HERMES=types.SimpleNamespace(get=get, post=post), get_range=lambda _: (422, {'error': 'invalid_or_uncovered_range'}))
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'actual-range-handler', 'exec'), namespace)
        for call in calls:
            with self.subTest(url=call['url'], method=call['options']['method']):
                uri=urlsplit(call['url']);options=call['options']
                self.assertEqual(uri.path, '/dashboard/fs-home/advisor.json')
                location=re.search(r'location = '+re.escape(uri.path)+r'\s*\{([\s\S]*?)\n\}', conf)
                self.assertIsNotNone(location, 'brain endpoint must exist in nginx')
                block=location.group(1)
                self.assertIn('auth_request /__auth_verify;', block)
                upstream=re.search(r'proxy_pass http://127\.0\.0\.1:8931([^;]+);', block).group(1)
                self.assertEqual(upstream, '/advisor')
                self.assertEqual(options['credentials'], 'same-origin')
                self.assertEqual(options['redirect'], 'error')
                instance=namespace['Handler']();instance.path=upstream+('?' + uri.query if uri.query else '')
                body=options.get('body','').encode()
                instance.headers={**options['headers'], 'X-Auth-User':'contract-test', 'Sec-Fetch-Site':'same-origin', 'Content-Length':str(len(body))}
                instance.rfile=io.BytesIO(body);instance.connection=types.SimpleNamespace(settimeout=lambda _:None)
                replies=[];instance.reply=lambda status,payload:replies.append((status,payload))
                if options['method']=='POST':
                    self.assertEqual(uri.query, '')
                    self.assertEqual(options['headers']['Content-Type'], 'application/json')
                    instance.do_POST()
                else:instance.do_GET()
                self.assertIn(replies[-1][0], (200,202), replies)
                self.assertEqual(replies[-1][1], {'contract':'hermes'})
        gets=[params for method,params in observations if method=='GET']
        self.assertIn({'mode':['hermes']}, gets)
        self.assertEqual({p['artifact'][0] for p in gets if 'artifact' in p}, {'json','html','boss'})
        self.assertEqual(sum(method=='POST' for method,_ in observations), 1)


if __name__ == '__main__':unittest.main()
