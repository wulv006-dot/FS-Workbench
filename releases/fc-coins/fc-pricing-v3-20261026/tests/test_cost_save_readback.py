"""A delayed inline save must be checked on a fresh page, never posted twice."""
import ast
from decimal import Decimal
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import Mock

SOURCE=Path(__file__).resolve().parents[1]/'source/price_writer.py'


class CostSaveReadback(TestCase):
    def setUp(self):
        self.preview=dict(targets=[dict(platform='PS',id='21942',targetCost='0.440496',quote='0.0828')],backend_before=dict(rows=[dict(platform='PS',costPrice='0.429324',b2c='0.0807')]))
        self.record=dict(changed=[])
        self.page=Mock()
        self.page.evaluate.side_effect=RuntimeError('inline confirmation timed out')
        self.read=Mock(return_value=dict(rows=[dict(platform='PS',costPrice='0.440496',b2c='0.0828')]))
        self.scope=dict(read_backend=self.read,same_money=lambda a,b:Decimal(a)==Decimal(b))
        nodes=[n for n in ast.parse(SOURCE.read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name in ('save_cost','expected_state')]
        self.assertEqual(len(nodes),2,'writer needs original-save readback recovery')
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),self.scope)

    def test_delayed_save_reads_twice_without_repeating_the_post(self):
        self.scope['save_cost'](self.page,self.preview,self.record,'PS')
        self.assertEqual(self.page.evaluate.call_count,1)
        self.assertEqual(self.page.reload.call_count,2)
        self.assertEqual(self.read.call_count,2)
        self.assertEqual(self.record['cost_save_readbacks']['PS']['status'],'saved_after_inline_timeout')

    def test_changed_or_missing_value_stays_unresolved(self):
        self.read.return_value['rows'][0]['costPrice']='0.429324'
        with self.assertRaisesRegex(ValueError,'before_cost_changed'):
            self.scope['save_cost'](self.page,self.preview,self.record,'PS')
        self.assertEqual(self.page.evaluate.call_count,1)
        self.assertNotIn('cost_save_readbacks',self.record)

    def test_unrelated_price_change_does_not_confirm_save(self):
        self.read.return_value['rows'][0]['b2c']='0.9999'
        with self.assertRaisesRegex(ValueError,'before_b2c_changed'):
            self.scope['save_cost'](self.page,self.preview,self.record,'PS')
        self.assertNotIn('cost_save_readbacks',self.record)

    def test_unstable_fresh_reads_remain_unresolved(self):
        self.read.side_effect=[dict(rows=[dict(platform='PS',costPrice='0.440496',b2c='0.0807')]),self.read.return_value]
        with self.assertRaisesRegex(ValueError,'save_readback_unstable'):
            self.scope['save_cost'](self.page,self.preview,self.record,'PS')

    def test_successful_inline_save_does_not_add_backend_reads(self):
        self.page.evaluate.side_effect=None
        self.scope['save_cost'](self.page,self.preview,self.record,'PS')
        self.page.reload.assert_not_called()
        self.read.assert_not_called()


if __name__=='__main__':main()
