"""Build LF Git payloads and fresh on-host stages; never write active targets."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

from runtime_release import (HERE, NGINX, TARGETS, NEW, FROZEN_IMAGE_MARKER, frozen,
                             protected_paths, worker_observation, INSTALLED_COMMIT,
                             INSTALLED_PROOF, INSTALLED_NGINX_SHA, installed_baseline)

MODULE = 'releases/fs-dashboard/hermes-conversation-20261018/'
CORE = 'releases/fs-dashboard/hermes-v2-core-20261020/source/'
FC = 'releases/fc-coins/'
PUBLISHER_SOURCES = {name: MODULE + 'deploy/' + name for name in (
    'runtime_release.py', 'runtime_prepare.py', 'release_navigation_base.py')}
PUBLISHER_SOURCES['release_readiness.py'] = FC + 'fc-pricing-v3-20261026/deploy/release_readiness.py'
SOURCES = {name: MODULE + 'source/' + name.rsplit('/', 1)[1] for name in (
    'runtime/conversation_store.py', 'runtime/conversation_files.py', 'runtime/conversation_file_bindings.py')}
SOURCES.update({name: CORE + name.rsplit('/', 1)[1] for name in (
    'runtime/conversation_file_tools.py', 'runtime/material_evidence.py')})
SOURCES.update({'runtime/conversation_service.py': FC + 'fc-pricing-v3-20261026/source/conversation_service.py',
                'runtime/runs_contract.py': FC + 'fc-pricing-v2-20261022/source/runs_contract.py',
                'runtime/proxy_gateway.py': FC + 'fc-review-channel-20261026/source/proxy_gateway.py',
                'runtime/hermes_worker.py': FC + 'fc-review-channel-20261026/source/hermes_worker.py',
                'http/conversation_http.py': FC + 'fc-pricing-v3-20261026/source/conversation_http.py'})
SOURCES.update({'frontend/' + name: MODULE + 'frontend/' + name
                for name in ('index.html', 'conversation.js', 'conversation.css')})
KNOWN = {
    'runtime/conversation_service.py': 'cfb06ef0321b9b2c1454956e585583809ec904be74e9803dd28e983edd3cbcc6',
    'runtime/conversation_store.py': '43d4f8bf1e67b86f9beb0ee87903c41cb62d9c86079c2c6a68a8d7b0c586fb45',
    'runtime/runs_contract.py': 'e02e94b83325f7aa1ec1b598cf25f11d26e77ec481d25bdd6fab9ffd9765c70c',
    'runtime/proxy_gateway.py': '784257f2e99340128c8163d92f8c2cf79c3229ebe952ff821687e9655705d3ff',
    'runtime/hermes_worker.py': '8c377abb19da520df2f92e02e0523430dd53fc1be2f1eac8c47c3f6de35854e9',
    'http/conversation_http.py': 'd74f0242b2d22a210f694218c0d5e1933af581f0c1e137f658fcb882f5b058b7',
    'frontend/index.html': '3d79a5642f1517a8c1e414702c2b7491dc0ff4ed079c7d09895a3b1251045a24',
    'frontend/conversation.js': '81debe079db8fdb83eff6145af55c743895871f65acbfb143841f93cff9226b6',
    'frontend/conversation.css': '68f1803296d5b6057ada86f569d8d26606f2b37a7a6178cf855b287c986cc029',
}


def configure_execution():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    release.configure_execution()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW
    SOURCES.update({'runtime/'+name: (MODULE if name.startswith('conversation_') else 'releases/fs-dashboard/hermes-v2-core-20261020/')+'source/'+name
                    for name in release.EXECUTION_MODULES})
    SOURCES.update({'runtime/fs_inprocess.py':FC+'fc-review-channel-20261026/source/fs_inprocess.py',
                    'http/range_api.py':'releases/fs-dashboard/dashboard-refresh-20261025/source/range_api.py'})


def configure_diagnostics():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    configure_execution()
    release.configure_diagnostics()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW


def configure_task_index_compat():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    configure_execution()
    release.configure_task_index_compat()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW


def configure_worker_diagnostics():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    configure_execution()
    release.configure_worker_diagnostics()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW


def configure_material_transport():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    configure_execution()
    release.configure_material_transport()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW
    SOURCES[release.TRANSPORT_CANDIDATE] = CORE + 'transport.py'


def configure_material_stream():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    configure_execution()
    release.configure_material_stream()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW
    SOURCES[release.TRANSPORT_CANDIDATE] = CORE + 'transport.py'


def configure_bindings_auth():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    configure_execution()
    release.configure_bindings_auth()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW
    SOURCES[release.TRANSPORT_CANDIDATE] = CORE + 'transport.py'


def configure_material_guard():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    configure_execution()
    release.configure_material_guard()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW
    SOURCES[release.TRANSPORT_CANDIDATE] = CORE + 'transport.py'


def native_generated():
    import runtime_release as release
    return {'unit/native-control.conf': json.dumps({'recipe':'native_worker_mounts_v2',
                'daily_source':release.TARGETS['approval/daily_review.py'],'daily_target':release.NATIVE_DAILY_CONTAINER,
                'daily_readonly':True},sort_keys=True).encode(),
            'runtime/native-backend.json': release.native_backend_bytes()}


def configure_native_chat():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    if not release.NATIVE_MODE:
        configure_material_guard()
        release.configure_native_chat()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW
    SOURCES.update({'runtime/conversation_native.py':MODULE+'source/conversation_native.py',
                    'runtime/native_chat.py':CORE+'native_chat.py',
                    'runtime/direct_provider.py':CORE+'direct_provider.py',
                    'runtime/transport.py':CORE+'transport.py'})
    SOURCES.update({'approval/'+name:'releases/fs-dashboard/hermes-memory-approval-20261022/'+name
                    for name in ('review_queue.py','native_review.py','reviewed_skills.py','daily_review.py')})
    SOURCES.update({name:None for name in native_generated()})


def configure_native_admission():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    configure_native_chat()
    release.configure_native_admission()
    INSTALLED_COMMIT, NEW = release.INSTALLED_COMMIT, release.NEW


def configure_native_archive():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    if not release.ARCHIVE_MODE:
        configure_native_chat();release.configure_native_archive()
    INSTALLED_COMMIT,NEW=release.INSTALLED_COMMIT,release.NEW
    for name in list(SOURCES):
        if name not in release.TARGETS:del SOURCES[name]


def configure_native_capabilities():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    release.configure_native_capabilities()
    INSTALLED_COMMIT,NEW=release.INSTALLED_COMMIT,release.NEW
    SOURCES.clear()
    SOURCES.update({'runtime/'+n:CORE+n for n in ('native_chat.py','transport.py','direct_provider.py')})
    SOURCES.update({'runtime/'+n:FC+'fc-review-channel-20261026/source/'+n for n in ('hermes_worker.py','proxy_gateway.py','fs_inprocess.py')})
    SOURCES.update({'runtime/'+n:MODULE+'source/'+n for n in ('conversation_store.py','conversation_native.py')})
    SOURCES['runtime/conversation_service.py']=FC+'fc-pricing-v3-20261026/source/conversation_service.py'
    SOURCES['http/conversation_http.py']=MODULE+'source/conversation_http.py'
    SOURCES.update({'runtime/conversation_user_data.py':MODULE+'source/conversation_user_data.py',
        'runtime/a2_query_context.py':'releases/fs-dashboard/user-analytics-20261022/source/a2_query_context.py',
        'runtime/user_runtime.py':'releases/fs-dashboard/user-analytics-20261022/source/user_runtime.py',
        'runtime/live_order_consumer.py':'releases/fs-dashboard/tiered-data-access-20261101/source/live_order_consumer.py',
        'runtime/b2_customer_followup.py':CORE+'b2_customer_followup.py',
        'runtime/fs_native_readonly.py':'releases/fs-dashboard/hermes-server-unify-20261022/fs_readonly/__init__.py'})
    campaign='releases/fs-dashboard/campaign-analytics-20261023/'
    SOURCES.update({name:campaign+('app/analytics/backend-client.mjs' if name.endswith('.mjs') else name[len('campaign/'):])
                    for name in (*release.CAMPAIGN_TARGETS,*release.CAPABILITIES_NEW)})


def configure_native_composer_static():
    import runtime_release as release
    global INSTALLED_COMMIT, NEW
    release.configure_native_composer_static()
    INSTALLED_COMMIT,NEW=release.INSTALLED_COMMIT,release.NEW
    SOURCES.clear();SOURCES['frontend/index.html']=MODULE+'frontend/index.html'


def admission_generated(repo):
    """Reproduce the installed v2 unit from pinned Git, never render live bytes."""
    import runtime_release as release
    original = subprocess.check_output(['git','show',INSTALLED_COMMIT+':'+MODULE+'source/worker-install-state-isolation.conf'],cwd=repo)
    unit = render_native_unit(original, {'socket':{'gid':release.NATIVE_SOCKET_GID}})
    if digest(unit) != release.NATIVE_CURRENT_UNIT_SHA:
        raise ValueError('native_admission_generated_unit_drift')
    return {'unit/native-control.conf':unit,'runtime/native-backend.json':release.native_backend_bytes()}


def render_native_unit(raw, dependencies):
    import runtime_release as release
    if digest(raw) != release.NATIVE_UNIT_BEFORE_SHA:
        raise ValueError('native_worker_unit_before_drift')
    gid = dependencies.get('socket',{}).get('gid')
    anchor = b' ' + FROZEN_IMAGE_MARKER.encode()
    if type(gid) is not int or not 0 <= gid <= 2147483647 or raw.count(anchor) != 1 or b'fs-native-bin' in raw:
        raise ValueError('native_worker_unit_anchor')
    extra = (' --group-add '+str(gid)+' --env HERMES_DOCKER_BINARY=/opt/fs-native-bin/docker'
        ' --mount type=bind,source=/usr/bin/docker,target=/opt/fs-native-bin/docker,readonly'
        ' --mount type=bind,source=/run/docker.sock,target=/var/run/docker.sock'
        ' --mount type=bind,source='+release.NATIVE_ROOT+',target='+release.NATIVE_ROOT+
        ' --mount type=bind,source='+release.NATIVE_EMPTY_SOURCE+',target=/opt/fs-native-backend-home,readonly'
        ' --mount type=bind,source='+release.TARGETS['approval/daily_review.py']+',target='+release.NATIVE_DAILY_CONTAINER+',readonly')
    return raw.replace(anchor, extra.encode()+anchor)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def patch_nginx(raw):
    """Only change the two existing conversation limits; retain every other byte."""
    result, count = [], 0
    lines = raw.splitlines(keepends=True)
    index = 0
    markers = (b'location = /api/hermes/conversations {', b'location ^~ /api/hermes/conversations/ {')
    seen = set()
    while index < len(lines):
        marker = lines[index].strip()
        if marker not in markers:
            result.append(lines[index]); index += 1
            continue
        if marker in seen:
            raise ValueError('duplicate_conversation_location')
        seen.add(marker)
        block, depth = [], 0
        while index < len(lines):
            row = lines[index]; index += 1; block.append(row)
            depth += row.count(b'{') - row.count(b'}')
            if depth == 0:
                break
        if depth:
            raise ValueError('conversation_location_unclosed')
        changed, n = re.subn(rb'(?m)^([ \t]*client_max_body_size[ \t]+)16k([ \t]*;)',
                             rb'\g<1>10m\g<2>', b''.join(block))
        if n != 1:
            raise ValueError('conversation_limit_anchor_drift')
        count += n; result.append(changed)
    if count != 2:
        raise ValueError('exact_conversation_locations_required')
    return b''.join(result)


def file_metadata(base, root, name, absent=False):
    path = base.rooted(root, name)
    base.no_target_link(path)
    if not path.exists():
        if not absent:
            raise ValueError('required_runtime_path_missing: ' + name)
        return {'path': name, 'sha256': None}
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != 0 or info.st_gid != 0:
        raise ValueError('runtime_regular_root_file_required: ' + name)
    import runtime_release as release
    if release.NATIVE_CAPABILITIES_MODE and name in release.CAMPAIGN_TARGETS.values():
        key=next(n for n,p in release.CAMPAIGN_TARGETS.items() if p==name)
        expected_sha,expected_size=release.CAMPAIGN_BEFORE[key]
        fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink','st_uid','st_gid','st_mode')
        if info.st_size!=expected_size or stat.S_IMODE(info.st_mode)!=0o644:
            raise ValueError('campaign_before_boundary_drift')
        with os.fdopen(os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)),'rb') as stream:
            opened=os.fstat(stream.fileno())
            if any(getattr(info,k)!=getattr(opened,k) for k in fields):raise ValueError('campaign_before_changed')
            raw=stream.read(expected_size+1)
        after=path.lstat();base.no_target_link(path)
        if any(getattr(info,k)!=getattr(after,k) for k in fields):raise ValueError('campaign_before_changed')
        if digest(raw)!=expected_sha:raise ValueError('campaign_before_git_drift')
        return {'path':name,'sha256':expected_sha,'mode':'0o644'}
    return {'path': name, 'sha256': digest(path.read_bytes()), 'mode': oct(stat.S_IMODE(info.st_mode))}


def observe(root=Path('/'), installed=None):
    base = frozen()
    import runtime_release as release
    rows = {name: file_metadata(base, root, target, name in NEW and (not installed or release.EXECUTION_MODE)) for name, target in TARGETS.items()}
    expected = {row['candidate']: row['sha256'] for row in installed['files']} if installed else KNOWN
    if (release.ARCHIVE_MODE or release.COMPOSER_STATIC_MODE) and installed:
        all_hashes=installed['archive_all_hashes']
        expected={name:all_hashes[target] for name,target in TARGETS.items()}
    if installed and release.NATIVE_MODE and not release.NATIVE_ADMISSION_MODE:
        expected.update({name:None for name in release.NEW})
        expected.update(release.NATIVE_EXTERNAL_BEFORE)
        expected['unit/native-control.conf'] = release.NATIVE_UNIT_BEFORE_SHA
        expected['runtime/direct_provider.py'] = release.NATIVE_PROVIDER_BEFORE_SHA
    if installed and release.TRANSPORT_MODE:
        expected[release.TRANSPORT_CANDIDATE] = release.promoted_transport_sha(installed, base)
    if installed and release.EXECUTION_MODE and not (release.DIAGNOSTICS_MODE or release.TASK_INDEX_MODE or release.WORKER_DIAGNOSTICS_MODE or release.TRANSPORT_MODE or release.STREAM_MODE or release.BINDINGS_MODE or release.GUARD_MODE or release.NATIVE_MODE or release.ARCHIVE_MODE):
        pinned = {r['path']:r['sha256'] for r in installed['unchangedRequired']}
        expected.update({name:None if name in NEW else pinned[target]
                         for name,target in TARGETS.items() if name not in release.LEGACY_TARGETS})
    for name, row in rows.items():
        if (not installed and name in NEW and row['sha256'] is not None) or (name in expected and row['sha256'] != expected[name]):
            raise ValueError('runtime_source_baseline_drift: ' + row['path'])
        expected_mode = '0o600' if row['path'] == NGINX else '0o644'
        if row['sha256'] is not None and row['mode'] != expected_mode:
            raise ValueError('runtime_mode_drift: ' + row['path'])
    if release.ARCHIVE_MODE or release.COMPOSER_STATIC_MODE:
        protected=[]
        for name in sorted(protected_paths(base)):
            if name==release.ARCHIVE_USAGE_LEDGER:
                protected.append(release.archive_usage_metadata(base,root));continue
            path=base.rooted(root,name);base.no_target_link(path);info=path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('archive_protected_regular_required')
            protected.append({'path':name,'sha256':digest(path.read_bytes()),'mode':oct(stat.S_IMODE(info.st_mode)),'owner':str(info.st_uid)+':'+str(info.st_gid)})
    else:protected = [file_metadata(base, root, path) for path in sorted(protected_paths(base))]
    expected_protected = {r['path']:r['sha256'] for r in installed['unchangedRequired']
                          if r['path'] in protected_paths(base)} if installed else None
    if installed and release.NATIVE_MODE:
        expected_protected[release.NATIVE_CLI] = release.NATIVE_CLI_SHA
        expected_protected[release.NATIVE_LEGACY_DAILY] = release.NATIVE_LEGACY_DAILY_SHA
        release.native_legacy_daily_guard(base,root)
    if installed and (release.ARCHIVE_MODE or release.COMPOSER_STATIC_MODE):
        expected_protected=dict(release.ARCHIVE_PROTECTED)
        for row in protected:
            if row['path']==release.ARCHIVE_USAGE_LEDGER and row['path'] in expected_protected:
                expected_protected[row['path']]=row['sha256']
    if installed and {r['path']: r['sha256'] for r in protected} != expected_protected:
        raise ValueError('installed_protected_baseline_drift')
    if (release.COMPOSER_STATIC_MODE or release.NATIVE_CAPABILITIES_MODE) and any(any(r[k]!=release.COMPOSER_STATIC_METADATA[r['path']][k] for k in ('owner','mode')) for r in protected):
        raise ValueError('composer_static_protected_metadata_drift')
    worker = worker_observation(allow_stopped=not (release.COMPOSER_STATIC_MODE or release.WORKER_DIAGNOSTICS_MODE or release.TRANSPORT_MODE or release.STREAM_MODE or release.BINDINGS_MODE or release.GUARD_MODE or release.NATIVE_MODE)) if root == Path('/') else {
        'image': FROZEN_IMAGE_MARKER if release.ARCHIVE_MODE or release.COMPOSER_STATIC_MODE else 'sha256:' + '0' * 64, 'state': 'active', 'source': 'container'}
    if installed and worker['image'] != (FROZEN_IMAGE_MARKER if release.ARCHIVE_MODE or release.COMPOSER_STATIC_MODE else installed['workerImageId']):
        raise ValueError('installed_worker_image_drift')
    result = {'observed_at': datetime.now(timezone.utc).isoformat(), 'files': rows, 'protected': protected,
              'worker_image': worker['image'], 'worker_state': worker['state'], 'worker_image_source': worker['source']}
    if release.NATIVE_MODE:
        result['native_dependencies'] = release.native_dependencies(base, root)
    return result


def pack(repo, output, commit):
    if output.exists() or not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('new_payload_and_exact_commit_required')
    output.mkdir(parents=True, mode=0o700)
    paths = {**{'payload/' + name: path for name, path in SOURCES.items()},
             **PUBLISHER_SOURCES}
    hashes = {}
    import runtime_release as release
    generated_bodies = admission_generated(repo) if release.NATIVE_ADMISSION_MODE else native_generated() if release.NATIVE_MODE else {}
    generated = {'payload/'+name:raw for name,raw in generated_bodies.items()}
    for name, path in paths.items():
        # Read exact Git bytes: neither Windows autocrlf nor a working copy is a
        # deployment input. This command cannot read credentials outside SOURCES.
        raw = generated[name] if name in generated else subprocess.check_output(['git', 'show', commit + ':' + path], cwd=repo)
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        hashes[name] = digest(raw)
    import runtime_release as release
    baseline = {name: (digest(generated_bodies[name]) if release.NATIVE_ADMISSION_MODE and name in generated_bodies else None if release.EXECUTION_MODE and name in NEW else release.NATIVE_UNIT_BEFORE_SHA if release.NATIVE_MODE and name == 'unit/native-control.conf' else digest(subprocess.check_output(['git', 'show', INSTALLED_COMMIT + ':' + path], cwd=repo)))
                for name, path in SOURCES.items()}
    if not (release.ARCHIVE_MODE or release.COMPOSER_STATIC_MODE):baseline['http/formal.conf'] = INSTALLED_NGINX_SHA
    if release.COMPOSER_STATIC_MODE and (baseline!={'frontend/index.html':release.COMPOSER_BEFORE_SHA} or
            hashes['payload/frontend/index.html']!=release.COMPOSER_AFTER_SHA):
        raise ValueError('exact_composer_static_git_delta_required')
    if release.NATIVE_ADMISSION_MODE:
        changed = [name for name in SOURCES if hashes['payload/'+name] != baseline[name]]
        if (changed != [release.NATIVE_ADMISSION_CANDIDATE] or
                baseline[release.NATIVE_ADMISSION_CANDIDATE] != release.NATIVE_ADMISSION_BEFORE_SHA or
                hashes['payload/'+release.NATIVE_ADMISSION_CANDIDATE] != release.NATIVE_ADMISSION_AFTER_SHA):
            raise ValueError('exact_native_admission_git_delta_required')
    if release.NATIVE_CAPABILITIES_MODE and ({name for name in SOURCES if hashes['payload/'+name]!=baseline[name]}!=set(release.CAPABILITIES_CHANGED) or {name for name,value in baseline.items() if value is None}!=set(release.NEW)):
        raise ValueError('exact_native_capabilities_git_delta_required')
    installed_baseline={'source_commit': INSTALLED_COMMIT, 'files': baseline}
    if release.NATIVE_MODE:
        legacy=digest(subprocess.check_output(['git','show',('23a27325b00f27a5c5696657c7c4141a06135f18' if release.NATIVE_ADMISSION_MODE else INSTALLED_COMMIT)+':'+SOURCES['approval/daily_review.py']],cwd=repo))
        if legacy!=release.NATIVE_LEGACY_DAILY_SHA:raise ValueError('native_legacy_daily_git_drift')
        installed_baseline['protected']={release.NATIVE_LEGACY_DAILY:legacy}
    raw = json.dumps({'source_commit': commit, 'files': hashes, 'material_execution':release.EXECUTION_MODE,
                      'material_diagnostics':release.DIAGNOSTICS_MODE,
                      'goal_task_index_compat':release.TASK_INDEX_MODE,
                      'worker_diagnostics':release.WORKER_DIAGNOSTICS_MODE,
                      'material_transport':release.TRANSPORT_MODE,
                      'material_stream':release.STREAM_MODE,
                      'bindings_auth':release.BINDINGS_MODE,
                      'material_guard':release.GUARD_MODE,
                      'native_chat':release.NATIVE_MODE and not release.NATIVE_ADMISSION_MODE,
                      'native_admission':release.NATIVE_ADMISSION_MODE,
                      'native_archive':release.ARCHIVE_MODE and not release.NATIVE_CAPABILITIES_MODE,
                      'native_capabilities':release.NATIVE_CAPABILITIES_MODE,
                      'native_composer_static':release.COMPOSER_STATIC_MODE,
                      'installed_baseline': installed_baseline},
                     sort_keys=True).encode('utf-8')
    (output / 'payload-manifest.json').write_bytes(raw)
    return {'source_commit': commit, 'payload_files': len(SOURCES), 'payload_sha256': digest(raw)}


def prepare(payload, stage, commit, payload_sha256, *, root=Path('/'), release_ready=False, followup=False):
    if stage.exists() or not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('new_stage_and_exact_commit_required')
    raw = (payload.parent / 'payload-manifest.json').read_bytes()
    if digest(raw) != payload_sha256:
        raise ValueError('approved_git_payload_required')
    descriptor = json.loads(raw)
    if sum(descriptor.get(key) is True for key in ('native_composer_static','native_capabilities','native_archive','native_admission','goal_task_index_compat', 'material_diagnostics', 'worker_diagnostics', 'material_transport', 'material_stream', 'bindings_auth', 'material_guard','native_chat')) > 1:
        raise ValueError('conflicting_material_followup_modes')
    if descriptor.get('native_composer_static') is True:
        if descriptor.get('material_execution') is not False or not followup:
            raise ValueError('composer_static_requires_installed_followup')
        configure_native_composer_static()
    if __import__('runtime_release').COMPOSER_STATIC_MODE and descriptor.get('native_composer_static') is not True:
        raise ValueError('composer_static_requires_installed_followup')
    if (descriptor.get('native_capabilities') is True or descriptor.get('native_archive') is True or descriptor.get('native_admission') is True or descriptor.get('native_chat') is True or descriptor.get('material_stream') is True or descriptor.get('bindings_auth') is True or descriptor.get('material_guard') is True) and descriptor.get('material_execution') is not True:
        raise ValueError('material_stream_requires_execution')
    if descriptor.get('material_execution') is True:
        if descriptor.get('native_capabilities') is True:configure_native_capabilities()
        elif descriptor.get('native_archive') is True:configure_native_archive()
        elif descriptor.get('native_admission') is True:configure_native_admission()
        elif descriptor.get('native_chat') is True:configure_native_chat()
        elif descriptor.get('material_guard') is True:configure_material_guard()
        elif descriptor.get('bindings_auth') is True:configure_bindings_auth()
        elif descriptor.get('material_stream') is True:configure_material_stream()
        elif descriptor.get('material_transport') is True:configure_material_transport()
        elif descriptor.get('worker_diagnostics') is True:configure_worker_diagnostics()
        elif descriptor.get('goal_task_index_compat') is True:configure_task_index_compat()
        elif descriptor.get('material_diagnostics') is True:configure_diagnostics()
        else:configure_execution()
        if not followup:raise ValueError('material_execution_requires_installed_followup')
    if descriptor.get('source_commit') != commit:
        raise ValueError('payload_source_commit_mismatch')
    expected = {'payload/' + name for name in SOURCES} | set(PUBLISHER_SOURCES)
    if set(descriptor.get('files', {})) != expected:
        raise ValueError('exact_git_payload_required')
    for name, sha in descriptor['files'].items():
        if digest((payload.parent / name).read_bytes()) != sha:
            raise ValueError('git_payload_changed')
    installed = installed_baseline(root, descriptor.get('installed_baseline')) if followup else None
    observed = observe(root, installed)
    # Source verification and body-limit generation happen before creating a stage.
    bodies = {name: (payload / name).read_bytes() for name in SOURCES}
    if descriptor.get('native_admission'):
        import runtime_release as release
        if (digest(bodies['unit/native-control.conf']) != release.NATIVE_CURRENT_UNIT_SHA or
                bodies['runtime/native-backend.json'] != release.native_backend_bytes() or
                observed['native_dependencies'].get('socket',{}).get('gid') != release.NATIVE_SOCKET_GID):
            raise ValueError('native_admission_existing_contract_required')
    if descriptor.get('native_chat'):
        import runtime_release as release
        if bodies['unit/native-control.conf'] != native_generated()['unit/native-control.conf']:
            raise ValueError('native_unit_recipe_changed')
        bodies['unit/native-control.conf'] = render_native_unit(
            frozen().rooted(root, release.NATIVE_UNIT).read_bytes(), observed['native_dependencies'])
    if not (__import__('runtime_release').ARCHIVE_MODE or __import__('runtime_release').COMPOSER_STATIC_MODE):
        nginx = frozen().rooted(root, NGINX).read_bytes()
        if digest(nginx) != observed['files']['http/formal.conf']['sha256']:
            raise ValueError('nginx_changed_during_prepare')
        bodies['http/formal.conf'] = nginx if installed else patch_nginx(nginx)
    files = [{'candidate': name, 'target': target, 'beforeSha256': observed['files'][name]['sha256'],
              'sha256': digest(bodies[name]), 'owner': '0:0', 'mode': '0o600' if target == NGINX else '0o644'}
             for name, target in TARGETS.items()]
    from runtime_release import SCOPE
    manifest = {'schemaVersion': 1, 'scope': SCOPE, 'sourceCommit': commit, 'releaseReady': release_ready,
                # Compatibility marker required by the unchanged historical
                # validator, not a claim about today's installed container.
                'imageId': FROZEN_IMAGE_MARKER, 'workerImageId': observed['worker_image'],
                'readinessSha256': descriptor['files']['release_readiness.py'],
                'businessWrites': False, 'timersChanged': False, 'files': files,
                'unchangedRequired': [({k:r[k] for k in ('path','sha256','owner','mode')} if __import__('runtime_release').ARCHIVE_MODE or __import__('runtime_release').COMPOSER_STATIC_MODE else {'path':r['path'],'sha256':r['sha256']}) for r in observed['protected']],
                'runtimeRequired': {unit: {'ActiveState': 'active'} for unit in (
                    'fs-business-range.service', 'fs-hermes-fc.service', 'nginx.service')},
                'runtimeBefore': {unit: {'ActiveState': observed['worker_state'] if unit == 'fs-hermes-fc.service' else 'active'}
                                  for unit in ('fs-business-range.service', 'fs-hermes-fc.service', 'nginx.service')},
                'workerImageSource': observed['worker_image_source'],
                'baselineObservedAt': observed['observed_at'], 'approvedPayloadSha256': payload_sha256}
    if installed:
        manifest['installedBaseline'] = INSTALLED_PROOF
        if __import__('runtime_release').COMPOSER_STATIC_MODE:
            release=__import__('runtime_release')
            if len(files)!=1 or files[0]['beforeSha256']!=release.COMPOSER_BEFORE_SHA or files[0]['sha256']!=release.COMPOSER_AFTER_SHA:
                raise ValueError('exact_composer_static_delta_required')
            manifest['nativeComposerStatic']=True
            manifest['materialChangedTargets']=[files[0]['target']]
        if __import__('runtime_release').EXECUTION_MODE:manifest['materialExecution']=True
        if __import__('runtime_release').DIAGNOSTICS_MODE:manifest['materialDiagnostics']=True
        if __import__('runtime_release').TASK_INDEX_MODE:manifest['goalTaskIndexCompat']=True
        if __import__('runtime_release').WORKER_DIAGNOSTICS_MODE:manifest['workerDiagnostics']=True
        if __import__('runtime_release').TRANSPORT_MODE:manifest['materialTransport']=True
        if __import__('runtime_release').STREAM_MODE:manifest['materialStream']=True
        if __import__('runtime_release').BINDINGS_MODE:manifest['bindingsAuth']=True
        if __import__('runtime_release').GUARD_MODE:manifest['materialGuard']=True
        if __import__('runtime_release').ARCHIVE_MODE:
            manifest['nativeArchive']=True
            if __import__('runtime_release').NATIVE_CAPABILITIES_MODE:
                manifest['nativeCapabilities']=True
                manifest['nativeStaticBaseline']=dict(__import__('runtime_release').CAPABILITIES_STATIC_PROOF)
            manifest['archiveException']=__import__('runtime_release').archive_check(frozen(),root,payload/'runtime/conversation_store.py',descriptor['files']['payload/runtime/conversation_store.py'])
        if __import__('runtime_release').NATIVE_MODE:
            manifest['nativeAdmission' if __import__('runtime_release').NATIVE_ADMISSION_MODE else 'nativeChat']=True
            manifest['nativeDependencies']=observed['native_dependencies']
        manifest['materialStaticOnly'] = all(row['beforeSha256'] == row['sha256'] or row['candidate'].startswith('frontend/')
                                            for row in files)
        if manifest['materialStaticOnly'] and (observed['worker_state'] != 'active' or observed['worker_image_source'] != 'container'):
            raise ValueError('static_followup_requires_running_worker')
        if manifest.get('nativeArchive') or manifest.get('nativeAdmission') or manifest.get('nativeChat') or manifest.get('materialGuard') or manifest.get('bindingsAuth') or manifest.get('materialStream') or manifest.get('materialTransport') or manifest.get('workerDiagnostics') or manifest.get('materialDiagnostics') or manifest.get('goalTaskIndexCompat'):
            allowed = tuple(TARGETS) if manifest.get('nativeArchive') else (__import__('runtime_release').NATIVE_ADMISSION_CANDIDATE,) if manifest.get('nativeAdmission') else __import__('runtime_release').NATIVE_ALLOWED if manifest.get('nativeChat') else ('runtime/conversation_file_bindings.py',) if manifest.get('bindingsAuth') else ('runtime/transport.py',) if manifest.get('materialTransport') or manifest.get('materialStream') or manifest.get('materialGuard') else ('runtime/hermes_worker.py',) if manifest.get('workerDiagnostics') else ('runtime/conversation_goal_tasks.py',) if manifest.get('goalTaskIndexCompat') else ('http/conversation_http.py', 'http/range_api.py')
            changed = [r['target'] for r in files if r['beforeSha256'] != r['sha256']]
            if (observed['worker_state'] != 'active' or observed['worker_image_source'] != 'container'
                    or manifest.get('nativeArchive') and changed != ([TARGETS[n] for n in __import__('runtime_release').CAPABILITIES_CHANGED] if manifest.get('nativeCapabilities') else list(TARGETS.values()))
                    or manifest.get('nativeAdmission') and (changed != [TARGETS[__import__('runtime_release').NATIVE_ADMISSION_CANDIDATE]] or digest(bodies[__import__('runtime_release').NATIVE_ADMISSION_CANDIDATE]) != __import__('runtime_release').NATIVE_ADMISSION_AFTER_SHA)
                    or manifest.get('workerDiagnostics') and changed != [TARGETS['runtime/hermes_worker.py']]
                    or manifest.get('bindingsAuth') and changed != [TARGETS['runtime/conversation_file_bindings.py']]
                    or (manifest.get('materialTransport') or manifest.get('materialStream') or manifest.get('materialGuard')) and changed != [TARGETS['runtime/transport.py']]
                    or any(r['beforeSha256'] != r['sha256'] and r['candidate'] not in allowed for r in files)):
                raise ValueError('exact_native_admission_delta_required' if manifest.get('nativeAdmission') else 'exact_material_guard_delta_required' if manifest.get('materialGuard') else 'exact_bindings_auth_delta_required' if manifest.get('bindingsAuth') else 'exact_material_stream_delta_required' if manifest.get('materialStream') else 'exact_material_transport_delta_required' if manifest.get('materialTransport') else 'exact_worker_diagnostics_delta_required' if manifest.get('workerDiagnostics') else 'exact_goal_task_index_delta_required' if manifest.get('goalTaskIndexCompat') else 'exact_material_diagnostics_delta_required')
            manifest['materialChangedTargets'] = changed
    stage.mkdir(parents=True, mode=0o700)
    for name, body in bodies.items():
        path = stage / 'candidate' / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(body)
        path.chmod(0o600)
    for name in ('runtime_release.py', 'release_navigation_base.py', 'release_readiness.py'):
        shutil.copyfile(payload.parent / name, stage / name)
    raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    (stage / 'approved-manifest.json').write_bytes(raw)
    (stage / 'baseline.json').write_text(json.dumps(observed, indent=2), encoding='utf-8')
    shutil.copyfile(payload.parent / 'payload-manifest.json', stage / 'payload-manifest.json')
    return {'stage': str(stage), 'manifest_sha256': digest(raw), 'files': len(files),
            'release_ready': release_ready, 'production_writes': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('observe', 'pack', 'prepare'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--payload', type=Path)
    parser.add_argument('--source-commit')
    parser.add_argument('--approved-payload-sha256')
    parser.add_argument('--release-ready', action='store_true')
    parser.add_argument('--followup', action='store_true')
    parser.add_argument('--materials-execution', action='store_true')
    parser.add_argument('--materials-diagnostics', action='store_true')
    parser.add_argument('--goal-task-index-compat', action='store_true')
    parser.add_argument('--worker-diagnostics', action='store_true')
    parser.add_argument('--material-transport', action='store_true')
    parser.add_argument('--material-stream', action='store_true')
    parser.add_argument('--bindings-auth', action='store_true')
    parser.add_argument('--material-guard', action='store_true')
    parser.add_argument('--native-chat', action='store_true')
    parser.add_argument('--native-admission', action='store_true')
    parser.add_argument('--native-archive', action='store_true')
    parser.add_argument('--native-capabilities', action='store_true')
    parser.add_argument('--native-composer-static', action='store_true')
    args = parser.parse_args()
    if sum((args.native_composer_static,args.native_capabilities,args.native_archive,args.native_admission,args.native_chat,args.material_guard, args.bindings_auth, args.material_stream, args.material_transport, args.worker_diagnostics, args.goal_task_index_compat, args.materials_diagnostics)) > 1 or args.native_composer_static and args.materials_execution:
        parser.error('choose one installed followup mode')
    if args.native_composer_static:configure_native_composer_static()
    elif args.native_capabilities:configure_native_capabilities()
    elif args.native_archive:configure_native_archive()
    elif args.native_admission:configure_native_admission()
    elif args.native_chat:configure_native_chat()
    elif args.material_guard:configure_material_guard()
    elif args.bindings_auth:configure_bindings_auth()
    elif args.material_stream:configure_material_stream()
    elif args.material_transport:configure_material_transport()
    elif args.worker_diagnostics:configure_worker_diagnostics()
    elif args.goal_task_index_compat:configure_task_index_compat()
    elif args.materials_diagnostics:configure_diagnostics()
    elif args.materials_execution:configure_execution()
    if args.action == 'observe':
        value = observe()
    elif args.action == 'pack':
        value = pack(args.repo, args.output, args.source_commit)
    else:
        value = prepare(args.payload, args.output, args.source_commit, args.approved_payload_sha256,
                        release_ready=args.release_ready, followup=args.followup)
    print(json.dumps(value, ensure_ascii=False, indent=2))
