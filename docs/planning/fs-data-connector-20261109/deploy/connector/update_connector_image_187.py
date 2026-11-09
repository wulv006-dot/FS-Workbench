"""CAS the existing connector unit to one reviewed image; nginx and OAuth state stay put."""
import argparse
import importlib.util
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('connector_existing_install',HERE/'install_connector_187.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
OLD_IMAGE='sha256:3caead07927408c26da245d25ad3aeeef8ba795a8b0936b2e909b772b85dc152'
REVISION='1d9ebb452772e8aa6f5dddca8fa85a9cf8382d95'
MERGED_COMMIT='f291f5306df70b5af7dfc3c526c6e14dc33f7aa3'
BACKUP=Path('/var/backups/fs-data-connector/dcr-1d9ebb')
base.BACKUP=BACKUP


def image_unit(before,image_id):
    if not isinstance(image_id,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',image_id) or image_id==OLD_IMAGE:
        raise ValueError('new_fixed_image_id_required')
    expected=base.unit_bytes(OLD_IMAGE)
    if before!=expected or before.count(OLD_IMAGE.encode())!=1:
        raise ValueError('existing_unit_sha_changed_reconcile_first')
    return before.replace(OLD_IMAGE.encode(),image_id.encode(),1)


def check(image_id):
    before=base.UNIT.read_bytes();after=image_unit(before,image_id)
    running=json.loads(base.run(['docker','inspect','fs-data-connector']))[0]
    if running['Image']!=OLD_IMAGE or not running['State']['Running']:
        raise ValueError('existing_running_image_changed')
    image=json.loads(base.run(['docker','image','inspect',image_id]))[0]
    labels=image['Config'].get('Labels') or {}
    if image['Id']!=image_id or labels.get('org.opencontainers.image.revision')!=REVISION or labels.get('fs.previous-image')!=OLD_IMAGE:
        raise ValueError('reviewed_derived_image_required')
    return before,after


def verify_public():
    spec=importlib.util.spec_from_file_location('connector_update_public',HERE/'client_public_probe.py')
    public=importlib.util.module_from_spec(spec);spec.loader.exec_module(public)
    base.wait_for_public_routes(public.request)
    spec=importlib.util.spec_from_file_location('connector_update_smoke',HERE/'connector_smoke.py')
    smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
    return smoke.probe()


def write_receipt(receipt):base.atomic(BACKUP/'receipt.json',json.dumps(receipt,indent=2).encode(),0o600)


def apply(image_id):
    with base.locks():
        before,after=check(image_id)
        if BACKUP.exists():raise ValueError('original_update_exists_reconcile_same_id')
        BACKUP.mkdir(parents=True,mode=0o700)
        base.atomic(BACKUP/'unit.before',before,0o600)
        receipt={'status':'prepared','source_commit':REVISION,'merged_commit':MERGED_COMMIT,
                 'image_before':OLD_IMAGE,'image_after':image_id,'unit_before_sha256':base.sha(before),
                 'unit_after_sha256':base.sha(after),'original_state':base.original_state(),
                 'oauth_directory_preserved':True,'nginx_unchanged':True}
        write_receipt(receipt)
        try:
            base.atomic(base.UNIT,after,0o644)
            base.run(['systemctl','daemon-reload']);base.run(['systemctl','restart','fs-data-connector.service'])
            receipt['anonymous_smoke']=verify_public()
            running=json.loads(base.run(['docker','inspect','fs-data-connector']))[0]
            if running['Image']!=image_id:raise ValueError('running_image_readback_failed')
            receipt['state_after']=base.original_state()
            receipt['original_services_unchanged']=receipt['original_state']['services']==receipt['state_after']['services']
            if not receipt['original_services_unchanged']:raise ValueError('original_service_state_changed')
            receipt['status']='updated_anonymous_entry_verified';write_receipt(receipt)
            print(json.dumps(receipt,ensure_ascii=False))
        except BaseException as exc:
            receipt.update(status='failed_reconcile_same_update',error_type=type(exc).__name__)
            write_receipt(receipt);raise


def rollback():
    with base.locks():
        receipt=json.loads((BACKUP/'receipt.json').read_text())
        before=(BACKUP/'unit.before').read_bytes()
        if base.sha(before)!=receipt['unit_before_sha256'] or base.sha(base.UNIT.read_bytes())!=receipt['unit_after_sha256']:
            raise ValueError('unit_or_backup_drift')
        ids=base.run(['docker','ps','-aq','--filter','name=^/fs-data-connector$']).splitlines()
        if ids:
            if len(ids)!=1:raise ValueError('connector_container_ambiguous')
            running=json.loads(base.run(['docker','inspect',ids[0]]))[0]
            if running['Image']!=receipt['image_after']:raise ValueError('running_image_drift')
        else:
            state=dict(line.split('=',1) for line in base.run(
                ['systemctl','show','fs-data-connector.service','--no-pager','-p','ActiveState']).splitlines() if '=' in line)
            if state.get('ActiveState') not in ('failed','inactive'):
                raise ValueError('missing_container_requires_stopped_or_failed_unit')
        base.atomic(base.UNIT,before,0o644)
        base.run(['systemctl','daemon-reload']);base.run(['systemctl','restart','fs-data-connector.service'])
        receipt['rollback_smoke']=verify_public();receipt['status']='rolled_back_oauth_preserved';write_receipt(receipt)
        print(json.dumps({'status':receipt['status'],'image_id':OLD_IMAGE,'oauth_directory_preserved':True}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image-id');parser.add_argument('--apply',action='store_true')
    parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    if args.rollback:rollback()
    elif args.apply:apply(args.image_id)
    else:
        before,after=check(args.image_id)
        print(json.dumps({'read_only_plan':True,'unit_before_sha256':base.sha(before),'unit_after_sha256':base.sha(after),
                          'image_after':args.image_id,'production_writes':0,'nginx_unchanged':True}))
