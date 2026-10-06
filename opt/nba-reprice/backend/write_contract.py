"""NBA immutable plan binding and no-replay receipts; upstream execution is supplied by caller."""
import contextlib
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import sys

_mutex=threading.RLock()
_state=threading.local()

@contextlib.contextmanager
def serialized_runtime(root):
    """One whole writer/login/cookie lifecycle. Never remove or 'clear' the lock file."""
    with _mutex:
        if getattr(_state,'depth',0):
            _state.depth+=1
            try:yield
            finally:_state.depth-=1
            return
        root=Path(root);_ensure_directory(root)
        fd=os.open(root/'writer.lock',os.O_RDWR|os.O_CREAT,0o600)
        stream=os.fdopen(fd,'r+b')
        locked=False
        try:
            if os.name=='nt':
                import msvcrt
                if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
                stream.seek(0)
                try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                except OSError:raise RuntimeError('WRITER_BUSY') from None
            else:
                import fcntl
                try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise RuntimeError('WRITER_BUSY') from None
            locked=True;_state.depth=1
            yield
        finally:
            _state.depth=0
            if locked:
                if os.name=='nt':
                    stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
            stream.close()

def serialized(root):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args,**kwargs):
            with serialized_runtime(root):return fn(*args,**kwargs)
        return wrapped
    return decorate

def validate_envelope(envelope):
    if not isinstance(envelope,dict) or set(envelope)!={'requestId','planSha256','planJson'}:
        raise ValueError('BOUND_PLAN_REQUIRED')
    request_id=envelope['requestId'];plan_hash=envelope['planSha256'];raw=envelope['planJson']
    if not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{32}',request_id):
        raise ValueError('INVALID_REQUEST_ID')
    if not isinstance(raw,str) or len(raw)>10000 or not isinstance(plan_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',plan_hash):
        raise ValueError('INVALID_PLAN_BINDING')
    if hashlib.sha256(raw.encode('utf-8')).hexdigest()!=plan_hash:
        raise ValueError('PLAN_HASH_MISMATCH')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('DUPLICATE_PLAN_KEY')
            result[key]=value
        return result
    plan=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(plan,dict) or set(plan)!={'confirm','operator','prices'} or plan['confirm']!='NBA_PRICE_APPLY':
        raise ValueError('CONFIRMED_PLAN_REQUIRED')
    if plan['operator'] not in ('wulv','chenchao','DY'):raise ValueError('ADMIN_REQUIRED')
    prices=plan['prices'];allowed={'PlayStation 5','Xbox Series X|S','PC Platform'}
    if not isinstance(prices,dict) or not prices or not set(prices)<=allowed:raise ValueError('INVALID_PLATFORMS')
    for value in prices.values():
        if type(value) not in (float,int) or not math.isfinite(value) or not 0<value<=9007199254740991 or round(value,4)<=0:
            raise ValueError('INVALID_PRICE')
    return request_id,plan_hash,plan

def persistence_capability():
    return 'linux-directory-fsync' if sys.platform=='linux' else 'file-fsync-only-no-power-loss-guarantee'

def _sync_directory(path):
    # Windows/other platforms do not claim Linux directory-entry durability.
    if sys.platform!='linux':return
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def _ensure_directory(path):
    if not path.exists():
        _ensure_directory(path.parent)
        path.mkdir(mode=0o700,exist_ok=True)
    # Also retry a previous failed mkdir sync before allowing a write.
    _sync_directory(path.parent)
    _sync_directory(path)

def _persist(path,value):
    # Directory is trusted operator-owned runtime, outside source. Atomic same-directory replacement.
    import tempfile
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.receipt-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,separators=(',',':'));f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)

def execute_bound_plan(root,envelope,execute):
    request_id,plan_hash,plan=validate_envelope(envelope)
    identity={'requestId':request_id,'planSha256':plan_hash,'operator':plan['operator'],
              'persistence':persistence_capability()}
    with serialized_runtime(root):
        folder=Path(root)/'receipts';_ensure_directory(folder)
        path=folder/(request_id+'.json')
        if path.exists():
            try:old=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):
                return {**identity,'ok':False,'error':'RECEIPT_READ_FAILED','state':'unknown'}
            if not isinstance(old,dict):
                return {**identity,'ok':False,'error':'RECEIPT_READ_FAILED','state':'unknown'}
            if any(old.get(k)!=identity[k] for k in ('requestId','planSha256','operator')):raise ValueError('REQUEST_ID_CONFLICT')
            if old.get('state')!='completed' or type(old.get('ok')) is not bool:
                return {**identity,'ok':False,'error':'WRITE_OUTCOME_UNKNOWN','state':'unknown'}
            return {**old,'persistence':old.get('persistence','unrecorded-no-power-loss-guarantee'),'replayedReceipt':True}
        try:_persist(path,{**identity,'state':'pending','ok':False})
        except OSError:
            return {**identity,'state':'rejected','ok':False,'error':'PENDING_PERSIST_FAILED'}
        try:
            result=execute(plan)
        except Exception:
            # Keep pending: no new write for this ID, including after crash/timeout.
            return {**identity,'ok':False,'error':'WRITE_OUTCOME_UNKNOWN','state':'unknown'}
        if not isinstance(result,dict) or type(result.get('ok')) is not bool:
            return {**identity,'ok':False,'error':'WRITE_OUTCOME_UNKNOWN','state':'unknown'}
        receipt={**result,**identity,'state':'completed'}
        try:_persist(path,receipt)
        except OSError:
            return {**identity,'state':'unknown','ok':False,'error':'WRITE_OUTCOME_UNKNOWN'}
        return receipt
