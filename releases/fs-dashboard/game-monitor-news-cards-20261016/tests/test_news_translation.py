"""Synthetic translation/provider checks; no external requests or real ledger writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('news_translation_candidate', HERE.parent/'source'/'mmoexp_news.py')
news = importlib.util.module_from_spec(spec)
spec.loader.exec_module(news)
AT = datetime(2026, 10, 16, 0, 5, tzinfo=timezone.utc)
GAMES = [('FC27', 'ea-sports-fc'), ('MLB The Show 26', 'mlb-the-show-26'),
         ('NBA 2K27', 'nba-2k'), ('Madden 27', 'madden-nfl'),
         ('College Football 27', 'college-football-27'), ('Diablo IV', 'diablo4'),
         ('Diablo II', 'diablo-2-resurrected'), ('PoE 2', 'poe2'), ('Aion 2', 'aion2')]


def snapshot(count=1):
    docs = []
    for i, (title, key) in enumerate(GAMES[:count]):
        row = dict(document_id=str(i), title=title+' update', summary='Version 1.2 costs 20.5 dollars.',
                   text='Original editorial text '*10, source_url=f'https://www.mmoexp.com/News/synthetic-{i}.html',
                   published_at='2026-10-15', observed_at=AT.isoformat(), game_keys=[key],
                   profiles=['FC27'] if i == 0 else [], source_kind='mmoexp_seo', source_label=news.LABEL,
                   event_date=None, event_time=None, timezone=None)
        row['text_sha256'] = news.sha256(row['text'].encode()).hexdigest()
        docs.append(row)
    value = dict(contract=news.CONTRACT, source_kind='mmoexp_seo', source_label=news.LABEL,
                 status='available', collected_at=AT.isoformat(), stale_after=(AT+timedelta(hours=30)).isoformat(),
                 documents=docs, failures=[], coverage={'returned_articles':count, 'game_keys':[r['game_keys'][0] for r in docs]})
    value['version'] = 'mmoexp-news-'+news.sha256(news.encoded(value)).hexdigest()[:20]
    return value


def projected(value):
    return {'contract':'mmoexp-news-zh-v1', 'articles':[
        {k:r[k] for k in ('document_id','title','summary')} for r in value['documents']]}


def translations(value):
    return [dict(document_id=r['document_id'], title_zh=r['title']+' 中文更新',
                 summary_zh='版本 1.2，价格 20.5 美元。') for r in value['articles']]


def response(rows):
    return {'choices':[{'message':{'content':json.dumps({'articles':rows},ensure_ascii=False)}}],
            'model':'fake-local', 'id':'synthetic-receipt', 'usage':{'total_tokens':123}}


def fake_translation(value, deadline=None):
    return news.validate_translation(response(translations(value)), value)


class NewsTranslationTests(unittest.TestCase):
    def test_month_word_translation_and_omitted_list_number_are_not_new_facts(self):
        value={'articles':[{'document_id':'a','title':'Aion 2 Patch Octombrie 2026','summary':'Energy 20/char.'}]}
        rows=[{'document_id':'a','title_zh':'Aion 2 2026年10月补丁','summary_zh':'能量上限为20/char。'}]
        self.assertEqual(news.validate_translation(response(rows),value)['status'],'succeeded')
        value={'articles':[{'document_id':'a','title':'POE 3.30','summary':'1. Season starts on 11 / 14.'}]}
        rows=[{'document_id':'a','title_zh':'POE 3.30赛季资讯','summary_zh':'赛季预计11月14日开始。'}]
        self.assertEqual(news.validate_translation(response(rows),value)['status'],'succeeded')

    def test_nine_game_categories_translate_and_retain_numbers(self):
        value = snapshot(9)
        for row, (_, key) in zip(value['documents'], GAMES):
            self.assertEqual(news.games(row['title']), [key])
        result = news.validate_translation(response(translations(projected(value))), projected(value))
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(result['articles']), 9)
        self.assertEqual(result['tokens'], 123)
        self.assertEqual(result['articles']['0']['summary_zh'], '版本 1.2，价格 20.5 美元。')

    def test_cfb26_removed_and_poe_versions_stay_distinct(self):
        self.assertEqual(news.games('CFB26 guide'), [])
        self.assertEqual(news.games('College Football 26 guide'), [])
        self.assertEqual(news.games('CFB27 guide'), ['college-football-27'])
        self.assertEqual(news.games('PoE update'), ['poe1'])
        self.assertEqual(news.games('PoE 2 update'), ['poe2'])

    def test_missing_extra_duplicate_unknown_ids_and_extra_fields_rejected(self):
        p = projected(snapshot(2)); rows = translations(p)
        malformed = [rows[:1], rows+[deepcopy(rows[0])], [rows[0], rows[0]],
                     [rows[0], dict(rows[1], document_id='unknown')],
                     [rows[0], dict(rows[1], event_time='made-up')]]
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(ValueError):
                news.validate_translation(response(value), p)

    def test_english_empty_non_string_and_overlong_fields_rejected(self):
        p = projected(snapshot()); base = translations(p)[0]
        for key, value in [('title_zh','English only'), ('summary_zh','English only'),
                           ('title_zh',' '), ('summary_zh',None),
                           ('title_zh','中'*161), ('summary_zh','中'*421)]:
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                news.validate_translation(response([dict(base, **{key:value})]), p)

    def test_numeric_additions_deletions_and_decimal_reordering_rejected(self):
        p = projected(snapshot()); base = translations(p)[0]
        for text in ('版本 1.2，价格 20.5 美元，新增 999。', '版本 1.2，价格 5.20 美元。'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                news.validate_translation(response([dict(base,summary_zh=text)]),p)

    def test_limits_inclusive_and_json_fence_allowed(self):
        p = {'articles':[{'document_id':'one','title':'Update','summary':'Guide'}]}
        raw = response([{'document_id':'one','title_zh':'中'*160,'summary_zh':'文'*420}])
        raw['choices'][0]['message']['content'] = '```json\n'+raw['choices'][0]['message']['content']+'\n```'
        self.assertEqual(news.validate_translation(raw,p)['status'],'succeeded')

    def test_enrichment_preserves_original_fields_and_input(self):
        value=snapshot(9); before=deepcopy(value)
        result=news.enrich_zh(value,translator=fake_translation)
        self.assertEqual(value,before)
        self.assertEqual(result['collected_at'],before['collected_at'])
        for old,new in zip(before['documents'],result['documents']):
            for key,item in old.items():self.assertEqual(new[key],item,key)
            self.assertTrue(new['title_zh']);self.assertTrue(new['summary_zh'])
            self.assertEqual(new['zh_source_sha256'],news.zh_source(old))
        self.assertEqual(result['translation']['translated_articles'],9)

    def test_hash_recomputed_and_read_snapshot_accepts_translation(self):
        value=snapshot(); result=news.enrich_zh(value,translator=fake_translation)
        self.assertNotEqual(result['version'],value['version'])
        with tempfile.TemporaryDirectory() as folder:
            news.atomic(Path(folder)/'seo-news.json',result)
            self.assertEqual(news.read_snapshot(folder,now=AT),result)

    def test_identical_text_reuses_translation_without_another_model_call(self):
        first=news.enrich_zh(snapshot(2),translator=fake_translation)
        current=snapshot(2);current['collected_at']=(AT+timedelta(days=1)).isoformat()
        current['documents'][0]['observed_at']=current['collected_at']
        current['documents'][0]['content_sha256']='changed page layout only'
        translator=Mock(side_effect=AssertionError('must reuse'))
        result=news.enrich_zh(current,previous=first,translator=translator)
        translator.assert_not_called()
        self.assertEqual(result['translation']['status'],'reused')
        self.assertEqual(result['documents'][0]['observed_at'],current['collected_at'])
        self.assertEqual(result['documents'][0]['title_zh'],first['documents'][0]['title_zh'])

    def test_partial_change_only_translates_changed_article(self):
        first=news.enrich_zh(snapshot(2),translator=fake_translation); current=snapshot(2)
        current['documents'][1]['summary']+=' New guide.'
        translator=Mock(side_effect=fake_translation)
        result=news.enrich_zh(current,previous=first,translator=translator)
        self.assertEqual([r['document_id'] for r in translator.call_args.args[0]['articles']],['1'])
        self.assertEqual(result['translation']['translated_articles'],2)

    def test_refresh_reads_shared_previous_and_translates_only_changes(self):
        translator=Mock(side_effect=fake_translation)
        with tempfile.TemporaryDirectory() as folder:
            current=snapshot(2)
            with patch.object(news,'collect',return_value=current):
                news.refresh(AT,root=Path(folder),translator=translator)
                news.refresh(AT,root=Path(folder),translator=translator)
            self.assertEqual(translator.call_count,1)
            current['documents'][1]['title']+=' revised'
            with patch.object(news,'collect',return_value=current):
                result=news.refresh(AT,root=Path(folder),translator=translator)
            self.assertEqual(translator.call_count,2)
            self.assertEqual([r['document_id'] for r in translator.call_args.args[0]['articles']],['1'])
            self.assertEqual(news.read_snapshot(folder,now=AT),result)

    def test_failed_translation_does_not_claim_chinese_or_reuse_old_changed_text(self):
        first=news.enrich_zh(snapshot(2),translator=fake_translation); current=snapshot(2)
        current['documents'][1]['summary']+=' Changed editorial.'
        result=news.enrich_zh(current,previous=first,translator=lambda *_:{'status':'unknown'})
        self.assertEqual(result['status'],'available')
        self.assertEqual(result['translation']['status'],'unknown')
        self.assertEqual(result['translation']['translated_articles'],1)
        self.assertNotIn('title_zh',result['documents'][1])
        self.assertEqual(result['documents'][1]['summary'],current['documents'][1]['summary'])

    def test_translation_exception_keeps_fresh_collected_facts(self):
        for error in (ValueError('bad response'),OSError('provider unavailable'),RuntimeError('ledger unavailable'),ImportError('provider missing')):
            with self.subTest(error=error),tempfile.TemporaryDirectory() as folder:
                previous=snapshot();previous['documents'][0]['title']='FC27 old editorial'
                previous=news.enrich_zh(previous,translator=fake_translation)
                news.atomic(Path(folder)/'seo-news.json',previous)
                current=snapshot();translator=Mock(side_effect=error)
                with patch.object(news,'collect',return_value=current):
                    result=news.refresh(AT,root=Path(folder),translator=translator)
                self.assertEqual(result['status'],'available')
                self.assertEqual(result['translation']['status'],'failed')
                self.assertEqual(result['translation']['translated_articles'],0)
                self.assertEqual(result['collected_at'],AT.isoformat())
                self.assertEqual(result['documents'][0]['title'],current['documents'][0]['title'])
                self.assertNotIn('title_zh',result['documents'][0])
                self.assertEqual(news.read_snapshot(folder,now=AT),result)

    def test_empty_collection_preserves_previous_without_translation(self):
        with tempfile.TemporaryDirectory() as folder:
            previous=news.enrich_zh(snapshot(),translator=fake_translation)
            path=Path(folder)/'seo-news.json';news.atomic(path,previous);before=path.read_bytes()
            empty=snapshot(0);empty['status']='empty';translator=Mock()
            with patch.object(news,'collect',return_value=empty):news.refresh(AT,root=Path(folder),translator=translator)
            self.assertEqual(path.read_bytes(),before);translator.assert_not_called()

    def test_translation_size_cap_remains_readable_and_count_is_accurate(self):
        value=snapshot(9)
        for row in value['documents']:row['text']='原文'*2400
        def large(p,*_):
            rows=translations(p)
            for row in rows:row['summary_zh']+='译'*390
            return news.validate_translation(response(rows),p)
        with patch.object(news,'MAX_SNAPSHOT_BYTES',18000):
            result=news.enrich_zh(value,translator=large)
            self.assertLessEqual(len(news.encoded(result)),18000)
            self.assertEqual(result['status'],'partial')
            self.assertGreater(len(result['documents']),0)
            self.assertEqual(result['translation']['translated_articles'],len(result['documents']))
            self.assertEqual(result['coverage']['returned_articles'],len(result['documents']))
            with tempfile.TemporaryDirectory() as folder:
                news.atomic(Path(folder)/'seo-news.json',result)
                self.assertEqual(news.read_snapshot(folder,now=AT),result)

    def test_translate_reuses_official_provider_and_ledger_with_no_real_network(self):
        p=projected(snapshot());fake=SimpleNamespace()
        fake.request_model=Mock(side_effect=lambda messages,query,validator,**kw:validator(response(translations(query)),query))
        fake.bounded_model=Mock(side_effect=lambda query,callback:callback(query))
        with patch.dict(sys.modules,{'workspace_official_model':fake}),patch.object(news.urllib.request,'build_opener',side_effect=AssertionError('no network')):
            result=news.translate(p)
        fake.bounded_model.assert_called_once();fake.request_model.assert_called_once()
        self.assertEqual(fake.bounded_model.call_args.args[0],p)
        self.assertEqual(fake.request_model.call_args.args[1],p)
        self.assertIs(fake.request_model.call_args.args[2],news.validate_translation)
        self.assertEqual(result['status'],'succeeded')
        messages=fake.request_model.call_args.args[0]
        self.assertIn('不可信网页资料',messages[0]['content'])
        self.assertEqual(json.loads(messages[1]['content']),p)
        self.assertLessEqual(fake.request_model.call_args.kwargs['timeout'],120)

    def test_deadline_skips_provider_call(self):
        fake=SimpleNamespace(bounded_model=Mock(),request_model=Mock())
        with patch.dict(sys.modules,{'workspace_official_model':fake}):
            self.assertEqual(news.translate(projected(snapshot()),datetime.now(timezone.utc)-timedelta(seconds=1)),{'status':'deadline'})
        fake.bounded_model.assert_not_called();fake.request_model.assert_not_called()


if __name__=='__main__':unittest.main()
