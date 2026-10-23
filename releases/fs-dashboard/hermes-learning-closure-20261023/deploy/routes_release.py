"""Single-policy activation scope over the original CAS/fence/backup publisher."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess

HERE=Path(__file__).resolve().parent
SCOPE='hermes-learning-routes-20261023'
TARGETS={'policy/knowledge-load-policy.json':'/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'}
NATIVE_SCOPE_SHA='d6b00e5c5119fcf236d0bac44b31f3ec92e030df318b0c75a77655e033676a7f'


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def checked(value,stage):
    if (value.get('scope')!=SCOPE or len(value.get('files',[]))!=1
            or {r['candidate']:r['target'] for r in value['files']}!=TARGETS
            or value.get('businessWrites') is not False or value.get('timersChanged') is not False):
        raise ValueError('routes_exact_policy_scope')
    if (value.get('nativeImageBefore')!=value.get('nativeImageRequired')
            or value.get('nativeImageAfter')!=value.get('nativeImageRequired')
            or value.get('nativeUnits')!=['fs-hermes-desktop.service','hermes-dingtalk.service']):
        raise ValueError('routes_same_image_cache_restart_required')
    stage=Path(stage);row=value['files'][0]
    before=(stage/'before-policy.json').read_bytes()
    after=(stage/'candidate/policy/knowledge-load-policy.json').read_bytes()
    if hashlib.sha256(before).hexdigest()!=row['beforeSha256'] or hashlib.sha256(after).hexdigest()!=row['sha256']:
        raise ValueError('routes_frozen_policy_bytes')
    prior,current=json.loads(before),json.loads(after)
    if ({k:v for k,v in prior.items() if k!='task_routes'}!={k:v for k,v in current.items() if k!='task_routes'}
            or prior.get('task_routes',{}).get('enabled') is True):
        raise ValueError('routes_existing_policy_preserved')
    routes=current.get('task_routes',{})
    if set(routes)!={'enabled','routes'} or routes['enabled'] is not True or not routes['routes']:
        raise ValueError('routes_activation_required')
    if digest(routes['routes'])!=value['taskRoutesSha256']:
        raise ValueError('routes_exact_approved_identities')
    for item in routes['routes']:
        if (item.get('project')!='FS' or set(item.get('modules',[]))!={'FS','FC27'}
                or item.get('catalog')!=value['catalogPath'] or item.get('sha256')!=value['catalogSha256']
                or item.get('reviewed_skills')!={'source':'approved_current'}):
            raise ValueError('routes_exact_published_catalog')
        if item.get('channel')=='fs':
            if (item.get('owner')!='wulv' or set(item.get('task_types',[]))!={'report','data','conversation'}
                    or item.get('baseline_compatibility')!={'mode':'retain_full_baseline','sha256':value['baselineSha256']}):
                raise ValueError('routes_fs_owner_and_full_baseline')
        elif item.get('channel')=='feishu':
            if (not item.get('owner') or not item.get('chat_id') or 'thread_id' not in item
                    or item.get('profile_name')!='default' or item.get('task_types')!=['conversation']):
                raise ValueError('routes_feishu_exact_scope')
        else:
            raise ValueError('routes_unapproved_channel')
    return value


def native_scope():
    path=HERE/'native_scope_base.py'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=NATIVE_SCOPE_SHA:
        raise ValueError('existing_native_scope_drift')
    spec=importlib.util.spec_from_file_location('existing_routes_native_scope',path)
    scope=importlib.util.module_from_spec(spec);spec.loader.exec_module(scope)
    return scope


def load_base():
    raw=(HERE/'release_adapter_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest()!='65794d515f78826e5a23c4c88966c603e1a46dd3c977c3dd0956bc770a581344':
        raise ValueError('existing_adapter_drift')
    value=checked(json.loads((HERE/'approved-manifest.json').read_text('utf-8')),HERE)
    spec=importlib.util.spec_from_file_location('existing_routes_scope',HERE/'release_adapter_base.py')
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    adapter.HERE,adapter.SCOPE,adapter.TARGETS,adapter.NEW=HERE,SCOPE,TARGETS,frozenset()
    base=adapter.load_base();group=base.approved_daily_group;inspect=base.inspect
    base.approved_daily_group=lambda v,r,p,i:group(v,r,p,i) or (v.get('scope')==SCOPE
        and p==base.rooted(r,'/var/lib/fs-hermes-fc') and (i.st_uid,i.st_gid,stat.S_IMODE(i.st_mode))==(0,9876,0o750))
    def ready(manifest,stage,root=Path('/')):
        info=json.loads(subprocess.check_output(['docker','inspect','fs-hermes-desktop'],text=True))[0]
        if info['Image']!=manifest['nativeImageRequired'] or not any(m.get('Source')=='/var/lib/fs-hermes-memory-approval/published-skills'
                and m.get('Destination')=='/approved-skills' and m.get('RW') is False for m in info['Mounts']):
            raise ValueError('routes_native_image_and_readonly_catalog_required')
        return inspect(manifest,stage,root)
    base.inspect=ready
    # Cached gateway agents select their wrapper at construction; recreate them under the existing turn fence.
    return native_scope().install_native_scope(base,value)


if __name__=='__main__':load_base().main()
