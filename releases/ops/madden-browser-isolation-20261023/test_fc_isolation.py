import sys,types,unittest
from unittest.mock import Mock,patch
import fc_isolation_patch as producer
import isolated_backend as backend


class FCIsolationTests(unittest.TestCase):
    def test_helper_uses_original_identity_and_closes_owned_browser(self):
        pw=Mock();browser=pw.chromium.launch.return_value;auth=types.SimpleNamespace(apply=Mock())
        with patch.dict(sys.modules,fs_order_client=auth):self.assertIs(backend.open_backend(pw),browser)
        pw.chromium.connect_over_cdp.assert_not_called();auth.apply.assert_called_once_with(browser.new_context.return_value)
        self.assertEqual(pw.chromium.launch.call_args.kwargs['env']['HOME'],'/tmp')
        self.assertEqual(pw.chromium.launch.call_args.kwargs['env']['XDG_CONFIG_HOME'],'/tmp/.config')
        page=Mock();page.context.browser=browser;page.close.side_effect=RuntimeError('page_close')
        with self.assertRaises(RuntimeError):backend.close_backend(page)
        browser.close.assert_called_once()

    def test_identity_failure_closes_browser_without_login_or_fallback(self):
        pw=Mock();auth=types.SimpleNamespace(apply=Mock(side_effect=RuntimeError('identity_unavailable')))
        with patch.dict(sys.modules,fs_order_client=auth):
            with self.assertRaises(RuntimeError):backend.open_backend(pw)
        pw.chromium.launch.return_value.close.assert_called_once();pw.chromium.connect_over_cdp.assert_not_called()

    def test_python_patch_preserves_every_other_original_byte(self):
        source='from playwright.sync_api import sync_playwright\ndef original():\n    browser=playwright.chromium.connect_over_cdp("original", timeout=8000)\n    original_business_write_check()\n    try: original_operation_id()\n    finally: page.close()\n'
        result=producer.python_source(source,{'page':1})
        self.assertIn('original_business_write_check()',result);self.assertIn('original_operation_id()',result)
        self.assertIn('open_backend(playwright)',result);self.assertNotIn('connect_over_cdp',result)
        with self.assertRaises(ValueError):producer.python_source(result,{'page':1})
        with self.assertRaises(ValueError):producer.python_source(source,{'page':2})

    def test_launcher_keeps_original_image_request_mount_and_timeout(self):
        source='timeout 120s docker run --rm --network host --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --mount type=bind,src=/opt/fs-order-session,dst=/opt/fs-order-session,readonly --mount type=bind,src=/run/fs-order-session,dst=/run/fs-order-session,readonly --mount type=bind,src="$request",dst=/run/request.json,readonly original-image /opt/writer.py\n'
        result=producer.launcher(source)
        for part in ('timeout 120s','--network host','--read-only','src="$request"','original-image /opt/writer.py'):self.assertIn(part,result)
        self.assertIn('--memory 2g',result);self.assertIn('size=256m',result)
        with self.assertRaises(ValueError):producer.launcher(result)
