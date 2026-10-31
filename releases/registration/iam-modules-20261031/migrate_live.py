"""Explicit operator migration, exact baseline, existing IAM save/audit, no accounts created."""
import sys,json,hashlib,subprocess,os,importlib.util
from pathlib import Path
from roles import migrate
root=Path(__file__).parent
sys.path.insert(0,'/opt/fs-access-policy')
import rbac
spec=importlib.util.spec_from_file_location('publisher',root/'publisher.py');pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)
expected=json.loads((root/'manifest.json').read_text())
expected_sha=next(x['sha256'] for x in expected['unchangedRequired'] if x['path']==rbac.LIVE_POLICY)
receipt=root/'policy-migration.json'
with pub.locks(Path('/')):
    if receipt.exists(): raise RuntimeError('migration already recorded; inspect rather than replay')
    raw=Path(rbac.LIVE_POLICY).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha: raise RuntimeError('live policy changed; do not overwrite')
    old=json.loads(raw);new=migrate(old,rbac)
    # Stop only the owning auth service briefly to exclude concurrent console writes.
    subprocess.run(['systemctl','stop','auth-portal.service'],check=True)
    changed=False
    try:
        if Path(rbac.LIVE_POLICY).read_bytes()!=raw:raise RuntimeError('policy changed before maintenance')
        backup=root/'policy-before.private.json'
        fd=os.open(str(backup),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        rbac.save_policy(new,'chenchao',note='2026-10-31 用户要求按工作区整理角色；保留成员已有授权及显式拒绝')
        changed=True
        live=rbac.load_policy()
        assert rbac.revision_of(live)==rbac.revision_of(new)
        subprocess.run(['systemctl','start','auth-portal.service'],check=True)
        subprocess.run(['systemctl','is-active','--quiet','auth-portal.service'],check=True)
        receipt.write_text(json.dumps({'generation':live['generation'],'revision':rbac.revision_of(live),'beforeSha256':expected_sha,'roles':list(live['roles']),'backup':str(backup)},indent=2))
        print(receipt.read_text())
    except BaseException:
        if changed:
            old['generation']=rbac.load_policy()['generation']
            rbac.save_policy(old,'chenchao',note='模块角色迁移失败，恢复本次变更前授权')
        subprocess.run(['systemctl','start','auth-portal.service'],check=True)
        raise
