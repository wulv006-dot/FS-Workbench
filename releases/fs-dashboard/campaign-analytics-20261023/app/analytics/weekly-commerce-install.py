"""Private confirm-only policy installer over the existing navigation publisher.
No Admin/coupon/model calls, publication, service restart or new scheduler.
"""
from contextlib import nullcontext
from pathlib import Path
import hashlib,json,os,re,sys,time,types

PUBLISHER='/opt/fs-release-stage/traffic-source-tabs-20261019-v3/release_navigation_base.py'
PUBLISHER_SHA='57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840'
PROPOSALS='/var/lib/fs-campaign-dashboard/center/weekly-commerce'
TARGET='/var/lib/fs-campaign-dashboard/backend/policy.json'
CENTER='/var/lib/fs-campaign-dashboard/center/state.json'
RECEIPTS='/var/backups/fs-campaign-commerce-policy'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def uuid(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}',value):raise ValueError('operation_id_invalid')
    return value
def safe(path):
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('symlink_forbidden')
def private(path):
    safe(path);s=path.stat()
    if not path.is_file() or s.st_size>4194304 or os.name=='posix' and s.st_mode&0o077:raise ValueError('private_file_required')
    return path.read_bytes()

def preserve(old,new,proposal):
    selected={m['model_id'] for m in proposal['resolved_models']}
    for key in set(old)|set(new):
        if key not in ('native_catalog','native_checkout','admin_reference_prices') and old.get(key)!=new.get(key):raise ValueError('unrelated_policy_changed')
    key=lambda p:(p['model_ref']['site_id'],p['model_ref']['game_id'],p['model_ref']['model_id'],p['quantity_value'],p['quantity_unit'])
    prices={key(p):p for p in new['admin_reference_prices']['entries']}
    for p in old['admin_reference_prices']['entries']:
        target=prices.get(key(p))
        if target is None or (p['model_ref']['game_id']!='1327' or p['model_ref']['model_id'] not in selected) and p!=target:raise ValueError('unrelated_policy_changed')
    for section,fields in (('admin_reference_prices',{'entries'}),('native_catalog',{'products','model_contracts'}),('native_checkout',{'bindings'})):
        if {k:v for k,v in old[section].items() if k not in fields}!={k:v for k,v in new[section].items() if k not in fields}:raise ValueError('unrelated_policy_changed')
    products={p['key']:p for p in new['native_catalog']['products']}
    for p in old['native_catalog']['products']:
        target=products.get(p['key'])
        if target is None or p['product_ref']!=target['product_ref'] or p['platform']!=target['platform']:raise ValueError('unrelated_policy_changed')
        if p['product_ref'].get('model_id') not in selected and p!=target:raise ValueError('unrelated_policy_changed')
    contracts=new['native_catalog']['model_contracts']
    for mid,c in old['native_catalog']['model_contracts'].items():
        if mid not in contracts or mid not in selected and c!=contracts[mid]:raise ValueError('unrelated_policy_changed')
    signature=lambda b:json.dumps([b.get(k) for k in ('page_id','product_key','quantity','attributes','off_percent')],sort_keys=True)
    bindings={signature(b):b for b in new['native_checkout']['bindings']}
    for b in old['native_checkout']['bindings']:
        target=bindings.get(signature(b))
        if target is None:raise ValueError('unrelated_policy_changed')
        if b['page_id'] not in ('fc27-weekly','fc27-trio','fc27-sbc') and b!=target:raise ValueError('unrelated_policy_changed')

def install(request,*,root=Path('/'),publisher=None,now=time.time):
    if not isinstance(request,dict) or set(request)!={'action','confirm','operation_id','proposal_id','proposal_sha','owner'} or request['action'] not in ('inspect','install'):raise ValueError('request_invalid')
    apply=request['action']=='install' and request['confirm'] is True
    if request['action']=='install' and not apply:raise ValueError('explicit_confirmation_required')
    op=uuid(request['operation_id']);proposal_id=uuid(request['proposal_id'])
    at=lambda name:root/name.lstrip('/')
    if publisher is None:
        source=at(PUBLISHER);raw=source.read_bytes();safe(source)
        if sha(raw)!=PUBLISHER_SHA:raise ValueError('original_publisher_drift')
        publisher=types.ModuleType('weekly_commerce_original_publisher');publisher.__file__=str(source);exec(compile(raw,str(source),'exec'),publisher.__dict__)
    proposal_raw=private(at(PROPOSALS)/(proposal_id+'.json'))
    if sha(proposal_raw)!=request['proposal_sha']:raise ValueError('proposal_changed')
    p=json.loads(proposal_raw)
    if p.get('proposal_id')!=proposal_id or p.get('owner')!=request['owner'] or p.get('can_publish') is not True:raise ValueError('proposal_binding_invalid')
    candidate=private(at(PROPOSALS)/(proposal_id+'.policy.json'))
    if sha(candidate)!=p['candidate_sha']:raise ValueError('candidate_changed')
    value=json.loads(candidate)
    if (len(value.get('admin_reference_prices',{}).get('entries',[]))>300 or len(value.get('native_catalog',{}).get('products',[]))>1000
        or len(value.get('native_checkout',{}).get('bindings',[]))>3000):raise ValueError('candidate_capacity_exceeded')
    identity=dict(operation_id=op,proposal_id=proposal_id,proposal_sha=request['proposal_sha'],owner=request['owner'],candidate_sha=p['candidate_sha'],before_sha=p['policy_before_sha'],draft_revision=p['revision'],draft_hash=p['draft_hash'])
    target=at(TARGET);receipt_dir=at(RECEIPTS)/op;receipt_file=receipt_dir/'receipt.json';backup=receipt_dir/'policy.before.json'
    with publisher.locks(root):
        safe(receipt_dir);current=private(target);current_sha=sha(current)
        receipt=json.loads(private(receipt_file)) if receipt_file.exists() else None
        if receipt and any(receipt.get(k)!=v for k,v in identity.items()):raise ValueError('operation_identity_conflict')
        if current_sha==p['candidate_sha'] and receipt:
            if not backup.exists() or sha(private(backup))!=p['policy_before_sha']:raise ValueError('original_backup_required')
            if apply and receipt.get('state')!='installed':publisher.atomic(receipt_file,encoded(dict(identity,state='installed',recovered_by_readback=True)),0o600)
            return dict(identity,state='already_installed',policy_write=False,published=False)
        if receipt and receipt.get('state')=='installed':raise ValueError('installed_receipt_policy_changed')
        if current_sha!=p['policy_before_sha']:raise ValueError('policy_revision_conflict')
        if receipt and current_sha==p['candidate_sha']:raise ValueError('original_receipt_required')
        from datetime import datetime
        if now()>=datetime.fromisoformat(p['expires_at'].replace('Z','+00:00')).timestamp():raise ValueError('proposal_expired')
        state=json.loads(at(CENTER).read_bytes())
        if state.get('revision')!=p['revision']:raise ValueError('draft_revision_conflict')
        # A proposal cannot change unrelated private policy sections or remove old objects.
        old=json.loads(current)
        preserve(old,value,p)
        if not apply:return dict(identity,state='validated_not_installed',policy_write=False,published=False)
        receipt_dir.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(receipt_dir.parent,0o700);os.chmod(receipt_dir,0o700)
        if backup.exists():
            if sha(private(backup))!=p['policy_before_sha']:raise ValueError('backup_conflict')
        else:publisher.atomic(backup,current,0o600)
        publisher.atomic(receipt_file,encoded(dict(identity,state='prepared')),0o600)
        if sha(private(target))!=p['policy_before_sha']:raise ValueError('policy_revision_conflict')
        if json.loads(at(CENTER).read_bytes()).get('revision')!=p['revision']:raise ValueError('draft_revision_conflict')
        publisher.atomic(target,candidate,0o600)
        if sha(private(target))!=p['candidate_sha']:raise ValueError('policy_readback_unknown')
        publisher.atomic(receipt_file,encoded(dict(identity,state='installed')),0o600)
        return dict(identity,state='installed',policy_write=True,published=False)

def main():
    raw=sys.stdin.buffer.read(1000001)
    if len(raw)>1000000:raise ValueError('request_too_large')
    print(json.dumps(install(json.loads(raw))))
if __name__=='__main__':
    try:main()
    except Exception as error:
        allowed={'request_invalid','explicit_confirmation_required','operation_id_invalid','symlink_forbidden','private_file_required','original_publisher_drift','proposal_changed','proposal_binding_invalid','candidate_changed','candidate_capacity_exceeded','operation_identity_conflict','original_backup_required','installed_receipt_policy_changed','policy_revision_conflict','original_receipt_required','proposal_expired','draft_revision_conflict','unrelated_policy_changed','backup_conflict','policy_readback_unknown','request_too_large'}
        print(json.dumps(dict(state='unknown',error=str(error) if type(error) is ValueError and str(error) in allowed else 'policy_install_failed_inspect_original')));raise SystemExit(1)
