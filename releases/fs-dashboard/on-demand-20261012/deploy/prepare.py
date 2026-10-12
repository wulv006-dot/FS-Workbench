"""Derive one server-private DY registry candidate; never export registry bytes."""
import argparse, hashlib, json, os, shutil
from pathlib import Path
from grant_dy import grant_all
from release_navigation import atomic, digest, no_target_link

def prepare(stage,commit):
 if os.geteuid()!=0 or len(commit)!=40 or any(c not in 'abcdef0123456789' for c in commit):raise ValueError('root and frozen source commit required')
 no_target_link(stage/'release-template.json')
 if stage.stat().st_mode & 0o077:raise ValueError('root-private staging required')
 if (stage/'approved-manifest.json').exists():raise ValueError('prepared manifest exists; reconcile original instead of retry')
 manifest=json.loads((stage/'release-template.json').read_text())
 manifest['sourceCommit']=commit
 for row in manifest['files']:
  destination=stage/'candidate'/row['candidate'];no_target_link(destination)
  if digest(Path(row['target']))!=row['beforeSha256']:raise ValueError('source CAS drift before candidate preparation')
  if row['candidate']=='machine/clients.json':
   registry=json.loads(Path(row['target']).read_text())
   payload=(json.dumps(grant_all(registry),indent=2)+'\n').encode()
   atomic(destination,payload,0o600);row['sha256']=digest(destination)
  else:
   source=stage.parent/'source'/Path(row['candidate']).name
   if digest(source)!=row['sha256']:raise ValueError('frozen source hash differs')
   atomic(destination,source.read_bytes(),0o600)
 manifest['releaseReady']=True
 raw=(json.dumps(manifest,indent=2)+'\n').encode()
 target=stage/'approved-manifest.json'
 if target.exists():raise ValueError('prepared manifest exists; reconcile original instead of retry')
 atomic(target,raw,0o600)
 return {'manifestSha256':hashlib.sha256(raw).hexdigest(),'files':len(manifest['files']),'privateRegistryChange':'DY.projects only','sourceCommit':commit}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--commit',required=True);a=p.parse_args()
 print(json.dumps(prepare(Path(__file__).resolve().parent,a.commit)))
