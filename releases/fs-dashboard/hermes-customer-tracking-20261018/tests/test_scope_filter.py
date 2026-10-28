import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs,urlsplit


from _paths import ROOT, RELEASE
from tracking_source import admin_paid_day


def order(ident,**changes):
    row={'id':ident,'gid':1327,'site_id':266,'pay_status':1,
         'paytime':'2026-09-30 10:00:00','order_no':'ORDER-'+str(ident),
         'email':'guest@example.invalid','uid':0,'amount':'501'}
    row.update(changes)
    return row


def source(rows,page_size=None):
    def request(path,timeout):
        query=parse_qs(urlsplit(path).query)
        assert query['order']==['id,desc']
        assert query['search[0][val]']==['1327']
        assert query['search[1][val]']==['266']
        assert query['search[2][val]']==['1']
        page=int(query['page'][0]);size=page_size or len(rows)
        selected=rows[(page-1)*size:page*size]
        return 200,json.dumps({'code':1,'data':{'total':len(rows),'list':selected}}).encode()
    return request


class ScopeFilterTests(unittest.TestCase):
    def test_small_pages_keep_complete_coverage_beyond_old_300_page_count(self):
        from tracking_source import DAY_PAGE_SIZE,DAY_MAX_PAGES,MAX_PAGES
        self.assertEqual(DAY_PAGE_SIZE*DAY_MAX_PAGES,MAX_PAGES*100)
        total=6001;calls=[]
        def request(path,timeout):
            query=parse_qs(urlsplit(path).query);page=int(query['page'][0]);size=int(query['limit'][0])
            self.assertEqual(size,20);self.assertLessEqual(timeout,10);calls.append(page)
            batch=[order(total-index) for index in range((page-1)*size,min(page*size,total))]
            return 200,json.dumps({'code':1,'data':{'total':total,'list':batch}}).encode()
        result=admin_paid_day(request,'2026-09-30','FC27',{'ORDER-1'})
        self.assertEqual(result['status'],'available');self.assertEqual(len(calls),301)
        self.assertEqual(result['coverage']['received'],total)
        self.assertEqual(result['coverage']['unique_source_ids'],total)
        self.assertEqual(set(result['orders']),{'ORDER-1'})

    def test_full_upstream_pages_keep_only_exact_paid_fc_main_site(self):
        rows=[order(4,gid=891),order(3,site_id=222),
              order(2,pay_status=2),order(1)]
        result=admin_paid_day(source(rows,2),'2026-09-30','FC27',
                              {'ORDER-1','ORDER-2','ORDER-3','ORDER-4'})
        self.assertEqual(result['status'],'available')
        self.assertEqual(set(result['orders']),{'ORDER-1'})
        coverage=result['coverage']
        self.assertEqual((coverage['source_total'],coverage['received'],coverage['unique_source_ids']),(4,4,4))
        self.assertEqual(coverage['scope_matched_source_rows'],1)
        self.assertEqual(coverage['scope_excluded_source_rows'],3)
        self.assertEqual(coverage['scope_excluded_by_field'],{'gid':1,'site_id':1,'pay_status':1})
        self.assertNotIn('ORDER-2',str(coverage))

    def test_missing_or_unparseable_scope_still_rejects_source(self):
        for change in ({'gid':None},{'site_id':'bad'},{'pay_status':True}):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'admin_day_scope'):
                admin_paid_day(source([order(1,**change)]),'2026-09-30','FC27',{'ORDER-1'})

    def test_duplicate_or_bad_ordering_cannot_claim_complete(self):
        duplicate=[order(2),order(2)]
        result=admin_paid_day(source(duplicate),'2026-09-30','FC27',{'ORDER-2'})
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['coverage']['source_total'],2)
        self.assertEqual(result['coverage']['unique_source_ids'],1)
        with self.assertRaisesRegex(ValueError,'admin_day_sort_or_duplicate'):
            admin_paid_day(source([order(1),order(2)]),'2026-09-30','FC27',{'ORDER-1'})
        with self.assertRaisesRegex(ValueError,'admin_day_time'):
            admin_paid_day(source([order(1,gid=891,paytime='2026-10-01 10:00:00')]),
                           '2026-09-30','FC27',{'ORDER-1'})


if __name__=='__main__':unittest.main()
