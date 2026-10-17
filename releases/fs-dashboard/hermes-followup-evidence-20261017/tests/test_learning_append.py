import hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];RELEASE=Path(__file__).resolve().parents[1]
RULES=('迁移题明确给定假设时，先在同一假设和窗口内回答','分别记录事件发生/生效、信息发布、获知、业务行动执行日期','经营与销售是报告主线','问题单状态数量、全体发货完成率、同一批问题单的最终履约/解决率分开')
class LearningAppend(unittest.TestCase):
 def test_only_append_to_exact_published_documents(self):
  mapping=json.loads((RELEASE/'SOURCE-MAP.json').read_bytes())
  self.assertEqual(len(mapping['learningTargets']),2);self.assertEqual(mapping['knowledgeFileCount'],18)
  for row in mapping['learningTargets']:
   raw=(RELEASE/row['candidate']).read_bytes();prefix=raw[:row['beforeBytes']];addition=raw[row['beforeBytes']:].decode('utf-8')
   self.assertEqual(hashlib.sha256(prefix).hexdigest(),row['beforeSha256'])
   self.assertEqual(hashlib.sha256(raw).hexdigest(),row['afterSha256'])
   self.assertTrue(row['appendOnly']);self.assertTrue(all(rule in addition for rule in RULES))
   self.assertIn('2026-10-17 真实学习复测补充',addition)
 def test_existing_loader_includes_both_additions_with_same_eighteen_paths(self):
  mapping=json.loads((RELEASE/'SOURCE-MAP.json').read_bytes())
  loader=ROOT/'releases/fs-dashboard/traffic-hermes-20261017/learning/business_context.py'
  with tempfile.TemporaryDirectory() as folder:
   base=Path(folder);data=base/'data';profile=base/'profile';skills=profile/'skills';runtime=base/'runtime'
   for row in mapping['preservedKnowledgeFiles']:
    name=row['path']
    if name.startswith('runtime/'):dest=runtime/name.removeprefix('runtime/');raw=(RELEASE/'source/learning-loop.md').read_bytes()
    elif name.startswith('profile/'):dest=profile/name.removeprefix('profile/');raw=b'synthetic reviewed memory'
    elif name.startswith('skills/'):
     dest=skills/name.removeprefix('skills/');raw=(RELEASE/'source/ops-report-family/SKILL.md').read_bytes() if name.endswith('ops-report-family/SKILL.md') else b'synthetic unchanged reference'
    else:dest=data/name;raw=b'synthetic owner business context'
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
   copied=runtime/'business_context.py';copied.write_bytes(loader.read_bytes())
   spec=importlib.util.spec_from_file_location('learning_append_fixture',copied);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   text,digest,rows=module.learning_bundle(data,skills,profile)
   self.assertEqual(len(rows),18);self.assertEqual({r['path'] for r in rows},{r['path'] for r in mapping['preservedKnowledgeFiles']})
   self.assertTrue(all(text.count(rule)==2 for rule in RULES))
   for row in mapping['learningTargets']:
    p=runtime/'learning-loop.md' if row['candidate'].endswith('learning-loop.md') else skills/'ops-report-brief/ops-report-family/SKILL.md'
    p.write_bytes(p.read_bytes()[:row['beforeBytes']])
   old_text,old_digest,old_rows=module.learning_bundle(data,skills,profile)
   self.assertEqual(len(old_rows),18);self.assertNotEqual(digest,old_digest)
   self.assertTrue(all(rule not in old_text for rule in RULES))
if __name__=='__main__':unittest.main()
