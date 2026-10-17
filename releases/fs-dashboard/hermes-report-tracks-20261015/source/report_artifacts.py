"""Idempotent dedicated report files in FS; no general file-write API."""
import hashlib,json,os,re,secrets
from datetime import datetime,timezone
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
    try:save_boss(root,task)
    except Exception:
        # A layout failure must not replay paid research or invalidate its immutable files.
        import logging
        logging.getLogger(__name__).warning('boss_report_render_failed; original research remains available')
    return hashes


def save_boss(root,task):
    from boss_projection import project
    from boss_renderer import render
    path=directory(root,task,create=False)
    def checked(name):
        p=path/name
        if p.is_symlink():raise ValueError('report_path_linked')
        return p.read_bytes()
    receipt=json.loads(checked('metadata.json'));ready=json.loads(checked('ready.json'))
    raw_result=checked('result.json');raw_evidence=checked('evidence.json');research=checked('report.html');original=checked('model.txt')
    if (digest_bytes(raw_result)!=ready['result_sha256'] or digest_bytes(research)!=ready['html_sha256'] or
            digest_bytes(raw_evidence)!=receipt['evidence_sha256'] or digest_bytes(original)!=receipt['raw_sha256']):raise ValueError('report_artifact_changed')
    result=json.loads(raw_result);evidence=json.loads(raw_evidence)
    result.setdefault('raw_model_text',original.decode('utf-8'))
    context=dict(receipt,artifact_written_at=datetime.fromtimestamp((path/'model.txt').stat().st_mtime,timezone.utc).isoformat())
    source_root=Path(__file__).resolve().parent
    pricing=receipt.get('report_track')=='pricing' or result.get('report_track')=='pricing'
    contract='fs-hermes-pricing-artifact-v1' if pricing else 'fs-hermes-boss-artifact-v2'
    source_names=('report_artifacts.py','pricing_report.py','report_tracks.py','boss_renderer.py') if pricing else ('report_artifacts.py','boss_projection.py','boss_renderer.py','report_semantics.py','report_constraints.py','report.template.html')
    sources={name:digest_bytes((source_root/name).read_bytes()) for name in source_names}
    revision=digest_bytes(json.dumps({'contract':contract,'sources':sources,'raw':receipt['raw_sha256'],
                                     'evidence':receipt['evidence_sha256'],'result':ready['result_sha256'],'research':ready['html_sha256']},sort_keys=True).encode())[:16]
    prefix=('pricing-report-v1-' if pricing else 'boss-semantic-v2-')+revision
    if pricing:
        from pricing_report import project as pricing_project,render as pricing_render
        content=pricing_project(result,evidence,context)
        rendered=pricing_render(result,evidence,context).encode('utf-8')
    else:
        content=project(result,evidence,context,ready['html_sha256'])
        rendered=render(content,evidence).encode('utf-8')
    body=json.dumps(content,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    proof={'contract':contract,'report_track':'pricing' if pricing else 'operations','revision':revision,'sources':sources,'task':task,'status':'ready',
           'html_file':prefix+'.html','content_file':prefix+'.content.json','receipt_file':prefix+'-ready.json',
           'html_sha256':write_file(path/(prefix+'.html'),rendered),'content_sha256':write_file(path/(prefix+'.content.json'),body),
           'evidence_sha256':receipt['evidence_sha256'],'research_html_sha256':ready['html_sha256'],'result_sha256':ready['result_sha256']}
    write_file(path/(prefix+'-ready.json'),json.dumps(proof,sort_keys=True).encode())
    return proof


def read_file(root,task,kind):
    names={'raw':('model.txt','text/plain; charset=utf-8'),'html':('report.html','text/html; charset=utf-8'),'json':('result.json','application/json; charset=utf-8'),'boss':('boss-report.html','text/html; charset=utf-8')}
    if kind not in names:raise ValueError('report_artifact_kind')
    name,mime=names[kind]
    proof=save_boss(root,task) if kind=='boss' else None
    if proof:name=proof['html_file']
    path=directory(root,task,create=False)/name
    if path.is_symlink():raise ValueError('report_path_linked')
    value=path.read_bytes()
    receipt_path=path.parent/('metadata.json' if kind=='raw' else proof['receipt_file'] if kind=='boss' else 'ready.json')
    if receipt_path.is_symlink():raise ValueError('report_path_linked')
    receipt=json.loads(receipt_path.read_text('utf-8'))
    expected=receipt['raw_sha256' if kind=='raw' else 'html_sha256' if kind in ('html','boss') else 'result_sha256']
    if digest_bytes(value)!=expected:raise ValueError('report_artifact_changed')
    return {'content':value.decode('utf-8'),'mime':mime,'sha256':digest_bytes(value),'filename':'FC27_Hermes_'+(('pricing_' if proof and proof.get('report_track')=='pricing' else 'boss_') if kind=='boss' else '')+task[:12]+('.html' if kind in ('html','boss') else '.json' if kind=='json' else '.txt')}
