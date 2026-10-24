import io,sys,types,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from shipping_readiness import extend

class Readiness(unittest.TestCase):
    def test_same_restart_fence_and_original_ok_assertion(self):
        calls=[];fence=object()
        def original(m,f):calls.append((m,f));raise ValueError('range health failed')
        answers=iter([io.StringIO('{"ok":false}'),io.StringIO('{"ok":true}')]);commands=[]
        base=types.SimpleNamespace(restart_for=original)
        extend(base,'rs',clock=lambda:0,sleep=lambda t:None,open_url=lambda *a,**kw:next(answers),run=lambda command,**kw:commands.append(command))
        base.restart_for({'scope':'rs'},fence)
        self.assertEqual(len(calls),1);self.assertIs(calls[0][1],fence);self.assertEqual(commands,[['nginx','-t'],['systemctl','reload','nginx']])
    def test_deadline_does_not_accept_unhealthy(self):
        base=types.SimpleNamespace(restart_for=lambda *a:(_ for _ in ()).throw(ValueError('range health failed')))
        times=iter([0,0,26]);commands=[]
        extend(base,'rs',clock=lambda:next(times),sleep=lambda t:None,open_url=lambda *a,**kw:io.StringIO('{"ok":false}'),run=lambda *a,**kw:commands.append(a))
        with self.assertRaisesRegex(ValueError,'bounded'):base.restart_for({'scope':'rs'},object())
        self.assertEqual(commands,[])
    def test_no_other_error_or_scope_is_retried(self):
        for scope,message in [('rs','source CAS failed'),('other','range health failed')]:
            base=types.SimpleNamespace(restart_for=lambda *a:(_ for _ in ()).throw(ValueError(message)))
            extend(base,'rs',open_url=lambda *a,**kw:self.fail('unexpected health read'))
            with self.assertRaisesRegex(ValueError,message):base.restart_for({'scope':scope},object())
if __name__=='__main__':unittest.main()
