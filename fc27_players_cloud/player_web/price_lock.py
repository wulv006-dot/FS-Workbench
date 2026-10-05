"""与既有 FC27 Coins 写价脚本共用同一个 inode 的进程锁。"""
from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

COINS_PRICE_LOCK = Path("/var/lib/fc27-cloud/state/price-writer.lock")


@contextmanager
def shared_price_lock(path: Path = COINS_PRICE_LOCK) -> Iterator[bool]:
    if os.name != "posix" or path.is_symlink() or not path.is_file():
        yield False
        return
    try:
        # Linux flock supports an exclusive lock on a read-only descriptor.
        # The Players service needs coordination, not permission to edit this file.
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        yield False
        return
    acquired = False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            yield False
            return
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
