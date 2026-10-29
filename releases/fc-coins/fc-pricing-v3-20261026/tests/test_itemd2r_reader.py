from copy import deepcopy
from pathlib import Path
import json,sys,unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import itemd2r_reader as reader


class ItemD2RReader(unittest.TestCase):
    def test_middle_platform_timeout_preserves_prior_and_later_current_quotes(self):
        for reason,expected in [('one_platform_timeout',['valid','missing','valid']),('itemd2r_read_budget',['valid','missing','missing'])]:
            page=Mock();page.url=reader.URL;page.goto.return_value=SimpleNamespace(status=200,headers={});page.title.return_value='FC27 Coins'
            selected={'device':None}
            def locator(selector):
                loc=Mock()
                if selector=='.platform-list li':
                    def filtered(*,has_text):
                        item=Mock()
                        if has_text.fullmatch('XBOX ONE'):item.click.side_effect=TimeoutError(reason)
                        return item
                    loc.filter.side_effect=filtered
                return loc
            page.locator.side_effect=locator
            page.wait_for_function.side_effect=lambda *a,arg,**kw:selected.update(device=arg)
            page.evaluate.side_effect=lambda _:dict(device=selected['device'],quantity='100000',tier='100000',tier_label='100 K',delivered='100',method='ai-automatic',
                method_selected=True,usd=True,busy=False,price='8.00',total='8.00',unit='.00008',fee='0')
            with self.subTest(reason=reason):
                rows=reader.collect(SimpleNamespace(new_page=lambda:page))
                self.assertEqual([r['status'] for r in rows],expected)
                self.assertEqual(rows[1]['reason'],'itemd2r_read_budget' if reason=='itemd2r_read_budget' else 'itemd2r_TimeoutError')
                self.assertNotIn('gross_usd',rows[1])
                if rows[2]['status']=='valid':self.assertEqual(rows[2]['platform'],'PC')

    def test_cloudflare_403_is_distinct_from_other_http_and_browser_errors(self):
        for status,headers,expected in [(403,{'server':'cloudflare'},'itemd2r_cloudflare_403'),(403,{'cf-ray':'test'},'itemd2r_cloudflare_403'),(403,{},'itemd2r_http_403'),(500,{},'itemd2r_http_500')]:
            page=Mock();page.goto.return_value=SimpleNamespace(status=status,headers=headers)
            with self.subTest(status=status,headers=headers),self.assertRaisesRegex(ValueError,'^'+expected+'$'):
                reader.collect(SimpleNamespace(new_page=lambda:page))
            page.close.assert_called_once()
        payload=dict(source='ItemD2R',status='error',reason='itemd2r_cloudflare_403',offers=[])
        with patch.object(reader.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(payload))),self.assertRaisesRegex(ValueError,'^itemd2r_cloudflare_403$'):
            reader.public_read()
        with patch.object(reader.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='')),self.assertRaisesRegex(ValueError,'^itemd2r_public_read_failed$'):
            reader.public_read()

    def test_offer_keeps_real_delivered_quantity_and_currency(self):
        data=dict(device='2',quantity='100000',tier='100000',tier_label='100 K',delivered='100',method='ai-automatic',
            method_selected=True,usd=True,busy=False,price='8.50',total='8.50',unit='.000085',fee='0')
        result=reader.offer(data,'PS','2')
        self.assertEqual((result['purchase_k'],result['bonus_k'],result['gross_usd']),('100','0','8.50'))
        self.assertTrue(result['coupon_excluded'])
        for update in (dict(usd=False),dict(fee='1'),dict(total='8.40'),dict(device='1'),dict(delivered='105')):
            with self.subTest(update=update),self.assertRaises(ValueError):reader.offer(dict(data,**update),'PS','2')

    def test_new_reader_launch_keeps_bounded_same_browser_contract_without_old_directory(self):
        payload=dict(source='ItemD2R',status='valid',offers=[dict(platform=p) for p in ('PS','XBOX','PC')])
        with patch.object(reader.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(payload))) as run:
            self.assertEqual(reader.public_read(),payload['offers'])
        command=run.call_args.args[0];script=run.call_args.kwargs['input']
        self.assertIn('fc27-cloud-browser',command)
        self.assertEqual(run.call_args.kwargs['timeout'],60)
        self.assertNotIn('/opt/fc27-price-observer',script)
        self.assertIn('http://127.0.0.1:9225',script)
        compile(script,'itemd2r-browser-reader','exec')


if __name__=='__main__':unittest.main()
