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


# A transport unit test must not imply that today's canonical/runtime migration is
# complete. Use the last attested canonical bytes, pinned by the real provenance;
# the separate unmocked CLI test below keeps the actual release failure visible.
ATTESTED_BASELINE_COMMIT = '9114a564b26ae1c1d91fa5dc0c063aebbfed7a6a'
CANONICAL_BASELINE = 'docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md'


def transport_fixture_blob(checkout, path):
    relative = path.relative_to(checkout).as_posix()
    if relative == CANONICAL_BASELINE:
        return subprocess.check_output(['git', 'show', ATTESTED_BASELINE_COMMIT + ':' + relative], cwd=checkout)
    raw = subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=checkout)
    if relative == 'knowledge/index.json':
        index = json.loads(raw)
        canonical = transport_fixture_blob(checkout, checkout / CANONICAL_BASELINE).replace(b'\r\n', b'\n')
        for row in index['entries']:
            if row['source']['path'] == CANONICAL_BASELINE:
                row['source']['sha256'] = hashlib.sha256(canonical).hexdigest()
        return json.dumps(index).encode()
    return raw


class KnowledgeStageTransportTest(unittest.TestCase):
    def test_new_revision_candidate_can_share_current_stable_id_without_publication(self):
        from copy import deepcopy
        sys.path.insert(0,str(BUILDER.parent))
        spec=importlib.util.spec_from_file_location('knowledge_shared_id_candidate',BUILDER)
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        original_blob=transport_fixture_blob
        index=json.loads(original_blob(ROOT,ROOT/'knowledge/index.json'))
        candidate=deepcopy(next(r for r in index['entries'] if r['id']=='fc.pricing.constraints'))
        candidate.update(layer='candidate',status='candidate',revision='unapproved-next',source_commit=None)
        candidate['source']['path']='knowledge/candidates/unpublished-next-financial.md'
        index['entries'].append(candidate)
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        def read(checkout,path):
            if path==ROOT/'knowledge/index.json':return json.dumps(index).encode()
            self.assertNotEqual(path,ROOT/candidate['source']['path'],'candidate content must not be read')
            return original_blob(checkout,path)
        with tempfile.TemporaryDirectory() as folder,patch.object(builder,'blob',side_effect=read):
            result=builder.build(ROOT,commit,Path(folder)/'candidate.tgz')
            with tarfile.open(result['archive']) as bundle:
                prefix=result['release']+'/candidate/artifact/'
                published=json.load(bundle.extractfile(prefix+'index.json'))
                rows=[r for r in published['entries'] if r['id']=='fc.pricing.constraints']
                self.assertEqual({(r['layer'],r['revision']) for r in rows},
                    {('current','fc27_dual20_d9_d2_platform_100k_v4'),('candidate','unapproved-next')})
                self.assertNotIn(prefix+'sources/'+candidate['source']['path'],bundle.getnames())
        duplicate=deepcopy(index);duplicate['entries'].append(deepcopy(candidate))
        with self.assertRaises(ValueError):self.prepare_module().checked_catalog_inventory(duplicate)

    def prepare_module(self):
        sys.path.insert(0,str(BUILDER.parent))
        spec=importlib.util.spec_from_file_location('knowledge_prepare_contract_test',BUILDER.parent/'prepare_manifest.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_verified_git_experience_is_incremental_without_a_total_inventory_cap(self):
        from copy import deepcopy
        module=self.prepare_module()
        index=json.loads((ROOT/'knowledge/index.json').read_text(encoding='utf-8-sig'))
        row=deepcopy(next(r for r in index['entries'] if r['id']=='fc.evolutions.experience.current-state-cutover'))
        row['id']='fc.experience.future-verified-learning'
        index['entries'].append(row)
        module.checked_catalog_inventory(index)
        for change in [dict(status='candidate'),dict(authority='unknown'),dict(provenance=[]),dict(layer='decision')]:
            bad=deepcopy(index);bad['entries'][-1].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):module.checked_catalog_inventory(bad)

    def test_experience_increment_is_shipped_with_its_exact_git_source_hash(self):
        from copy import deepcopy
        sys.path.insert(0,str(BUILDER.parent))
        spec=importlib.util.spec_from_file_location('knowledge_experience_increment_builder',BUILDER)
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        original_blob=transport_fixture_blob
        index=json.loads(original_blob(ROOT,ROOT/'knowledge/index.json'))
        row=deepcopy(next(r for r in index['entries'] if r['id']=='fc.evolutions.experience.current-state-cutover'))
        data=b'# Verified incremental experience\n'
        row.update(id='fc.experience.future-verified-learning',revision='test-1',source_commit=None)
        row['source']=dict(path='knowledge/experience/test-increment.md',sha256=hashlib.sha256(data).hexdigest(),hash_basis='utf8_lf')
        index['entries'].append(row)
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        def read(checkout,path):
            if path==ROOT/'knowledge/index.json':return json.dumps(index).encode()
            if path==ROOT/row['source']['path']:return data
            return original_blob(checkout,path)
        with tempfile.TemporaryDirectory() as folder,patch.object(builder,'blob',side_effect=read):
            result=builder.build(ROOT,commit,Path(folder)/'increment.tgz')
            with tarfile.open(result['archive']) as bundle:
                prefix=result['release']+'/candidate/artifact/'
                published=json.load(bundle.extractfile(prefix+'index.json'))
                self.assertEqual({r['id'] for r in published['entries'] if r['layer']=='current'},
                                 {r['id'] for r in index['entries'] if r['layer']=='current'})
                self.assertEqual(bundle.extractfile(prefix+'sources/'+row['source']['path']).read(),data)
                self.assertEqual(next(r for r in published['entries'] if r['id']==row['id'])['layer'],'experience')
            row['source']['sha256']='a'*64
            with self.assertRaisesRegex(ValueError,'source_sha_mismatch'):
                builder.build(ROOT,commit,Path(folder)/'bad.tgz')

    def test_prepare_uses_same_inventory_and_exact_published_source_root(self):
        from copy import deepcopy
        module=self.prepare_module();commit='a'*40
        index=json.loads((ROOT/'knowledge/index.json').read_text(encoding='utf-8-sig'))
        release='fc-three-platform-100k-knowledge-20261110-'+commit
        index.update(release=release,release_state='published',source_commit=commit,
                     source_root='knowledge-releases/'+release+'/sources')
        module.checked_catalog_inventory(index,source_commit=commit,release=release)
        for change in [dict(source_root='sources'),dict(source_commit='b'*40),dict(release=release+'-other')]:
            bad=deepcopy(index);bad.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                module.checked_catalog_inventory(bad,source_commit=commit,release=release)

    def test_prepare_payload_contract_keeps_all_experiences_and_rejects_missing_or_extra_files(self):
        module=self.prepare_module()
        index=json.loads((ROOT/'knowledge/index.json').read_text(encoding='utf-8-sig'))
        expected=module.catalog_payload_names(index)
        for identity in ('fc.evolutions.experience.current-state-cutover','fc.pricing.experience.lootbar-source-availability'):
            row=next(r for r in index['entries'] if r['id']==identity)
            self.assertIn('artifact/sources/'+row['source']['path'],expected)
        for row in index['entries']:
            if row['layer']=='candidate':self.assertNotIn('artifact/sources/'+row['source']['path'],expected)
        for names in [expected|{'artifact/sources/unknown.md'},expected-{'artifact/index.json'}]:
            with self.assertRaisesRegex(ValueError,'git_payload_inventory_invalid'):
                module.checked_payload_names(index,{n:'a'*64 for n in names})

    def test_unpublished_candidate_does_not_change_effective_inventory(self):
        sys.path.insert(0,str(BUILDER.parent))
        spec=importlib.util.spec_from_file_location('knowledge_stage_candidate',BUILDER)
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        original_blob=transport_fixture_blob
        index=json.loads(original_blob(ROOT,ROOT/'knowledge/index.json'))
        candidate=next(row.copy() for row in index['entries'] if row['layer']=='candidate')
        candidate['id']='test.unpublished';index['entries'].append(candidate)
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        def source(checkout,path):
            return json.dumps(index).encode() if path==ROOT/'knowledge/index.json' else original_blob(checkout,path)
        with tempfile.TemporaryDirectory() as folder,patch.object(builder,'blob',side_effect=source):
            result=builder.build(ROOT,commit,Path(folder)/'candidate.tar.gz')
            self.assertEqual(result['sourceCommit'],commit)
            with tarfile.open(result['archive']) as bundle:
                prefix=result['release']+'/candidate/artifact/'
                catalog=json.load(bundle.extractfile(prefix+'index.json'))
                unpublished=next(r for r in catalog['entries'] if r['id']=='test.unpublished')
                self.assertEqual(unpublished['layer'],'candidate')
                self.assertIsNone(unpublished.get('source_commit'))
                self.assertNotIn(prefix+'sources/'+candidate['source']['path'],bundle.getnames())

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

    def test_actual_head_requires_attested_runtime_migration(self):
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        canonical = subprocess.check_output(['git', 'show', 'HEAD:' + CANONICAL_BASELINE], cwd=ROOT).replace(b'\r\n', b'\n')
        runtime = 'releases/fs-dashboard/fs-business-baseline-20261021/source/hermes/business-baseline.md'
        provenance = json.loads(subprocess.check_output(['git', 'show', 'HEAD:' + runtime.replace('.md', '.provenance.json')], cwd=ROOT))
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'actual-head.tgz'
            result = subprocess.run([sys.executable, str(BUILDER), str(ROOT), commit, str(archive)], capture_output=True, text=True)
            if provenance['canonical_sha256'] != hashlib.sha256(canonical).hexdigest():
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('runtime_baseline_patch_provenance_invalid', result.stderr)
                self.assertFalse(archive.exists())
            else:
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_stage_publisher_equals_committed_blob(self):
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'knowledge.tar.gz'
            sys.path.insert(0, str(BUILDER.parent))
            spec = importlib.util.spec_from_file_location('knowledge_transport_fixture', BUILDER)
            builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
            with patch.object(builder, 'blob', side_effect=transport_fixture_blob):
                metadata = builder.build(ROOT, commit, archive)
            self.assertEqual(metadata['sourceCommit'], commit)
            self.assertEqual(metadata['release'],'fc-three-platform-100k-knowledge-20261110-'+commit)
            prefix = metadata['release'] + '/deploy/'
            with tarfile.open(archive, 'r:gz') as bundle:
                release = prefix.removesuffix('deploy/')
                catalog = json.load(bundle.extractfile(release + 'candidate/artifact/index.json'))
                self.assertFalse(any(row['status'] == 'retired' for row in catalog['entries']))
                committed_catalog=json.loads(subprocess.check_output(['git','show',commit+':knowledge/index.json'],cwd=ROOT))
                self.assertEqual({r['id'] for r in catalog['entries'] if r['layer']=='current'},
                                 {r['id'] for r in committed_catalog['entries'] if r['layer']=='current'})
                for identity in ('fc.evolutions.experience.current-state-cutover','fc.pricing.experience.lootbar-source-availability'):
                    row=next(r for r in catalog['entries'] if r['id']==identity)
                    expected=next(r for r in committed_catalog['entries'] if r['id']==identity)
                    self.assertEqual((row['layer'],row['status'],row['revision'],row['source']['sha256']),
                                     ('experience','verified',expected['revision'],expected['source']['sha256']))
                    body=bundle.extractfile(release+'candidate/artifact/sources/'+row['source']['path']).read()
                    self.assertEqual(hashlib.sha256(body).hexdigest(),row['source']['sha256'])
                self.assertEqual(next(r for r in catalog['entries'] if r['id']=='fc.pricing.v3')['revision'],'20261111-lootbar-no-coupon')
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
