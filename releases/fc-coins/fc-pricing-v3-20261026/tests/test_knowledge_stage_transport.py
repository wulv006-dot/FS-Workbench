"""The knowledge release stage ships committed bytes, including frozen publisher."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[4]
BUILDER = ROOT / 'releases/fc-coins/fc-pricing-v3-20261026/deploy/knowledge/build_stage.py'


class KnowledgeStageTransportTest(unittest.TestCase):
    def test_unpublished_candidate_does_not_change_effective_inventory(self):
        sys.path.insert(0,str(BUILDER.parent))
        spec=importlib.util.spec_from_file_location('knowledge_stage_candidate',BUILDER)
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        original_blob=builder.blob
        index=json.loads(original_blob(ROOT,ROOT/'knowledge/index.json'))
        candidate=next(row.copy() for row in index['entries'] if row['layer']=='candidate')
        candidate['id']='test.unpublished';index['entries'].append(candidate)
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        def source(checkout,path):
            return json.dumps(index).encode() if path==ROOT/'knowledge/index.json' else original_blob(checkout,path)
        with tempfile.TemporaryDirectory() as folder,patch.object(builder,'blob',side_effect=source):
            result=builder.build(ROOT,commit,Path(folder)/'candidate.tar.gz')
            self.assertEqual(result['sourceCommit'],commit)

    def test_candidate_requires_exact_current_ids(self):
        sys.path.insert(0, str(BUILDER.parent))
        spec=importlib.util.spec_from_file_location('knowledge_stage_validation',BUILDER)
        build_stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(build_stage)
        index=json.loads(subprocess.check_output(['git','show','HEAD:knowledge/index.json'],cwd=ROOT))
        entry=next(row for row in index['entries'] if row['id']=='fc.reporting.methods')
        entry['id']='unexpected.reporting.methods'
        with patch.object(build_stage.subprocess,'check_output',return_value='a'*40), \
             patch.object(build_stage,'blob',return_value=json.dumps(index).encode()):
            with self.assertRaisesRegex(ValueError,'v3_current_knowledge_selection_invalid'):
                build_stage.build(ROOT,'a'*40,ROOT/'unused.tar.gz')

    def test_current_contract_rejects_old_financial_revision_before_reading_any_payload(self):
        sys.path.insert(0,str(BUILDER.parent))
        spec=importlib.util.spec_from_file_location('knowledge_stage_revision',BUILDER)
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        index=json.loads((ROOT/'knowledge/index.json').read_text(encoding='utf-8-sig'))
        next(row for row in index['entries'] if row['id']=='fc.pricing.constraints')['revision']='fc27_dual20_d9_d2_v2'
        with patch.object(builder.subprocess,'check_output',return_value='a'*40),patch.object(builder,'blob',return_value=json.dumps(index).encode()) as blob:
            with self.assertRaisesRegex(ValueError,'v3_current_knowledge_revision_invalid'):
                builder.build(ROOT,'a'*40,ROOT/'unused.tar.gz')
        self.assertEqual(blob.call_count,1)

    def test_unknown_effective_id_cannot_replace_new_platform_decision(self):
        sys.path.insert(0,str(BUILDER.parent))
        spec=importlib.util.spec_from_file_location('knowledge_stage_effective',BUILDER)
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        index=json.loads((ROOT/'knowledge/index.json').read_text(encoding='utf-8-sig'))
        next(row for row in index['entries'] if row['id']=='fc.pricing.decision.three-platform-100k')['id']='unreviewed.decision'
        with patch.object(builder.subprocess,'check_output',return_value='a'*40),patch.object(builder,'blob',return_value=json.dumps(index).encode()):
            with self.assertRaisesRegex(ValueError,'v3_effective_knowledge_selection_invalid'):
                builder.build(ROOT,'a'*40,ROOT/'unused.tar.gz')

    def test_stage_publisher_equals_committed_blob(self):
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'knowledge.tar.gz'
            result = subprocess.run([sys.executable, str(BUILDER), str(ROOT), commit, str(archive)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata = json.loads(result.stdout)
            self.assertEqual(metadata['sourceCommit'], commit)
            self.assertEqual(metadata['release'],'fc-three-platform-100k-knowledge-20261110-'+commit)
            prefix = metadata['release'] + '/deploy/'
            with tarfile.open(archive, 'r:gz') as bundle:
                release = prefix.removesuffix('deploy/')
                catalog = json.load(bundle.extractfile(release + 'candidate/artifact/index.json'))
                self.assertFalse(any(row['status'] == 'retired' for row in catalog['entries']))
                baseline = bundle.extractfile(release + 'candidate/runtime/business-baseline.md').read()
                runtime='releases/fs-dashboard/fs-business-baseline-20261021/source/hermes/business-baseline.md'
                self.assertEqual(baseline,subprocess.check_output(['git','show','HEAD:'+runtime],cwd=ROOT))
                provenance=json.loads(subprocess.check_output(['git','show','HEAD:'+runtime.replace('.md','.provenance.json')],cwd=ROOT))
                self.assertEqual(provenance['after_sha256'],hashlib.sha256(baseline).hexdigest())
                expected={row['source']['sha256'] for row in catalog['entries']
                          if row['source']['path']=='docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md'}
                self.assertEqual(expected,{provenance['canonical_sha256']})
                self.assertIn(b'fc27_dual20_d9_d2_platform_100k_v4',baseline)
                self.assertIn('Xbox不继承PS售价'.encode(),baseline)
                self.assertIn('历史UNKNOWN若已由后续有效真实现态覆盖，不再阻断当前执行'.encode(),baseline)
                self.assertIn('保留原未知回执，不冒充旧POST成功'.encode(),baseline)
                self.assertIn('未来每笔新写仍核当轮新鲜来源、当前价及原锁/CAS/单发保护'.encode(),baseline)
                for name in ('release.py', 'prepare_manifest.py', 'release_navigation_base.py'):
                    relative = 'releases/fc-coins/fc-pricing-v3-20261026/deploy/knowledge/' + name
                    committed = subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=ROOT)
                    staged = bundle.extractfile(prefix + name).read()
                    self.assertEqual(staged, committed, name)
                helper='releases/fc-coins/fc-pricing-v3-20261026/deploy/release_readiness.py'
                self.assertEqual(bundle.extractfile(prefix+'release_readiness.py').read(),subprocess.check_output(['git','show','HEAD:'+helper],cwd=ROOT))
                frozen = bundle.extractfile(prefix + 'release_navigation_base.py').read()
                self.assertEqual(hashlib.sha256(frozen).hexdigest(),
                                 '57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840')


class KnowledgeReleaseIdentityTest(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('current_full_baseline_publisher',BUILDER.parent/'release.py')
        self.publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.publisher)
        self.commit='a'*40
        self.release='fc-three-platform-100k-knowledge-20261110-'+self.commit
        self.prefix='/var/lib/fs-hermes-fc/fs/knowledge-releases/'+self.release+'/'
        self.manifest=dict(scope=self.publisher.SCOPE,sourceCommit=self.commit,knowledgeRelease=self.release,
            businessWrites=False,timersChanged=False,releaseReady=True,
            files=[dict(candidate=name,target=target) for name,target in self.publisher.RUNTIME.items()]+
                  [dict(candidate='artifact/index.json',target=self.prefix+'index.json')])

    def test_release_identity_binds_full_source_commit_and_original_two_runtime_targets(self):
        self.assertEqual(self.publisher.release_identity(self.commit),(self.release,self.prefix))
        mapping=self.publisher.targets(self.manifest)
        self.assertEqual({name:target for name,target in mapping.items() if name.startswith('runtime/')},self.publisher.RUNTIME)
        self.assertEqual(len(self.publisher.RUNTIME),2)
        self.assertEqual(self.publisher.BASE_SHA,'57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840')

    def test_wrong_commit_old_release_or_scope_cannot_reuse_original_immutable_directory(self):
        for key,value in [('sourceCommit','b'*40),('sourceCommit','a'*8),
                          ('knowledgeRelease','fc-pricing-v3-20261026-12'),('scope','knowledge-layering-20261023')]:
            with self.subTest(key=key,value=value):
                with self.assertRaisesRegex(ValueError,'knowledge_release_identity_invalid'):
                    self.publisher.targets(dict(self.manifest,**{key:value}))

    def test_new_runtime_target_and_artifact_escape_are_rejected(self):
        for name,target in [('runtime/business_context.py','/opt/fs-hermes-fc/business_context.py'),
                            ('artifact/../outside.json',self.prefix+'../outside.json')]:
            with self.subTest(name=name):
                manifest=dict(self.manifest,files=self.manifest['files']+[dict(candidate=name,target=target)])
                with self.assertRaisesRegex(ValueError,'knowledge_immutable_release_boundary'):
                    self.publisher.targets(manifest)


if __name__ == '__main__':
    unittest.main()
