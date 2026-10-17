"""Exact five-target learning adapter for the existing frozen publisher."""
import hashlib,json,types
from pathlib import Path
HERE=Path(__file__).resolve().parent
BASE_SHA='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
CONTRACT_SHA='PREPARE_REPLACES_THIS'

def load_base():
    raw=(HERE/'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BASE_SHA:raise ValueError('frozen_publisher_drift')
    contract=(HERE/'approved-manifest.json').read_bytes()
    if hashlib.sha256(contract).hexdigest()!=CONTRACT_SHA:raise ValueError('learning_contract_drift')
    approved=json.loads(contract);mapping={r['candidate']:r['target'] for r in approved['files']}
    # Retain the existing history admission/service path, only this isolated module's scope.
    source=raw.decode().replace("HERMES_HISTORY_SCOPE='hermes-fc-history-pagination-20261014'","HERMES_HISTORY_SCOPE='hermes-private-learning-20261017-v1'")
    needle="if any(r.get('beforeSha256') is None for r in files if not (("
    if source.count(needle)!=1:raise ValueError('base_patch_anchor_changed')
    source=source.replace(needle,"if any(r.get('beforeSha256') is None for r in files if r['target'] not in LEARNING_NEW and not ((")
    old="else 0o600 if row['candidate']=='hermes/nightly/nightly-schedule.json' else 0o644"
    if source.count(old)!=1:raise ValueError('base_mode_anchor_changed')
    source=source.replace(old,"else 0o600 if row['target'] in LEARNING_NEW or row['candidate']=='hermes/nightly/nightly-schedule.json' else 0o644")
    base=types.ModuleType('learning_frozen_base');base.__file__=str(HERE/'release_navigation_base.py')
    base.LEARNING_NEW={r['target'] for r in approved['files'] if r['beforeSha256'] is None}
    exec(compile(source,base.__file__,'exec'),base.__dict__)
    base.HERMES_HISTORY_TARGETS=mapping
    original_target=base.target_for
    base.target_for=lambda rel:mapping[rel] if rel in mapping else original_target(rel)
    base.expected_files=lambda m:set(mapping) if m.get('scope')==base.HERMES_HISTORY_SCOPE else (_ for _ in ()).throw(ValueError('learning_scope_only'))
    validate=base.validate
    def exact(m,stage):
        if m!=approved:raise ValueError('exact_learning_manifest_required')
        return validate(m,stage)
    base.validate=exact
    # Original atomic operations preserve existing modes; check owner/mode before CAS.
    guards=base.guards
    state={'applying':False,'journal':None}
    journal_write=base.journal_write
    def durable_journal(backup,journal):
        journal_write(backup,journal)
        if state['applying'] and journal.get('manifest')==approved:
            # Copy only after durable write; later in-memory mutations are not proof.
            state['journal']=json.loads(json.dumps(journal))
    base.journal_write=durable_journal
    def guarded(m,root,**kwargs):
        guards(m,root,**kwargs)
        for r in m['files']:
            p=base.rooted(root,r['target'])
            if p.exists():
                s=p.stat()
                if r['beforeSha256'] is None:
                    own=next((x for x in (state['journal'] or {}).get('files',[]) if x['target']==r['target']),{})
                    if not (state['applying'] and own.get('intent') is True and own.get('written') is True and own.get('sha256')==r['sha256'] and base.digest(p)==r['sha256']):raise ValueError('new_learning_reference_conflict')
                if (s.st_uid,s.st_gid,s.st_mode&0o777)!=(0,0,int(r['mode'],8)):raise ValueError('learning_owner_mode_drift')
    base.guards=guarded
    apply=base.apply
    def apply_owned(*args,**kwargs):
        if state['applying']:raise ValueError('learning_apply_already_active')
        state.update(applying=True,journal=None)
        try:return apply(*args,**kwargs)
        finally:state.update(applying=False,journal=None)
    apply_owned.__wrapped__=apply
    base.apply=apply_owned
    return base

if __name__=='__main__':load_base().main()
