import ast
import copy
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock
import zipfile
from xml.etree import ElementTree as ET

SOURCE=Path(__file__).resolve().parents[1]/'source'
LEGACY=SOURCE.parents[1]/'fc_reference_weighting_20261024'
if not LEGACY.is_dir():LEGACY=SOURCE.parent
sys.path[:0]=[str(SOURCE),str(LEGACY/'source'),str(LEGACY/'tests')]
import pricing_v2 as pricing
from test_pricing_v2 import fixture,NOW


def function(name,filename,**scope):
    path=SOURCE/filename
    if not path.is_file() and filename=='es_order_structure.py':
        path=SOURCE.parents[2]/'fs-dashboard/fs-business-baseline-20261021/source/hermes/es_order_structure.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),filename,'exec'),scope)
    return scope[name]


class Fallback(unittest.TestCase):
    def previous(self):
        e,rows,_=fixture()
        quotes={p:'.2017' for p in ('PS','XBOX','PC')}
        prior=pricing.apply_decision(rows,e,dict(quotes=quotes),now=NOW)
        e['previous_confirmed_decision']=dict(execution_id='original',receipt=copy.deepcopy(prior))
        for row in e['storefront']['rows'].values():row['package_usd']='20.17'
        return e,rows

    def test_model_failure_preserves_confirmed_choice_when_market_unchanged(self):
        e,rows=self.previous()
        receipt=pricing.apply_decision(rows,e,{},now=NOW)
        for d in receipt['decisions']:
            self.assertEqual(d['model_unavailable_fallback_usd'],'20.17')
            self.assertEqual(d['model_unavailable_fallback_reason'],'unchanged_market_confirmed_price')

    def test_changed_market_can_raise_or_lower_without_model(self):
        for market,expected in (('21','20.99'),('19.5','19.5')):
            e,rows=self.previous()
            for offer in e['offers'].values():offer['Lootbar']['usd_price']=market
            receipt=pricing.apply_decision(rows,e,{},now=NOW)
            for d in receipt['decisions']:
                self.assertEqual(pricing.number(d['model_unavailable_fallback_usd']),pricing.number(expected))
                self.assertEqual(d['model_unavailable_fallback_reason'],'current_weighted_program')

    def test_cost_floor_overrides_unchanged_market_hold(self):
        e,rows=self.previous()
        for c in e['costs'].values():c['cny_per_1k']='2'
        receipt=pricing.apply_decision(rows,e,{},now=NOW)
        for d in receipt['decisions']:
            self.assertGreater(pricing.number(d['model_unavailable_fallback_usd']),pricing.number('20.17'))

    def test_no_confirmed_decision_and_model_choice_do_not_change_program_basis(self):
        e,rows,_=fixture()
        receipt=pricing.apply_decision(rows,e,dict(quotes={p:'.2017' for p in ('PS','XBOX','PC')}),now=NOW)
        for d in receipt['decisions']:
            self.assertEqual(pricing.number(d['model_unavailable_fallback_usd']),pricing.number('19.99'))

    def test_previous_decision_requires_confirmed_sync_public_readback_and_exact_package(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for d in ('jobs','quotes','executions'):(root/d).mkdir()
            e,rows,_=fixture();receipt=pricing.apply_decision(rows,e,{},now=NOW)
            for row in rows:e['storefront']['rows'][row['platform']]['package_usd']=row['target_page_usd']
            audit=dict(execution_id='old',run_id='oldrun',status='CONFIRMED',sync_confirmed=True,created_at=NOW.isoformat())
            (root/'executions/old.json').write_text(json.dumps(audit))
            (root/'quotes/oldrun.json').write_text(json.dumps(dict(evidence=e,result=dict(rows=rows,decision_receipt=receipt))))
            job=root/'jobs/old.json';job.write_text(json.dumps(dict(public_page_readback=dict(status='verified'))))
            read=function('previous_confirmed_decision','server_quote_job.py',ROOT=root,json=json,PLATFORMS=('PS','XBOX','PC'),positive=lambda v,k:pricing.number(v),nonnegative=lambda v,k:pricing.number(v,zero=True))
            self.assertEqual(read('new',e['storefront'])['execution_id'],'old')
            job.write_text('{}');self.assertIsNone(read('new',e['storefront']))
            job.write_text(json.dumps(dict(public_page_readback=dict(status='verified'))))
            e['storefront']['rows']['PC']['bonus_k']='10';self.assertIsNone(read('new',e['storefront']))
            audit['status']='UNKNOWN';(root/'executions/old.json').write_text(json.dumps(audit));self.assertIsNone(read('new',e['storefront']))


class Spreadsheet(unittest.TestCase):
    def reader(self):
        return function('xlsx_rows','es_order_structure.py',MAX_FILE=32*1024*1024,MAX_ROWS=200000,zipfile=zipfile,io=io,ET=ET,re=re,NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'},COLUMNS={'product':'产品类型','game':'游戏'})

    def book(self,sheet,shared=None):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('xl/worksheets/sheet1.xml',sheet)
            if shared:z.writestr('xl/sharedStrings.xml',shared)
        return out.getvalue()

    def test_inline_shared_rich_text_and_empty_rows_are_preserved(self):
        raw=self.book('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row><row><c r="A2" t="inlineStr"><is><r><t>货币</t></r><r><t>(Gold)</t></r></is></c><c r="B2" t="s"><v>2</v></c></row><row/></sheetData></worksheet>','<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>产品类型</t></si><si><t>游戏</t></si><si><r><t>FC </t></r><r><t>27</t></r></si></sst>')
        self.assertEqual(self.reader()(raw),[{'产品类型':'货币(Gold)','游戏':'FC 27'}])

    def test_entities_and_formulas_remain_rejected(self):
        with self.assertRaisesRegex(ValueError,'es_xml_entities'):self.reader()(self.book('<!DOCTYPE worksheet><worksheet/>'))
        with self.assertRaisesRegex(ValueError,'es_formula_cell'):self.reader()(self.book('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>'))

    def test_archive_read_uses_existing_export_lock(self):
        class Lock:
            held=False
            def __enter__(self):self.held=True
            def __exit__(self,*args):self.held=False
        lock=Lock()
        original=Mock(side_effect=lambda *a:self.assertTrue(lock.held))
        f=function('archived_dataset','es_order_structure.py',Path=Path,SERVER_LOCK=lock,_archived_dataset=original)
        f({'start':'old','end':'old'});self.assertEqual(original.call_count,1);self.assertFalse(lock.held)


if __name__=='__main__':unittest.main()
