"""Single bounded stdin transport QA; native UID11027 or existing fixed Docker image.

Only dummy input and actual frozen candidate code are supplied. Actual probe entry
must stop at absent private proof_provenance before credentials/network. No price
proof success is claimed. Docker mode stats the existing secret mount, never reads
its contents. No root override, new account, persistent permission change or pull.
"""
import argparse, ast, base64, hashlib, json, os, re, shutil, stat, subprocess, sys, tempfile
from pathlib import Path

SOURCE_SHA='42f4151547e2d96a3e7b7331b2bb69a59e9496a03590b29d6d47166ac60fcde4'
digest=lambda raw:hashlib.sha256(raw).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-root',default=str(Path(__file__).resolve().parent/'source'))
    parser.add_argument('--image',help='Optional existing fixed sha256 image ID; never pull')
    args=parser.parse_args()
    assert sys.platform=='linux' and os.geteuid()==0 and os.getegid()==0
    if args.image:
        assert re.fullmatch(r'sha256:[0-9a-f]{64}',args.image)
        user=subprocess.check_output(['docker','image','inspect','--format','{{.Config.User}}',args.image],text=True).strip()
        assert user=='fc27chrome', 'fixed_image_user_changed'
    root=Path(args.source_root).resolve()
    files={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
    raw=files['SOURCE-MANIFEST.json'];assert digest(raw)==SOURCE_SHA
    manifest=json.loads(raw)
    assert set(files)==set(manifest['files'])|{'SOURCE-MANIFEST.json'}
    assert len(manifest['files'])==25
    for name,wanted in manifest['files'].items():assert digest(files[name])==wanted,name
    dirs={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_dir()}
    namespace={'__name__':'approved_transport_contract_validation'}
    exec(compile(files['launch.py'],'verified-launch','exec'),namespace)
    namespace['validate_bundle'](files,dirs,SOURCE_SHA)
    parsed=ast.parse(files['runner.py'].decode(),feature_version=(3,9))
    bootstrap=next(ast.literal_eval(n.value) for n in parsed.body
                   if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PROBE_BOOTSTRAP' for t in n.targets))
    cmd_literal=next(ast.literal_eval(n.value) for n in ast.walk(parsed)
                    if isinstance(n,ast.Assign) and isinstance(n.value,ast.List)
                    and any(isinstance(t,ast.Name) and t.id=='cmd' for t in n.targets))
    assert cmd_literal.count('-i')==1 and '--user' not in cmd_literal
    assert '--read-only' in cmd_literal and '--cap-drop' in cmd_literal and 'ALL' in cmd_literal
    assert 'no-new-privileges' in cmd_literal and '--group-add' in cmd_literal and '11028' in cmd_literal
    assert '/run/reconcile-input.json' not in files['runner.py'].decode()
    assert "if len(raw)>32000000:fail('probe_input_changed')" in files['runner.py'].decode()
    call=next(n for n in ast.walk(parsed) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
              and isinstance(n.func.value,ast.Name) and n.func.value.id=='subprocess' and n.func.attr=='run')
    keywords={k.arg:k.value for k in call.keywords}
    assert isinstance(keywords['input'],ast.Name) and keywords['input'].id=='raw'
    assert ast.literal_eval(keywords['capture_output']) is True and ast.literal_eval(keywords['timeout'])==75
    assert "os.chown(source,0,11028);os.chmod(source,0o640)" in files['runner.py'].decode()
    assert "('/etc/fc27-cloud/fc27.env','/run/secrets/fc27.env')" in files['runner.py'].decode()
    candidate={n:base64.b64encode(files[n+'.py']).decode('ascii') for n in ['probe','verified_loader']}
    bundle={'scope':{},'candidate':candidate,'candidate_sha256':{n:digest(files[n+'.py']) for n in candidate}}
    payload=json.dumps(bundle,separators=(',',':')).encode()
    scratch=Path(tempfile.mkdtemp(prefix='fc422-stdin-',dir='/tmp'))
    os.chown(scratch,0,11028);os.chmod(scratch,0o750)
    locked=scratch/'root-input.json';locked.write_bytes(b'no-secret-dummy')
    os.chown(locked,0,0);os.chmod(locked,0o600)
    ledger=scratch/'ledger-dummy.json';ledger.write_bytes(b'no-secret-ledger-dummy')
    os.chown(ledger,0,11028);os.chmod(ledger,0o640)
    config=scratch/'config-dummy';config.write_bytes(b'no-secret-config-dummy')
    os.chown(config,0,11028);os.chmod(config,0o640)
    passed=[]
    def drop_identity():
        os.setgroups([11027,11028]);os.setgid(11027);os.setuid(11027)
    def child(code,data=b'',tail=()):
        if args.image:
            command=['timeout','70s','docker','run','--rm','-i','--pull=never','--network','fc27-cloud-net',
                     '--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
                     '--cap-drop','ALL','--security-opt','no-new-privileges','--group-add','11028',
                     '--mount','type=bind,src='+str(locked)+',dst=/run/reconcile-input.json,readonly',
                     '--mount','type=bind,src='+str(ledger)+',dst=/run/reconcile-original-ledger.json,readonly',
                     '--mount','type=bind,src=/etc/fc27-cloud/fc27.env,dst=/run/secrets/fc27.env,readonly',
                     '--entrypoint','python3',args.image,'-I','-B','-c',code,*tail]
            return subprocess.run(command,input=data,capture_output=True,timeout=75)
        return subprocess.run([sys.executable,'-I','-B','-c',code,*tail],input=data,capture_output=True,
                              timeout=75,cwd='/tmp',preexec_fn=drop_identity)
    def mark(name):passed.append(name)
    def reject(name,data,expected_sha,reason):
        result=child(bootstrap,data,(expected_sha,))
        assert result.returncode!=0 and reason.encode() in result.stderr, name
        assert not result.stdout, name
        mark(name)
    try:
        mark('actual_manifest_and_producer_contract')
        result=child("import os,json;print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(),'groups':os.getgroups()}))")
        assert result.returncode==0
        identity=json.loads(result.stdout)
        assert identity['uid']==11027 and identity['gid']==11027 and set(identity['groups'])=={11027,11028}
        mark('actual_nonroot_identity')
        denied_path='/run/reconcile-input.json' if args.image else str(locked)
        denial="import os,json\ntry:\n fd=os.open("+repr(denied_path)+",os.O_RDONLY|os.O_NOFOLLOW)\n os.close(fd)\n print(json.dumps({'errno':0}))\nexcept PermissionError as e:\n print(json.dumps({'errno':e.errno}))"
        result=child(denial);assert result.returncode==0 and json.loads(result.stdout)['errno']==13
        mark('old_root0600_contract_denies_nonroot')
        # Real frozen probe/loader bytes execute; no fake successful proof/binding.
        # The intentional empty private scope fails before source/secret/network reads.
        reject('stdin_delivered_to_actual_private_proof_guard',payload,digest(payload),"KeyError: 'proof_provenance'")
        reject('wrong_input_sha_rejected',payload,'0'*64,'probe_input_changed')
        reject('truncated_input_rejected',payload[:-1],digest(payload),'probe_input_changed')
        excessive=b'x'*32000001
        reject('oversized_input_rejected',excessive,digest(excessive),'probe_input_changed')
        wrong=json.loads(payload);wrong['candidate_sha256']['probe']='0'*64
        data=json.dumps(wrong,separators=(',',':')).encode()
        reject('wrong_candidate_sha_rejected',data,digest(data),'probe_candidate_hash_changed')
        wrong=json.loads(payload);wrong['candidate']['unapproved']=base64.b64encode(b'raise RuntimeError()').decode()
        data=json.dumps(wrong,separators=(',',':')).encode()
        reject('candidate_closure_rejected',data,digest(data),'probe_candidate_closure_invalid')
        paths=['/run/reconcile-original-ledger.json','/run/secrets/fc27.env'] if args.image else [str(ledger),str(config)]
        code="import os,stat,json\npaths="+repr(paths)+"\nprint(json.dumps([{'regular':stat.S_ISREG(os.lstat(p).st_mode),'uid':os.lstat(p).st_uid,'gid':os.lstat(p).st_gid,'mode':stat.S_IMODE(os.lstat(p).st_mode),'nlink':os.lstat(p).st_nlink,'readable':os.access(p,os.R_OK)} for p in paths]))"
        result=child(code);assert result.returncode==0
        metadata=json.loads(result.stdout)
        for item in metadata:assert item=={'regular':True,'uid':0,'gid':11028,'mode':0o640,'nlink':1,'readable':True}
        mark('existing_group_read_contract_metadata_only')
        assert len(passed)==10
        print(json.dumps({'status':'stdin_transport_qa_passed','checks_passed':len(passed),'checks':passed,
                          'recipient_identity':identity,'fixed_image_tested':bool(args.image),
                          'mode':'existing_fixed_image' if args.image else 'native_uid11027',
                          'source_manifest_sha256':SOURCE_SHA,'bootstrap_sha256':digest(bootstrap.encode()),
                          'business_posts':0,'http_requests':0,'secret_contents_read':False,
                          'full_runtime_preflight_completed':False},sort_keys=True))
    finally:
        assert scratch.parent==Path('/tmp') and scratch.name.startswith('fc422-stdin-')
        shutil.rmtree(scratch)

if __name__=='__main__':
    main()
