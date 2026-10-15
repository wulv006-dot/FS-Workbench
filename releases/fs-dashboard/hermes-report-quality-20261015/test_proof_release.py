import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock,patch

import test_release_quality as legacy
release=legacy.release
HERE=Path(__file__).resolve().parent


class ProofRelease(unittest.TestCase):
    def stage(self,path):
        old=legacy.ReleaseQuality().stage(path)
        baseline={r['path']:r['sha256'] for r in json.loads((HERE/'CURRENT-BASELINE.json').read_text('utf-8'))['files']}
        rows=[]
        for rel,target in release.HERMES_PROOF_TARGETS.items():
            name=rel.removeprefix('report-proof/');src=HERE/'candidate'/name;dst=path/'candidate'/rel
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
            rows.append({'candidate':rel,'target':target,'sha256':release.digest(dst),'beforeSha256':baseline.get(target)})
        return dict(old,scope=release.HERMES_PROOF_SCOPE,files=rows)

    def test_distinct_scope_keeps_legacy_scope_and_only_one_new_file(self):
        self.assertEqual(len(release.HERMES_QUALITY_TARGETS),10)
        self.assertEqual(len(release.HERMES_PROOF_TARGETS),11)
        self.assertEqual(release.HERMES_PROOF_NEW,{'report-proof/report_constraints.py'})
        self.assertEqual(set(release.HERMES_PROOF_TARGETS.values())-set(release.HERMES_QUALITY_TARGETS.values()),{'/opt/fs-hermes-fc/report_constraints.py'})

    def test_current_baseline_and_new_guard_validate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.stage(root)
            self.assertEqual(len(release.validate(m,root)),11)
            self.assertEqual({r['candidate'] for r in m['files'] if r['beforeSha256'] is None},release.HERMES_PROOF_NEW)

    def test_wrong_new_existing_or_redirected_target_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.stage(root)
            for kind in ('existing_as_new','new_as_existing','redirect'):
                bad=copy.deepcopy(m)
                if kind=='existing_as_new':bad['files'][0]['beforeSha256']=None
                elif kind=='new_as_existing':next(r for r in bad['files'] if r['candidate'] in release.HERMES_PROOF_NEW)['beforeSha256']='a'*64
                else:bad['files'][0]['target']='/var/lib/fs-hermes-fc/profile/memories/USER.md'
                with self.assertRaises(ValueError):release.validate(bad,root)

    def test_exact_report_source_ownership_checked_for_new_scope(self):
        path=Mock();path.parents=[];path.exists.return_value=False
        with patch.object(release,'hermes_quiescent'),patch.object(release,'no_target_link'),patch.object(release,'rooted',return_value=path) as rooted:
            release.guards({'scope':release.HERMES_PROOF_SCOPE,'unchangedRequired':[]},Path('/'))
        self.assertEqual({call.args[1] for call in rooted.call_args_list},set(release.HERMES_PROOF_TARGETS.values()))

    def test_new_scope_reuses_fence_before_service_reload(self):
        with patch.object(release.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'admission fence'):release.restart_for({'scope':release.HERMES_PROOF_SCOPE})
        run.assert_not_called()


if __name__=='__main__':unittest.main()
