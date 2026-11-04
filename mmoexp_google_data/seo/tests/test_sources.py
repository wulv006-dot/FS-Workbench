import unittest
from mmoexp_google_data.seo import sources


class Sources(unittest.TestCase):
    def test_gsc_exact_main_site_and_game_filter(self):
        calls = []
        def request(kind, url, body=None):
            calls.append((kind, url, body))
            return dict(rows=[dict(keys=['2026-11-02'], clicks=2, impressions=10, position=3, ctr=.2)], responseAggregationType='byPage')
        source = sources.GoogleSource('gsc', request, resource='sc-domain:mmoexp.com', timezone='America/Los_Angeles', page_size=10)
        page = next(source.pages('WOW_FOREVER', '2026-11-02'))
        expression = calls[0][2]['dimensionFilterGroups'][0]['filters'][0]['expression']
        import re
        self.assertTrue(re.search(expression, 'https://www.mmoexp.com/Wow-Forever/Gold.html'))
        self.assertFalse(re.search(expression, 'https://satellite.com/Wow-Forever/Gold.html'))
        self.assertFalse(re.search(expression, 'https://www.mmoexp.com/Wow/Gold.html'))
        self.assertEqual(page['source_timezone'], 'America/Los_Angeles')
        self.assertEqual(page['quality']['aggregation'], 'byPage')
        self.assertEqual(page['rows'][0]['metrics']['clicks'], '2')

    def test_ga4_organic_filter_and_actual_timezone(self):
        calls=[]
        def request(kind,url,body=None):
            calls.append((url,body))
            if url.endswith('/metadata'):
                return dict(dimensions=[dict(apiName=x) for x in ('date','hostName','landingPage','sessionDefaultChannelGroup')],
                            metrics=[dict(apiName=x) for x in ('sessions','engagedSessions')])
            if url.endswith(':checkCompatibility'):
                return dict(dimensionCompatibilities=[dict(dimensionMetadata=dict(apiName='date'),compatibility='COMPATIBLE')],
                            metricCompatibilities=[dict(metricMetadata=dict(apiName=x),compatibility='COMPATIBLE') for x in ('sessions','engagedSessions')])
            return dict(dimensionHeaders=[dict(name='date')], metricHeaders=[dict(name='sessions'),dict(name='engagedSessions')],
                        metadata=dict(timeZone='Asia/Shanghai'), rowCount=1,
                        rows=[dict(dimensionValues=[dict(value='20261102')], metricValues=[dict(value='10'),dict(value='4')])])
        page=next(sources.GoogleSource('ga4', request, resource='541418940', timezone='Asia/Shanghai').pages('D4','2026-11-02'))
        self.assertEqual(page['status'],'provisional')
        self.assertIn('Organic Search',str(calls[-1][1]['dimensionFilter']))
        self.assertEqual(page['rows'][0]['metrics']['engagedSessions'],'4')

    def test_empty_rows_remain_missing(self):
        page=next(sources.GoogleSource('gsc',lambda *a,**k: {},resource='sc-domain:mmoexp.com',timezone='America/Los_Angeles').pages('FC27','2026-11-02'))
        self.assertEqual(page['status'],'no_rows')
        self.assertEqual(page['rows'],[])

    def test_wrong_response_date_rejected(self):
        source=sources.GoogleSource('gsc',lambda *a,**k:dict(rows=[dict(keys=['2020-01-01'],clicks=1,impressions=2,position=3)]),resource='sc-domain:mmoexp.com',timezone='America/Los_Angeles')
        with self.assertRaises(ValueError):next(source.pages('FC27','2026-11-02'))

    def test_uses_shared_identity_without_weekly_request_hard_cap(self):
        source=sources.GoogleSource('gsc',lambda *a,**k: {},resource='sc-domain:mmoexp.com',timezone='America/Los_Angeles')
        for n in range(201):
            next(source.pages('FC27','2026-11-02'))

    def test_game_binding_is_strict(self):
        with self.assertRaises(ValueError):sources.path_expression('WOW')

    def test_malformed_google_payload_is_a_source_failure(self):
        source=sources.GoogleSource('gsc',lambda *a,**k:dict(rows=[dict(keys=['2026-11-02'])]),resource='sc-domain:mmoexp.com',timezone='America/Los_Angeles')
        with self.assertRaises(sources.SourceError):next(source.pages('FC27','2026-11-02'))


if __name__=='__main__':unittest.main()
