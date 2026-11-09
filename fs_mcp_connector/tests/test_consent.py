from html.parser import HTMLParser
from types import SimpleNamespace
import unittest

from fs_mcp_connector.consent import render_browser_error, render_consent


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__();self.elements=[];self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.elements.append((tag,dict(attrs)))


class ConsentTests(unittest.TestCase):
    def render(self, **changes):
        args=dict(principal=SimpleNamespace(subject='fixture-user'),client_name='Fixture client',
            redirect_uri='http://127.0.0.1:8765/callback',pending_id='pending-fixture',csrf_token='csrf-fixture',
            oauth_base='/connector/oauth',asset_base='/connector/assets')
        return render_consent(**(args|changes))

    def test_native_post_contract_and_readonly_scope(self):
        html=self.render();elements=Markup(html).elements
        self.assertIn(('form',{'method':'post','action':'/connector/oauth/authorize','class':'connector-actions'}),elements)
        inputs=[attrs for tag,attrs in elements if tag=='input']
        self.assertEqual({p['name']:p['value'] for p in inputs},{'pending_id':'pending-fixture','csrf_token':'csrf-fixture'})
        buttons=[attrs for tag,attrs in elements if tag=='button']
        self.assertEqual({p['value'] for p in buttons},{'approve','deny'})
        self.assertTrue(all(p['type']=='submit' and p['name']=='decision' for p in buttons))
        self.assertIn('fixture-user',html);self.assertIn('Fixture client',html)
        self.assertIn('原有 private 权限',html);self.assertIn('不提供改价',html)
        self.assertIn(('details',{'class':'connector-callback'}),elements)

    def test_all_dynamic_values_are_escaped(self):
        hostile='"><script>alert(1)</script>'
        html=self.render(principal=SimpleNamespace(subject=hostile),client_name=hostile,
            redirect_uri=hostile,pending_id=hostile,csrf_token=hostile)
        self.assertNotIn('<script>alert',html)
        self.assertEqual(html.count('&lt;script&gt;'),5)
        self.assertEqual(len([tag for tag,_ in Markup(html).elements if tag=='script']),1)

    def test_uses_only_original_shared_assets_and_no_inline_script_style(self):
        elements=Markup(self.render()).elements
        self.assertEqual([a['href'] for t,a in elements if t=='link'],
            ['/connector/assets/fs-tokens.css','/connector/assets/fs-ui.css','/connector/assets/consent.css'])
        self.assertEqual([a['src'] for t,a in elements if t=='script'],['/connector/assets/fs-theme.js'])
        self.assertFalse(any(t=='style' or 'style' in a or any(k.startswith('on') for k in a) for t,a in elements))

    def test_browser_error_explains_reconnection_without_internal_details(self):
        for reason in ('login_required','access_denied','temporarily_unavailable','unknown_internal_trace_secret'):
            html=render_browser_error(reason=reason,asset_base='/connector/assets')
            self.assertIn('重新',html);self.assertNotIn(reason,html)
            self.assertNotIn('<form',html);self.assertIn('href="/dashboard/"',html)

    def test_assets_and_form_stay_on_original_origin(self):
        for path in ('https://other.example','//other.example','/path?secret=x','/bad\\path'):
            with self.subTest(path=path),self.assertRaises(ValueError):self.render(asset_base=path)
            with self.subTest(path=path),self.assertRaises(ValueError):self.render(oauth_base=path)


if __name__=='__main__':
    unittest.main()
