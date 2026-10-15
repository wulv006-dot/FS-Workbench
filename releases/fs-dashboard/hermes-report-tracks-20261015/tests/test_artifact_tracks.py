"""Frozen artifact routing with synthetic inputs; no paid research or business writes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import ast
import json
import re
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'hermes-fs-research-integration-20261015'/'source'
if not OLD.exists():OLD=ROOT.parent/'hermes_fs_research_integration_20261015'/'source'
sys.path[:0]=[str(ROOT/'source'),str(OLD)]
import boss_renderer,boss_projection


class ArtifactTrackTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);deployment=self.root/'runtime';deployment.mkdir()
        for name in ('report_artifacts.py','report_tracks.py','pricing_report.py'):
            shutil.copyfile(ROOT/'source'/name,deployment/name)
        for name in ('boss_renderer.py','boss_projection.py','report_semantics.py','report_constraints.py'):
            shutil.copyfile(OLD/name,deployment/name)
        (deployment/'report.template.html').write_text('synthetic template',encoding='utf-8')
        spec=importlib.util.spec_from_file_location('track_artifacts',deployment/'report_artifacts.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.task='a'*32

    def save(self,track):
        self.module.save_raw(self.root,self.task,'Synthetic original research.',{},dict(report_track=track))
        result=dict(report_track=track,snapshot_id='fc-detail-synthetic',period={'start':'2026-01-01','end':'2026-01-07'},summary='Synthetic decision',research_text='Synthetic original research.')
        with patch.object(boss_projection,'project',return_value={'synthetic':'operations'}),patch.object(boss_renderer,'render',return_value='<html>Operating report</html>'):
            self.module.save_result(self.root,self.task,result,'<html>Original research</html>')
            before={p.name:p.read_bytes() for p in self.module.directory(self.root,self.task).iterdir() if p.is_file()}
            receipt=self.module.save_boss(self.root,self.task)
            artifact=self.module.read_file(self.root,self.task,'boss')
        self.assertTrue(all((self.module.directory(self.root,self.task)/n).read_bytes()==b for n,b in before.items()))
        return receipt,artifact

    def test_pricing_uses_independent_contract_and_filename(self):
        receipt,artifact=self.save('pricing')
        self.assertEqual(receipt['contract'],'fs-hermes-pricing-artifact-v1')
        self.assertTrue(receipt['html_file'].startswith('pricing-report-v1-'))
        self.assertIn('pricing_',artifact['filename'])
        self.assertNotIn('Operating report',artifact['content'])

    def test_operations_keeps_existing_contract(self):
        receipt,artifact=self.save('operations')
        self.assertEqual(receipt['contract'],'fs-hermes-boss-artifact-v2')
        self.assertTrue(receipt['html_file'].startswith('boss-semantic-v2-'))
        self.assertIn('Operating report',artifact['content'])

    def test_host_and_worker_bind_the_same_explicit_mode(self):
        host=(ROOT/'source/controller.py').read_text('utf-8')
        worker=(ROOT/'source/hermes_worker.py').read_text('utf-8')
        self.assertIn("load_bundle(self.source_root,question=body['question'],mode=body['mode'])",host)
        self.assertIn("'report_mode':body['mode']",host)
        self.assertIn("load_bundle(Path(__file__).parent,question=item['prompt'],mode=item.get('report_mode'))",worker)
        self.assertIn("report_track=meta.get('report_track','operations')",host)

    def test_worker_admission_accepts_pricing_without_other_authority(self):
        tree=ast.parse((ROOT/'source/hermes_worker.py').read_text('utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='admission')
        namespace=dict(Path=Path,json=json,re=re,ADMISSIONS=self.root,MAX_PROVIDER_WIRE_BYTES=10000)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'admission','exec'),namespace)
        session='fc_'+'b'*64
        item=dict(session_id=session,token='c'*48,model='deepseek-flash',prompt='Research',report_mode='pricing')
        path=self.root/(session+'.json');path.write_text(json.dumps(item),encoding='utf-8')
        self.assertEqual(namespace['admission'](session)['report_mode'],'pricing')
        item['report_mode']='write_prices';path.write_text(json.dumps(item),encoding='utf-8')
        with self.assertRaisesRegex(PermissionError,'admission_report_mode'):namespace['admission'](session)
        item['report_mode']='pricing';item['new_tool']='shell';path.write_text(json.dumps(item),encoding='utf-8')
        with self.assertRaisesRegex(PermissionError,'admission_invalid'):namespace['admission'](session)
