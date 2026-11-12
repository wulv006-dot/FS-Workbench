import fcntl,hashlib,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
MANIFEST=ROOT/'receipt.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True).stdout.strip()
def write(p,data):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.loot-v11-')
 with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 os.chmod(tmp,0o644);os.replace(tmp,p)
def main(action):
 lock=open('/var/lock/bot-console-release.lock','a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 if action=='rollback':
  d=json.loads(MANIFEST.read_text())
  for x in d['files']:
   if sha(x['target'])!=x['after']:raise RuntimeError('File drift: '+x['target'])
  run('systemctl','stop','mmoexp-lucky-loot')
  for x in d['files']:
   if x.get('backup'):write(x['target'],Path(x['backup']).read_bytes())
  run('systemctl','restart','mmoexp-lucky-loot','bot-console');print('rolled back code only; current state preserved');return
 if MANIFEST.exists():raise RuntimeError('Already applied')
 expected=json.loads((ROOT/'expected.json').read_text())
 for name,digest in expected.items():
  if sha(name)!=digest:raise RuntimeError('Baseline changed: '+name)
 files=[];backup=ROOT/'backup';backup.mkdir(exist_ok=True)
 for p in (ROOT/'src').iterdir():
  if not p.is_file():continue
  targets=[Path('/opt/mmoexp-lucky-loot')/p.name]
  if p.name.startswith('giveaway.'):targets.append(Path('/opt/bot-console/static')/p.name)
  if p.name=='lucky_proxy.py':targets.append(Path('/opt/bot-console')/p.name)
  for target in targets:
   item={'source':p.name,'target':str(target),'after':sha(p)}
   if target.exists():
    dest=backup/(str(len(files))+'-'+target.name);shutil.copy2(target,dest);item.update(backup=str(dest),before=sha(target))
   files.append(item)
 try:
  run('systemctl','stop','mmoexp-lucky-loot')
  for x in files:write(x['target'],(ROOT/'src'/x['source']).read_bytes())
  for name in ['app.cjs','cards.cjs','core.cjs','giveaway.js']:run('/usr/local/bin/node','--check','/opt/mmoexp-lucky-loot/'+name)
  run('/opt/bot-console/venv/bin/python','-m','py_compile','/opt/bot-console/lucky_proxy.py')
  run('systemctl','restart','mmoexp-lucky-loot','bot-console')
  write(MANIFEST,json.dumps({'version':'1.1.0','files':files,'state_restored':False},indent=2).encode())
  print(json.dumps({'deployed':'1.1.0','service':run('systemctl','is-active','mmoexp-lucky-loot'),'console':run('systemctl','is-active','bot-console')}))
 except Exception:
  for x in files:
   if x.get('backup'):write(x['target'],Path(x['backup']).read_bytes())
  subprocess.run(['systemctl','restart','mmoexp-lucky-loot','bot-console']);raise
if __name__=='__main__':main(sys.argv[1])
