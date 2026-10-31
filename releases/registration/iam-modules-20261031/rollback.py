"""Roll back only this release, refusing later code/policy edits; preserve all databases."""
import sys,json,subprocess,importlib.util,hashlib
from pathlib import Path
root=Path(__file__).parent
sys.path.insert(0,'/opt/fs-access-policy');import rbac
spec=importlib.util.spec_from_file_location('publisher',root/'publisher.py');pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)
manifest=json.loads((root/'manifest.json').read_text());targets={r['candidate']:r['target'] for r in manifest['files']}
pub.RELATIVE=set(targets);pub.target_for=lambda rel:targets[rel]
backup=Path('/var/backups/fs-navigation-20261006/nav-20261031T094000Z')
journal=json.loads((backup/'journal.json').read_text())
receipt=json.loads((root/'policy-migration.json').read_text())
with pub.locks(Path('/')):
    current=rbac.load_policy()
    assert rbac.revision_of(current)==receipt['revision'],'later policy edits require targeted reconciliation'
    pub.rollback_credentials(backup,journal,hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest())
    assert all(pub.digest(Path(r['target']))==r['sha256'] for r in manifest['files']),'later code edits require targeted reconciliation'
    old=json.loads((root/'policy-before.private.json').read_text())
    subprocess.run(['systemctl','stop','auth-portal.service'],check=True)
    try:
        assert rbac.revision_of(rbac.load_policy())==receipt['revision']
        old['generation']=current['generation']
        rbac.save_policy(old,'chenchao',note='回滚2026-10-31工作区角色修复，仅还原该次授权变更')
        pub.rollback_journal(backup,journal,Path('/'))
    finally:
        subprocess.run(['systemctl','start','auth-portal.service'],check=True)
    subprocess.run(['systemctl','is-active','--quiet','auth-portal.service'],check=True)
    print('Restored six pre-release code files and prior role policy; databases, sessions and audit retained.')
