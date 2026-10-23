import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock,patch

SOURCE=Path(__file__).parent/'source/service.py'
spec=importlib.util.spec_from_file_location('bounded_order_service',SOURCE)
S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)


class ProbeTests(unittest.TestCase):
    def test_only_original_docker_exec_arguments_changed(self):
        before="['docker', 'exec', 'fs-order-browser', 'python3', '-c', PROBE]"
        after="['docker', 'exec', 'fs-order-browser', 'timeout', '--signal=TERM', '--kill-after=1s', '33s', 'python3', '-B', '-c', PROBE]"
        source=SOURCE.read_bytes();self.assertEqual(source.count(after.encode()),1)
        restored=source.replace(after.encode(),before.encode())
        self.assertEqual(hashlib.sha256(restored).hexdigest(),'e94f54cebe50cbede113ce4205ad2fe337b176438e0e864c1caa73ae90d3c88a')

    def test_inner_process_group_deadline_precedes_original_host_timeout(self):
        with patch.object(S.subprocess,'run',return_value=Mock(returncode=0,stdout='{"ready": false}')) as run:
            self.assertEqual(S.Session.browser_probe(),{'ready':False})
        args=run.call_args.args[0]
        self.assertEqual(args[:10],['docker','exec','fs-order-browser','timeout','--signal=TERM','--kill-after=1s','33s','python3','-B','-c'])
        self.assertEqual(run.call_args.kwargs['timeout'],35)
        self.assertNotIn('--foreground',args)
        self.assertLess(33+1,35)

    def test_timeout_exit_never_issues_cookies_or_ready(self):
        for code in (124,137):
            with patch.object(S.subprocess,'run',return_value=Mock(returncode=code,stdout='')):
                session=S.Session();self.assertFalse(session.get()['ready'])
                self.assertEqual(session.result['error'],'order_probe_unavailable')
                self.assertNotIn('cookies',session.result)

    def test_get_is_single_flight_and_health_never_spawns(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def probe():
            calls.append(1);entered.set();self.assertTrue(release.wait(2));return {'ready':True,'cookies':[{'synthetic':True}]}
        session=S.Session(probe);threads=[threading.Thread(target=session.get) for _ in range(6)]
        for thread in threads:thread.start()
        self.assertTrue(entered.wait(2))
        self.assertTrue(session.health()['checking']);self.assertFalse(session.health()['ready'])
        release.set()
        for thread in threads:thread.join(2);self.assertFalse(thread.is_alive())
        self.assertEqual(calls,[1]);self.assertTrue(session.health()['ready'])

    def test_twenty_second_ttl_and_no_health_secrets_preserved(self):
        probe=Mock(return_value={'ready':True,'cookies':[{'value':'synthetic-only'}]})
        session=S.Session(probe);session.get();session.get();self.assertEqual(probe.call_count,1)
        self.assertNotIn('synthetic-only',json.dumps(session.health()))
        session.checked-=21;session.get();self.assertEqual(probe.call_count,2)
        session.checked-=46;self.assertFalse(session.health()['ready'])

    def test_identity_rules_not_weakened(self):
        scope={};exec(S.IDENTITY_CHECK,scope);check=scope['identity_ok']
        url='https://order.p2pah.cn/admin/index/index.html';body='<a href="/admin/public/logout.html">logout</a>'
        self.assertTrue(check(200,url,body))
        for status,address,text in ((403,url,body),(200,'https://example.test/admin/index/index.html',body),(200,url,'<input type=password>')):
            self.assertFalse(check(status,address,text))


if __name__=='__main__':unittest.main()
