"""Prepare a local sealed stage from one committed Git revision; never applies it."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

PREFIX = 'releases/fc-players/direct-json-20261029/'
CONFIG_SHA = {
    'base_env_sha256': '165451691cdb2f0e93590fb1120c488cef85ed3498efaa4df6afdb926ca107ab',
    'base_unit_sha256': '91f2fcee26451bac22480424ecb3c63fc263f8c760ffd22ff86871d4e17afba5',
    'base_on_demand_sha256': '50fc07e2a959bb0bcc68423ce7d85217a1b4eeb86dc9f77da4750fd76febd76b',
}


def digest(data):return hashlib.sha256(data).hexdigest()


def prepare(repo, commit, stage):
    def git(*args):return subprocess.check_output(['git','-C',str(repo),*args])
    revision=git('rev-parse',commit+'^{commit}').decode().strip()
    def blob(path):return git('show',revision+':'+path)
    contract_bytes=blob(PREFIX+'tag-labels/SOURCE-MAP.json')
    contract=json.loads(contract_bytes)
    contents={target:blob(row['source']) for target,row in contract['files'].items()}
    if set(contents)!={'VERSION','player_web/model_service.py','player_web/static/app.js'}:
        raise RuntimeError('Only exact three targets can be prepared')
    for name,data in contents.items():
        if digest(data)!=contract['files'][name]['candidate_sha256']:
            raise RuntimeError('Committed candidate SHA mismatch: '+name)
    if stage.exists() or stage.is_symlink():raise RuntimeError('Stage already exists; never overwrite or replay')
    stage.mkdir(mode=0o700,parents=True)
    (stage/'SOURCE-MAP.json').write_bytes(contract_bytes)
    for source,target in [('publisher/upgrade_direct_json.py','upgrade_direct_json.py'),
                          ('tag-labels/upgrade_tag_labels.py','upgrade_tag_labels.py'),
                          ('tag-labels/Dockerfile','Dockerfile')]:
        (stage/target).write_bytes(blob(PREFIX+source))
    with (stage/'delta.tar.gz').open('xb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',filename='',mtime=0) as zipped,tarfile.open(fileobj=zipped,mode='w') as archive:
        for name,data in sorted(contents.items()):
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=0
            archive.addfile(info,io.BytesIO(data))
    manifest={'version':contract['version'],'base_version':contract['base_version'],
              'base_image_id':contract['base_image_id'],'manual_flag':'FS_SHARED_BACKEND_SESSION',
              'baseline':{**contract['protected'],**{name:row['baseline_sha256'] for name,row in contract['files'].items()}},
              'files':{name:digest(data) for name,data in contents.items()},**CONFIG_SHA,
              'base_source_manifest_sha256':contract['base_source_manifest_sha256'],
              'archive_sha256':digest((stage/'delta.tar.gz').read_bytes()),
              'dockerfile_sha256':digest((stage/'Dockerfile').read_bytes()),'git_revision':revision}
    (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    receipt={'prepared_only':True,'applied':False,'git_revision':revision,
             'files':{path.name:digest(path.read_bytes()) for path in sorted(stage.iterdir())}}
    (stage/'stage-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo',type=Path);parser.add_argument('commit');parser.add_argument('stage',type=Path)
    args=parser.parse_args()
    print(json.dumps(prepare(args.repo,args.commit,args.stage),ensure_ascii=False))
