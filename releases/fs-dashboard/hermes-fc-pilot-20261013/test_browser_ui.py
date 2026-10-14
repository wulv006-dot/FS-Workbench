import json
from pathlib import Path
import shutil
import subprocess
import unittest


class BrowserUiTests(unittest.TestCase):
    def test_blocked_history_and_error_recovery_are_visible(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'existing Node runtime required for UI acceptance')
        source = (Path(__file__).parent / 'index.html').read_text('utf-8').split('<script>', 1)[1].split('</script>', 1)[0]
        program = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();
function element(){return {value:'',textContent:'',disabled:false,hidden:false,style:{},children:[],appendChild(e){this.children.push(e)},replaceChildren(){this.children=[]}}}
function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)}
get('mode').value='investigation';
const reads=[];let blocked=true;
const history={can_generate:false,admission:{status:'blocked',reason:'pilot_usage_hold'},items:[{id:'failed_fixture',state:'FAILED',body:{start:'2026-10-13',end:'2026-10-13'}}]};
const job={state:'FAILED',error:'runtime_failed',model_usage:{calls:0,total_tokens:0,reasoning_tokens:0,estimated_microcny:0,unknown_calls:0}};
const context={document:{getElementById:get,createElement:element},Date,Intl,JSON,Error,encodeURIComponent,crypto:{randomUUID:()=>{throw Error('must not submit')}},setTimeout:()=>0,clearTimeout:()=>{},fetch:async(url,options)=>{reads.push({url,method:options.method||'GET'});assert.equal(options.method,undefined);return {ok:true,json:async()=>url.includes('&id=')?job:{...history,can_generate:!blocked,admission:{reason:blocked?'pilot_usage_hold':null}}}}};
vm.runInNewContext(SOURCE,context);
const flush=()=>new Promise(setImmediate);
(async()=>{await flush();assert.equal(get('submit').disabled,true);assert.match(get('status').textContent,/费用记录待核验/);assert.doesNotMatch(get('status').textContent,/需要原管理权限/);assert.equal(get('history').children.length,1);assert.match(get('history').children[0].textContent,/FAILED/);get('history').children[0].onclick();await flush();await flush();assert.match(get('usage').textContent,/模型 0 次/);assert.match(get('status').textContent,/费用记录待核验/);assert.equal(get('result').hidden,true);blocked=false;await vm.runInNewContext('history()',context);assert.equal(get('submit').disabled,false);assert.equal(reads.filter(r=>r.method==='POST').length,0);console.log(JSON.stringify({blocked_button:true,safe_recovery_message:true,failed_history_retained:true,new_submission_after_recovery:true,model_calls:0}));})().catch(e=>{console.error(e);process.exitCode=1});
'''.replace('SOURCE', json.dumps(source))
        result = subprocess.run([node, '-'], input=program, text=True, encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt['blocked_button'])
        self.assertTrue(receipt['failed_history_retained'])
        self.assertEqual(receipt['model_calls'], 0)


if __name__ == '__main__':
    unittest.main()
