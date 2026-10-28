"""Two existing transaction targets through the original CAS/fence/rollback publisher."""
from contextlib import contextmanager
from pathlib import Path
import os
import stat
import threading

SCOPE='business-transaction-lock-scope-20261029'
TARGETS={'source/atomic_snapshot.py':'/opt/fs-transaction-snapshot/atomic_snapshot.py',
         'source/collector.py':'/opt/fs-transaction-snapshot/collector.py'}
NEW=frozenset()
SNAPSHOT_LOCK='/var/www/dashboard/fs-home/transactions/transaction-snapshot.lock'
ATOMIC_TARGET='/opt/fs-transaction-snapshot/atomic_snapshot.py'
LEGACY_ATOMIC_SHA='7ba36c66a24e735241469440d9a9e634357fc06cb554d8184ef6aaaeb6936a54'


def extend(base):
    if base.HERMES_HISTORY_SCOPE!=SCOPE:raise ValueError('transaction_web_fence_not_bound')
    original_live,original_inspect=base.live_lock,base.inspect
    owned=threading.local()

    @contextmanager
    def snapshot_lock(root,create):
        import fcntl
        path=base.rooted(root,SNAPSHOT_LOCK);base.no_target_link(path)
        if not path.exists():
            source=base.rooted(root,ATOMIC_TARGET);base.no_target_link(source)
            if base.digest(source)!=LEGACY_ATOMIC_SHA:raise ValueError('transaction_snapshot_lock_missing')
            if not create:
                yield
                return
        fd=os.open(str(path),os.O_RDWR|(os.O_CREAT if create else 0)|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            info=os.fstat(fd);current=path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or info.st_mode&0o022
                    or (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino)):
                raise ValueError('unsafe_transaction_snapshot_lock')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('transaction_snapshot_busy') from None
            yield
        finally:os.close(fd)

    @contextmanager
    def live_lock(manifest,root):
        if manifest.get('scope')!=SCOPE:
            with original_live(manifest,root):yield
            return
        # Collection takes snapshot before browser; publication uses the same order.
        with snapshot_lock(root,True),original_live(manifest,root):
            owned.root=Path(root).resolve()
            try:yield
            finally:owned.root=None

    def inspect(manifest,stage,root=Path('/')):
        if manifest.get('scope')!=SCOPE or getattr(owned,'root',None)==Path(root).resolve():
            return original_inspect(manifest,stage,root)
        # Prepare/inspect is read-only; only the pinned legacy collector may lack the new lock.
        with snapshot_lock(root,False),original_live(manifest,root):
            return original_inspect(manifest,stage,root)

    base.live_lock,base.inspect=live_lock,inspect
    return base


def load_base():
    import actual_release
    actual_release.SCOPE,actual_release.TARGETS,actual_release.NEW=SCOPE,TARGETS,NEW
    return extend(actual_release.load_base())


if __name__=='__main__':load_base().main()
