import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent/'candidate'))
import report_artifacts as artifacts


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.task='1'*32
        self.project=types.SimpleNamespace(project=lambda *a:{'title':'synthetic'})
        self.renderer=types.SimpleNamespace(render=lambda *a:'<html>synthetic boss</html>')
        self.patch=patch.dict(sys.modules,boss_projection=self.project,boss_renderer=self.renderer)
        self.patch.start();self.addCleanup(self.patch.stop)
        artifacts.save_raw(self.root,self.task,'original',{}, {'owner':'synthetic'})

    def test_dual_artifacts_keep_original_and_hashes(self):
        result={'period':{'start':'2026-10-14','end':'2026-10-14'}}
        proof=artifacts.save_result(self.root,self.task,result,'<html>original research</html>')
        self.assertEqual(artifacts.read_file(self.root,self.task,'html')['sha256'],proof['html_sha256'])
        boss=artifacts.read_file(self.root,self.task,'boss')
        self.assertEqual(boss['content'],'<html>synthetic boss</html>')
        self.assertIn('boss_',boss['filename'])
        self.assertEqual(artifacts.save_result(self.root,self.task,result,'<html>original research</html>'),proof)

    def test_layout_failure_never_changes_research_ready(self):
        self.renderer.render=lambda *a:(_ for _ in ()).throw(ValueError('synthetic_render_failure'))
        artifacts.save_result(self.root,self.task,{},'research')
        self.assertEqual(artifacts.read_file(self.root,self.task,'html')['content'],'research')
        self.assertFalse((self.root/'reports'/self.task/'boss-ready.json').exists())
        self.renderer.render=lambda *a:'recovered layout'
        self.assertEqual(artifacts.read_file(self.root,self.task,'boss')['content'],'recovered layout')

    def test_frozen_evidence_tamper_blocks_projection(self):
        self.renderer.render=lambda *a:(_ for _ in ()).throw(ValueError('defer'))
        artifacts.save_result(self.root,self.task,{},'research')
        (self.root/'reports'/self.task/'evidence.json').write_text('{"changed":1}')
        self.renderer.render=lambda *a:'must not render'
        with self.assertRaisesRegex(ValueError,'report_artifact_changed'):artifacts.read_file(self.root,self.task,'boss')

    def test_path_and_unknown_variants_rejected(self):
        for kind in ('../../secret','boss-ready.json','pdf'):
            with self.assertRaisesRegex(ValueError,'report_artifact_kind'):artifacts.read_file(self.root,self.task,kind)
        with self.assertRaisesRegex(ValueError,'report_task_identity'):artifacts.read_file(self.root,'../../secret','boss')

    def test_original_research_text_is_verified_and_passed_to_projection(self):
        seen=[]
        self.project.project=lambda result,*args: (seen.append(result['raw_model_text']) or {'title':'synthetic'})
        artifacts.save_result(self.root,self.task,{},'research')
        self.assertEqual(seen,['original'])
        (self.root/'reports'/self.task/'boss-ready.json').unlink()
        (self.root/'reports'/self.task/'model.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'report_artifact_changed'):artifacts.read_file(self.root,self.task,'boss')

    def test_existing_boss_bytes_immutable(self):
        artifacts.save_result(self.root,self.task,{},'research')
        path=self.root/'reports'/self.task/'boss-report.html';path.write_text('tampered')
        with self.assertRaisesRegex(ValueError,'report_artifact_changed'):artifacts.read_file(self.root,self.task,'boss')


if __name__=='__main__':unittest.main()
