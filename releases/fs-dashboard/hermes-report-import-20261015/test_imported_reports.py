import ast
from contextlib import contextmanager
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import textwrap
import types
import unittest

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'source'))
from imported_reports import ImportedReports, encoded, sha

class ImportedReportsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.fs=self.root/'fs';self.fs.mkdir();self.source=self.fs/'desktop-reports/20261015';self.source.mkdir(parents=True)
        self.html=b'<!doctype html><html><body><h1>sample</h1><script>window.sample=true</script></body></html>'
        self.md='# Example\nSource and period retained.\n'.encode()
        (self.source/'report.html').write_bytes(self.html);(self.source/'report.md').write_bytes(self.md)
        self.manifest=self.source/'MANIFEST.json';self.manifest.write_bytes(encoded({'contract':'hermes-desktop-reports-v1','files':[{'file':n,'bytes':len(b),'sha256':sha(b)} for n,b in [('report.html',self.html),('report.md',self.md)]]}))
        self.plan=[{'html':'report.html','markdown':'report.md','author':'Hermes','version':'20261015-v1','title':'FC27 example','start':'2026-10-01','end':'2026-10-14','report_kind':'monthly'}]
        self.store=ImportedReports(self.fs)

    def apply(self,**kwargs):return self.store.register(self.source,self.manifest,self.plan,apply=True,**kwargs)
    def test_preview_has_no_writes_or_task_creation(self):
        before=list(self.root.rglob('*'));r=self.store.register(self.source,self.manifest,self.plan)
        self.assertFalse(r['applied']);self.assertEqual(before,list(self.root.rglob('*')));self.assertEqual(r['task_rows_written'],0)
    def test_exact_html_md_and_provenance(self):
        r=self.apply();key=r['new_ids'][0]
        for kind,raw in [('html',self.html),('boss',self.html),('md',self.md)]:
            code,v=self.store.get({'id':[key],'artifact':[kind]},'wulv',False)
            self.assertEqual(code,200);self.assertEqual(v['content'].encode(),raw);self.assertEqual(v['sha256'],sha(raw))
        code,job=self.store.get({'id':[key]},'wulv',True)
        self.assertEqual(job['state'],'IMPORTED');self.assertEqual(job['imported']['author'],'Hermes');self.assertFalse(job['can_followup']);self.assertNotIn('task_id',job)
        self.assertEqual(self.store.root,self.root/'imported-reports');self.assertFalse((self.fs/'reports').exists());self.assertFalse((self.fs/'tasks.sqlite3').exists())
    def test_reimport_idempotent(self):
        r=self.apply();before=self.store.catalog.read_bytes();r2=self.apply(expected_catalog_sha256=r['catalog_sha256'])
        self.assertEqual(r2['new_ids'],[]);self.assertEqual(r2['reused'],1);self.assertEqual(before,self.store.catalog.read_bytes())
    def test_new_version_preserves_original(self):
        r=self.apply();self.plan[0]['version']='20261015-v2';self.apply(expected_catalog_sha256=r['catalog_sha256'])
        self.assertEqual(len(self.store.load()),2);self.assertEqual((self.store.root/r['new_ids'][0]/'report.html').read_bytes(),self.html)
    def test_cas_rejects_stale_catalog(self):
        self.apply()
        with self.assertRaisesRegex(ValueError,'catalog_changed'):self.apply()
    def test_tampered_source_not_registered(self):
        (self.source/'report.html').write_bytes(self.html+b'x')
        with self.assertRaisesRegex(ValueError,'source_changed'):self.apply()
        self.assertFalse(self.store.catalog.exists())
    def test_tampered_saved_file_not_served(self):
        r=self.apply();key=r['new_ids'][0];(self.store.root/key/'report.html').write_bytes(b'changed')
        self.assertEqual(self.store.get({'id':[key],'artifact':['html']},'wulv',True)[0],409)
    def test_authorized_visibility_and_filters(self):
        r=self.apply();key=r['new_ids'][0]
        self.assertEqual(self.store.get({'id':[key]},'stranger',False)[0],404)
        self.assertEqual(len(self.store.listed('admin',True,{})),1)
        self.assertEqual(self.store.listed('admin',True,{'scope':['mine']}),[])
        self.assertEqual(self.store.listed('wulv',True,{'scope':['trash']}),[])
        self.assertEqual(len(self.store.listed('wulv',False,{'q':['EXAMPLE'],'start':['2026-10-01']})),1)
        self.assertEqual(self.store.listed('wulv',True,{'end':['2026-10-13']}),[])
    def test_traversal_unknown_kind_and_invalid_metadata(self):
        for name in ['../report.html','folder/report.html','C:report.html']:
            self.plan[0]['html']=name
            with self.assertRaises(ValueError):self.apply()
        self.plan[0]['html']='report.html';self.plan[0]['title']='<script>'
        with self.assertRaises(ValueError):self.apply()
    def test_symlinks_rejected(self):
        try:(self.root/'alias').symlink_to(self.source,target_is_directory=True)
        except OSError:self.skipTest('symlink privilege not available')
        with self.assertRaisesRegex(ValueError,'linked'):self.store.register(self.root/'alias',self.root/'alias/MANIFEST.json',self.plan)
    def test_original_model_methods_byte_preserved(self):
        s=(ROOT/'source/controller.py').read_text('utf8');cls=next(n for n in ast.parse(s).body if isinstance(n,ast.ClassDef) and n.name=='HermesService')
        functions={n.name:sha(ast.get_source_segment(s,n).encode()) for n in cls.body if isinstance(n,ast.FunctionDef) and n.name!='get'}
        expected=json.loads((ROOT/'SOURCE-MAP.json').read_text('utf8'))['preserved_method_hashes']
        self.assertEqual(functions,expected)

    def test_controller_get_import_and_existing_list(self):
        self.apply();dbpath=self.fs/'tasks.sqlite3'
        with sqlite3.connect(dbpath) as db:
            db.executescript('CREATE TABLE requests(id TEXT,owner TEXT,state TEXT,error TEXT,body TEXT);CREATE TABLE report_trash(id TEXT,deleted_by TEXT,deleted_at TEXT);CREATE TABLE model_calls(value TEXT);')
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?)',('a'*32,'wulv','FAILED','original_error',json.dumps({'start':'2026-10-01','end':'2026-10-14','question':'original','request_id':'old'})))
        db.close()
        @contextmanager
        def database():
            db=sqlite3.connect(dbpath);db.row_factory=sqlite3.Row
            try:yield db
            finally:db.close()
        p=ROOT/'source/controller.py';s=p.read_text('utf8');cls=next(n for n in ast.parse(s).body if isinstance(n,ast.ClassDef) and n.name=='HermesService');fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='get')
        namespace={'ImportedReports':ImportedReports,'re':re,'date':date,'json':json,'spending_hold':lambda *a:None,'load_bundle':lambda *a:{'version':'test'},'can_continue':lambda *a:False}
        exec(textwrap.dedent(ast.get_source_segment(s,fn)),namespace)
        service=types.SimpleNamespace(root=self.fs,authorizer=lambda user:user=='wulv',tasks=types.SimpleNamespace(db=database),daily=None,source_root=None,nightly=types.SimpleNamespace(status=lambda user:{}))
        before=sha(dbpath.read_bytes());get=namespace['get']
        code,v=get(service,{'mode':['hermes']},'wulv');self.assertEqual(code,200);self.assertEqual(v['items'][0]['error'],'original_error');self.assertEqual(len(v['imported_items']),1)
        key=v['imported_items'][0]['id'];self.assertEqual(get(service,{'mode':['hermes'],'id':[key],'artifact':['md']},'wulv')[1]['content'].encode(),self.md)
        self.assertEqual(get(service,{'mode':['hermes'],'id':[key]},None)[0],401)
        self.assertEqual(get(service,{'mode':['hermes'],'id':[key]},'stranger')[0],404)
        self.assertEqual(before,sha(dbpath.read_bytes()))

if __name__=='__main__':unittest.main()
