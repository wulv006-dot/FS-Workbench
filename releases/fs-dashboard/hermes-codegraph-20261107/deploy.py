"""Install the pinned tool and native plugin in the existing Hermes profile."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

PROFILE = Path('/var/lib/fs-hermes-fc/profile')
ROOT = PROFILE/'cache/fs-codegraph'
VERSION = '1.6.2'
EXPECTED = 'ef0af416092128fb1ccc723786000b7edf4a6971fe604acd08bf966e4f37b828'


def save(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(str(temporary), str(path))


def container_python(code, timeout=120):
    result = subprocess.run(['docker','exec','-i','fs-hermes-desktop','/opt/hermes/.venv/bin/python','-'],
                            input=code, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, timeout=timeout)
    if result.returncode:
        # The child only prints setup/code metadata; model configuration values are never printed.
        raise RuntimeError('Hermes setup failed: '+result.stdout+'\n'+result.stderr)
    return result.stdout.strip()


def deploy(payload):
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt_path = ROOT/'install-20261107.json'
    if receipt_path.is_file():
        previous = json.loads(receipt_path.read_text())
        if previous.get('phase') == 'complete':
            print(json.dumps(previous, ensure_ascii=False))
            return
        if (previous.get('phase') != 'started' or (ROOT/'config.before-20261107.yaml').exists()
                or (PROFILE/'plugins/fs-codegraph').exists()):
            raise RuntimeError('Prior installation receipt requires reconciliation before retry')
    receipt = {'phase':'started','version':VERSION,'production_source_changes':False}
    save(receipt_path, receipt)
    tool = PROFILE/'tools/codegraph'/VERSION
    tool.mkdir(parents=True, exist_ok=True)
    archive = tool/'codegraph-linux-x64.tar.gz'
    assert archive.is_file(), 'Transfer the verified Linux release archive before installation'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == EXPECTED, 'Release checksum mismatch'
    with tarfile.open(str(archive)) as bundle:
        for entry in bundle.getmembers():
            target = os.path.realpath(str(tool/entry.name))
            assert os.path.commonpath([str(tool),target]) == str(tool)
            assert entry.isfile() or entry.isdir() or entry.issym() or entry.islnk()
            if entry.issym() or entry.islnk():
                base = os.path.dirname(target) if entry.issym() else str(tool)
                assert os.path.commonpath([str(tool),os.path.realpath(os.path.join(base,entry.linkname))]) == str(tool)
        bundle.extractall(str(tool))
    version = container_python("import subprocess; print(subprocess.check_output(['/profile/tools/codegraph/1.6.2/codegraph-linux-x64/bin/codegraph','--version']).decode().strip())")
    assert version == VERSION, version
    receipt.update(phase='binary_verified',archive_sha256=EXPECTED)
    save(receipt_path, receipt)
    print(json.dumps({'phase':'binary_verified','version':version}), flush=True)
    inventory_path = ROOT/'inventory_187.py'
    inventory_path.write_text(payload['inventory'], encoding='utf-8')
    result = subprocess.run([sys.executable,str(inventory_path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                            universal_newlines=True,timeout=120)
    if result.returncode:
        raise RuntimeError('Source inventory failed: '+result.stderr)
    inventory = json.loads(result.stdout)
    receipt.update(phase='inventory_captured',inventory_summary=inventory)
    save(receipt_path,receipt)
    print(json.dumps({'phase':'inventory_captured','units':inventory['units'],'projects':list(inventory['projects'])}),flush=True)
    plugin = PROFILE/'plugins/fs-codegraph'
    plugin.mkdir(parents=True,exist_ok=True)
    for name,text in payload['plugin_files'].items():
        assert name in ('__init__.py','plugin.yaml')
        target = plugin/name
        if target.exists() and target.read_text(encoding='utf-8') != text:
            raise RuntimeError('Existing plugin differs; preserve it and review before replacement')
        target.write_text(text,encoding='utf-8')
    indexes = container_python(r'''
import json,os,pathlib,subprocess
root=pathlib.Path('/profile/cache/fs-codegraph')
projects=json.loads((root/'projects.json').read_text())['projects']
binary='/profile/tools/codegraph/1.6.2/codegraph-linux-x64/bin/codegraph'
env=dict(os.environ,CODEGRAPH_TELEMETRY='0')
results={}
for key,entry in projects.items():
    project=pathlib.Path(entry['path'])
    assert project.is_dir()
    assert entry['source_files']<=600, 'Initial source scope needs partitioning: '+key
    with (root/('index-'+key+'.log')).open('w') as log:
        done=subprocess.run([binary,'init','--yes',str(project)],stdout=log,stderr=subprocess.STDOUT,env=env,timeout=180)
    assert done.returncode==0, 'Initial index failed: '+key
    results[key]={'indexed':(project/'.codegraph/codegraph.db').is_file(),'source_files':entry['source_files']}
    assert results[key]['indexed']
print(json.dumps(results))
''',timeout=700)
    receipt.update(phase='indexes_ready',indexes=json.loads(indexes))
    save(receipt_path,receipt)
    print(json.dumps({'phase':'indexes_ready','projects':list(receipt['indexes'])}),flush=True)
    activation = container_python(r'''
import hashlib,json,pathlib
from hermes_cli.config import read_user_config_raw
from hermes_cli.plugins_cmd import dashboard_set_agent_plugin_enabled
from hermes_cli.plugins_activation import activate_plugin_now
home=pathlib.Path('/profile'); root=home/'cache/fs-codegraph'
config=home/'config.yaml'; before_bytes=config.read_bytes(); before=read_user_config_raw()
backup=root/'config.before-20261107.yaml'
assert not backup.exists(), 'Prior config backup requires reconciliation'
backup.write_bytes(before_bytes); backup.chmod(0o600)
assert hashlib.sha256(config.read_bytes()).digest()==hashlib.sha256(before_bytes).digest(), 'Concurrent config change'
result=dashboard_set_agent_plugin_enabled('fs-codegraph',enabled=True)
assert result.get('ok'),result
after=read_user_config_raw()
for key in ('model','agent','terminal','approvals','memory','skills','platforms'):
    assert after.get(key)==before.get(key),'Existing configuration changed: '+key
assert set(before['platform_toolsets']['cli'])<=set(after['platform_toolsets']['cli'])
assert set(before.get('plugins',{}).get('enabled',[]))<=set(after.get('plugins',{}).get('enabled',[]))
notified=activate_plugin_now('fs-codegraph',in_process=False)
print(json.dumps({'enable':result,'live_notification':notified,'config_before_sha256':hashlib.sha256(before_bytes).hexdigest(),
                  'config_after_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),'existing_toolsets_preserved':True}))
''',timeout=180)
    receipt.update(phase='plugin_enabled',activation=json.loads(activation))
    save(receipt_path,receipt)
    print(json.dumps({'phase':'plugin_enabled','activation':receipt['activation']},ensure_ascii=False),flush=True)
    receipt['phase']='complete'
    save(receipt_path,receipt)
    print(json.dumps(receipt,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    deploy(json.load(sys.stdin))
