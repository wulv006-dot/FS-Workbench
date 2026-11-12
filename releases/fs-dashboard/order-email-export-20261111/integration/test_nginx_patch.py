import hashlib
import unittest
from unittest.mock import patch

import nginx_patch as subject


BLOCK = b'''location = /dashboard/workspace-assets/workspace-native-20261006-4f4a56f7a335/data-workspace.js {
    if ($request_method !~ ^(GET|HEAD)$) { return 405; }
    auth_request /__nav_formal_native_session;
    error_page 401 = @auth_login;
    types { }
    default_type application/javascript;
    alias /var/lib/fs-navigation-formal-static/workspace-native-20261006-4f4a56f7a335/data-workspace.js;
    disable_symlinks on;
    expires -1;
    sub_filter '</body>' '</body>';
}'''
SOURCE = b'# Synthetic fixture; not a production nginx configuration.\r\n' + BLOCK + b'\n# keep trailing bytes'


class NginxPatchTests(unittest.TestCase):
    def prepare(self, source):
        with patch.object(subject, 'EXPECTED_SHA256', hashlib.sha256(source).hexdigest()):
            return subject.prepare_nginx(source)

    def reject(self, source, error='anchor_changed'):
        with self.assertRaisesRegex(ValueError, error):
            self.prepare(source)

    def test_pinned_production_hash_and_wrong_hash_rejected(self):
        self.assertEqual(subject.EXPECTED_SHA256,
                         '3b77089472b1f21e25f05015055e0badfec4836569c7836d2d23d38359733db0')
        with self.assertRaisesRegex(ValueError, 'baseline_changed'):
            subject.prepare_nginx(SOURCE)

    def test_exact_four_routes_auth_methods_alias_and_original_bytes(self):
        result = self.prepare(SOURCE)
        self.assertEqual(result[:len(SOURCE)], SOURCE)
        expected = b'\n' + b'\n'.join(
            BLOCK.replace(b'data-workspace.js', name) + b'\n' for name in subject.FILENAMES)
        self.assertEqual(result[len(SOURCE):], expected)
        self.assertEqual(result.count(b'location = '), 5)
        for name in subject.FILENAMES:
            block = BLOCK.replace(b'data-workspace.js', name)
            self.assertEqual(result.count(block), 1)
            self.assertIn(b'location = ' + subject.ASSET_PREFIX + name + b' {', block)
            self.assertIn(b'alias ' + subject.ALIAS_PREFIX + name + b';', block)
            self.assertIn(b'if ($request_method !~ ^(GET|HEAD)$) { return 405; }', block)
            self.assertIn(b'auth_request /__nav_formal_native_session;', block)
        self.assertNotIn(b'location /dashboard/workspace-assets/', result)

    def test_absent_duplicate_commented_and_nonexact_anchors_rejected(self):
        for source in (b'# no anchor', BLOCK + b'\n' + BLOCK,
                       b'\n'.join(b'# ' + line for line in BLOCK.splitlines()),
                       BLOCK.replace(b'location = ', b'location '),
                       BLOCK.replace(b'location = ', b'location ^~ '),
                       b'server {\n' + BLOCK + b'\n}'):
            with self.subTest(source=source[:60]):
                self.reject(source)

    def test_existing_routes_refused_including_quoted_and_prefix_locations(self):
        for name in subject.FILENAMES:
            for header in (b'location = ' + subject.ASSET_PREFIX + name,
                           b'location "' + subject.ASSET_PREFIX + name + b'"',
                           b'location ~ ' + name):
                with self.subTest(header=header):
                    self.reject(SOURCE + b'\n' + header + b' { return 200; }',
                                'routes_already_present')
        self.reject(self.prepare(SOURCE), 'routes_already_present')

    def test_missing_or_bypassed_security_and_content_directives_refused(self):
        changes = (
            (b'GET|HEAD', b'GET|HEAD|POST'),
            (b'^(GET|HEAD)$', b'GET|HEAD'),
            (b'return 405;', b'return 200;'),
            (b'auth_request /__nav_formal_native_session;', b'auth_request off;'),
            (b'error_page 401 = @auth_login;', b'error_page 401 = /public;'),
            (b'types { }', b'types { text/plain js; }'),
            (b'default_type application/javascript;', b'default_type text/plain;'),
            (b'/var/lib/fs-navigation-formal-static/', b'/var/www/public/'),
            (b'disable_symlinks on;', b'disable_symlinks off;'),
            (b'expires -1;', b'expires 1d;'),
            (b"sub_filter '</body>' '</body>';", b''),
            (b'auth_request /__nav_formal_native_session;',
             b'# auth_request /__nav_formal_native_session;'),
            (b'auth_request /__nav_formal_native_session;',
             b'auth_request /__nav_formal_native_session; satisfy any; allow all;'),
        )
        for old, new in changes:
            with self.subTest(old=old, new=new):
                self.reject(BLOCK.replace(old, new))
        for line in BLOCK.splitlines()[1:-1]:
            with self.subTest(missing=line):
                self.reject(BLOCK.replace(line, b''))

    def test_comments_and_quoted_braces_do_not_fake_active_blocks(self):
        source = b'# location = ignored { }\n' + SOURCE + b'\n# order-email-panel.js'
        self.assertTrue(self.prepare(source).startswith(source))
        self.reject(BLOCK.replace(b'expires -1;', b'expires -1; set $fake "}";'))
        for source in (BLOCK[:-1], BLOCK + b'\n}', BLOCK + b'\n"unterminated'):
            self.reject(source)


if __name__ == '__main__':
    unittest.main()
