"""Readable projection of the one existing FS handbook HTML response."""
from html.parser import HTMLParser
import re

from .redaction import redact


class DocumentError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _HandbookParser(HTMLParser):
    ignored_tags = {'script', 'style', 'template', 'noscript', 'iframe', 'svg', 'canvas', 'object'}
    boundaries = {'p', 'div', 'section', 'article', 'main', 'header', 'footer', 'nav',
                  'ul', 'ol', 'dl', 'dt', 'dd', 'blockquote', 'pre', 'hr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.blocks, self.parts = [], [], []
        self.ignored = []
        self.in_title = False
        self.kind, self.level = 'paragraph', None
        self.cells, self.in_cell = None, False

    @staticmethod
    def clean(parts):
        return re.sub(r'\s+', ' ', ''.join(parts)).strip()

    def flush(self):
        text = ''.join(self.parts).strip('\r\n') if self.kind == 'preformatted' else self.clean(self.parts)
        self.parts = []
        if text:
            self.blocks.append(dict(type=self.kind, text=text,
                                    **({'level': self.level} if self.level is not None else {})))

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored_tags:
            self.ignored.append(tag)
        if self.ignored:
            return
        if tag == 'title':
            self.in_title = True
        elif tag == 'tr':
            self.flush()
            self.cells = []
        elif tag in ('td', 'th') and self.cells is not None:
            self.parts = []
            self.in_cell = True
        elif tag == 'br':
            self.parts.append(' ')
        elif not self.in_cell and (tag in self.boundaries or tag == 'li' or re.fullmatch(r'h[1-6]', tag)):
            self.flush()
            self.kind = ('heading' if re.fullmatch(r'h[1-6]', tag) else 'list_item' if tag == 'li'
                         else 'preformatted' if tag == 'pre' else 'paragraph')
            self.level = int(tag[1]) if self.kind == 'heading' else None

    def handle_endtag(self, tag):
        if self.ignored:
            if tag in self.ignored:
                self.ignored = self.ignored[:len(self.ignored)-1-self.ignored[::-1].index(tag)]
            return
        if tag == 'title':
            self.in_title = False
        elif tag in ('td', 'th') and self.cells is not None:
            self.cells.append(self.clean(self.parts))
            self.parts = []
            self.in_cell = False
        elif tag == 'tr' and self.cells is not None:
            if any(self.cells):
                self.blocks.append(dict(type='table_row', text=' | '.join(self.cells)))
            self.cells = None
        elif not self.in_cell and (tag in self.boundaries or tag == 'li' or re.fullmatch(r'h[1-6]', tag)):
            self.flush()
            self.kind, self.level = 'paragraph', None

    def handle_data(self, data):
        if self.ignored:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.parts.append(data)


def parse_handbook(raw):
    """Decode and project already-authorized bytes; never accept a URL or local path."""
    if not isinstance(raw, bytes):
        raise DocumentError('invalid_document_bytes')
    try:
        html = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise DocumentError('invalid_document_encoding') from None
    if '\x00' in html:
        raise DocumentError('invalid_document_html')
    parser = _HandbookParser()
    try:
        parser.feed(html)
        parser.close()
        parser.flush()
    except (ValueError, AssertionError):
        raise DocumentError('invalid_document_html') from None
    title = parser.clean(parser.title)
    original = dict(title=title, blocks=parser.blocks)
    blocks = [{**block, 'text': redact(block['text'])} for block in parser.blocks]
    projected_title = redact(title)
    return dict(title=projected_title, blocks=blocks,
                text='\n\n'.join(block['text'] for block in blocks),
                redacted=projected_title != original['title'] or blocks != original['blocks'])
