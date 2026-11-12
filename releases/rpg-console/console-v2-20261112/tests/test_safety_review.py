"""Regression probes for independent review findings; fabricated temp files only."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from support import APP
from console_config import ConfigStore, ConfigError, _json_bytes
from console_web import jobs_summary


class ReviewSafetyTests(unittest.TestCase):
    def make_store(self, root):
        doc = {'汇率': {'USDCNY': 6.65}, '跟价': {'跟随策略': {'让价百分比': 2, '最低毛利率': .15}}, '金币': {}}
        (root/'config.json').write_bytes(_json_bytes(doc))
        return ConfigStore(root)

    def test_restore_rejects_changed_inherited_default_without_writing(self):
        with tempfile.TemporaryDirectory(prefix='review09-') as td:
            root=Path(td); store=self.make_store(root)
            saved=store.save('d4', {'version':store.read('d4')['version'],'patch':{'item_discount':3}}, 'test')
            path=root/'config.json'; changed=json.loads(path.read_text(encoding='utf-8'))
            changed['跟价']['跟随策略']['让价百分比']=4
            path.write_bytes(_json_bytes(changed)); before=path.read_bytes()
            with self.assertRaises(ConfigError) as caught:
                store.restore({'id':saved['history_id'],'version':store.read('d4')['version']},'test')
            self.assertEqual(caught.exception.status,409)
            self.assertEqual(caught.exception.code,'restore_inheritance_changed')
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(store.history()['items']),1)

    def test_restore_unchanged_inheritance_keeps_effective_history_value(self):
        with tempfile.TemporaryDirectory(prefix='review09-') as td:
            root=Path(td); store=self.make_store(root)
            saved=store.save('d4',{'version':store.read('d4')['version'],'patch':{'item_discount':3}},'test')
            result=store.restore({'id':saved['history_id'],'version':store.read('d4')['version']},'test')
            field=next(f for f in result['data']['fields'] if f['key']=='item_discount')
            self.assertEqual(field['value'],2)
            doc=json.loads((root/'config.json').read_text(encoding='utf-8'))
            self.assertNotIn('让价百分比',doc['跟价']['按游戏']['暗黑破坏神4']['跟随策略'])

    def test_result_counts_use_real_ok_fail_fields_and_reject_booleans(self):
        with tempfile.TemporaryDirectory(prefix='review09-') as td:
            root=Path(td); (root/'data').mkdir()
            con=sqlite3.connect(root/'data'/'iggm_follow.db')
            con.execute('CREATE TABLE local_job(id,title,status,created_at,finished_at,result_json,plan_json)')
            for idx,result in enumerate([{'ok':8,'fail':0,'write_state':'confirmed'}, {'ok':True,'fail':False,'write_state':'confirmed'}]):
                con.execute('INSERT INTO local_job VALUES(?,?,?,?,?,?,?)',(str(idx),'test','done',str(idx),str(idx),json.dumps(result),json.dumps({'游戏':['WoW Forever']})))
            con.commit(); con.close()
            jobs,pending=jobs_summary(root); byid={j['id']:j for j in jobs}
            self.assertEqual(byid['0']['success'],8)
            self.assertEqual(byid['0']['failed'],0)
            self.assertIsNone(byid['1']['success'])
            self.assertIsNone(byid['1']['failed'])
            self.assertEqual(pending,0)

    def test_attention_copy_matches_actual_scope(self):
        html=(APP/'templates'/'console.html').read_text(encoding='utf-8')
        self.assertIn('采集状态需关注',html)
        self.assertNotIn('异常与待确认任务',html)


if __name__=='__main__':
    unittest.main(verbosity=2)
