"""Owner-maintained desktop instructions, frozen once for each new FS task."""
import hashlib


def read_desktop_context(root):
    path = root / 'desktop-business-context.md'
    if not path.exists():
        return '', None
    if path.is_symlink() or not path.is_file():
        raise ValueError('desktop_business_context_invalid')
    raw = path.read_bytes()
    if len(raw) > 131072:
        raise ValueError('desktop_business_context_too_large')
    text = raw.decode('utf-8-sig').strip()
    return text, hashlib.sha256(raw).hexdigest() if text else None
