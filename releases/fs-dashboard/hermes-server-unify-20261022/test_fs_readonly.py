import unittest
from unittest.mock import Mock,patch
import types
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'releases/fs-dashboard/knowledge-layering-20261023/source'),
              str(ROOT/'releases/fs-dashboard/user-analytics-20261022/source'),
              str(ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013')]
import fs_readonly as plugin


class ReadonlyTools(unittest.TestCase):
    def test_v4_user_contract_is_registered_and_forwarded_unchanged(self):
        import user_tools
        ctx = Mock()
        toolsets = types.ModuleType('toolsets'); toolsets.TOOLSET_SESSION_PLATFORMS = {}
        with patch.dict(sys.modules, {'toolsets': toolsets}): plugin.register(ctx)
        registered = next(c.kwargs for c in ctx.register_tool.call_args_list if c.kwargs['name'] == 'fs_query_user_analytics')
        self.assertEqual(registered['schema']['parameters']['properties'], user_tools.PROPERTIES)
        self.assertEqual(user_tools.PROPERTIES['section']['enum'], ['summary', 'cohorts', 'stages', 'coverage'])
        args = {'scope': 'project', 'scope_id': '1327', 'cohort_start': '2026-01', 'windows': '30,90,180'}
        with patch.object(plugin, 'read', return_value={'status': 'available'}) as read:
            plugin.call('fs_query_user_analytics', args)
            read.assert_called_once_with('/users', dict(args, action='tool'))
            read.reset_mock()
            poll = {'query_id': 'a'*32, 'section': 'cohorts'}
            plugin.call('fs_query_user_analytics', poll)
            read.assert_called_once_with('/users', dict(poll, action='tool'))

    def test_owner_url_and_extra_fields_cannot_be_overridden(self):
        for bad in [{'owner':'other'},{'url':'https://example.test'},{'headers':{}},{'force':True}]:
            with patch.object(plugin,'read') as read:
                with self.assertRaises(ValueError):plugin.call('fs_get_data_catalog',bad)
                read.assert_not_called()

    def test_no_write_tool(self):
        with self.assertRaises(ValueError):plugin.call('fs_create_coupon',{})
        with self.assertRaises(ValueError):plugin.call('fs_query_es_order_structure',{'profile':'FC27'})

    def test_native_poll_retains_exact_catalog_identity(self):
        query={'profile':'FC27','start':'2026-10-21','end':'2026-10-21'}
        with patch.object(plugin,'read',side_effect=[{'catalogId':'catalog-1'},{'status':'pending','retryAfter':2}]) as read:
            result=plugin.call('fs_query_native_statistics',query)
            self.assertEqual(result['repeat_arguments'],dict(query,catalog_id='catalog-1'))
        with patch.object(plugin,'read',return_value={'status':'available'}) as read:
            plugin.call('fs_query_native_statistics',result['repeat_arguments'])
            read.assert_called_once_with('/range',dict(query,grain='day',snapshotId='catalog-1'))

    def test_discount_uses_existing_es_projection(self):
        q={'profile':'ALL','start':'2026-10-21','end':'2026-10-21','group_by':'day'}
        with patch.object(plugin,'read',return_value={'status':'pending'}) as read:
            plugin.call('fs_query_discount_analysis',q)
            read.assert_called_once_with('/advisor',dict(q,mode='hermes',structure='es',group_by='discount_day'))

    def test_bad_value_and_redirect_are_rejected(self):
        with self.assertRaises(ValueError):plugin.call('fs_query_product_orders',{'profile':'FC27','start':'2026-10-21','end':'2026-10-21','product_id':True})
        self.assertIsNone(plugin.NoRedirect().redirect_request(None,None,302,'',{},'http://other'))
        with patch.object(plugin,'read') as read:
            with self.assertRaises(ValueError):plugin.call('fs_query_es_order_structure',{'profile':'FC27','start':'2026-10-21','end':'2026-10-21','group_by':'day'})
            read.assert_not_called()

    def test_official_registry_retains_five_and_adds_user_analytics(self):
        ctx=Mock()
        toolsets=types.ModuleType('toolsets');toolsets.TOOLSET_SESSION_PLATFORMS={}
        with patch.dict(sys.modules,{'toolsets':toolsets}):plugin.register(ctx)
        self.assertEqual(ctx.register_tool.call_count,8)
        self.assertEqual({item.kwargs['name'] for item in ctx.register_tool.call_args_list}, {
            'fs_get_data_catalog','fs_query_native_statistics','fs_query_es_order_structure',
            'fs_query_discount_analysis','fs_query_product_orders','fs_query_user_analytics',
            'fs_get_knowledge_index','fs_read_knowledge'})
        for item in ctx.register_tool.call_args_list:
            if item.kwargs['name'] not in plugin.TOOLS:
                self.assertEqual(item.kwargs['toolset'],'fs_knowledge')
                self.assertFalse(item.kwargs['schema']['parameters']['additionalProperties'])
                continue
            self.assertEqual(item.kwargs['toolset'],'fs_readonly')
            self.assertFalse(item.kwargs['schema']['parameters']['additionalProperties'])
            with patch.object(plugin,'read',return_value={'status':'available'}):
                if item.kwargs['name']=='fs_get_data_catalog':self.assertIn('available',item.kwargs['handler']({}))


if __name__=='__main__':unittest.main()
