import unittest

from fs_mcp_connector.documents import DocumentError, parse_handbook
from fs_mcp_connector.redaction import redact


class DocumentsTests(unittest.TestCase):
    def parse(self, html):
        return parse_handbook(html.encode('utf-8'))

    def test_chinese_title_headings_paragraphs_lists_and_entities(self):
        value = self.parse('<html><head><title>丰实 &amp; 部门手册</title></head><body>'
            '<h1>部门手册</h1><p>中文<b>正文</b> &lt;说明&gt; &#x4E2D;&#25991;。</p>'
            '<h2>工作流程</h2><ul><li>第一步</li><li>第二步<br>继续</li></ul>'
            '<table><tr><th>字段</th><th>说明</th></tr><tr><td>销售额</td><td>美元</td></tr></table>'
            '</body></html>')
        self.assertEqual(value['title'], '丰实 & 部门手册')
        self.assertEqual(value['blocks'][0], {'type': 'heading', 'text': '部门手册', 'level': 1})
        self.assertEqual(value['blocks'][1]['text'], '中文正文 <说明> 中文。')
        self.assertIn({'type': 'heading', 'text': '工作流程', 'level': 2}, value['blocks'])
        self.assertIn({'type': 'list_item', 'text': '第二步 继续'}, value['blocks'])
        self.assertIn({'type': 'table_row', 'text': '销售额 | 美元'}, value['blocks'])
        self.assertFalse(value['redacted'])

    def test_scripts_styles_templates_and_attributes_never_become_document_text(self):
        value = self.parse('<title>手册</title><style>.x{content:"private-style"}</style>'
            '<script>document.write("private-script");</script><template><p>private-template</p></template>'
            '<noscript>private-noscript</noscript><svg><text>private-svg</text></svg>'
            '<p>正文<a href="https://host/?token=private">可读链接</a></p>'
            '<input value="private-input"><!--private-comment--><p>后续正文</p>')
        self.assertEqual(value['text'], '正文可读链接\n\n后续正文')
        self.assertNotIn('private', str(value))

    def test_original_document_redaction_is_reused(self):
        content = '联系 owner@example.test https://host.test/a?access_token=private-value api_key='+'a'*30
        value = self.parse('<title>owner@example.test</title><p>'+content+'</p>')
        self.assertEqual(value['blocks'][0]['text'], redact(content))
        self.assertEqual(value['title'], redact('owner@example.test'))
        self.assertTrue(value['redacted'])
        self.assertIn('owner@example.test', value['text'])
        self.assertNotIn('private-value', value['text'])
        self.assertNotIn('a'*30, value['text'])

    def test_invalid_encoding_and_null_bytes_are_explicit_errors(self):
        for raw, code in [(b'\xff\xfe<\x00h\x00', 'invalid_document_encoding'),
                          ('中文'.encode('gb18030'), 'invalid_document_encoding'),
                          (b'<p>bad\x00html</p>', 'invalid_document_html'),
                          ('<p>text</p>', 'invalid_document_bytes')]:
            with self.subTest(code=code), self.assertRaises(DocumentError) as error:
                parse_handbook(raw)
            self.assertEqual(error.exception.code, code)

    def test_utf8_bom_unclosed_paragraph_and_empty_document(self):
        self.assertEqual(parse_handbook(b'\xef\xbb\xbf<p>Text')['text'], 'Text')
        self.assertEqual(parse_handbook(b'<style>only CSS</style>')['blocks'], [])
        self.assertEqual(parse_handbook(b'')['text'], '')
        self.assertEqual(self.parse('<p>First<hr>Second<pre>command one\n  command two</pre>')['blocks'],
            [{'type': 'paragraph', 'text': 'First'}, {'type': 'paragraph', 'text': 'Second'},
             {'type': 'preformatted', 'text': 'command one\n  command two'}])


if __name__ == '__main__':
    unittest.main()
