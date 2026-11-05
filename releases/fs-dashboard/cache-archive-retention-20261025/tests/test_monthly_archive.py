"""Bounded fresh monthly exports and reference-safe archive compaction."""
from copy import deepcopy
import ast,hashlib,json,os,re,tempfile,threading,time,types,unittest
from contextlib import contextmanager
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch
SOURCE=Path(__file__).resolve().parents[1]/'source/es_order_structure.py'
NOW=datetime(2026,11,5,tzinfo=timezone.utc)
Q=dict(profile='ALL',start='2026-10-01',end='2026-10-31',group_by='new_customer',status='all')
def module():
    tree=ast.parse(SOURCE.read_text('utf-8'));scope=dict(Path=Path,threading=threading,json=json,hashlib=hashlib,re=re,datetime=datetime,date=date,timedelta=timedelta,timezone=timezone,time=time,SHANGHAI=timezone(timedelta(hours=8)),ARCHIVE_LOCK=threading.RLock(),SERVER_LOCK=threading.RLock(),_EXCEL_DEPTH=threading.local(),contextmanager=contextmanager,MAX_FILE=32*1024*1024,MAX_ARCHIVE_BYTES=512*1024*1024,MAX_ARCHIVE_FILES=512,ARCHIVE_RESERVE_BYTES=64*1024*1024,RULE_VERSION='exact-rules',deepcopy=deepcopy,COLUMNS={'order':'order','product':'product','game':'game'},parse_files=lambda files:([{'order':'same-order'}], [hashlib.sha256(x).hexdigest() for x in files],0),checked_query=lambda q:dict(q))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name not in ('parse_files','checked_query')]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),scope)
    return scope

def write(p,v):p.write_text(json.dumps(v));os.chmod(p,0o600)
def archived(root,raw,start,end,capture='2026-11-01T00:00:00+00:00'):
    h=hashlib.sha256(raw).hexdigest();f=root/(h+'.xlsx');f.write_bytes(raw);os.chmod(f,0o600)
    v=dict(file_sha256=[h],query=dict(profile='ALL',start=start,end=end),captured_at=capture,file_set=dict(declared_files=1,failed_files=0))
    n=hashlib.sha256(json.dumps(v).encode()).hexdigest()+'.json';write(root/n,v);return n,h

class MonthlyArchive(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);os.chmod(self.root,0o700);self.m=module()
    def tearDown(self):self.temp.cleanup()
    def refs(self,pins=(),hashes=()):return dict(complete=True,publication_id='pub-current',manifests=list(pins),file_hashes=list(hashes),inflight=[])
    def test_new_capture_same_bytes_does_not_modify_pinned_manifest(self):
        self.m['archive_files']([b'bytes'],Q,self.root);old={p.name:p.read_bytes() for p in self.root.glob('*.json')}
        self.m['archive_files']([b'bytes'],Q,self.root,capture_context='ur_test')
        self.assertEqual(len(list(self.root.glob('*.xlsx'))),1);self.assertEqual(len(list(self.root.glob('*.json'))),2)
        for name,raw in old.items():self.assertEqual((self.root/name).read_bytes(),raw)
    def test_cleanup_only_unpinned_covered_exports_and_cas(self):
        month,mh=archived(self.root,b'month','2026-10-01','2026-10-31');day,dh=archived(self.root,b'day','2026-10-08','2026-10-08');other,oh=archived(self.root,b'other','2026-09-07','2026-09-07')
        refs=Mock(return_value=self.refs([month]));plan=self.m['compact_archive'](self.root,refs)
        self.assertIn(day,[r['name'] for r in plan['manifests']]);self.assertNotIn(other,[r['name'] for r in plan['manifests']])
        self.assertTrue((self.root/day).exists());self.m['compact_archive'](self.root,refs,apply=True,expected_plan_sha256=plan['plan_sha256'])
        self.assertFalse((self.root/day).exists());self.assertFalse((self.root/(dh+'.xlsx')).exists());self.assertTrue((self.root/(mh+'.xlsx')).exists());self.assertTrue((self.root/other).exists())
    def test_reference_change_or_incomplete_scan_preserves_data(self):
        month,mh=archived(self.root,b'month','2026-10-01','2026-10-31');day,dh=archived(self.root,b'day','2026-10-08','2026-10-08')
        refs=Mock(return_value=self.refs([month]));plan=self.m['compact_archive'](self.root,refs)
        refs.return_value=self.refs([month,day])
        with self.assertRaisesRegex(ValueError,'changed'):self.m['compact_archive'](self.root,refs,True,plan['plan_sha256'])
        refs.return_value=dict(self.refs(),complete=False)
        self.assertFalse(self.m['compact_archive'](self.root,refs)['manifests']);self.assertTrue((self.root/day).exists())
    def test_partial_month_cannot_replace_day_or_delete_unique_data(self):
        month,mh=archived(self.root,b'month','2026-10-01','2026-10-31');day,dh=archived(self.root,b'day','2026-10-08','2026-10-08')
        v=json.loads((self.root/month).read_text());v['file_set']['failed_files']=1;write(self.root/month,v)
        self.assertFalse(self.m['compact_archive'](self.root,lambda:self.refs([month]))['manifests'])
    def test_external_file_reference_protects_original(self):
        month,mh=archived(self.root,b'month','2026-10-01','2026-10-31');day,dh=archived(self.root,b'day','2026-10-08','2026-10-08')
        plan=self.m['compact_archive'](self.root,lambda:self.refs([month], [dh]));self.assertFalse(plan['manifests'])
    def test_fresh_cycle_does_not_regenerate_success_or_unknown(self):
        value=dict(kind='es_order_structure_bundle',status='available',snapshots=[dict(query=Q,value=dict(kind='es_order_structure',captured_at=NOW.isoformat(),quality=dict(file_set_complete=True)))])
        reader=Mock(return_value=value)
        self.m['server_bundle_after'](Q,NOW.isoformat(),'ur_test',root=self.root,source=reader)
        with patch.object(time,'time',return_value=time.time()+99999):self.m['server_bundle_after'](Q,NOW.isoformat(),'ur_test',root=self.root,source=reader)
        reader.assert_called_once()
        reader=Mock(side_effect=TimeoutError())
        a=self.m['server_bundle_after'](Q,NOW.isoformat(),'ur_unknown',root=self.root,source=reader);b=self.m['server_bundle_after'](Q,NOW.isoformat(),'ur_unknown',root=self.root,source=reader)
        self.assertIn('unknown',b['reason']);reader.assert_called_once()

    def test_same_sha_month_and_day_never_delete_the_shared_original(self):
        month,h=archived(self.root,b'shared','2026-10-01','2026-10-31');day,_=archived(self.root,b'shared','2026-10-08','2026-10-08')
        plan=self.m['compact_archive'](self.root,lambda:self.refs([month]));self.assertEqual(plan['files'],[])
        self.m['compact_archive'](self.root,lambda:self.refs([month]),True,plan['plan_sha256']);self.assertTrue((self.root/(h+'.xlsx')).exists())
    def test_unique_order_absent_from_month_is_protected(self):
        month,h=archived(self.root,b'month','2026-10-01','2026-10-31');day,_=archived(self.root,b'day','2026-10-08','2026-10-08')
        self.m['parse_files']=lambda files:([{'order':files[0].decode()}],[hashlib.sha256(x).hexdigest() for x in files],0)
        plan=self.m['compact_archive'](self.root,lambda:self.refs([month]));self.assertEqual(plan['manifests'],[])
        self.assertIn('unique_order_not_in_month',[x['reason'] for x in plan['protected']])
    def test_failure_after_manifest_removal_can_resume_original_plan(self):
        month,h=archived(self.root,b'month','2026-10-01','2026-10-31');day,dh=archived(self.root,b'day','2026-10-08','2026-10-08')
        refs=lambda:self.refs([month]);plan=self.m['compact_archive'](self.root,refs);original=Path.unlink
        def stop(path,*a,**kw):
            if path.name==dh+'.xlsx':raise OSError('simulated interruption')
            return original(path,*a,**kw)
        with patch.object(Path,'unlink',stop),self.assertRaises(OSError):self.m['compact_archive'](self.root,refs,True,plan['plan_sha256'])
        self.assertFalse((self.root/day).exists());self.assertTrue((self.root/(dh+'.xlsx')).exists());self.assertTrue((self.root/month).exists())
        self.m['compact_archive'](self.root,refs,True,plan['plan_sha256']);self.assertFalse((self.root/(dh+'.xlsx')).exists())
    def test_partial_cleanup_then_next_daily_reconciles_only_original_remaining_files(self):
        month,h=archived(self.root,b'month','2026-10-01','2026-10-31');day,dh=archived(self.root,b'day','2026-10-08','2026-10-08')
        refs=Mock(return_value=self.refs([month]));plan=self.m['compact_archive'](self.root,refs);original=Path.unlink
        def stop(path,*a,**kw):
            if path.name==dh+'.xlsx':raise OSError('simulated interruption')
            return original(path,*a,**kw)
        with patch.object(Path,'unlink',stop),self.assertRaises(OSError):self.m['compact_archive'](self.root,refs,True,plan['plan_sha256'])
        new_day,nh=archived(self.root,b'new daily','2026-11-04','2026-11-04','2026-11-05T00:00:00+00:00')
        refs.return_value=dict(self.refs([month,new_day]),publication_id='next-day-pub')
        with self.assertRaisesRegex(ValueError,'references_changed'):self.m['compact_archive'](self.root,refs,True,plan['plan_sha256'])
        resumed=self.m['compact_archive'](self.root,refs)
        self.assertEqual(resumed['resume_from'],plan['plan_sha256']);self.assertEqual([x['sha256'] for x in resumed['files']],[dh])
        self.m['compact_archive'](self.root,refs,True,resumed['plan_sha256'])
        self.assertFalse((self.root/(dh+'.xlsx')).exists());self.assertTrue((self.root/(nh+'.xlsx')).exists());self.assertTrue((self.root/new_day).exists())
    def test_missing_sku_line_in_same_order_is_not_full_coverage(self):
        month,h=archived(self.root,b'month','2026-10-01','2026-10-31');day,_=archived(self.root,b'day','2026-10-08','2026-10-08')
        def parse(files):
            rows=[dict(order='same',product='gold',game='FC')]
            if files[0]==b'day':rows.append(dict(order='same',product='item',game='FC'))
            return rows,[hashlib.sha256(x).hexdigest() for x in files],0
        self.m['parse_files']=parse
        self.assertFalse(self.m['compact_archive'](self.root,lambda:self.refs([month]))['manifests'])
    def test_self_consistent_receipt_path_escape_is_refused_at_delete_boundary(self):
        refs=self.refs();plan=dict(root=str(self.root.resolve()),references=refs,inventory=[('../outside.json','a'*64)],manifests=[dict(name='../outside.json',sha256='a'*64,replacement='b'*64+'.json')],files=[])
        plan['plan_sha256']=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError,'path'):self.m['_apply_archive_compaction'](self.root,plan,lambda:refs)
    def test_channel_customer_flags_still_read_after_compaction_receipt(self):
        month,h=archived(self.root,b'month','2026-10-01','2026-10-31');day,_=archived(self.root,b'day','2026-10-08','2026-10-08')
        plan=self.m['compact_archive'](self.root,lambda:self.refs([month]));self.m['compact_archive'](self.root,lambda:self.refs([month]),True,plan['plan_sha256'])
        self.assertFalse((self.root/'.compaction.json').exists());self.assertTrue((self.root/'.compaction.receipt').exists())
        channel=SOURCE.parents[2]/'channel-effects-20261021/source/channel_source.py'
        from functools import lru_cache
        scope=dict(Path=Path,json=json,hashlib=hashlib,sys=__import__('sys'),date=date,timedelta=timedelta,lru_cache=lru_cache,ES_ARCHIVE=self.root,apply_current_mapping=lambda x:x)
        nodes=[n for n in ast.parse(channel.read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name in ('customer_types','apply_customer_types')]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(channel),'exec'),scope)
        order='fixture-order';ident=hashlib.sha256(order.encode()).hexdigest()
        dataset=dict(rows=[{'付款时间':'2026/10/08 10:00:00','订单号':ident,'是否新客户':'是','游戏':'FC','订单来源':'google-FC'}],hashes=[h],captured_at=NOW.isoformat(),parse_failures=0,failed_files=0,declared_files=1)
        es=types.SimpleNamespace(SERVER_LOCK=threading.RLock(),archive_access=self.m['archive_access'],archived_dataset=lambda *a,**k:dataset)
        with patch.dict(__import__('sys').modules,es_order_structure=es):out=scope['apply_customer_types'](dict(period=dict(start='2026-10-08',end='2026-10-08'),orders=[dict(orderNo=order)],sources={}))
        self.assertEqual(out['sources']['customer']['status'],'complete');self.assertEqual(out['orders'][0]['customerType'],'新客')
    @unittest.skipIf(os.name!='posix','Unix symlinks are the deployment boundary')
    def test_symlink_archive_root_is_rejected(self):
        link=self.root/'alias';target=self.root/'target';target.mkdir(mode=0o700);link.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):self.m['compact_archive'](link,lambda:self.refs())
    def test_fresh_api_bypasses_both_reuse_layers(self):
        client=Mock();auth=types.SimpleNamespace(Session=lambda:client,ADMIN_API='http://existing',UA='existing')
        capture=Mock(return_value=dict(status='available'));old=Mock(side_effect=AssertionError('old export reuse is not fresh'))
        import sys
        with patch.dict(sys.modules,p2pah_auth=auth),patch.dict(self.m,export_bundle=capture,export_dataset=old):
            self.m['api_dataset'](Q,time.monotonic()+30,capture_context='ur_test',archive_root=self.root)
        capture.assert_called_once();old.assert_not_called();client.close.assert_called_once()
    def test_month_archive_can_serve_subday_without_false_outside_rows(self):
        month,h=archived(self.root,b'month','2026-10-01','2026-10-31')
        self.m['COLUMNS']['time']='time';self.m['parse_files']=lambda f:([{'time':'2026/10/08 10:00:00','order':'one'},{'time':'2026/10/09 10:00:00','order':'two'}],[h],0)
        self.m['make_dataset']=lambda rows,*a:dict(rows=rows)
        q=dict(Q,start='2026-10-08',end='2026-10-08');out=self.m['_archived_dataset'](q,self.root)
        self.assertEqual([r['order'] for r in out['rows']],['one'])

if __name__=='__main__':unittest.main()
