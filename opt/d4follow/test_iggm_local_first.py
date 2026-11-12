import ast
import datetime as dt
import importlib.util
import json
import tempfile
import types
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent

def extract(path, name, namespace, cls=None):
    tree = ast.parse((HERE / path).read_text(encoding='utf-8-sig'))
    nodes = tree.body
    if cls:
        nodes = next(x for x in nodes if isinstance(x, ast.ClassDef) and x.name == cls).body
    node = next(x for x in nodes if isinstance(x, ast.FunctionDef) and x.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), namespace)
    return namespace[name]

class LocalFirstTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        spec = importlib.util.spec_from_file_location('fixed_net', HERE / 'net_util.py')
        self.net = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.net)
        self.net.__file__ = str(self.root / 'net_util.py')
        self.configure()

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self, mode='auto', age=10, saved=8):
        (self.root / 'config.json').write_text(json.dumps({'iggm': {
            '抓取来源': mode, '本机推送有效分钟': 70}}), encoding='utf-8')
        (self.root / 'data' / 'iggm_local_push.json').write_text(json.dumps({
            'pushed_at': (dt.datetime.now() - dt.timedelta(minutes=age)).isoformat(),
            'saved': saved}), encoding='utf-8')

    def test_online_blocks_paid_gate_and_direct_request(self):
        self.assertTrue(self.net.iggm_local_preferred())
        with patch.object(self.net.urllib.request, 'urlopen', side_effect=AssertionError('network')):
            self.assertFalse(self.net.decodo_on('www.iggm.com'))
            with self.assertRaisesRegex(RuntimeError, '本机优先'):
                self.net.decodo_get('https://www.iggm.com/test')

    def test_offline_and_explicit_modes(self):
        for mode, age, expected in [('auto',71,False),('auto',-1,False),
                                    ('local',1000,True),('server',1,False),
                                    ('alternate',1,False)]:
            self.configure(mode,age)
            self.assertEqual(self.net.iggm_local_preferred(),expected,(mode,age))
        self.configure(saved=0)
        self.assertFalse(self.net.iggm_local_preferred())

    def fetch(self, pushed=None):
        get = Mock(return_value=json.dumps({'data': {'one_goods': {'price': 2},
                                                       'result_goods': []}}))
        ns = {'net_util':self.net, '_pushed_iggm_gold':lambda *a,**k:pushed,
              'urllib':urllib, 'json':json, '_ci':types.SimpleNamespace(_get=get),
              'IGGM_BASE':'https://www.iggm.com', '_f':lambda x:x}
        method = extract('core_gold.py','fetch',ns,cls='IggmGold')
        obj = types.SimpleNamespace(log=lambda *a:None,timeout=40,sess=object())
        return lambda:method(obj,'123',page='/gold'),get

    def test_online_missing_gold_does_not_fetch(self):
        run,get = self.fetch()
        with self.assertRaisesRegex(RuntimeError,'本机优先'):
            run()
        get.assert_not_called()

    def test_fresh_gold_is_used(self):
        run,get = self.fetch({'unit_price':3})
        self.assertEqual(run()['unit_price'],3)
        get.assert_not_called()

    def test_offline_gold_server_fallback_is_preserved(self):
        self.configure(age=71)
        run,get = self.fetch()
        self.assertEqual(run()['unit_price'],2)
        get.assert_called_once()

    def test_wow_dual_source_plan_never_fetches_missing_iggm(self):
        # v5.4 removed IGGM from pricing; local monitor snapshots are display-only.
        import core_wow_gold as wow
        paid=Mock(side_effect=AssertionError('paid request'))
        tree=ast.parse((HERE/'core_wow_gold.py').read_text(encoding='utf-8'))
        plan=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_plan')
        self.assertNotIn('iggm',[a.arg for a in plan.args.args])
        self.assertFalse(any(isinstance(n,ast.Name) and n.id in
                              ('load_iggm','fetch_iggm_decodo') for n in ast.walk(plan)))
        row={'id':'synthetic','name':'test','region':'美服','type':'PVP','faction':'A',
             'cost':1,'margin':.2,'b2c':1.2}
        cfg={'参数':{},'区服':[{'区':'美服','类型':'PVP','阵营':'A',
                               '后台行ID':'synthetic','启用':True}]}
        with patch('urllib.request.urlopen',paid):
            result=wow.build_plan([row],{},cfg,6.65,log=lambda *a:None,bjq_pages={})[0]
        self.assertEqual(result['动作'],'hold')
        self.assertIsNone(result['目标b2c'])
        self.assertIsNone(result['IGGM'])
        paid.assert_not_called()

if __name__ == '__main__':
    unittest.main()
