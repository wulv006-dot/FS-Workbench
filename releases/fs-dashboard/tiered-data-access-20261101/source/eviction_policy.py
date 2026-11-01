"""Proof/reference-aware dry-run only. No remove/rename, daemon or new lock."""
import hashlib,math,os,re,stat
from pathlib import Path

PROTECTED_ROOTS=('/var/lib/fs-user-analytics','/var/lib/fc27-es-exports','/var/lib/fc27-cloud')
PROTECTED_SUFFIXES=('.key','.pem','.sqlite3','.db','.xlsx','.xls','.journal')
CHECKS=('scope_enforced','pagination_complete','time_boundaries','required_fields','stable_identity','refund_correction','failures_not_empty')


class Hold(ValueError):pass


def inside(path,root):
    try:path.relative_to(root);return True
    except ValueError:return False


def proof_valid(proof,item,*,fixture=False):
    if not isinstance(proof,dict) or proof.get('verified') is not True:raise Hold('regeneration_not_proven')
    if proof.get('evidence_kind')!=('synthetic' if fixture else 'live'):raise Hold('regeneration_evidence_kind')
    if proof.get('mode')!='current_state' or item.get('mode')!='fresh':raise Hold('historical_asof_not_regenerable')
    if any(proof.get(key)!=item.get(key) for key in ('dataset_id','scope_hash','source_contract')):raise Hold('regeneration_scope_or_contract')
    if not all(proof.get('checks',{}).get(key) is True for key in CHECKS):raise Hold('regeneration_checks_incomplete')
    if any(not isinstance(proof.get(k),str) or not proof[k] for k in ('proof_id','dataset_id','scope_hash','source_contract','stable_key')) or re.fullmatch('[a-f0-9]{64}',str(proof.get('evidence_sha256',''))) is None:raise Hold('regeneration_evidence_missing')
    start,end=item.get('start'),item.get('end_exclusive')
    from date_policy import day
    if not isinstance(start,str) or not isinstance(end,str):raise Hold('regeneration_range_missing')
    if not day(proof['start'])<=day(start)<day(end)<=day(proof['end_exclusive']):raise Hold('regeneration_range_not_covered')
    if type(item.get('fields')) is not list or not item['fields'] or type(proof.get('fields')) is not list or any(type(field) is not str or not field for field in item['fields']+proof['fields']) or not set(item['fields'])<=set(proof['fields']):raise Hold('regeneration_fields_missing')


def evaluate(item,policy,proof,references,*,now,fixture=False):
    """Explicit manifest objects only; unknown files/roots never discovered as cache."""
    if policy.get('contract')!='fs-cache-eviction-dryrun-v1' or policy.get('quarantine_days',0)<7:raise Hold('policy_contract')
    if item.get('classification')!='L1' or item.get('active_job') is not False:raise Hold('protected_or_active_object')
    if item.get('dataset_id') not in policy.get('datasets',[]):raise Hold('dataset_not_managed')
    path=Path(item['path']).absolute()
    if any(part.is_symlink() for part in (path,*path.parents)):raise Hold('symlink_object_or_parent')
    resolved=path.resolve()
    if any(inside(resolved,Path(root)) for root in PROTECTED_ROOTS) or resolved.suffix.lower() in PROTECTED_SUFFIXES:raise Hold('protected_root_or_type')
    roots=[Path(root).absolute() for root in policy.get('roots',[])]
    if not roots or not any(root.is_dir() and not any(p.is_symlink() for p in (root,*root.parents)) and inside(resolved,root.resolve()) for root in roots):raise Hold('outside_managed_root')
    if not re.fullmatch('[a-f0-9]{64}\\.data\\.json',path.name):raise Hold('unknown_file_type')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise Hold('special_or_linked_object')
    if info.st_size>policy['max_object_bytes']:raise Hold('object_budget')
    if type(item.get('expires_at')) not in (int,float) or not math.isfinite(item['expires_at']) or item['expires_at']>now:raise Hold('not_expired')
    if references.get('complete') is not True or not references.get('epoch'):raise Hold('reference_scan_incomplete')
    pins=references.get('pins',{}).get(item['object_id'],None)
    if type(pins) is not int or pins!=0:raise Hold('pinned_or_unknown')
    if item['object_id'] in references.get('references',[]):raise Hold('retained_reference')
    proof_valid(proof,item,fixture=fixture)
    checksum=hashlib.sha256()
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    with os.fdopen(fd,'rb') as source:
        opened=os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev,opened.st_ino,opened.st_size)!=(info.st_dev,info.st_ino,info.st_size):raise Hold('object_changed')
        consumed=0
        for chunk in iter(lambda:source.read(65536),b''):
            consumed+=len(chunk)
            if consumed>info.st_size:raise Hold('object_changed')
            checksum.update(chunk)
    if checksum.hexdigest()!=path.name[:-10] or checksum.hexdigest()!=item['object_id']:raise Hold('object_integrity')
    after=path.stat()
    stamp=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
    if stamp!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise Hold('object_changed')
    return dict(path=str(path),object_id=item['object_id'],bytes=info.st_size,stat=list(stamp),reference_epoch=references['epoch'],proof_id=proof['proof_id'],policy_id=policy['policy_id'],
                action='candidate_for_existing_reversible_quarantine',dry_run=True)


def dry_run(items,policy,proofs,reference_reader,*,now,fixture=False):
    candidates=[];held=[];total=0
    for item in items:
        try:
            refs=reference_reader(item['dataset_id'])
            row=evaluate(item,policy,proofs.get(item.get('proof_id')),refs,now=now,fixture=fixture)
            if total+row['bytes']>policy['max_batch_bytes']:raise Hold('batch_budget')
            candidates.append(row);total+=row['bytes']
        except Exception as error:
            held.append(dict(object_id=item.get('object_id'),reason=str(error) if isinstance(error,Hold) else 'inspection_failed'))
    return dict(dry_run=True,mutations=0,candidates=candidates,held=held,candidate_bytes=total)


def recheck(proposal,item,policy,proof,reference_reader,maintenance_lock,*,now,fixture=False):
    """Use caller's existing maintenance lock; no deletion callback is accepted."""
    try:
        with maintenance_lock():
            refs=reference_reader(item['dataset_id'])
            current=evaluate(item,policy,proof,refs,now=now,fixture=fixture)
            if any(current[key]!=proposal[key] for key in ('object_id','stat','reference_epoch','proof_id','policy_id')):raise Hold('proposal_stale')
            return dict(eligible_under_existing_lock=True,dry_run=True,mutations=0)
    except Exception as error:return dict(eligible_under_existing_lock=False,dry_run=True,mutations=0,reason=str(error) if isinstance(error,Hold) else 'recheck_or_lock_failed')
