from pathlib import Path
import hashlib,json,shutil,subprocess,fcntl
root=Path('/opt/mmoexp-lucky-loot-release-20261112')
lock=open('/var/lock/bot-console-release.lock','a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
backup=root/'backup-ui-finish';backup.mkdir(exist_ok=True)
files=['giveaway.html','giveaway.js','giveaway.css','app.cjs','core.cjs','lucky_proxy.py']
for name in files:
    p=Path('/opt/mmoexp-lucky-loot')/name
    shutil.copy2(p,backup/name)
    shutil.copy2(root/'src'/name,p)
    if name.startswith('giveaway.'):shutil.copy2(p,Path('/opt/bot-console/static')/name)
    if name=='lucky_proxy.py':shutil.copy2(p,Path('/opt/bot-console')/name)
for name in ['app.cjs','core.cjs','giveaway.js']:subprocess.run(['/usr/local/bin/node','--check','/opt/mmoexp-lucky-loot/'+name],check=True)
subprocess.run(['systemctl','restart','mmoexp-lucky-loot','bot-console'],check=True)
m=root/'release-receipt.json';d=json.loads(m.read_text());d['files']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('/opt/mmoexp-lucky-loot').iterdir() if p.is_file()};d['unit_sha256']=hashlib.sha256(Path('/etc/systemd/system/mmoexp-lucky-loot.service').read_bytes()).hexdigest();m.write_text(json.dumps(d,indent=2))
print('patched independent giveaway module; state preserved')
