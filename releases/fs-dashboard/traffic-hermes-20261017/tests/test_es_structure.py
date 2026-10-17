"""Synthetic XLSX and actual read/controller boundaries; no business records in fixtures."""
import ast
from concurrent.futures import Future
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import threading
import tempfile
from unittest.mock import patch
from types import SimpleNamespace
import unittest
from xml.sax.saxutils import escape
import zipfile

ROOT=Path(__file__).resolve().parents[4]
SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path[:0]=[str(SOURCE),str(ROOT/'mmoexp_google_data/details'),str(ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013')]
import es_order_structure as es

Q={'profile':'FC27','start':'2026-10-15','end':'2026-10-15','group_by':'source_game','status':'all'}

def row(order='private-fixture-1',**changes):
    result={name:'' for name in es.COLUMNS.values()}
    result.update({'订单号':order,'游戏':'FC 27','订单金额（美元）':'10.25','实付金额':'99','实付币种':'BRL','订单状态':'已完成','付款时间':'2026/10/15 12:00:00','产品类型':'物品(Items)','国家代码':'US','支付大类':'fixture','支付方式':'cardpay','是否新客户':'是','支付账号':'private-account-fixture'})
    result.update(changes);return result


def xlsx(rows,missing=None):
    headers=list(row())
    if missing:headers.remove(missing)
    xml=['<worksheet xmlns="'+es.NS['m']+'"><sheetData>']
    for n,values in enumerate([headers]+[[r.get(h,'') for h in headers] for r in rows],1):
        xml.append('<row>')
        for col,value in enumerate(values):
            xml.append('<c r="'+chr(65+col)+str(n)+'" t="inlineStr"><is><t>'+escape(str(value))+'</t></is></c>')
        xml.append('</row>')
    xml.append('</sheetData></worksheet>');out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('xl/worksheets/sheet1.xml',''.join(xml))
    return out.getvalue()


class ParseTests(unittest.TestCase):
    def value(self,rows,**kwargs):return es.aggregate([xlsx(rows)],Q,declared_files=1,**kwargs)

    def test_usd_separate_from_original_paid_and_pii_removed(self):
        value=self.value([row(),row('private-fixture-2',**{'实付币种':'EUR','订单金额（美元）':'5'})])
        self.assertEqual(value['structure_totals']['order_amount_usd'],'15.25')
        self.assertEqual(value['quality']['original_paid_by_currency'],{'BRL':'99','EUR':'99'})
        text=json.dumps(value,ensure_ascii=False)
        for secret in ('private-fixture','private-account','订单号','支付账号','https://'):self.assertNotIn(secret,text)
        self.assertFalse(value['scope']['site_verified']);self.assertEqual(value['quality']['upstream_completeness'],'unknown')

    def test_all_statuses_default_and_exact_status_filter(self):
        records=[row(),row('2',**{'订单状态':'验证·未通过'})]
        self.assertEqual(self.value(records)['structure_totals']['orders'],2)
        filtered=es.aggregate([xlsx(records)],dict(Q,status='已完成'),1)
        self.assertEqual(filtered['structure_totals']['orders'],1)

    def test_duplicate_files_and_conflicting_order_no_double_count(self):
        raw=xlsx([row()]);value=es.aggregate([raw,raw],Q,2)
        self.assertEqual(value['structure_totals']['orders'],1);self.assertEqual(value['quality']['duplicate_records'],1)
        for change in ({'游戏':'Diablo 4'},{'订单金额（美元）':'999'},{'订单状态':'验证·未通过'}):
            value=self.value([row(),row(**change)])
            self.assertEqual(value['structure_totals']['orders'],0);self.assertEqual(value['quality']['ambiguous_orders'],1)
            self.assertIsNone(value['structure_totals']['order_amount_usd'])

    def test_manifest_failure_and_bad_file_keep_partial(self):
        value=es.aggregate([xlsx([row()]),b'bad-file'],Q,3,1)
        self.assertEqual(value['status'],'partial');self.assertFalse(value['quality']['file_set_complete'])
        self.assertEqual(value['quality']['parse_failures'],1)

    def test_empty_file_missing_column_and_empty_valid_sheet(self):
        self.assertEqual(es.aggregate([],Q,0)['status'],'unavailable')
        self.assertEqual(es.aggregate([xlsx([row()],missing='订单来源')],Q,1)['status'],'unavailable')
        empty=self.value([]);self.assertEqual(empty['structure_totals']['orders'],0);self.assertEqual(empty['structure_totals']['order_amount_usd'],'0')

    def test_game_and_brand_independent_natural_source(self):
        value=self.value([row(),row('2',**{'订单来源':'google-FC27-PMAX-Coins-US'}),row('3',**{'游戏':'Diablo 4','订单来源':'google-FC27-PMAX-Coins-US'})])
        self.assertEqual(value['structure_totals']['orders'],2)
        self.assertTrue(any('业务自然' in r['label'] for r in value['groups']))
        self.assertTrue(any('global_brand' in r['label'] for r in value['groups']))
        self.assertEqual(value['quality']['profile_basis'],'exact export game label FC 27')

    def test_top_other_after_complete_collection(self):
        records=[row(str(n),**{'国家代码':'country-'+str(n)}) for n in range(25)]
        value=es.aggregate([xlsx(records)],dict(Q,group_by='country'),1)
        self.assertEqual(len(value['groups']),21);self.assertEqual(value['groups'][-1]['orders'],5)
        self.assertEqual(sum(r['orders'] for r in value['groups']),25)

    def test_bad_amount_missing_id_and_boundary(self):
        value=self.value([row(**{'订单金额（美元）':'NaN'}),row('',**{}),row('3',**{'付款时间':'2026/10/16 00:00:00'}),row('4',**{'付款时间':'2026/10/15 00:00:00'})])
        self.assertEqual(value['status'],'partial');self.assertEqual(value['structure_totals']['orders'],2)
        self.assertEqual(value['structure_totals']['priced_orders'],1)
        self.assertEqual(value['quality']['outside_period_records'],1)

    def test_query_rejects_injection_large_range_and_unknown_profile(self):
        for change in ({'url':'https://example.com'},{'profile':'FC26'},{'group_by':'payment_account'},{'end':'2026-12-31'},{'status':'x\nunsafe'}):
            with self.assertRaises((ValueError,TypeError)):es.checked_query(dict(Q,**change))


class ExportTests(unittest.TestCase):
    def manager(self,urls):
        calls=[]
        def request(path,token=None,timeout=15):calls.append(path);return 200,json.dumps({'code':1,'data':{'urls':urls}}).encode()
        return SimpleNamespace(lock=threading.RLock(),token='fixture-secret',identity_ok=lambda token:True,request=request),calls

    def test_all_files_authenticated_and_no_urls_in_result(self):
        urls=['https://admin-api.p2pah.cn/static/a.xlsx','https://admin-api.p2pah.cn/static/b.xlsx'];manager,calls=self.manager(urls);seen=[]
        def download(url,headers):seen.append(headers);return xlsx([row(url[-6])])
        bundle=es.export_bundle(manager,{k:Q[k] for k in ('profile','start','end')},{'Origin':'fixture'},download)
        self.assertEqual(len(calls),1);self.assertEqual(len(seen),2);self.assertEqual(seen[0]['batoken'],'fixture-secret')
        self.assertEqual(bundle['status'],'available');text=json.dumps(bundle)
        self.assertNotIn('https://',text);self.assertNotIn('fixture-secret',text)

    def test_host_restriction_and_failed_shard(self):
        manager,calls=self.manager(['https://evil.test/a.xlsx','https://admin-api.p2pah.cn/static/a.xlsx']);downloads=[]
        bundle=es.export_bundle(manager,{k:Q[k] for k in ('profile','start','end')},{},lambda url,h:downloads.append(url) or xlsx([row()]))
        self.assertEqual(len(downloads),1);self.assertEqual(bundle['snapshots'][0]['value']['status'],'partial')
        self.assertEqual(bundle['snapshots'][0]['value']['quality']['failed_files'],1)

    def test_single_generation_pending_and_config_barrier(self):
        future=Future();submits=[]
        pool=SimpleNamespace(submit=lambda *args:submits.append(args) or future)
        config={'enabled':True};reader=es.ESReader(config,pool)
        self.assertEqual(reader.get(Q)['status'],'pending');reader.get(dict(Q,group_by='country'))
        self.assertEqual(len(submits),2)
        config['enabled']=False;self.assertEqual(reader.get(Q)['quality']['reason'],'fc_detail_disabled')
        future.set_result({'status':'available','snapshots':[{'query':Q,'value':es.aggregate([xlsx([row()])],Q,1)}]})
        self.assertEqual(reader.get(Q)['status'],'unavailable')
        config['enabled']=True;self.assertEqual(reader.get(Q)['structure_totals']['orders'],1)

    def test_research_book_freezes_version_and_declares_scope(self):
        from fs_evidence import SourcePins
        from research import ResearchBook,RESEARCH_NAMES
        from pilot import digest
        values=[es.aggregate([xlsx([row()])],Q,1)]
        pins=SourcePins();read=pins.wrap(lambda q:deepcopy(values[0]),'Admin-ES-file-set')
        dataset={'snapshot_id':'fc-detail-fixture','as_of':'2026-10-17T00:00:00+00:00'}
        book=ResearchBook(dataset,{}, {'start':Q['start'],'end':Q['end']},es_structure=read)
        first=book.call('fc.query_es_order_structure',Q)
        values[0]['source_version']='different-later-source'
        second=book.call('fc.query_es_order_structure',Q)
        self.assertEqual(first,second);self.assertEqual(first['scope'],'Admin ES导出原范围');self.assertEqual(first['timezone'],'unverified')
        original=dict(first);original.pop('evidence_id')
        self.assertEqual(first['evidence_id'],'ev_'+digest(original)[:24])
        self.assertIn('fc.query_es_order_structure',RESEARCH_NAMES)

    def test_one_parse_per_file_and_immutable_archive(self):
        manager,calls=self.manager(['https://admin-api.p2pah.cn/static/a.xlsx'])
        raw=xlsx([row(),row('2',**{'订单状态':'验证·未通过'})])
        with patch.object(es,'xlsx_rows',wraps=es.xlsx_rows) as parser:
            bundle=es.export_bundle(manager,{k:Q[k] for k in ('profile','start','end')},{},lambda *a:raw)
        self.assertEqual(parser.call_count,1);self.assertEqual(len(bundle['snapshots']),21)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'archive';es.archive_files([raw],Q,root);es.archive_files([raw],Q,root)
            self.assertEqual(len(list(root.glob('*.xlsx'))),1)
            path=next(root.glob('*.xlsx'));path.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'es_archive_integrity'):es.archive_files([raw],Q,root)

    def test_durable_cache_reuses_success_but_never_replays_unknown(self):
        args={k:Q[k] for k in ('profile','start','end')};calls=[]
        value={'kind':'es_order_structure_bundle','status':'available','snapshots':[{'query':Q,'value':es.aggregate([xlsx([row()])],Q,1)}]}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(value).encode()
        def opened(*args,**kwargs):calls.append(args);return Response()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'success';opener=SimpleNamespace(open=opened)
            self.assertEqual(es.server_bundle(args,root,opener)['status'],'available');es.server_bundle(args,root,opener)
            self.assertEqual(len(calls),1)
            root=Path(folder)/'unknown'
            def failed(*args,**kwargs):calls.append(args);raise TimeoutError()
            opener=SimpleNamespace(open=failed)
            self.assertIn('unknown',es.server_bundle(args,root,opener)['reason'])
            self.assertIn('poll_only',es.server_bundle(args,root,opener)['reason']);self.assertEqual(len(calls),3)
            self.assertFalse(json.loads(calls[1][0].data)['poll_only']);self.assertTrue(json.loads(calls[2][0].data)['poll_only'])

    def test_actual_session_method_and_handler_wire_existing_manager(self):
        tree=ast.parse((SOURCE/'p2pah_session_service.py').read_text('utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SessionManager')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='fc_capability')
        serve=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='serve')
        captured=[]
        class FakeServer:
            def __init__(self,address,handler):captured.append(handler)
            def serve_forever(self):pass
        scope={'HEADERS':{'Origin':'fixture'},'json':json,'SessionManager':object,'BaseHTTPRequestHandler':object,'ThreadingHTTPServer':FakeServer}
        node=ast.ClassDef(name='Manager',bases=[],keywords=[],body=[method],decorator_list=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node,serve],type_ignores=[])),'actual-session-es','exec'),scope)
        manager=scope['Manager']();expected={'kind':'es_order_structure_bundle','status':'available','snapshots':[]}
        with patch.object(es,'session_bundle',return_value=expected) as export:
            result=manager.fc_capability(dict(kind='es_structure',**{k:Q[k] for k in ('profile','start','end')}))
            self.assertIs(export.call_args.args[0],manager);self.assertEqual(result['kind'],'es_order_structure_bundle')
        with self.assertRaises(ValueError):manager.fc_capability(dict(Q,kind='es_structure',url='https://evil.test'))
        calls=[];manager.fc_capability=lambda q:calls.append(q) or {'kind':'es_order_structure_bundle','status':'available'}
        scope['serve'](manager);handler=captured[0]();body=json.dumps(dict(Q,kind='es_structure')).encode();handler.path='/business/fc-capability';handler.headers={'Content-Length':str(len(body))};handler.rfile=io.BytesIO(body);handler.wfile=io.BytesIO();codes=[]
        handler.send_response=codes.append;handler.send_header=lambda *a:None;handler.end_headers=lambda:None;handler.send_error=codes.append
        handler.do_POST();self.assertEqual(codes,[200]);self.assertEqual(calls[0]['kind'],'es_structure')
        handler.path='/arbitrary';handler.do_POST();self.assertEqual(codes[-1],404)

    def test_shanghai_midnight_today_and_ttl(self):
        from datetime import datetime,timezone
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return datetime(2026,10,16,17,0,tzinfo=timezone.utc).astimezone(tz)
        with patch.object(es,'datetime',Clock):
            es.checked_query(dict(Q,start='2026-10-17',end='2026-10-17'))
            self.assertEqual(es.cache_seconds('2026-10-17'),900);self.assertEqual(es.cache_seconds('2026-10-16'),21600)

    def test_download_releases_identity_lock_and_export_timeout(self):
        manager,calls=self.manager(['https://admin-api.p2pah.cn/static/a.xlsx']);timeouts=[]
        request=manager.request
        def unlocked_request(path,token=None,timeout=15):
            self.assertFalse(manager.lock._is_owned());timeouts.append(timeout);return request(path,token,timeout)
        manager.request=unlocked_request
        def download(*args):
            self.assertFalse(manager.lock._is_owned());return xlsx([row()])
        es.export_bundle(manager,{k:Q[k] for k in ('profile','start','end')},{},download)
        self.assertEqual(timeouts,[90])

    def test_source_future_poll_never_regenerates_unknown(self):
        q={k:Q[k] for k in ('profile','start','end')};future=Future();calls=[]
        pool=SimpleNamespace(submit=lambda *args:calls.append(args) or future)
        with patch.object(es,'SESSION_JOBS',{}),patch.object(es,'SESSION_POOL',pool),patch.object(es,'archive_files'):
            self.assertIn('reconcile',es.session_bundle(None,q,{},True)['reason']);self.assertEqual(calls,[])
            self.assertEqual(es.session_bundle(None,q,{})['status'],'pending')
            self.assertEqual(es.session_bundle(None,q,{},True)['status'],'pending');self.assertEqual(len(calls),1)
            future.set_result({'status':'available','snapshots':[]})
            self.assertEqual(es.session_bundle(None,q,{},True)['status'],'available');self.assertEqual(len(calls),1)

    def test_failed_refresh_preserves_original_version_and_known_auth_backoff(self):
        args={k:Q[k] for k in ('profile','start','end')};original=es.aggregate([xlsx([row()])],Q,1)
        values=[{'kind':'es_order_structure_bundle','status':'available','snapshots':[{'query':Q,'value':original}]}, {'kind':'es_order_structure_bundle','status':'unavailable','reason':'existing_auth_unavailable','retryable':True,'stage':'not_generated'}]
        calls=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(values[min(len(calls)-1,1)]).encode()
        opener=SimpleNamespace(open=lambda *args,**kwargs:calls.append(args) or Response())
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'cache'
            with patch.object(es.time,'time',return_value=1000):es.server_bundle(args,root,opener)
            with patch.object(es.time,'time',return_value=1000+21601):
                value=es.server_bundle(args,root,opener);again=es.server_bundle(args,root,opener)
            self.assertEqual(len(calls),2);projection=value['snapshots'][0]['value']
            self.assertEqual(projection['source_version'],original['source_version']);self.assertEqual(projection['captured_at'],original['captured_at'])
            self.assertEqual(projection['status'],'partial');self.assertTrue(projection['quality']['retained_previous'])
            self.assertFalse(list(root.glob('*.attempt')));self.assertTrue(value['retryable'])

    def test_archive_quotas_and_free_space_refuse_without_deleting(self):
        raw=xlsx([row()])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'archive'
            with patch.object(es,'MAX_ARCHIVE_BYTES',len(raw)-1):
                with self.assertRaisesRegex(ValueError,'es_archive_capacity'):es.archive_files([raw],Q,root)
            self.assertEqual(list(root.iterdir()),[])
            with patch.object(es,'MAX_ARCHIVE_FILES',1):
                with self.assertRaisesRegex(ValueError,'es_archive_capacity'):es.archive_files([raw],Q,root)
            self.assertEqual(list(root.iterdir()),[])
            with patch('shutil.disk_usage',return_value=SimpleNamespace(free=0)):
                with self.assertRaisesRegex(ValueError,'es_archive_disk_reserve'):es.archive_files([raw],Q,root)
            es.archive_files([raw],Q,root);before={p.name:p.read_bytes() for p in root.iterdir()}
            with patch.object(es,'MAX_ARCHIVE_BYTES',sum(map(len,before.values()))):
                with self.assertRaisesRegex(ValueError,'es_archive_capacity'):es.archive_files([xlsx([row('new')])],Q,root)
            self.assertEqual({p.name:p.read_bytes() for p in root.iterdir()},before)

    def test_source_preflight_blocks_export_when_archive_mount_unavailable(self):
        calls=[];pool=SimpleNamespace(submit=lambda *args:calls.append(args))
        with patch.object(es,'SESSION_JOBS',{}),patch.object(es,'SESSION_POOL',pool),patch.object(es,'archive_files',side_effect=OSError('readonly')):
            value=es.session_bundle(None,{k:Q[k] for k in ('profile','start','end')},{})
        self.assertEqual(value['stage'],'not_generated');self.assertEqual(calls,[])

    def test_candidate_unit_only_adds_archive_mount_and_new_image(self):
        import hashlib
        unit=(SOURCE/'fc27-p2pah-session.service').read_bytes()
        original=unit.replace(b'fc27-cloud-session:traffic-hermes-20261017-es',b'fc27-cloud-session:business-live-20261010').replace(b' --mount type=bind,src=/var/lib/fc27-es-exports,dst=/var/lib/fc27-es-exports',b'')
        self.assertEqual(hashlib.sha256(original).hexdigest(),'ac783f78773b57d63884fd1643d8079e9ac1aa35e069b87bd4684c9346899e73')
        docker=(SOURCE/'Dockerfile.session').read_text('utf-8')
        self.assertIn('ARG SESSION_BASE_IMAGE',docker);self.assertIn('FROM ${SESSION_BASE_IMAGE}',docker)
        self.assertIn('sha256:88963f9429c84615a7ba24623cf0f54a7d4c313644c64092098e0adb52e835d8',docker)
        self.assertNotIn('pip install',docker);self.assertNotIn('apt',docker)
        tree=ast.parse((SOURCE/'p2pah_session_service.py').read_text('utf-8'))
        manager=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SessionManager')
        request=next(n for n in manager.body if isinstance(n,ast.FunctionDef) and n.name=='request')
        self.assertEqual(request.args.kwonlyargs[-1].arg,'timeout');self.assertEqual(request.args.kw_defaults[-1].value,15)

    def test_actual_controller_auth_validation_and_only_read(self):
        tree=ast.parse((SOURCE/'controller.py').read_text('utf-8'));cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='HermesService');method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='get')
        node=ast.ClassDef(name='Service',bases=[],keywords=[],body=[method],decorator_list=[]);ns={}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual-es-controller','exec'),ns)
        detail=SimpleNamespace(config={'enabled':False},pool=None);service=ns['Service']();service.detail=detail
        params={k:[v] for k,v in dict(Q,mode='hermes',structure='es').items()}
        self.assertEqual(service.get(params,None)[0],401)
        code,value=service.get(params,'viewer');self.assertEqual(code,200);self.assertEqual(value['status'],'unavailable')
        self.assertEqual(service.get(dict(params,sql=['bad']),'viewer')[0],422)

    def test_live_six_field_handler_routes_default_profile_and_rejects_bad_profile(self):
        from urllib.parse import urlsplit,parse_qs,urlencode
        tree=ast.parse((SOURCE/'controller.py').read_text('utf-8'));cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='HermesService');method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='get')
        ns={};exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Service',bases=[],keywords=[],body=[method],decorator_list=[])],type_ignores=[])),'actual-controller','exec'),ns)
        service=ns['Service']();service.detail=SimpleNamespace(config={'enabled':False},pool=None)
        handler_ns={'urlsplit':urlsplit,'parse_qs':parse_qs,'HERMES':service}
        # AST-extracted actual shared-range-live Handler.do_GET; no runtime data.
        shared=ast.parse((SOURCE/'shared_range_es_v3.py').read_text('utf-8'));handler_class=next(n for n in shared.body if isinstance(n,ast.ClassDef) and n.name=='Handler');handler_get=next(n for n in handler_class.body if isinstance(n,ast.FunctionDef) and n.name=='do_GET')
        fixture=ast.unparse(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Handler',bases=[],keywords=[],body=[handler_get],decorator_list=[])],type_ignores=[])))
        self.assertIn('max_num_fields=7',fixture)
        exec(compile(fixture,'live-handler-ast','exec'),handler_ns);handler=handler_ns['Handler']();replies=[];handler.reply=lambda *args:replies.append(args)
        query={'mode':'hermes','structure':'es','start':'2026-10-15','end':'2026-10-15','group_by':'source_game','status':'all'}
        handler.path='/advisor?'+urlencode(query);handler.headers={};handler.do_GET();self.assertEqual(replies[-1][0],401)
        handler.headers={'X-Auth-User':'viewer'};handler.do_GET();self.assertEqual(replies[-1][0],200);self.assertEqual(replies[-1][1]['status'],'unavailable')
        for profile in ('FC26',''):
            bad={k:v for k,v in query.items() if k!='status'};bad['profile']=profile
            handler.path='/advisor?'+urlencode(bad);handler.do_GET();self.assertEqual(replies[-1][0],422)
        unknown={k:v for k,v in query.items() if k not in ('status','group_by')};unknown['unknown']='fixture'
        handler.path='/advisor?'+urlencode(unknown);handler.do_GET();self.assertEqual(replies[-1][0],422)
        duplicate=[(k,v) for k,v in query.items() if k not in ('status','group_by')]+[('start','2026-10-15')]
        self.assertLessEqual(len(duplicate),6)
        handler.path='/advisor?'+urlencode(duplicate);handler.do_GET();self.assertEqual(replies[-1][0],422)
        handler.path='/advisor?'+urlencode(dict(query,profile='FC27'));handler.do_GET();self.assertEqual(replies[-1][0],200)
        handler.path='/advisor?'+urlencode(dict(query,profile='D4'));handler.do_GET();self.assertEqual(replies[-1][0],200)
        handler.path='/advisor?'+urlencode(dict(query,profile='D4',unknown='no'));handler.do_GET();self.assertEqual(replies[-1][0],503)

class MultiGameTests(unittest.TestCase):
    def test_global_game_exact_profiles_unmapped_and_brand_are_independent(self):
        records=[row('fc',**{'游戏':'FC 27'}),row('d4',**{'游戏':'Diablo 4','订单来源':'google-FC27-PMAX-Coins-US'}),row('aion',**{'游戏':'Aion 2'}),row('other',**{'游戏':'Unmapped Game'})]
        args=dict(Q,profile='ALL',group_by='game');raw=xlsx(records);result=es.aggregate([raw],args,1)
        self.assertEqual(result['structure_totals']['orders'],4);self.assertEqual(len(result['groups']),4);self.assertEqual(result['quality']['unmapped_game_records'],1)
        self.assertIn('Unmapped Game',[r['label'] for r in result['groups']]);self.assertIn({'code':'D4','label':'Diablo 4'},result['available_profiles'])
        d4=es.aggregate([raw],dict(Q,profile='D4'),1);self.assertEqual(d4['structure_totals']['orders'],1);self.assertIn('global_brand',d4['groups'][0]['key'])
        self.assertEqual(es.aggregate([raw],dict(Q,profile='AION2'),1)['structure_totals']['orders'],1)
        conflict=es.aggregate([xlsx([row('same'),row('same',**{'游戏':'Diablo 4'})])],args,1)
        self.assertEqual(conflict['quality']['ambiguous_orders'],1);self.assertEqual(conflict['structure_totals']['orders'],0)
        with self.assertRaises(ValueError):es.checked_query(dict(args,profile='diablo-ish'))

    def test_one_period_source_future_for_all_profiles_and_no_private_rows_return(self):
        future=Future();submits=[];pool=SimpleNamespace(submit=lambda *a:submits.append(a) or future)
        base=dict(Q,profile='ALL',group_by='game')
        with patch.object(es,'SESSION_JOBS',{}),patch.object(es,'SESSION_POOL',pool),patch.object(es,'archive_files'),patch.object(es,'archived_dataset',return_value=None):
            self.assertEqual(es.session_bundle(None,base,{})['status'],'pending')
            self.assertEqual(es.session_bundle(None,dict(Q,profile='D4'),{})['status'],'pending');self.assertEqual(len(submits),1)
            dataset=es.make_dataset([row('private-order',**{'游戏':'Diablo 4','支付账号':'private-account'})],['f'*64],0,1,0);future.set_result(dataset)
            d4=es.session_bundle(None,dict(Q,profile='D4'),{},True);global_=es.session_bundle(None,base,{},True)
            self.assertEqual(len(submits),1);self.assertEqual(len(d4['snapshots']),1);self.assertEqual(d4['snapshots'][0]['value']['structure_totals']['orders'],1)
            self.assertEqual(global_['snapshots'][0]['query']['profile'],'ALL');self.assertNotIn('private-order',json.dumps(d4));self.assertNotIn('private-account',json.dumps(dataset));self.assertNotIn('_private_dataset',json.dumps(d4))

    def test_legacy_archive_reuse_is_partial_without_fabricating_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private';raw=xlsx([row('d4',**{'游戏':'Diablo 4'})]);es.archive_files([raw],Q,root)
            dataset=es.archived_dataset(dict(Q,profile='ALL'),root)
            value=es.aggregate_rows(dataset['rows'],dataset['hashes'],dataset['parse_failures'],dict(Q,profile='ALL',group_by='game'),dataset['declared_files'],dataset['failed_files'])
            self.assertEqual(value['status'],'partial');self.assertFalse(value['quality']['file_set_complete']);self.assertIsNone(value['quality']['declared_files']);self.assertIsNone(value['quality']['failed_files'])
            with patch.object(es,'SESSION_JOBS',{}),patch.object(es,'archived_dataset',return_value=dataset),patch.object(es,'SESSION_POOL') as pool:
                reply=es.session_bundle(None,dict(Q,profile='D4'),{},True)
                self.assertEqual(reply['status'],'available');pool.submit.assert_not_called()
            manifest=next(root.glob('*.json'));data=json.loads(manifest.read_text());data['file_set']={'declared_files':1,'failed_files':0};manifest.write_text(json.dumps(data));manifest.chmod(0o600)
            dataset=es.archived_dataset(Q,root);self.assertEqual(dataset['declared_files'],1)

    def test_same_bytes_different_period_archive_manifests_do_not_collide(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'private';raw=xlsx([row()]);es.archive_files([raw],Q,root)
            different=dict(Q,start='2026-10-14',end='2026-10-14');es.archive_files([raw],different,root)
            self.assertEqual(len(list(root.glob('*.xlsx'))),1);self.assertEqual(len(list(root.glob('*.json'))),2)
            self.assertIsNotNone(es.archived_dataset(different,root))
        empty=es.aggregate([xlsx([row()])],dict(Q,profile='D4'),1)
        self.assertEqual(empty['structure_totals']['orders'],0);self.assertEqual(empty['structure_totals']['order_amount_usd'],'0')
        unknown=es.aggregate([xlsx([row()])],dict(Q,profile='D4'))
        self.assertIsNone(unknown['structure_totals']['order_amount_usd'])

    def test_source_completed_archive_datasets_can_evict_but_unknown_never_does(self):
        dataset=es.make_dataset([row()],['f'*64],0,None,None)
        jobs={}
        with patch.object(es,'SESSION_JOBS',jobs),patch.object(es,'SESSION_ACCESS',{}),patch.object(es,'archived_dataset',return_value=dataset),patch.object(es,'SESSION_POOL') as pool:
            for day in range(1,7):
                query=dict(Q,start='2026-10-%02d'%day,end='2026-10-%02d'%day)
                self.assertEqual(es.session_bundle(None,query,{},True)['status'],'available')
            self.assertEqual(len(jobs),4);pool.submit.assert_not_called()
        jobs={}
        for day in range(1,5):
            future=Future();future.set_result({'status':'unavailable','retryable':False});jobs[('ALL','2026-10-%02d'%day,'2026-10-%02d'%day)]=(future,es.time.monotonic())
        with patch.object(es,'SESSION_JOBS',jobs),patch.object(es,'archived_dataset') as archived:
            reply=es.session_bundle(None,dict(Q,start='2026-10-08',end='2026-10-08'),{},True)
            self.assertEqual(reply['reason'],'es_source_capacity');archived.assert_not_called()

    def test_completed_projection_lru_survives_more_than_sixteen_queries(self):
        calls=[]
        class Pool:
            def submit(self,reader,args):
                calls.append(args);future=Future();future.set_result({'status':'available','snapshots':[{'query':args,'value':es.aggregate([xlsx([row()])],args,1)}]});return future
        reader=es.ESReader({'enabled':True},Pool())
        for profile in ('FC27','D4','AION2'):
            for group in es.GROUPS:
                value=reader.get(dict(Q,profile=profile,group_by=group));self.assertNotEqual(value['quality'].get('reason'),'es_cache_capacity')
        self.assertEqual(len(calls),21);self.assertEqual(len(reader.jobs),16)
        running=es.ESReader({'enabled':True},SimpleNamespace(submit=lambda *a:Future()))
        for n in range(16):running.get(dict(Q,status='fixture'+str(n)))
        self.assertEqual(running.get(dict(Q,status='seventeenth'))['quality']['reason'],'es_cache_capacity');self.assertEqual(len(running.jobs),16)

    def test_durable_attempt_is_shared_across_profile_and_dimension(self):
        calls=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,*a):return json.dumps({'kind':'es_order_structure_bundle','status':'pending','reason':'es_source_running'}).encode()
        class Opener:
            def open(self,request,**kwargs):calls.append(json.loads(request.data));return Response()
        with tempfile.TemporaryDirectory() as folder:
            es.server_bundle(dict(Q,profile='ALL',group_by='game'),Path(folder),Opener())
            es.server_bundle(dict(Q,profile='D4',group_by='country'),Path(folder),Opener())
            self.assertFalse(calls[0]['poll_only']);self.assertTrue(calls[1]['poll_only']);self.assertEqual(len(list(Path(folder).glob('*.attempt'))),1)

if __name__=='__main__':unittest.main()
