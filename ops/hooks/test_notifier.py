import copy, json, unittest
from unittest.mock import patch
from hooks_notifier import format_message, send_bot


class ChineseAlerts(unittest.TestCase):
    def test_real_screenshot_and_recovery_are_plain_and_safe_on_send_path(self):
        event = {'event_id':'a'*64, 'kind':'incident', 'status':'critical',
                 'created_at':'2026-10-09T01:12:07.320304+00:00', 'operation_ids':[],
                 'issues':[{'level':'warning','code':'latest_attempt_or_monitor_run_unverified'},
                           {'level':'warning','code':'gallery_automation_disabled'},
                           {'level':'critical','code':'latest_coin_job_failed'}]}
        original = copy.deepcopy(event)
        with patch('hooks_notifier.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"errcode":0}'
            send_bot({'webhook':'https://example.invalid','secret':''}, event)
            request = opener.return_value.open.call_args.args[0]
            text = json.loads(request.data)['text']['content']
        self.assertIn('北京时间：2026-10-09 09:12:07', text)
        self.assertIn('最近一次 FC 金币自动改价任务失败', text)
        self.assertLess(text.index('自动改价任务失败'), text.index('最新采集任务状态'))
        self.assertIn('状态说明（不代表新的系统故障）', text)
        self.assertIn('若是主动关闭，无需处理', text)
        self.assertIn('现有售价是否安全，需要另行核对', text)
        self.assertNotIn('latest_coin_job_failed', text)
        self.assertNotIn('incident critical', text)
        self.assertNotIn('已止损', text)
        self.assertEqual(event, original)
        recovered = event | {'kind':'recovery','status':'warning','issues':[event['issues'][1]]}
        text = format_message(recovered)
        self.assertIn('异常有所缓解，仍有提醒', text)
        self.assertNotIn('本次巡检恢复正常', text)
        self.assertIn('不代表自动改价或售卖保护已恢复', text)
        operation = '11111111-1111-4111-8111-111111111111'
        unknown = event | {'operation_ids':[operation], 'created_at':'bad',
                           'issues':[{'code':'future_fault','level':'critical'},
                                     {'code':'unsafe\nexternal-content','level':'critical'}]}
        text = format_message(unknown)
        self.assertIn('未识别的巡检异常', text)
        self.assertIn('检查时间：尚未确认', text)
        self.assertIn('原操作编号：'+operation, text)
        self.assertIn('不清锁、不重放、不修改账本', text)
        self.assertNotIn('external-content', text)
        for code in ('three_platform_publication_unverified','service_unavailable:fc27-cloud-worker.service'):
            with self.subTest(code=code):
                text = format_message(event | {'issues':[{'code':code,'level':'critical'}]})
                self.assertNotIn(code, text)
                if code.startswith('three_platform'):self.assertIn('不能证明已经止损', text)
                else:self.assertIn('FC 任务执行服务或访问检查未通过', text)


if __name__ == '__main__':unittest.main()
