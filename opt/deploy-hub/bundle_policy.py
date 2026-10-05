"""Static site publishing policy shared by client/server; no deployment effects."""
import json
import re
from pathlib import PurePosixPath

EXTENSIONS = frozenset(('.html','.htm','.css','.js','.mjs','.json','.webmanifest','.png','.jpg','.jpeg',
    '.gif','.webp','.avif','.svg','.ico','.woff','.woff2','.ttf','.otf','.eot','.wasm','.mp3','.mp4','.ogg','.webm'))
TEXT_EXTENSIONS = frozenset(('.html','.htm','.css','.js','.mjs','.json','.webmanifest','.svg'))
DENIED_DIRS = frozenset(('.git','.svn','.hg','.venv','venv','node_modules','__pycache__','runtime','logs','backups','data','raw'))
DENIED_NAMES = frozenset(('deploy_client.json','hub_config.json','config.json','server_config.json','automation.json',
    '_token.txt','_ck.txt','_api_body.tmp','apply_log.jsonl','.admin_prices.tmp.json','.cookies.txt','.iggm.cookies.txt'))
SECRET = re.compile(r'''(?i)["']?(password|passwd|client_secret|refresh_token|access_token|api_key|session_token|cookie|set-cookie|batoken|authorization)["']?\s*[:=]\s*["']([^"'\n]+)["']''')
TOKEN = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}|\bya29\.[A-Za-z0-9_-]{20,}|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')
CREDENTIAL_KEYS = frozenset(('password','passwd','clientsecret','refreshtoken','accesstoken',
    'apikey','sessiontoken','cookie','setcookie','batoken','authorization'))
AUTH_VALUE = re.compile(r'(?i)^\s*(?:Basic|Bearer)\s+\S+')
HEADER_VALUE = re.compile(r'(?i)^\s*(?:Cookie|Set-Cookie|batoken|Authorization)\s*:\s*\S+')
PLACEHOLDER = re.compile(r'^(?:(?:REPLACE|EXAMPLE|YOUR)_[A-Z0-9_]+|\$\{[A-Za-z_][A-Za-z0-9_]*\}|<[A-Z0-9_]+>)$')

def is_placeholder(value):
    if not isinstance(value,str):return False
    if not value or PLACEHOLDER.fullmatch(value):return True
    # A literal header scheme or an explicit template has no credential bytes.
    auth=re.fullmatch(r'(?i)(Basic|Bearer)(?:\s+(.*))?',value)
    return bool(auth and (not (auth.group(2) or '').strip() or PLACEHOLDER.fullmatch(auth.group(2))))

def _json_pairs(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('DUPLICATE_STATIC_JSON_KEY')
        value[key]=item
    return value

def validate_json_value(value, credential=False):
    """Parsed keys handle JSON unicode escapes; never expose a rejected value."""
    if isinstance(value,dict):
        for key,item in value.items():
            name=re.sub(r'[^a-z0-9]','',key.casefold())
            validate_json_value(item,credential or name in CREDENTIAL_KEYS)
    elif isinstance(value,list):
        for item in value:validate_json_value(item,credential)
    elif isinstance(value,str):
        if not is_placeholder(value) and (credential or AUTH_VALUE.search(value)
                                         or HEADER_VALUE.search(value) or TOKEN.search(value)):
            raise ValueError('SENSITIVE_STATIC_CONTENT_REFUSED')
    elif credential and value not in (None,False):
        raise ValueError('SENSITIVE_STATIC_CONTENT_REFUSED')

def validate_publish_name(name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or name.startswith('/'):
        raise ValueError('UNSAFE_STATIC_MEMBER')
    parts = name.split('/')
    if any(not p or p in ('.','..') or p.endswith((' ','.')) or any(ord(c)<32 for c in p) for p in parts):
        raise ValueError('UNSAFE_STATIC_MEMBER')
    reserved = frozenset(('con','prn','aux','nul','clock$') + tuple('com'+str(i) for i in range(1,10)) + tuple('lpt'+str(i) for i in range(1,10)))
    if any(p.split('.')[0].lower() in reserved or any(c in p for c in '<>"|?*%') for p in parts):
        raise ValueError('UNSAFE_STATIC_MEMBER')
    low = [p.lower() for p in parts]
    if any(p in DENIED_DIRS or p.startswith('.') for p in low):
        raise ValueError('PRIVATE_STATIC_MEMBER_REFUSED')
    fn = low[-1]
    if fn in DENIED_NAMES or any(x in fn for x in ('cookie','token','credential','password','secret')):
        raise ValueError('PRIVATE_STATIC_MEMBER_REFUSED')
    if PurePosixPath(fn).suffix not in EXTENSIONS:
        raise ValueError('STATIC_TYPE_NOT_ALLOWED')
    return name

def validate_publish_content(name, data):
    validate_publish_name(name)
    if PurePosixPath(name).suffix.lower() not in TEXT_EXTENSIONS:
        return
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('STATIC_TEXT_ENCODING_REFUSED') from None
    if TOKEN.search(text):
        raise ValueError('SENSITIVE_STATIC_CONTENT_REFUSED')
    if PurePosixPath(name).suffix.lower() in ('.json','.webmanifest'):
        try:
            value=json.loads(text,object_pairs_hook=_json_pairs,
                parse_constant=lambda value:(_ for _ in ()).throw(ValueError('INVALID_STATIC_JSON')))
            validate_json_value(value)
        except (json.JSONDecodeError,RecursionError):
            raise ValueError('INVALID_STATIC_JSON') from None
    for match in SECRET.finditer(text):
        value = match.group(2)
        if is_placeholder(value):
            continue
        raise ValueError('SENSITIVE_STATIC_CONTENT_REFUSED')

def escaped_text(value):
    import html
    return html.escape(str(value or ''), quote=True)

def validated_zip_members(data, max_files=5000, max_unzip=300*1024*1024):
    """Validate every member and CRC before returning any bytes to the writer."""
    import io
    import zipfile
    import stat
    result, seen, files, total = [], set(), set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > max_files:
                raise ValueError('STATIC_MEMBER_LIMIT')
            for info in infos:
                raw = info.filename
                if info.flag_bits & 1:
                    raise ValueError('ENCRYPTED_STATIC_MEMBER_REFUSED')
                mode = (info.external_attr >> 16) & 0xF000
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError('SPECIAL_STATIC_MEMBER_REFUSED')
                directory = info.is_dir()
                name = raw[:-1] if directory else raw
                # Reuse full path validation without granting a file type exception.
                validate_publish_name(name + '/directory-check.css' if directory else name)
                key = name.casefold()
                if key in seen:
                    raise ValueError('DUPLICATE_STATIC_MEMBER_REFUSED')
                seen.add(key)
                parents = ['/'.join(key.split('/')[:i]) for i in range(1,len(key.split('/')))]
                if any(p in files for p in parents) or (not directory and any(s.startswith(key+'/') for s in seen)):
                    raise ValueError('STATIC_HIERARCHY_CONFLICT')
                if directory:
                    continue
                files.add(key)
                total += info.file_size
                if total > max_unzip or info.file_size < 0:
                    raise ValueError('STATIC_BYTE_LIMIT')
                payload = archive.read(info)  # CRC checked by zipfile, bounded by declared size.
                if len(payload) != info.file_size:
                    raise ValueError('STATIC_SIZE_MISMATCH')
                validate_publish_content(name, payload)
                result.append((name, payload))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ValueError('INVALID_STATIC_ARCHIVE') from None
    if not result:
        raise ValueError('EMPTY_STATIC_ARCHIVE')
    return result
