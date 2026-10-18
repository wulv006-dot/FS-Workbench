import hashlib,importlib.util,json,os,stat,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'source'
spec=importlib.util.spec_from_file_location('single_current_method',SOURCE/'report_method.py');method=importlib.util.module_from_spec(spec);spec.loader.exec_module(method)

class CurrentMethodTests(unittest.TestCase):
 def test_only_current_four_documents_are_active_and_tampering_is_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);texts={'SKILL.md':'version: 1.5.1\nCURRENT_SKILL','METHOD.md':'CURRENT_METHOD','APPLICATIONS.md':'CURRENT_APPLICATIONS','ACCEPTANCE.md':'CURRENT_ACCEPTANCE'}
   files=[]
   for name,text in texts.items():
    raw=text.encode();(root/name).write_bytes(raw);files.append(dict(path=name,role=method.HTML_DESIGN_FILES[name],sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)))
   manifest=dict(contract='hermes-autonomous-method-v1',version='1.5.1',status='test',root=str(root),files=files,total_bytes=sum(r['bytes'] for r in files),profile_skill='/profile/skills/report-html-authoring/SKILL.md',context_policy='single_current_method_no_legacy_examples',permissions={'directory':'0700','file':'0600','owner':'0:0'})
   raw=json.dumps(manifest).encode();(root/'manifest.json').write_bytes(raw)
   original_fstat=os.fstat
   def file_stat(fd):
    info=original_fstat(fd);return SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=0,st_gid=0,st_nlink=1,st_size=info.st_size)
   def path_stat(path,**kwargs):
    info=os.stat(path,**kwargs);return SimpleNamespace(st_mode=stat.S_IFDIR|0o700 if stat.S_ISDIR(info.st_mode) else stat.S_IFREG|0o600,st_uid=0,st_gid=0)
   with patch.object(method,'HTML_DESIGN_ROOT',root),patch.object(method,'HTML_DESIGN_MANIFEST_SHA256',hashlib.sha256(raw).hexdigest()),patch.object(method.os,'fstat',file_stat),patch.object(Path,'stat',path_stat):
    context,receipt=method.html_design_context('a short question')
    bundle=method.method_bundle('operations')
    self.assertEqual(bundle['version'],'report-html-1.5.1')
    self.assertEqual(bundle['text'],texts['SKILL.md'])
    self.assertEqual(bundle['methods_text'],'CURRENT_METHOD\nCURRENT_APPLICATIONS')
    self.assertEqual(bundle['governance_text'],'CURRENT_ACCEPTANCE')
    self.assertEqual(len(receipt['files']),4)
    self.assertNotIn('examples/daily',context)
    self.assertNotIn('旧教学示例',context)
    (root/'METHOD.md').write_text('tampered',encoding='utf-8')
    with self.assertRaisesRegex(ValueError,'html_design_material_drift'):method.html_design_context('same')
 def test_manifest_pin_and_no_legacy_files(self):
  self.assertEqual(set(method.HTML_DESIGN_FILES),{'SKILL.md','METHOD.md','ACCEPTANCE.md','APPLICATIONS.md'})
  self.assertNotIn('html-design-context-reset',str(method.HTML_DESIGN_ROOT))
  self.assertEqual(method.HTML_DESIGN_MANIFEST_SHA256,'950f429d386924f734d2459c2a2b8dc3ad03e004a326ba4f268aa51aec72296d')

if __name__=='__main__':unittest.main()
