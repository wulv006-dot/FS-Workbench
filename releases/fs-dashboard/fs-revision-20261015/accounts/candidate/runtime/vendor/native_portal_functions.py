# Exact selected native source functions. No main/config/password file load on import.
import base64,hashlib,hmac,json,os,threading,time
CFG={}
GROUPS={}
_B64="./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_ht_cache={}
_ht_lock=threading.Lock()

def _to64(v, n):
    out = []
    while n > 0:
        out.append(_B64[v & 0x3F])
        v >>= 6
        n -= 1
    return "".join(out)

def apr1_md5(password, salt):
    """Apache $apr1$ (md5-crypt) 摘要，纯标准库实现。

    注意：alt[i % 16] 在 Python3 里是 int，必须切片成 bytes 再 update，
    否则 hashlib 会抛 TypeError —— 这是移植该算法最常见的坑。
    """
    magic = b"$apr1$"
    pw = password.encode("utf-8")
    sb = salt.encode("ascii")

    ctx = hashlib.md5(pw + magic + sb)
    alt = hashlib.md5(pw + sb + pw).digest()
    for i in range(len(pw)):
        ctx.update(alt[i % 16:i % 16 + 1])
    i = len(pw)
    while i:
        ctx.update(b"\x00" if (i & 1) else pw[0:1])
        i >>= 1
    digest = ctx.digest()

    for i in range(1000):
        c = hashlib.md5()
        c.update(pw if (i & 1) else digest)
        if i % 3:
            c.update(sb)
        if i % 7:
            c.update(pw)
        c.update(digest if (i & 1) else pw)
        digest = c.digest()

    seq = [
        (digest[0] << 16) | (digest[6] << 8) | digest[12],
        (digest[1] << 16) | (digest[7] << 8) | digest[13],
        (digest[2] << 16) | (digest[8] << 8) | digest[14],
        (digest[3] << 16) | (digest[9] << 8) | digest[15],
        (digest[4] << 16) | (digest[10] << 8) | digest[5],
        digest[11],
    ]
    return "$apr1$" + salt + "$" + "".join(_to64(v, 4) for v in seq[:5]) + _to64(seq[5], 2)

def check_hash(password, stored):
    """校验明文密码与 htpasswd 中的摘要是否匹配。"""
    if not stored:
        return False
    stored = stored.strip()
    try:
        if stored.startswith("$apr1$"):
            parts = stored.split("$")
            # ['', 'apr1', '<salt>', '<hash>']
            if len(parts) < 4:
                return False
            salt = parts[2][:8]
            return hmac.compare_digest(apr1_md5(password, salt), stored)
        if stored.startswith("{SHA}"):
            d = base64.b64encode(hashlib.sha1(password.encode("utf-8")).digest()).decode()
            return hmac.compare_digest("{SHA}" + d, stored)
        if stored.startswith("$5$") or stored.startswith("$6$"):
            import crypt
            return hmac.compare_digest(crypt.crypt(password, stored), stored)
        if stored.startswith("$2"):          # bcrypt：标准库无实现，明确不支持
            return False
        # 退化为明文比对（老文件可能出现）
        return hmac.compare_digest(password, stored)
    except Exception:
        return False

def load_htpasswd(path):
    try:
        st = os.stat(path)
        key = (st.st_mtime, st.st_size)
    except OSError:
        return {}
    with _ht_lock:
        hit = _ht_cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
    users = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                u, h = line.split(":", 1)
                users[u.strip()] = h.strip()
    except OSError:
        return {}
    with _ht_lock:
        _ht_cache[path] = (key, users)
    return users

def authenticate(username, password):
    """在所有组里找这个账号；返回命中的组列表。"""
    hits = []
    for gname, gpath in GROUPS.items():
        users = load_htpasswd(gpath)
        if username in users and check_hash(password, users[username]):
            hits.append(gname)
    return hits

def groups_of(username):
    """已登录用户当前仍有效的组（用户名从凭据里来，视为可信）。"""
    return [g for g, p in GROUPS.items() if username in load_htpasswd(p)]

def _b64e(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def _b64d(txt):
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)

def _sign(payload_b64):
    mac = hmac.new(CFG["secret"].encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return _b64e(mac.digest())

def make_token(username, groups, ttl_seconds):
    payload = {
        "u": username,
        "g": ",".join(groups),
        "e": int(time.time()) + int(ttl_seconds),
        "n": _b64e(os.urandom(9)),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    return body + "." + _sign(body)

def read_token(token):
    """校验签名与有效期；通过返回 payload，否则 None。"""
    if not token or "." not in token:
        return None
    body, _, sig = token.rpartition(".")
    if not body or not sig:
        return None
    if not hmac.compare_digest(_sign(body), sig):
        return None
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("e") or 0) < int(time.time()):
        return None
    if not payload.get("u"):
        return None
    return payload

def parse_cookies(header):
    jar = {}
    for part in (header or "").split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        jar[k.strip()] = v.strip()
    return jar
