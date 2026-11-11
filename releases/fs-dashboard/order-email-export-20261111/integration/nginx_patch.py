"""Pure, baseline-pinned addition of four authenticated exact asset routes."""
import hashlib
import re

EXPECTED_SHA256 = '3b77089472b1f21e25f05015055e0badfec4836569c7836d2d23d38359733db0'
ASSET_PREFIX = b'/dashboard/workspace-assets/workspace-native-20261006-4f4a56f7a335/'
ALIAS_PREFIX = b'/var/lib/fs-navigation-formal-static/workspace-native-20261006-4f4a56f7a335/'
FILENAMES = (b'order-email-panel.js', b'order-email-run.js',
             b'order-email-csv.js', b'order-email-xlsx.js')
# Tokens retain offsets so the original block is copied, never reserialized.
_TOKEN = re.compile(rb'''\s+|\#[^\r\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{};]|(?:\\.|[^\s{};#'"\\])+''')


def _tokens(source):
    result = []
    offset = 0
    for match in _TOKEN.finditer(source):
        if match.start() != offset:
            raise ValueError('nginx_anchor_changed')
        offset = match.end()
        raw = match.group()
        if raw.isspace() or raw.startswith(b'#'):
            continue
        value = raw[1:-1] if raw[:1] in (b'"', b"'") else raw
        result.append((value, match.start(), match.end()))
    if offset != len(source):
        raise ValueError('nginx_anchor_changed')
    return result


def _directives(tokens):
    """Parse the pinned include's directives; not a general nginx validator."""
    position = 0

    def parse(nested=False):
        nonlocal position
        result = []
        while position < len(tokens):
            start = position
            header = []
            while position < len(tokens) and tokens[position][0] not in (b'{', b'}', b';'):
                header.append(tokens[position][0])
                position += 1
            if position == len(tokens):
                raise ValueError('nginx_anchor_changed')
            delimiter = tokens[position][0]
            position += 1
            if delimiter == b'}':
                if not nested or header:
                    raise ValueError('nginx_anchor_changed')
                return result
            if not header:
                raise ValueError('nginx_anchor_changed')
            children = parse(True) if delimiter == b'{' else None
            result.append((tuple(header), children, tokens[start][1], tokens[position - 1][2]))
        if nested:
            raise ValueError('nginx_anchor_changed')
        return result

    return parse()


def prepare_nginx(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != EXPECTED_SHA256:
        raise ValueError('nginx_baseline_changed')
    directives = _directives(_tokens(source))
    anchors = []

    def inspect(items, nested=False):
        for header, children, start, end in items:
            if header[0] == b'location':
                if any(name in part for name in FILENAMES for part in header[1:]):
                    raise ValueError('nginx_routes_already_present')
                if header == (b'location', b'=', ASSET_PREFIX + b'data-workspace.js'):
                    if nested:
                        raise ValueError('nginx_anchor_changed')
                    anchors.append((children, start, end))
            if children is not None:
                inspect(children, True)

    inspect(directives)
    if len(anchors) != 1:
        raise ValueError('nginx_anchor_changed')
    body, start, end = anchors[0]
    required = {
        (b'auth_request', b'/__nav_formal_native_session'),
        (b'error_page', b'401', b'=', b'@auth_login'),
        (b'default_type', b'application/javascript'),
        (b'alias', ALIAS_PREFIX + b'data-workspace.js'),
        (b'disable_symlinks', b'on'), (b'expires', b'-1'),
        (b'sub_filter', b'</body>', b'</body>'),
    }
    seen = set()
    methods = types = 0
    for header, children, _, _ in body:
        if header in required and children is None and header not in seen:
            seen.add(header)
        elif header == (b'types',) and children == []:
            types += 1
        elif (header == (b'if', b'($request_method', b'!~', b'^(GET|HEAD)$)')
              and children is not None and len(children) == 1
              and children[0][:2] == ((b'return', b'405'), None)):
            methods += 1
        else:
            raise ValueError('nginx_anchor_changed')
    if seen != required or methods != 1 or types != 1:
        raise ValueError('nginx_anchor_changed')
    block = source[start:end]
    if block.count(b'data-workspace.js') != 2:
        raise ValueError('nginx_anchor_changed')
    return source + b'\n' + b'\n'.join(
        block.replace(b'data-workspace.js', name) + b'\n' for name in FILENAMES)
