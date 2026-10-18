"""Immutable aggregate evidence shared by workspace and Hermes adapters."""
from pathlib import Path
import hashlib
import json
import re
MAX_BYTES=1024*1024


def safe_path(path):
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('workspace_evidence_link')


def aggregate_only(value):
    if isinstance(value,dict):
        if set(value)&{'customer_key','uid','order_no','email','phone','address','password','token','cookie','authorization'}:raise ValueError('workspace_raw_identity_forbidden')
        for child in value.values():aggregate_only(child)
    elif isinstance(value,list):
        for child in value:aggregate_only(child)


def save(detail,kind,query,value):
    if value.get('status') not in ('available','partial'):return value
    from fc_detail import atomic
    aggregate_only(value)
    core={'kind':kind,'query':query,'data':value}
    ident='ws_'+hashlib.sha256(json.dumps(core,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    path=Path(detail.cache)/'workspace-evidence'/(ident+'.json')
    safe_path(path)
    if len(json.dumps(core,ensure_ascii=False).encode())>MAX_BYTES:raise ValueError('workspace_evidence_size')
    if not path.exists():atomic(path,core)
    if path.stat().st_size>MAX_BYTES or json.loads(path.read_text('utf-8'))!=core:raise ValueError('workspace_evidence_readback')
    return dict(value,evidence_id=ident,archive_id=ident)


def read(detail,kind,query,ident):
    if not isinstance(ident,str) or not re.fullmatch(r'ws_[a-f0-9]{24}',ident):raise ValueError('workspace_evidence_id')
    path=Path(detail.cache)/'workspace-evidence'/(ident+'.json')
    safe_path(path)
    if not path.exists():return {'status':'unavailable','reason':'workspace_evidence_missing'}
    if path.stat().st_size>MAX_BYTES:raise ValueError('workspace_evidence_size')
    core=json.loads(path.read_text('utf-8'))
    expected='ws_'+hashlib.sha256(json.dumps(core,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    if expected!=ident or core['kind']!=kind or core['query']!=query:raise ValueError('workspace_evidence_scope_or_integrity')
    return dict(core['data'],evidence_id=ident,archive_id=ident)
