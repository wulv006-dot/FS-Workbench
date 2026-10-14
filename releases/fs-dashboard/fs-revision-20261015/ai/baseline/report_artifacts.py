"""Idempotent dedicated report files in FS; no general file-write API."""
import hashlib,json,os,re,secrets
from pathlib import Path


def digest_bytes(value):return hashlib.sha256(value).hexdigest()


def write_file(path,value):
    path=Path(path)
    if path.is_symlink():raise ValueError('report_path_linked')
    if path.exists():
        if path.read_bytes()!=value:raise ValueError('report_artifact_conflict')
        return digest_bytes(value)
    temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        with temporary.open('xb') as out:out.write(value);out.flush();os.fsync(out.fileno())
        temporary.chmod(0o600);temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()
    return digest_bytes(value)


def directory(root,task,create=True):
    if not isinstance(task,str) or not re.fullmatch(r'[a-f0-9]{32}',task):raise ValueError('report_task_identity')
    path=Path(root)/'reports'/task
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('report_path_linked')
    if create:path.mkdir(parents=True,exist_ok=True,mode=0o700)
    return path


def save_raw(root,task,text,evidence,metadata):
    path=directory(root,task)
    raw=text.encode('utf-8');ev=json.dumps(evidence,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    receipt=dict(metadata,contract='fs-hermes-report-artifact-v1',task=task,raw_sha256=digest_bytes(raw),evidence_sha256=digest_bytes(ev))
    write_file(path/'model.txt',raw);write_file(path/'evidence.json',ev)
    write_file(path/'metadata.json',json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    return receipt


def save_result(root,task,result,html):
    path=directory(root,task);raw=json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    hashes={'html_sha256':write_file(path/'report.html',html.encode('utf-8')),'result_sha256':write_file(path/'result.json',raw)}
    write_file(path/'ready.json',json.dumps(hashes,sort_keys=True).encode())
    return hashes


def read_file(root,task,kind):
    names={'raw':('model.txt','text/plain; charset=utf-8'),'html':('report.html','text/html; charset=utf-8'),'json':('result.json','application/json; charset=utf-8')}
    if kind not in names:raise ValueError('report_artifact_kind')
    name,mime=names[kind];path=directory(root,task,create=False)/name
    if path.is_symlink():raise ValueError('report_path_linked')
    value=path.read_bytes()
    receipt_path=path.parent/('metadata.json' if kind=='raw' else 'ready.json')
    if receipt_path.is_symlink():raise ValueError('report_path_linked')
    receipt=json.loads(receipt_path.read_text('utf-8'))
    expected=receipt['raw_sha256' if kind=='raw' else 'html_sha256' if kind=='html' else 'result_sha256']
    if digest_bytes(value)!=expected:raise ValueError('report_artifact_changed')
    return {'content':value.decode('utf-8'),'mime':mime,'sha256':digest_bytes(value),'filename':'FC27_Hermes_'+task[:12]+('.html' if kind=='html' else '.json' if kind=='json' else '.txt')}
