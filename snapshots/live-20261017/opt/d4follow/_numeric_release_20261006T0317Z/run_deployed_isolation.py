"""Repeat reviewed29 synthetic tests with the five installed source bytes.
No production module imports, config/queue mounts, real Session or business I/O.
"""
import pathlib,hashlib,json,tarfile,tempfile,subprocess,datetime
s=pathlib.Path(__file__).resolve().parent
m=json.loads((s/'deploy-file-cas-manifest.json').read_text(encoding='utf-8-sig'))
a=s/'reviewed-mock-only.tar.gz'
assert hashlib.sha256(a.read_bytes()).hexdigest()=='3424c68266cbc9d0b58d713ac118f8e7486f2ff896be33db9b0149d769bcac78'
out={'startUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'fiveInstalledSHAs':{},'testMethods':29,'isolated':True,'realBusinessWrites':False}
with tempfile.TemporaryDirectory(prefix='d4-installed-mock-') as td:
 root=pathlib.Path(td)
 with tarfile.open(a) as tar:
  members=tar.getmembers();assert len(members)==33
  for item in members:
   p=root/item.name
   assert item.isfile() and not item.issym() and not item.islnk() and root in p.resolve().parents
   p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(tar.extractfile(item).read())
 for f in m['files']:
  p=pathlib.Path(f['path']);b=p.read_bytes();h=hashlib.sha256(b).hexdigest()
  assert h==f['expectedAfterSHA256'];out['fiveInstalledSHAs'][p.name]=h
  target=root/'d4_final_guard_review_20261006/candidate'/f['path'].lstrip('/')
  target.write_bytes(b)
 env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1','HOME':td}
 p=subprocess.run(['/opt/d4follow/venv/bin/python','-I','-B','-X','utf8',str(root/'d4_predeploy_closure_20261006/test_current_writer_mock.py')],cwd=root,env=env,capture_output=True,text=True,timeout=90)
 out.update(exitCode=p.returncode,stdout=p.stdout,stderr=p.stderr)
out['isolatedTempTreeRemoved']=not root.exists();out['endUTC']=datetime.datetime.now(datetime.timezone.utc).isoformat()
(s/'installed-isolation-result.json').write_text(json.dumps(out,ensure_ascii=True,indent=2))
print(json.dumps(out,ensure_ascii=True))
raise SystemExit(p.returncode)
