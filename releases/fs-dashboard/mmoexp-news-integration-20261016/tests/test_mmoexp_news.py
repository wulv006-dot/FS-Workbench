"""Bounded synthetic sitemap/articles and local snapshots; never contact a site."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'source'))
import mmoexp_news as news

AT=datetime(2026,10,16,0,5,tzinfo=timezone.utc)
URL='https://www.mmoexp.com/News/fc27-synthetic.html'
QUERY={'profile':'FC27','start':'2026-10-05','end':'2026-10-11'}

def sitemap(rows):
    body=''.join('<url><loc>'+url+'</loc><news:news><news:title>'+title+'</news:title><news:publication_date>'+day+'</news:publication_date></news:news></url>' for url,title,day in rows)
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'+body+'</urlset>').encode()

def html(title='FC27 synthetic update',before=''):
    return (before+'<main><h1>'+title+'</h1><div class="article-body"><p>'+('Synthetic game editorial content with enough readable text. '*5)+'</p><script>private script marker</script></div></main><footer>PoE 2 menu</footer>').encode()

def fetcher(url,deadline):
    if url==news.INDEX:return sitemap([(URL,'FC27 synthetic update','2026-10-10')])
    if url==URL:return html()
    raise AssertionError('Unexpected synthetic URL: '+url)

def versioned(value):
    value=deepcopy(value);value.pop('version',None)
    value['version']='mmoexp-news-'+news.sha256(news.encoded(value)).hexdigest()[:20]
    return value


class NewsCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def snapshot(self):return news.collect(AT,fetcher=fetcher)

    def save(self,value=None):
        value=self.snapshot() if value is None else value
        news.atomic(self.root/'seo-news.json',value)
        return value

    def test_sitemap_parses_dates_deduplicates_and_ignores_unrelated_sites(self):
        rows=news.index_rows(sitemap([(URL,'FC27 synthetic update','2026-10-10T10:00:00Z'),
                                     (URL,'FC27 duplicate','2026-10-11'),
                                     ('https://evil.test/News/fc27.html','FC27 bad','2026-10-12'),
                                     (URL.replace('synthetic','bad-date'),'FC27 bad date','unknown')]))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['published_at'],'2026-10-10')
        self.assertEqual(rows[0]['game_keys'],['ea-sports-fc'])

    def test_xml_entities_and_oversize_index_are_rejected(self):
        for raw in (b'<!DOCTYPE x><urlset/>',b'<!ENTITY secret SYSTEM "file:///secret">',b'x'*(news.MAX_BYTES+1)):
            with self.subTest(raw=raw[:30]),self.assertRaises(ValueError):news.index_rows(raw)

    def test_url_boundary_rejects_non_source_and_control_characters(self):
        self.assertEqual(news.checked_url(URL),URL)
        self.assertEqual(news.checked_url(news.INDEX,index=True),news.INDEX)
        for url in ('http://www.mmoexp.com/News/a.html','https://mmoexp.com/News/a.html',
                    'https://www.mmoexp.com.evil.test/News/a.html','https://user@www.mmoexp.com/News/a.html',
                    'https://www.mmoexp.com:444/News/a.html','https://www.mmoexp.com/News/a.html?q=x',
                    'https://www.mmoexp.com/News/a.html#fragment','https://www.mmoexp.com/News/../a.html',
                    'https://www.mmoexp.com/News/%2e%2e/a.html',URL+'\n',URL+'\t'):
            with self.subTest(url=url),self.assertRaises(ValueError):news.checked_url(url)

    def test_redirect_cannot_escape_news_boundary(self):
        request=news.urllib.request.Request(URL)
        with self.assertRaises(ValueError):news.Redirects().redirect_request(request,None,302,'',{},'https://evil.test/a')

    def test_navigation_game_names_do_not_contaminate_title_or_body(self):
        row=news.index_rows(sitemap([(URL,'FC27 synthetic update','2026-10-10')]))[0]
        before='<nav><h1>PoE 2 menu</h1>Diablo IV menu</nav><aside>NBA 2K</aside>'
        value=news.article(row,html(before=before),AT.isoformat())
        self.assertEqual(value['game_keys'],['ea-sports-fc'])
        self.assertEqual(value['profiles'],['FC27'])
        self.assertNotIn('PoE 2 menu',value['title'])
        self.assertNotIn('private script marker',value['text'])
        self.assertNotIn('PoE 2 menu',value['text'])

    def test_fc26_fc27_profiles_include_hyphenated_titles(self):
        for title,profile in [('FC 26 guide','FC26'),('FC27 guide','FC27'),('EA Sports FC-27 guide','FC27')]:
            with self.subTest(title=title):
                row=dict(source_url=URL,title=title,published_at='2026-10-10',game_keys=['ea-sports-fc'])
                self.assertEqual(news.article(row,html(title),AT.isoformat())['profiles'],[profile])

    def test_poe_and_poe2_are_distinct_and_mismatched_article_is_rejected(self):
        self.assertEqual(news.games('Path of Exile 2 update'),['poe2'])
        self.assertEqual(news.games('PoE 2 update'),['poe2'])
        self.assertEqual(news.games('Path of Exile guide'),['poe1'])
        row=dict(source_url=URL,title='PoE 2',published_at='2026-10-10',game_keys=['poe2'])
        with self.assertRaisesRegex(ValueError,'game_mismatch'):news.article(row,html('Path of Exile guide'),AT.isoformat())

    def test_publication_does_not_create_event_time_or_countdown(self):
        value=self.snapshot();row=value['documents'][0]
        self.assertEqual(row['published_at'],'2026-10-10')
        for field in ('event_date','event_time','timezone'):self.assertIsNone(row[field])
        self.assertEqual(row['source_kind'],'mmoexp_seo')
        self.assertEqual(row['source_label'],news.LABEL)

    def test_collect_is_bounded_and_retains_partial_failure(self):
        rows=[(URL.replace('synthetic',str(i)),'FC27 article '+str(i),'2026-10-10') for i in range(20)]
        calls=[]
        def read(url,deadline):
            calls.append(url)
            if url==news.INDEX:return sitemap(rows)
            if url==rows[0][0]:raise TimeoutError('synthetic timeout')
            return html()
        value=news.collect(AT,fetcher=read)
        self.assertEqual(len(calls),news.MAX_ARTICLES+1)
        self.assertEqual(value['status'],'partial')
        self.assertEqual(len(value['documents']),news.MAX_ARTICLES-1)
        self.assertEqual(value['coverage']['returned_articles'],news.MAX_ARTICLES-1)

    def test_failed_collection_preserves_exact_last_success(self):
        self.save();before=(self.root/'seo-news.json').read_bytes()
        def fail(*args):raise TimeoutError('synthetic source failure')
        value=news.refresh(AT,root=self.root,fetcher=fail)
        self.assertEqual(value['status'],'unavailable')
        self.assertEqual((self.root/'seo-news.json').read_bytes(),before)
        self.assertTrue(json.loads((self.root/'seo-news.status.json').read_bytes())['last_success_preserved'])

    def test_empty_collection_also_keeps_last_success(self):
        self.save();before=(self.root/'seo-news.json').read_bytes()
        value=news.refresh(AT,root=self.root,fetcher=lambda *args:sitemap([]))
        self.assertEqual(value['status'],'empty')
        self.assertEqual((self.root/'seo-news.json').read_bytes(),before)

    def test_atomic_save_is_readable_and_leaves_no_temporary_files(self):
        value=self.save()
        self.assertEqual(news.read_snapshot(self.root,now=AT)['version'],value['version'])
        self.assertEqual(list(self.root.glob('.seo-news-*')),[])

    def test_multibyte_articles_cannot_exceed_the_readers_snapshot_limit(self):
        rows=[(URL.replace('synthetic',str(i)),'FC27 article '+str(i),'2026-10-10') for i in range(news.MAX_ARTICLES)]
        def read(url,deadline):
            if url==news.INDEX:return sitemap(rows)
            return ('<h1>FC27 中文资讯</h1><div class="article-body">'+'中文资讯'*1500+'</div>').encode()
        value=news.collect(AT,fetcher=read)
        self.save(value)
        actual=news.read_snapshot(self.root,now=AT)
        self.assertEqual(actual['version'],value['version'])
        self.assertLessEqual((self.root/'seo-news.json').stat().st_size,160000)
        self.assertGreater(value['coverage']['source_documents_omitted'],0)
        self.assertEqual(value['status'],'partial')

    def test_tampered_snapshot_is_rejected(self):
        value=self.save();value['documents'][0]['text']='tampered'
        (self.root/'seo-news.json').write_bytes(news.encoded(value))
        with self.assertRaisesRegex(ValueError,'snapshot_contract'):news.read_snapshot(self.root,now=AT)

    def test_even_rehashed_wrong_labels_and_event_times_are_rejected(self):
        original=self.snapshot()
        for update in ({'source_kind':'official'},{'source_label':'EA official'},{'event_date':'2026-10-17'},
                       {'event_time':'07:00'},{'timezone':'UTC+08:00'}):
            value=deepcopy(original);value['documents'][0].update(update);self.save(versioned(value))
            with self.subTest(update=update),self.assertRaisesRegex(ValueError,'label_or_time'):news.read_snapshot(self.root,now=AT)

    def test_stale_snapshot_keeps_original_source_timestamp_and_version(self):
        value=self.save();result=news.read_snapshot(self.root,now=AT+timedelta(hours=31))
        self.assertEqual(result['status'],'stale')
        self.assertEqual(result['last_success_status'],'available')
        self.assertEqual(result['collected_at'],value['collected_at'])
        self.assertEqual(result['version'],value['version'])

    def test_shared_read_is_file_only_and_filters_fc26(self):
        value=self.snapshot();fc26=deepcopy(value['documents'][0]);fc26.update(profiles=['FC26'],title='FC26 only')
        value['documents'].append(fc26);value=versioned(value);self.save(value)
        actual=news.read_snapshot
        with patch.object(news,'read_snapshot',side_effect=lambda:actual(self.root,now=AT)),\
             patch.object(news,'fetch',side_effect=AssertionError('Read path must not fetch')),\
             patch.object(news,'collect',side_effect=AssertionError('Read path must not collect')),\
             patch.object(news.urllib.request,'build_opener',side_effect=AssertionError('Read path must not use network')):
            result=news.read_shared(QUERY)
        self.assertEqual(len(result['documents']),1)
        self.assertEqual(result['documents'][0]['profiles'],['FC27'])
        self.assertEqual(result['network_requests'],0)
        self.assertEqual(result['source_kind'],'mmoexp_seo')
        self.assertEqual(result['shared_snapshot_id'],value['version'])

    def test_shared_missing_and_invalid_snapshots_never_become_zero_success(self):
        actual=news.read_snapshot
        with patch.object(news,'read_snapshot',side_effect=lambda:actual(self.root,now=AT)):
            result=news.read_shared(QUERY)
        self.assertEqual(result['status'],'not_available')
        self.assertEqual(result['http_status'],503)
        with patch.object(news,'read_snapshot',side_effect=ValueError('invalid')):
            self.assertEqual(news.read_shared(QUERY)['reason'],'shared_news_snapshot_invalid')

    def test_shared_input_rejects_noncanonical_dates_and_extra_paths(self):
        for update in ({'profile':'FC26'},{'start':'20261005'},{'start':'2026-02-30'},
                       {'end':'2026-01-01'},{'path':'/etc/secret'},{'url':'https://evil.test/'},
                       {'end':'2027-10-11'}):
            with self.subTest(update=update),self.assertRaises((ValueError,TypeError)):news.read_shared({**QUERY,**update})


if __name__=='__main__':unittest.main()
