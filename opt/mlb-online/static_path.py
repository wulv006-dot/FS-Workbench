"""Portable component boundary for static reads; roots must be trusted/read-only."""
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

def safe_static_path(root, relative):
    if not isinstance(relative, str):
        raise ValueError('INVALID_STATIC_PATH')
    for _ in range(3):
        decoded = unquote(relative)
        if decoded == relative:
            break
        relative = decoded
    if not relative or '\\' in relative or ':' in relative or '\0' in relative or relative.startswith('/'):
        raise ValueError('INVALID_STATIC_PATH')
    parts = relative.split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise ValueError('INVALID_STATIC_PATH')
    base = Path(root).resolve(strict=True)
    current = base
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('STATIC_SYMLINK_REFUSED')
    target = current.resolve(strict=True)
    if not target.is_relative_to(base) or not target.is_file():
        raise ValueError('STATIC_OUTSIDE_ROOT')
    return target
