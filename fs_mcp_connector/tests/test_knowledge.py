"""Use the actual existing selector with isolated published fixtures and original route/FS gates."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from fs_mcp_connector.catalog import CatalogPermissionError, CatalogUnavailable, ValidationError
from fs_mcp_connector.knowledge import KnowledgeService, KnowledgeUnavailable
from fs_mcp_connector.portal import Principal


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('connector_test_original_knowledge',
    ROOT/'releases/fs-dashboard/knowledge-layering-20261023/source/knowledge_catalog.py')
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)
from fs_mcp_connector import redaction as documents


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.principal = Principal('alice', 'MMOEXP_AUTH=fixture')
        self.decisions, self.calls = {}, []
        def authorize(principal, path, method):
            self.calls.append((principal.subject, path, method))
            return self.decisions.get(path, 200)
        self.authorize = authorize
        self.content = 'Approved current business method. owner@example.test'
        self.entry = dict(id='fs.test.method', revision='v2', layer='current', status='effective',
            modules=['FS'], effective_at='2026-11-09', owner='fixture', authority='git',
            provenance=['isolated_test_only'], supersedes=[], source_commit='a'*40,
            source={'path':'current.md', 'sha256':hashlib.sha256(self.content.encode()).hexdigest()})
        self.old = dict(deepcopy(self.entry), id='fs.test.archive', revision='v1', layer='archive', status='archived',
            source={'path':'old.md','sha256':hashlib.sha256(b'Historical fixture').hexdigest()})
        (self.root/'current.md').write_text(self.content, 'utf-8')
        (self.root/'old.md').write_text('Historical fixture', 'utf-8')
        self.catalog = dict(contract=original.CONTRACT, release='fixture', release_state='published',
            source_commit='a'*40, entries=[self.entry, self.old])
        self.save()
        self.service = KnowledgeService(self.root, original, authorize, redact=documents.redact)

    def save(self, owner='alice', history=True):
        target=self.root/'knowledge-releases/fixture/index.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        raw=json.dumps(self.catalog).encode()
        target.write_bytes(raw)
        route=dict(owner=owner,project='FS',channel='fs',task_types=['data'],
            catalog='knowledge-releases/fixture/index.json',sha256=hashlib.sha256(raw).hexdigest(),modules=['FS'],
            baseline_compatibility={'mode':'retain_full_baseline','sha256':'b'*64})
        if history:
            route['history_entry_ids']=['fs.test.archive']
        policy=dict(contract='fs-knowledge-load-policy-v1',task_routes={'enabled':True,'routes':[route]})
        (self.root/'knowledge-load-policy.json').write_text(json.dumps(policy),'utf-8')

    def snapshot(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_real_subject_published_selection_and_no_writes(self):
        before=self.snapshot()
        index=self.service.index(self.principal)
        self.assertEqual(index['status'],'index_only')
        self.assertEqual([r['id'] for r in index['entries']],['fs.test.method'])
        result=self.service.read(self.principal,'fs.test.method')
        self.assertFalse(result['redacted'])
        self.assertIn('owner@example.test',result['content'])
        self.assertNotIn('artifact_path',json.dumps(result))
        self.assertEqual(result['source_content_sha256'],hashlib.sha256(self.content.encode()).hexdigest())
        self.assertEqual(result['content_sha256'],hashlib.sha256(result['content'].encode()).hexdigest())
        self.assertEqual(before,self.snapshot())
        self.assertTrue(all(subject=='alice' for subject,_,_ in self.calls))

    def test_no_owner_route_is_unavailable_without_admin_fallback(self):
        with self.assertRaises(KnowledgeUnavailable) as error:
            self.service.index(Principal('other-user','MMOEXP_AUTH=fixture'))
        self.assertEqual(error.exception.code,'knowledge_route_unavailable')

    def test_original_route_limits_modules_and_entry_ids_without_a_new_acl_table(self):
        private = dict(deepcopy(self.entry), id='private.module.document', modules=['OTHER'])
        second = dict(deepcopy(self.entry), id='fs.second.method')
        self.catalog['entries'].extend([private, second])
        self.save()
        policy_path=self.root/'knowledge-load-policy.json'
        policy=json.loads(policy_path.read_bytes())
        policy['task_routes']['routes'][0]['entry_ids']=['fs.test.method']
        policy_path.write_text(json.dumps(policy),'utf-8')
        result=self.service.index(self.principal)
        self.assertEqual(result['status'],'index_only')
        self.assertEqual([entry['id'] for entry in result['entries']],['fs.test.method'])
        self.assertTrue(result['complete'])
        self.assertIn('Approved current business method',self.service.read(self.principal,'fs.test.method')['content'])
        for entry_id in ('private.module.document','fs.second.method'):
            with self.subTest(entry_id=entry_id),self.assertRaises(PermissionError):
                self.service.read(self.principal,entry_id)

    def test_module_gate_denial_and_portal_unavailability_are_not_empty_results(self):
        self.decisions['/dashboard/fs-home/brain/']=403
        with self.assertRaises(CatalogPermissionError):
            self.service.index(self.principal)
        self.decisions['/dashboard/fs-home/brain/']=503
        with self.assertRaises(CatalogUnavailable):
            self.service.index(self.principal)

    def test_history_requires_explicit_original_allowed_id_set(self):
        with self.assertRaises(PermissionError):
            self.service.read(self.principal,'fs.test.archive')
        with self.assertRaises(ValidationError):
            self.service.read(self.principal,'fs.test.archive',revision='v1')
        result=self.service.read(self.principal,'fs.test.archive',history=True,revision='v1')
        self.assertEqual(result['entry']['layer'],'archive')
        self.assertTrue(result['history'])
        history_index=self.service.index(self.principal,history=True)
        self.assertEqual({row['id'] for row in history_index['entries']},{'fs.test.method','fs.test.archive'})
        self.save(history=False)
        self.assertEqual([row['id'] for row in self.service.index(self.principal,history=True)['entries']],['fs.test.method'])
        with self.assertRaises(PermissionError):
            self.service.read(self.principal,'fs.test.archive',history=True)

    def test_candidate_and_hash_drift_are_refused(self):
        self.catalog['release_state']='candidate'
        self.save()
        with self.assertRaises(KnowledgeUnavailable):
            self.service.index(self.principal)
        self.catalog['release_state']='published'
        self.save()
        (self.root/'current.md').write_text('changed','utf-8')
        with self.assertRaises(KnowledgeUnavailable):
            self.service.read(self.principal,'fs.test.method')

    def test_model_cannot_supply_path_profile_modules_or_arbitrary_entry(self):
        for value in ('../current.md','/etc/private','https://host/doc','fs.test.method?profile=admin'):
            with self.subTest(value=value),self.assertRaises(ValidationError):
                self.service.read(self.principal,value)
        with self.assertRaises(PermissionError):
            self.service.read(self.principal,'fs.private.missing')
        with self.assertRaises(TypeError):
            self.service.read(self.principal,'fs.test.method',profile='administrator')

    def test_content_needs_projection_and_rechecks_original_portal_grants(self):
        service=KnowledgeService(self.root,original,self.authorize)
        with self.assertRaises(KnowledgeUnavailable):
            service.read(self.principal,'fs.test.method')
        def revoke(content):
            self.decisions['/dashboard/fs-home/brain/']=403
            return content
        self.service.redact=revoke
        with self.assertRaises(PermissionError):
            self.service.read(self.principal,'fs.test.method')


if __name__=='__main__':
    unittest.main()
