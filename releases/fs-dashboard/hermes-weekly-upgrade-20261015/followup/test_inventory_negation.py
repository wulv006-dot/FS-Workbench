"""Synthetic checks for explicit inventory prohibitions and unchanged model gates."""
import ast,copy,importlib.util,unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

renderer=load('inventory_negation_renderer',HERE/'source/boss_renderer.py')
for package in ('hermes_fs_research_integration_20261015','hermes-fs-research-integration-20261015'):
    path=ROOT/package/'tests/test_executive_render.py'
    if path.is_file():fixtures=load('inventory_negation_fixtures',path);break
else:raise FileNotFoundError('integration/tests/test_executive_render.py')

class InventoryNegationTests(unittest.TestCase):
    def validate(self,text):
        content=fixtures.content();content['actions'][0]['risk']=text
        before=copy.deepcopy(content)
        result=renderer.validate(content,{fixtures.EID:{'source':'synthetic'}})
        self.assertEqual(content,before)
        return result

    def test_explicit_negative_actions_are_not_positive_advice(self):
        allowed=[
            '人工核查与跨组沟通成本；无预算支出；不建议囤货或调整价格。；提取不代表通过业务验证。',
            '内容与运营工时；不预付囤货、不预设折扣；活动时间与销量变化不能直接认作因果。',
            '本业务不囤货。','禁止囤货。','无需备库存。','不建议囤货，也不要补库存。',
        ]
        for text in allowed:
            with self.subTest(text=text):self.assertEqual(self.validate(text)['schema'],'passed')

    def test_positive_and_mixed_actions_still_fail(self):
        blocked=['建议囤货。','本周需要补库存。','不建议囤货，但本周应囤货。','无需备库存；先补库存。','不预付囤货，后续建议囤货。']
        for text in blocked:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'Inventory advice'):self.validate(text)

    def test_double_and_reversed_negations_still_fail(self):
        blocked=['不是不建议囤货。','不能不囤货。','不得不囤货。','不建议不囤货。','并非无需囤货。','不建议囤货是错误的。','禁止囤货不适用。']
        for text in blocked:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'Inventory advice'):self.validate(text)

    def test_business_model_gate_and_other_inventory_terms_unchanged(self):
        for key,value in [('holds_inventory',True),('fulfillment','stocked'),('supplier_settlement','prepaid')]:
            content=fixtures.content();content['business_model'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'business model'):renderer.validate(content,{fixtures.EID:{}})
        for text in ['建立库存日志。','需要库存/可售记录。','扩库存。','备库存。']:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'Inventory advice'):self.validate(text)
        ast.parse((HERE/'source/boss_renderer.py').read_text('utf-8'),feature_version=(3,9))

if __name__=='__main__':unittest.main()
