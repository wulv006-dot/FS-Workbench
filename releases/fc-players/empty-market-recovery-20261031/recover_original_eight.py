"""One controlled recovery of the original eight null-market-price add failures."""
from copy import deepcopy
import json
from pathlib import Path

from player_web import direct_model_import as direct
from player_web.repository import StateError, digest
from 球员维护工具.admin_adapter import AdminAdapter, build_existing_model_map

EXECUTION = '4eb2f5ce34bb4951bd81a357a2d737d8'
PLAN = '838d48881a63424aaebc8db61ebe099b'
FIDS = {'23741','23743','23745','23747','23748','23749','23753','23757'}
PHASE = 'add_empty_market_recovery'


def corrected_body(item):
    body = deepcopy(item['payload'])
    fields = []
    for entry in body['more']['extend']:
        if entry['key'] in ('ps_price','pc_price') and entry['value'] is None:
            entry['value'] = ''
            fields.append(entry['key'])
    if not fields or item.get('missing_price_policy') != 'fallback_9999':
        raise StateError('RECOVERY_NULL_PRICE_PROOF_REQUIRED')
    return body


def recover_adds(settings, repo, client, execution_id, plan, *, apply=False):
    direct._bound_plan(repo, execution_id, plan)
    if not settings.new_card_write_enabled or (settings.data_root/'STOP_WRITES').exists():
        raise StateError('WRITE_DISABLED')
    adapter = AdminAdapter(client, state_root=settings.data_root/'admin_state/shared', write_enabled=False)
    current = build_existing_model_map(adapter.list_all_models())
    execution = repo.get_execution(execution_id, plan['owner'])
    closed = {r['planned']['futbin_id'] for r in execution['items'] if r['status']=='verified'}
    targets = [i for i in plan['direct_items'] if i['futbin_id'] in FIDS and i['futbin_id'] not in closed]
    report = []
    for item in targets:
        fid = item['futbin_id']
        original = [e for e in execution['events'] if e['step']=='direct_add' and e['status']=='unknown'
                    and e['detail'].get('futbin_id')==fid]
        if (not original or original[-1]['detail'].get('diagnostic',{}).get('http_status')!=500
                or original[-1]['detail'].get('payload_sha256')!=item['payload_sha256']):
            raise StateError('RECOVERY_ORIGINAL_HTTP500_REQUIRED')
        body = corrected_body(item)
        report.append({'futbin_id':fid,'original_seq':original[-1]['seq'],
                       'original_payload_sha256':item['payload_sha256'],
                       'corrected_payload_sha256':digest(body),'existing_model_id':current.get(fid)})
    if not apply:
        return report
    for item, audit in zip(targets, report):
        fid = item['futbin_id']
        body = corrected_body(item)

        def verify():
            return {'model_id':direct._model(adapter,client,item,repo,execution_id)}

        def dispatch():
            # Refresh immediately before the only permitted corrected add.
            present = build_existing_model_map(adapter.list_all_models()).get(fid)
            if present:
                verify()
                return {'code':1,'reconciled_existing':True}
            return client.add_model(body)

        payload = {'original_seq':audit['original_seq'],'original_payload_sha256':item['payload_sha256'],'body':body}
        if not direct._action(repo,execution_id,item,PHASE,payload,dispatch,verify):
            repo.set_execution(execution_id,'needs_reconcile','empty_market_recovery_unknown',audit)
            raise StateError('RECOVERY_RESULT_UNKNOWN_NO_RETRY')
    return report


def main():
    import argparse,os,shutil,sqlite3,time
    from player_web.collection import collection_lock
    from player_web.new_card_service import verify_manual_new_card_scope,verify_source_policy
    from player_web.repository import Repository
    from player_web.settings import Settings
    from player_web.shared_session import shared_client
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    settings=Settings.from_env();repo=Repository(settings.data_root/'db/control.sqlite3')
    job=repo.get_execution(EXECUTION,'wulv');plan=repo.get_plan(PLAN,'wulv')
    if job['plan_id']!=PLAN or job['status'] not in {'needs_reconcile','partial_readback','waiting_price_lock','completed_readback'}:
        raise StateError('RECOVERY_EXECUTION_CHANGED')
    verify_source_policy(settings,plan);verify_manual_new_card_scope(settings,plan)
    client=shared_client(settings)
    if not args.apply:
        print(json.dumps({'read_only':True,'reconciliation':recover_adds(settings,repo,client,EXECUTION,plan)}));return
    # Reuse the API instance lock; the normal web process must be stopped first.
    with collection_lock(settings.data_root/'locks/api-instance.lock') as acquired:
        if not acquired:raise StateError('RECOVERY_WEB_PROCESS_ACTIVE')
        with repo.connection() as db:
            if db.execute("select 1 from executions where status in ('queued','running','waiting_price_lock')").fetchone():
                raise StateError('RECOVERY_WRITER_BUSY')
        check=recover_adds(settings,repo,client,EXECUTION,plan)
        backup=settings.data_root/'runs'/('empty-market-recovery-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
        backup.mkdir(mode=0o700,exist_ok=False)
        pending=backup/'control.sqlite3.pending'
        with sqlite3.connect(str(repo.path)) as source,sqlite3.connect(str(pending)) as target:source.backup(target)
        with pending.open('rb') as f:os.fsync(f.fileno())
        os.replace(pending,backup/'control.sqlite3')
        tasks=settings.data_root/'admin_state/shared/admin_tasks.json'
        if tasks.is_file():shutil.copy2(tasks,backup/'admin_tasks.json')
        (backup/'reconciliation.json').write_text(json.dumps(check,indent=2),encoding='utf-8')
        print(json.dumps({'backup':str(backup),'reconciliation':check}),flush=True)
        try:
            recover_adds(settings,repo,client,EXECUTION,plan,apply=True)
            result=direct.execute_direct_plan(settings,repo,client,EXECUTION,plan,only_futbin_ids=FIDS)
            print(json.dumps({'execution_id':EXECUTION,'result':result}),flush=True)
        except Exception:
            repo.set_execution(EXECUTION,'needs_reconcile','empty_market_recovery_stopped',{'same_execution':True})
            raise


if __name__=='__main__':main()
