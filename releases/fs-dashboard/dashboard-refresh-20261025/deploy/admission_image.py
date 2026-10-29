"""One COPY layer over the current pinned image; never activate or change a unit."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BEFORE='sha256:0a6b8e71c8b88db2d008024306c87a7feaeec105b8232598d91df5854374bc3c'
BASE_TAG='fs-hermes-native:learning-a9b57cc31b395fdf0ba669df'
ENTRY='/opt/hermes/fs_native_entry.py'
BEFORE_SOURCES={ENTRY:'a6aab410cad21162e42bd94d99d1810a489eceb66f974fca24177e2a9bed5224',
 '/opt/hermes/tui_gateway/server.py':'5e69b1d2290d5cca7ea9fd8be543585ad393d65fd9a8d9d1d9645437dc853252',
 '/opt/hermes/gateway/run_turn_runner.py':'23b99dac6998e1e1e4639bcaf80b3cd6cc72e6582c3fcb13f423754bbd36aaf9',
 '/opt/hermes/reviewed_skills.py':'a3d546177396ba906f66c4f8411111aaefb3c96371dc628ac5ada2daf023e660'}
DOCKERFILE=b'ARG NATIVE_BASE\nFROM ${NATIVE_BASE}\nCOPY fs_native_entry.py /opt/hermes/fs_native_entry.py\n'


def read(template,image):
    return subprocess.check_output(['docker','image','inspect','-f',template,image],text=True).strip()


def sources(image):
    raw=subprocess.check_output(['docker','run','--rm','--read-only','--network','none','--entrypoint','sha256sum',image,*sorted(BEFORE_SOURCES)],text=True)
    return {line.split()[1]:line.split()[0] for line in raw.splitlines()}


def build(context,state_path,commit,source_sha):
    context,state_path=Path(context),Path(state_path)
    if (not re.fullmatch('[a-f0-9]{40}',commit) or not re.fullmatch('[a-f0-9]{64}',source_sha)
            or {p.name for p in context.iterdir()}!={'Dockerfile','fs_native_entry.py'}
            or (context/'Dockerfile').read_bytes()!=DOCKERFILE
            or hashlib.sha256((context/'fs_native_entry.py').read_bytes()).hexdigest()!=source_sha):
        raise ValueError('admission_committed_image_context_required')
    compile((context/'fs_native_entry.py').read_bytes(),ENTRY,'exec')
    if state_path.exists():raise ValueError('admission_build_exists_reconcile_original_operation')
    if read('{{.Id}}',BASE_TAG)!=BEFORE or read('{{.Id}}',BEFORE)!=BEFORE or sources(BEFORE)!=BEFORE_SOURCES:
        raise ValueError('admission_current_native_image_drift')
    layers=json.loads(read('{{json .RootFS.Layers}}',BEFORE));user=read('{{json .Config.User}}',BEFORE)
    tag='fs-hermes-native:admission-'+commit[:24]
    prior=subprocess.run(['docker','image','inspect','-f','{{.Id}}',tag],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15)
    if prior.returncode==0:raise ValueError('admission_build_tag_exists_reconcile_original_operation')
    if prior.returncode!=1 or 'No such image' not in prior.stderr:raise ValueError('admission_build_tag_probe_unknown')
    expected=dict(BEFORE_SOURCES);expected[ENTRY]=source_sha
    state=dict(status='build_intent',source_commit=commit,source_sha256=source_sha,before=BEFORE,tag=tag,base_layers=layers,runtime_user=user)
    fd=os.open(state_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as stream:json.dump(state,stream,indent=2)
    try:
        with state_path.with_suffix('.stdout').open('wb') as out,state_path.with_suffix('.stderr').open('wb') as err:
            subprocess.run(['docker','build','--network','none','--pull=false','--build-arg','NATIVE_BASE='+BASE_TAG,
                '-f',str(context/'Dockerfile'),'-t',tag,str(context)],check=True,stdout=out,stderr=err,timeout=180)
        after=read('{{.Id}}',tag);child=json.loads(read('{{json .RootFS.Layers}}',after))
        if (not re.fullmatch('sha256:[a-f0-9]{64}',after) or after==BEFORE or child[:len(layers)]!=layers
                or len(child)!=len(layers)+1 or read('{{json .Config.User}}',after)!=user
                or sources(after)!=expected or read('{{.Id}}',BASE_TAG)!=BEFORE):
            raise ValueError('admission_derived_image_readback_differs')
        subprocess.run(['docker','run','--rm','--read-only','--network','none','--entrypoint','python',after,
            '-I','-B','-c',"from pathlib import Path; compile(Path('/opt/hermes/fs_native_entry.py').read_bytes(),'/opt/hermes/fs_native_entry.py','exec')"],check=True,timeout=30)
        state.update(status='built_verified_not_activated',image=after,sources=expected,child_layers=child)
    except BaseException as error:
        state.update(status='unknown-needs-reconcile',failure=type(error).__name__+':'+str(error))
        state_path.write_text(json.dumps(state,indent=2));raise
    state_path.write_text(json.dumps(state,indent=2));return state
