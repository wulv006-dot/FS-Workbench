"""Reuse the actual native publisher against a temporary Linux root; no production actions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
STAGE=HERE/'stage'
sys.path.insert(0,str(STAGE))
if os.name=='nt':
    # Import only. Linux syscall tests below remain skipped on Windows.
    sys.modules.setdefault('fcntl',types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4))
spec=importlib.util.spec_from_file_location('native_revision_publisher',STAGE/'release_workspace.py')
r=importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
import release_navigation as nav
CONTRACT=json.loads((STAGE/'release-contract.json').read_text('utf-8'))

class ExactFrozenContract(unittest.TestCase):
    def test_current_139_assets_four_targets_and_exact_contract(self):
        rows=r.validate(CONTRACT,None)
        self.assertEqual(len(CONTRACT['immutableAssets']),139)
        self.assertEqual(len(CONTRACT['targets']),4)
        self.assertEqual(len(rows),143)
        for kind in ('asset','target','contract'):
            bad=copy.deepcopy(CONTRACT)
            if kind=='asset':bad['immutableAssets'][0]['target']='/etc/passwd'
            elif kind=='target':bad['targets'].pop()
            else:bad['scope']='unapproved'
            with self.subTest(kind=kind),self.assertRaises(ValueError):r.validate(bad,None)

    def test_game_and_management_html_aliases_receive_shared_navigation(self):
        expected=set()
        for row in CONTRACT['immutableAssets']:
            name=row['candidate'][7:]
            if name.endswith('.html') and name.startswith(('management/','game-monitor/')):
                expected.update((row['url'],'/dashboard/'+name))
        fragment=(STAGE/'candidate/formal.conf').read_text('utf-8')
        observed=set()
        for match in re.finditer(r'(^location = (\S+) \{\n)(.*?)(^\})',fragment,re.M|re.S):
            if match[2] not in expected:continue
            directive=re.findall(r'^    sub_filter "</body>" (.+);$',match[3],re.M)
            self.assertEqual(len(directive),1,match[2])
            html=json.loads(directive[0])
            self.assertEqual(html.count('src="/__hub/hubnav.js?v=fs-revision-20261015"'),1,match[2])
            self.assertIn('.fs-unified-navigation .fs-nav',html)
            self.assertIn('.fs-unified-navigation .fs-links',html)
            self.assertTrue(html.endswith('</body>'))
            observed.add(match[2])
        self.assertEqual(observed,expected)
        self.assertEqual(len(observed),36)

    def test_retired_html_keeps_auth_gate_and_static_fragments(self):
        fragment=(STAGE/'candidate/formal.conf').read_text('utf-8')
        blocks={m[1]:m[0] for m in re.finditer(r'^location ([^\n{]+) \{\n.*?^\}',fragment,re.M|re.S)}
        prefix='/dashboard/workspace-assets/'+CONTRACT['releaseId']+'/'
        weekly=('/dashboard/marketing/weekly/index.html','/dashboard/marketing/weekly/legacy-index.html',prefix+'advisor.html',prefix+'weekly-legacy.html')
        google=('/dashboard/marketing/','/dashboard/marketing/index.html')
        for paths,kind in ((weekly,'weekly'),(google,'google')):
            for path in paths:
                with self.subTest(path=path):
                    body=blocks['= '+path]
                    self.assertIn('auth_request /',body)
                    self.assertIn('error_page 401 = @auth_login;',body)
                    self.assertIn('try_files "" @fs_revision_legacy_'+kind+';',body)
                    self.assertNotIn('alias ',body)
                    self.assertNotIn('return 302',body)
        self.assertIn('return 302 "/dashboard/fs-home/brain/index.html?report_kind=weekly#reports";',blocks['@fs_revision_legacy_weekly'])
        self.assertIn('return 302 "/dashboard/analytics/?mode=google";',blocks['@fs_revision_legacy_google'])
        for name in ('google.html','business.html'):
            self.assertIn('alias ',blocks['= '+prefix+name])
        self.assertIn('proxy_pass ',blocks['= /dashboard/marketing/range.json'])
        self.assertIn('proxy_pass ',blocks['= /dashboard/marketing/business-links.json'])

@unittest.skipIf(os.name=='nt','Linux flock/fsync/rename QA; not simulated as a Linux pass')
class LinuxTemporaryRoot(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fs-native-revision-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.stage=self.root/'stage'
        shutil.copytree(STAGE,self.stage)
        self.contract=copy.deepcopy(CONTRACT)
        # Independent synthetic before-bytes make this QA portable without E: or production exports.
        for row in self.contract['targets']:
            target=r.at(self.root,row['target'])
            target.parent.mkdir(parents=True,exist_ok=True)
            before=('synthetic-before:'+row['target']).encode()
            target.write_bytes(before);row['beforeSha256']=r.hashed(before)
        for row in self.contract['unchangedRequired']:
            target=r.at(self.root,row['path'])
            target.parent.mkdir(parents=True,exist_ok=True)
            value=('synthetic-protected:'+row['path']).encode()
            target.write_bytes(value);row['sha256']=r.hashed(value)
        frozen=(json.dumps(self.contract,ensure_ascii=False,indent=2)+'\n').encode()
        (self.stage/'release-contract.json').write_bytes(frozen)
        self.manifest=copy.deepcopy(self.contract);self.manifest['releaseReady']=True
        self.raw=json.dumps(self.manifest).encode();self.approval=r.hashed(self.raw)
        ledger=r.at(self.root,'/var/lib/fs-dashboard-release/current.json')
        ledger.parent.mkdir(parents=True,exist_ok=True)
        ledger.write_text(json.dumps(self.contract['requiredBusinessLedger']),'utf-8')
        for unit in ('dashboard-pipeline.service','dashboard-publish.service','dashboard-fallback.service'):
            link=r.at(self.root,'/etc/systemd/system/'+unit)
            link.parent.mkdir(parents=True,exist_ok=True);link.symlink_to('/dev/null')
        self.unrelated=r.at(self.root,'/var/lib/unrelated-peer/evidence.json')
        self.unrelated.parent.mkdir(parents=True,exist_ok=True);self.unrelated.write_bytes(b'peer-evidence-do-not-change')
        self.patches=[patch.object(r,'HERE',self.stage),patch.object(r,'CONTRACT_SHA',r.hashed(frozen)),
                      patch.object(r,'runtime',lambda argv:{'argv':argv,'returncode':0}),
                      patch.object(nav.subprocess,'run',lambda argv,**kw:types.SimpleNamespace(returncode=0,stdout='UnitFileState=disabled\nActiveState=inactive\n',stderr=''))]
        if os.geteuid()!=0:
            # Normalize only fixture ownership; real Linux mode/link/locking/fsync/rename guards stay active.
            original_stat=Path.stat
            def fixture_stat(path,*args,**kwargs):
                info=original_stat(path,*args,**kwargs);values=list(info);values[4]=values[5]=0
                return os.stat_result(values)
            self.patches.append(patch.object(Path,'stat',fixture_stat))
        for item in self.patches:item.start();self.addCleanup(item.stop)

    def apply(self):return r.apply(self.manifest,self.stage,self.raw,self.approval,self.root)

    def backup(self):return r.at(self.root,r.BACKUPS+'/'+self.manifest['releaseId'])

    def assert_original(self):
        for row in self.manifest['targets']:self.assertEqual(r.digest(r.at(self.root,row['target'])),row['beforeSha256'])
        self.assertEqual(self.unrelated.read_bytes(),b'peer-evidence-do-not-change')

    def test_staged_bytes_and_exact_asset_set_are_enforced(self):
        self.assertEqual(r.inspect(self.manifest,self.stage,self.root)['assets'],139)
        file=self.stage/'assets/extra.js';file.write_bytes(b'unapproved')
        with self.assertRaisesRegex(ValueError,'Extra/missing'):r.inspect(self.manifest,self.stage,self.root)
        file.unlink();row=self.manifest['immutableAssets'][0]
        (self.stage/row['candidate']).write_bytes(b'changed staged bytes')
        with self.assertRaisesRegex(ValueError,'Staged bytes drift'):r.inspect(self.manifest,self.stage,self.root)
        self.assert_original()

    def test_temporary_root_cas_conflict_preserves_peer_change(self):
        target=r.at(self.root,self.manifest['targets'][0]['target']);target.write_bytes(b'peer-before-cas')
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(target.read_bytes(),b'peer-before-cas')
        self.assertFalse(self.backup().exists())
        self.assertEqual(self.unrelated.read_bytes(),b'peer-evidence-do-not-change')

    def test_activation_failure_rolls_back_four_targets_and_preserves_other_data(self):
        reloads=0
        def runtime(argv):
            nonlocal reloads
            if argv==['systemctl','reload','nginx']:
                reloads+=1
                if reloads==1:raise RuntimeError('injected activation failure')
        with patch.object(r,'runtime',runtime),self.assertRaises(RuntimeError):self.apply()
        self.assertEqual(reloads,2);self.assert_original()
        self.assertFalse(r.pending(self.root).exists())
        for row in self.manifest['immutableAssets']:self.assertEqual(r.digest(r.at(self.root,row['target'])),row['sha256'])

    def test_rollback_refuses_to_overwrite_post_release_peer_change(self):
        self.apply();target=r.at(self.root,self.manifest['targets'][-1]['target'])
        target.write_bytes(b'peer-after-release')
        before={row['target']:r.digest(r.at(self.root,row['target'])) for row in self.manifest['targets']}
        with self.assertRaisesRegex(ValueError,'Peer target drift'):r.rollback(self.backup(),self.approval,self.root)
        self.assertEqual(before,{row['target']:r.digest(r.at(self.root,row['target'])) for row in self.manifest['targets']})
        self.assertEqual(self.unrelated.read_bytes(),b'peer-evidence-do-not-change')

if __name__=='__main__':unittest.main(verbosity=2)
