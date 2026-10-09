import json, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import hooks, probe_worker
from collector import persist
from hooks_notifier import format_message
from test_hooks import healthy


class RpgAlerts(unittest.TestCase):
    def probe(self, tasks, ok=True):
        body = json.dumps({'ok':ok,'data':{'tasks':tasks,'config':{'password':'private-value'}}}).encode()
        with patch('probe_worker.state',return_value='active'), patch('probe_worker.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = body
            result = probe_worker.rpg_probe()
            self.assertEqual(opener.return_value.open.call_args.args[0],'http://127.0.0.1:8900/api/state')
        self.assertNotIn('private-value',json.dumps(result))
        return result

    def test_real_task_shape_scope_dedupe_and_existing_notice_do_not_block_fc(self):
        failed = {'id':'123456abcdef','kind':'collect','status':'error','params':{'game':'流放之路2'}}
        observed = self.probe([failed])
        self.assertEqual(observed['issues'],[{'level':'critical','code':'rpg_task_failed:poe2:collect:123456abcdef'}])
        value = healthy(); value['issues'] = observed['issues']; value['status'] = 'critical'
        control = hooks.controls(value)
        self.assertTrue(all(not p['reasons'] for p in control['platforms'].values()))
        with tempfile.TemporaryDirectory() as name:
            root = Path(name);persist(root,value)
            event = json.loads(next((root/'outbox').glob('*.json')).read_text())
            text = format_message(event)
            self.assertIn('PoE2的采集与改价任务失败',text)
            self.assertIn('123456abcdef',text)
            self.assertIn('不表示已暂停写价',text)
            self.assertNotIn('FC 自动改价存在阻塞',text)
            self.assertNotIn('private-value',text)
            persist(root,value); self.assertEqual(len(list((root/'outbox').glob('*.json'))),1)
        success = failed | {'id':'abcdef123456','status':'done'}
        running = success | {'status':'running'}
        self.assertEqual(self.probe([running,failed])['issues'],observed['issues'])
        self.assertEqual(self.probe([running,success,failed])['issues'],[])
        self.assertEqual(self.probe([success,failed])['issues'],[])
        other_game = success | {'params':{'game':'暗黑破坏神4'}}
        self.assertEqual(len(self.probe([other_game,failed])['issues']),1)
        self.assertIn(':shared:',self.probe([failed | {'params':{}}])['issues'][0]['code'])
        self.assertTrue(self.probe([failed],ok=False)['issues'])

    def test_fc_and_rpg_probe_failures_remain_independent_and_bounded(self):
        with patch('probe_worker.state',return_value='failed'),patch('probe_worker.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = TimeoutError('sensitive-raw-error')
            result = probe_worker.rpg_probe()
            self.assertEqual(len(result['issues']),3)
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],8)
            self.assertNotIn('sensitive-raw-error',json.dumps(result))
        for code in ('rpg_dependency_unavailable:d4follow.service','rpg_state_unavailable'):
            event = {'kind':'incident','status':'critical','created_at':datetime.now(timezone.utc).isoformat(),
                     'event_id':'a'*64,'issues':[{'level':'critical','code':code}]}
            self.assertIn('RPG',format_message(event))
            self.assertNotIn(code,format_message(event))
        with patch('probe_worker.fc_report',side_effect=TimeoutError('do-not-leak')), \
             patch('probe_worker.rpg_probe',return_value={'issues':[{'code':'rpg_state_unavailable','level':'critical'}]}):
            value = probe_worker.main()
            self.assertEqual([x['code'] for x in value['issues']],['collection_unavailable','rpg_state_unavailable'])
            self.assertNotIn('do-not-leak',json.dumps(value))


if __name__ == '__main__':unittest.main()
