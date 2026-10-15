"""Exercise original candidate functions with synthetic transports only."""
import ast
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / 'source/webapp.py').read_text(encoding='utf-8-sig'))


def original(name, **namespace):
    node = next(n for n in TREE.body if getattr(n, 'name', None) == name)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), 'candidate/webapp.py', 'exec'), namespace)
    return namespace[name]


spec = importlib.util.spec_from_file_location('sbc_auto_test', ROOT / 'source/auto_flow.py')
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


class Security(unittest.TestCase):
    def request(self, headers=None, path='/api/auto/save', method='POST', body=b'{}'):
        self.writes = []
        session = NS(busy=False, lock=threading.Lock(), log=lambda *_: None)
        Handler = original('Handler', BaseHTTPRequestHandler=object, SESSION=session,
            BadInput=ValueError, ac=NS(AdminAuthError=type('AuthError', (Exception,), {})),
            urlparse=urlparse, parse_qs=parse_qs, json=json, AUTOMATION=NS(status=lambda: {'running': None}),
            _route_path=lambda p: p, do_auto_save=lambda b: self.writes.append(b) or {'ok': True})
        req = Handler()
        req.path = path
        req.headers = headers or {}
        req.rfile = io.BytesIO(body)
        req.result = None
        req._json = lambda payload, code=200: setattr(req, 'result', (code, payload))
        getattr(req, 'do_' + method)()
        return req

    def test_missing_identity_rejects_before_body(self):
        self.assertEqual(self.request().result[0], 401)
        self.assertFalse(self.writes)

    def test_readonly_cannot_write(self):
        req = self.request({'X-SBC-User': 'synthetic', 'X-SBC-Role': 'readonly'})
        self.assertEqual(req.result[0], 403)
        self.assertFalse(self.writes)

    def test_role_without_identity_rejected(self):
        self.assertEqual(self.request({'X-SBC-Role': 'admin'}).result[0], 401)

    def test_untrusted_header_name_rejected(self):
        self.assertEqual(self.request({'X-Auth-User': 'synthetic', 'X-Auth-Role': 'admin'}).result[0], 401)

    def test_admin_json_reaches_local_fake_writer(self):
        req = self.request({'X-SBC-User': 'synthetic', 'X-SBC-Role': 'admin', 'Content-Type': 'application/json'})
        self.assertEqual(req.result[0], 200)
        self.assertEqual(self.writes, [{}])

    def test_form_request_rejected(self):
        req = self.request({'X-SBC-User': 'synthetic', 'X-SBC-Role': 'admin', 'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(req.result[0], 415)
        self.assertFalse(self.writes)

    def test_json_array_rejected(self):
        req = self.request({'X-SBC-User': 'synthetic', 'X-SBC-Role': 'admin', 'Content-Type': 'application/json', 'Content-Length': '2'}, body=b'[]')
        self.assertEqual(req.result[0], 400)
        self.assertFalse(self.writes)

    def test_health_is_readonly_and_has_version(self):
        self.assertEqual(self.request(path='/health', method='GET').result[1]['version'], 'sbc-security-20261015')

    def test_no_identity_cannot_download(self):
        self.assertEqual(self.request(path='/api/download', method='GET').result[0], 401)

    def test_paths_confined(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = (Path(tmp) / 'output').resolve()
            root.mkdir()
            resolve = original('_workbook_path', Path=Path, BadInput=ValueError, OUTPUT_DIR=root, DEFAULT_XLSX=root/'default.xlsx')
            self.assertEqual(resolve(), root/'default.xlsx')
            self.assertEqual(resolve('inside.xlsx'), root/'inside.xlsx')
            for path in ('../escape.xlsx', root.parent/'escape.xlsx', root/'bad.py', root):
                with self.subTest(path=str(path)), self.assertRaises(ValueError):
                    resolve(path)

    def test_resolved_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = (Path(tmp) / 'output').resolve()
            root.mkdir()
            resolve = original('_workbook_path', Path=Path, BadInput=ValueError, OUTPUT_DIR=root, DEFAULT_XLSX=root/'default.xlsx')
            real_resolve = Path.resolve
            def redirected(p, *a, **kw):
                if p == root/'link.xlsx':
                    return root.parent/'outside.xlsx'
                return real_resolve(p, *a, **kw)
            with patch.object(Path, 'resolve', redirected), self.assertRaises(ValueError):
                resolve(root/'link.xlsx')

    def test_every_workbook_body_path_uses_shared_guard(self):
        for name in ('do_fetch', 'do_fetch_packs', 'do_reload', 'do_prune_item_score', 'do_save'):
            node = next(n for n in TREE.body if getattr(n, 'name', '') == name)
            self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == '_workbook_path' for n in ast.walk(node)), name)

    def pipeline(self, failure_index=None, value=None):
        with tempfile.TemporaryDirectory() as tmp:
            engine = auto.Automation(Path(tmp)/'settings.json')
            calls = []
            host = {'session': NS(lock=threading.Lock(), busy=False), 'log': lambda *_: None}
            for index, (_, key) in enumerate(engine._PIPELINE_STEPS):
                def step(index=index, key=key):
                    calls.append(key)
                    if index == failure_index:
                        return value
                    return {'ok': True}
                host[key] = step
            engine.bind(host)
            engine._pipeline_job(trigger='synthetic')
            record = json.loads(engine.settings_path.read_text(encoding='utf-8'))['last_pipeline']
            return calls, record, host['session']

    def test_failure_at_each_step_stops_following_writes(self):
        for index in range(8):
            with self.subTest(index=index):
                calls, record, session = self.pipeline(index, {'ok': False, 'error': 'synthetic'})
                self.assertEqual(len(calls), index+1)
                self.assertFalse(record['ok'])
                self.assertFalse(session.busy)

    def test_unknown_or_malformed_result_is_failure(self):
        for result in (None, {}, {'ok': 'true'}, {'ok': 1}, {'state': 'unknown'}):
            with self.subTest(result=result):
                calls, record, _ = self.pipeline(0, result)
                self.assertEqual(len(calls), 1)
                self.assertFalse(record['ok'])

    def test_success_records_all_steps(self):
        calls, record, _ = self.pipeline()
        self.assertEqual(len(calls), 8)
        self.assertTrue(record['ok'])

    def test_stale_rate_stops_automatic_writes(self):
        step = original('_step_fetch_rates', do_fetch_rates=lambda b: {'ok': True, 'from_cache': True})
        self.assertFalse(step()['ok'])

    def test_fresh_rate_passes(self):
        step = original('_step_fetch_rates', do_fetch_rates=lambda b: {'ok': True, 'from_cache': False})
        self.assertTrue(step()['ok'])

    def test_duplicate_automation_is_rejected(self):
        engine = auto.Automation(Path('unused'))
        engine._job_running = 'pipeline'
        with patch.object(auto.threading, 'Thread') as thread:
            self.assertFalse(engine.run_pipeline()['ok'])
            self.assertFalse(engine.run_delist()['ok'])
            thread.assert_not_called()

    def delist(self, readback=0, write_error=False, missing=False):
        writes = []
        def write(mid, value):
            writes.append(mid)
            if write_error:
                raise TimeoutError('synthetic unknown')
        client = NS(edit_model_status=write, get_model=lambda mid: readback if isinstance(readback, dict) else {'status': readback})
        models = [{'id': mid, 'title': str(mid), **({} if missing else {'status': 1})} for mid in (101, 102)]
        func = original('do_delist', SESSION=NS(logged_in=True, rows=[NS(title='keep')], client=client, log=lambda *_: None),
            DELIST_RECEIPTS=Path(tempfile.gettempdir())/'sbc-nonexistent-test-receipt.json', json=json,
            _save_delist_receipts=lambda receipts: None, time=__import__('time'), BadInput=ValueError,
            _truthy=bool, uploader=NS(normalize_title=lambda s: str(s).lower()),
            _auto_settings_load=lambda: NS(data={'delist_protect': []}),
            _all_models=lambda cid: models if cid == 1 else [],
            ac=NS(CID_SBC=1, CID_PACKS=2, AdminClient=NS(model_row=lambda row: row)), fnmatch=__import__('fnmatch'))
        return func({}), writes

    def test_delist_requires_confirmed_zero(self):
        result, writes = self.delist(0)
        self.assertTrue(result['ok'])
        self.assertEqual(result['delisted'], 2)
        self.assertEqual(writes, [101, 102])

    def test_delist_mismatch_stops_and_reports_unknown(self):
        result, writes = self.delist(1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['delisted'], 0)
        self.assertEqual(result['details'][0]['state'], 'unknown')
        self.assertEqual(writes, [101])

    def test_delist_missing_readback_status_is_unknown(self):
        result, writes = self.delist({})
        self.assertFalse(result['ok'])
        self.assertEqual(writes, [101])

    def test_delist_write_timeout_stops_without_retry(self):
        result, writes = self.delist(write_error=True)
        self.assertFalse(result['ok'])
        self.assertEqual(writes, [101])

    def test_delist_missing_input_status_never_writes(self):
        result, writes = self.delist(missing=True)
        self.assertFalse(result['ok'])
        self.assertEqual(writes, [])

    def test_settings_atomic_replace_and_disable_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = auto.AutoSettings(Path(tmp)/'settings.json')
            settings.data.update(enabled=False, delist_enabled=False)
            settings.save()
            auto._save_record(settings.path, 'last_pipeline', {'ok': False})
            data = json.loads(settings.path.read_text(encoding='utf-8'))
            self.assertIs(data['enabled'], False)
            self.assertIs(data['delist_enabled'], False)
            self.assertEqual(list(Path(tmp).iterdir()), [settings.path])

    def test_failed_receipt_save_is_not_swallowed(self):
        with patch.object(auto.AutoSettings, 'save', side_effect=OSError('synthetic disk full')):
            with self.assertRaises(OSError):
                auto._save_record(Path('unused'), 'last_pipeline', {})

    def test_unknown_delist_receipt_prevents_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'receipts.json'
            path.write_text(json.dumps([{'mid': 101, 'state': 'unknown'}]), encoding='utf-8')
            writer = unittest.mock.Mock()
            func = original('do_delist', SESSION=NS(logged_in=True, client=NS(get_model=lambda mid: {'status': 1}, edit_model_status=writer)),
                DELIST_RECEIPTS=path, json=json, _truthy=bool, BadInput=ValueError,
                ac=NS(AdminClient=NS(model_row=lambda row: row)))
            self.assertFalse(func({})['ok'])
            writer.assert_not_called()

    def test_delist_receipt_save_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'receipts.json'
            save = original('_save_delist_receipts', DELIST_RECEIPTS=path,
                os=__import__('os'), tempfile=tempfile, json=json)
            save([{'mid': 101, 'state': 'unknown'}])
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))[0]['state'], 'unknown')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_nginx_overwrites_identity_and_uses_original_request_guard(self):
        text = (ROOT/'config/fc27-sbc-location.conf').read_text()
        for line in ('auth_request /__auth_verify;', 'proxy_set_header X-SBC-User $sbc_user;', 'proxy_set_header X-SBC-Role $sbc_role;'):
            self.assertIn(line, text)

    def test_python39_syntax(self):
        for p in (ROOT/'source').glob('*.py'):
            ast.parse(p.read_text(encoding='utf-8-sig'), feature_version=(3, 9))


if __name__ == '__main__':
    unittest.main()
