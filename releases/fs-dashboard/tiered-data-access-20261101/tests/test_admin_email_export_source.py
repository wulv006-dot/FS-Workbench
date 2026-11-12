import datetime
import hashlib
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'source'))
import admin_email_export_source as source
import admin_email_export_worker as worker
import admin_order_email_export as export

NOW = lambda: '2026-11-11T12:00:00+08:00'

class ExportSourceTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(activation_status='W0_verified', live_admin_single_page=True,
                           sites={'267': {}}, projects={'2': {}})
        self.calls = []
        self.allowed = True
        self.request = dict(site_id='267', game_id='2', start='2026-10-01', end_exclusive='2026-10-02',
                            filters={k: ('US' if k == 'country' else 'x' if k in ('content', 'discount_code') else '0') for k in source.FILTERS})
        def fetch(path, params, timeout, cap):
            self.calls.append(params)
            rows = [dict(id=i, site_id=267, gid=2, paytime='2026-10-01 12:00:00', status='11', email='Example@example.test') for i in (range(21, 1, -1) if params['page'] == 1 else [1])]
            return 200, json.dumps(dict(code=1, data=dict(total=21, list=rows))).encode()
        self.deps = dict(load_config=lambda: self.config, load_policy=lambda: {},
                         rbac=types.SimpleNamespace(validate=lambda p: p), authorize=lambda *a: self.allowed,
                         fetch=fetch)
        self.handler = source.build_handler(**self.deps, run_source=lambda op, timeout: op(), observed_at=NOW)
    def call(self, request=None, user='actor'):
        return self.handler({k: [v] for k, v in (request or self.request).items()}, user)
    def test_all_fourteen_terms_and_date_semantics(self):
        status, result = self.call()
        self.assertEqual(status, 206)
        params = self.calls[0]
        fields = {params['search[%d][field]' % i]: (params['search[%d][operator]' % i], params['search[%d][val]' % i]) for i in range(14)}
        self.assertEqual(len(fields), 14)
        for key, operator in source.FILTERS.items():
            self.assertEqual(fields[key], (operator, self.request['filters'][key]))
        self.assertEqual(fields['paytime'], ('RANGE', '2026-10-01 00:00:00,2026-10-01 23:59:59'))
        self.assertEqual(params['search[2][render]'], 'datetime')
        self.assertEqual(params['limit'], 20)
        self.assertEqual(result['data'][0]['customer_email'], 'Example@example.test')
        with patch.dict(sys.modules, user_runtime=types.SimpleNamespace(authorize=lambda *a: True)), patch.object(source, 'get', lambda q, u, **kw: self.handler(q, u)):
            response = export.page_get(self.request, 'actor', run_source=lambda op, t: op())
        self.assertEqual(response[0], 206)
        self.assertEqual(response[1]['filters'], self.request['filters'])
    def test_empty_filters_leave_admin_defaults(self):
        status, result = self.call(dict(self.request, filters={}))
        self.assertEqual(status, 206)
        params = self.calls[0]
        fields = [value for key, value in params.items() if key.endswith('[field]')]
        self.assertEqual(fields, ['site_id', 'gid', 'paytime'])
        self.assertFalse(set(fields) & {'progress', 'status', 'cid', 'aid'})

    def test_cursor_binds_every_filter_scope_actor_and_date(self):
        cursor = self.call()[1]['next_cursor']
        for key in source.FILTERS:
            filters = dict(self.request['filters'], **{key: '1' if key in source.NUMERIC else 'changed'})
            self.assertEqual(self.call(dict(self.request, filters=filters, cursor=cursor))[0], 422)
        self.assertEqual(self.call(dict(self.request, cursor=cursor), user='other')[0], 422)
        self.assertEqual(self.call(dict(self.request, cursor=cursor, start='2026-09-30'))[0], 422)
        status, last = self.call(dict(self.request, cursor=cursor))
        self.assertEqual(status, 206)
        self.assertIsNone(last['next_cursor'])
    def test_private_selection_and_revocation(self):
        self.config['sites'] = {'266': {}}
        self.config['projects'] = {}
        self.assertEqual(self.call()[0], 206)
        self.calls.clear()
        self.allowed = False
        self.assertEqual(self.call()[0], 403)
        self.assertEqual(self.calls, [])
    def test_body_validation_and_serial_aggregate_filters(self):
        self.assertEqual(export.parse_page_body(json.dumps(self.request).encode(), observed_at=NOW), self.request)
        seen = []
        def page(query, actor):
            seen.append(query)
            return 206, dict(semantics='live_non_snapshot', limitation='live_pagination_not_snapshot', source_reported_total=0, data=[], next_cursor=None)
        request = dict(self.request)
        del request['game_id']
        request['game_ids'] = ['2', '3']
        request['end_exclusive'] = '2026-11-02'
        status, payload = export.collect(request, 'actor', page_get=page, observed_at=NOW)
        self.assertEqual(status, 200)
        self.assertEqual(payload['filters'], self.request['filters'])
        self.assertEqual(len(seen), 4)
        self.assertTrue(all(q['filters'] == [self.request['filters']] for q in seen))
        for filters in ({'paytime': 'x'}, {'country': 1}, {'content': '\n'}, {'status': 'paid'}):
            with self.assertRaises(ValueError):
                source.validate_filters(filters)
    def test_metadata_allowlist_permission_and_admission(self):
        calls = []
        deps = dict(self.deps, fetch=lambda p, q, t, c: (calls.append(q) or (200, b'{"code":1,"data":{"list":[],"total":0}}')))
        for name, (_, keys) in source.METADATA.items():
            args = {k: '8,11' if name == 'admins' else '2' for k in keys}
            request = dict(site_id='267', directory=name, arguments=args)
            self.assertEqual(source.metadata_get(request, 'actor', deps=deps, run_source=lambda op, t: op())[0], 200)
        self.assertEqual(len(calls), 8)
        self.allowed = False
        self.assertEqual(source.metadata_get(dict(site_id='267', directory='sites'), 'actor', deps=deps, run_source=lambda op,t: op())[0], 403)
        self.assertEqual(source.metadata_get(dict(site_id='267', directory='/write'), 'actor', deps=deps, run_source=lambda op,t: op())[0], 422)
    def test_worker_real_protocol_with_fake_session_no_network(self):
        import base64
        from urllib.parse import urlsplit, parse_qs
        calls = []
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, cap): return b'{"code":1,"data":{"list":[],"total":0}}'
        def open_request(request, timeout):
            calls.append((request, timeout))
            return Response()
        shared = types.SimpleNamespace(SessionManager=lambda config: types.SimpleNamespace(config={}, opener=types.SimpleNamespace(open=open_request)),
            api_base=lambda config: 'http://127.0.0.1:8912', API_BASES=['http://127.0.0.1:8912'], HEADERS={})
        params = source.source_params(self.request, 1, NOW)
        envelope = dict(path='/admin/order.Order/index', params=params, max_bytes=1024)
        result = worker.handle(envelope, loader=lambda: shared, today=lambda: datetime.date(2026, 11, 11))
        self.assertEqual(result['status'], 200)
        self.assertIn(b'"code":1', base64.b64decode(result['body']))
        request, timeout = calls[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(timeout, 10)
        query = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(query['search[0][val]'], ['267'])
        self.assertEqual(len([key for key in query if key.endswith('[field]')]), 14)
        with self.assertRaises(ValueError):
            worker.handle(envelope, loader=lambda: self.fail(), today=lambda: datetime.date(2027, 11, 11))
        for name, (path, keys) in source.METADATA.items():
            args = {key: '8,11' if name == 'admins' else '2' for key in keys}
            worker.handle(dict(envelope, params={'metadata': name, 'arguments': args, 'page': 1}), loader=lambda: shared)
            self.assertEqual(urlsplit(calls[-1][0].full_url).path, path)
            query = parse_qs(urlsplit(calls[-1][0].full_url).query, keep_blank_values=True)
            self.assertEqual(query['select'], ['true'])
            self.assertEqual(query['quick_search'], [''])
            self.assertEqual(query['page'], ['1'])
            self.assertEqual(query['initKey'], [{'status': 'status', 'countries': 'country'}.get(name, 'id')])
            self.assertEqual(query['initValue'], [''])
            for key, value in args.items():
                self.assertEqual(query[key], [value])
        for params in ({'metadata': '/admin/write', 'arguments': {}}, {'metadata': 'admins', 'arguments': {'gid': '1'}}):
            with self.assertRaises(ValueError):
                worker.handle(dict(envelope, params=params), loader=lambda: self.fail())

    def test_options_dependencies_permissions_and_pagination(self):
        self.config['sites']['999'] = {}
        self.config['projects']['3'] = {}
        self.deps['authorize'] = lambda user, scope, private: (scope.get('scope') == 'all' or scope.get('scope_id') == '267') and self.allowed and private
        calls = []
        rows = {
            'sites': [{'id': 267, 'full_title': 'Site'}, {'id': 999, 'full_title': 'Denied'}],
            'games': [{'id': 2, 'title': 'Game'}, {'id': 3, 'title': 'Other'}, {'id': 99, 'title': 'Unconfigured'}],
            'progress': [{'id': 1, 'title': 'Paid'}, {'id': '7', 'title': 'Refunding'}],
            'status': [{'status': 71, 'title': 'Review'}, {'status': '72', 'title': 'Returned'}],
            'types': [{'id': 0, 'title': 'Items'}, {'id': '42', 'title': 'New type'}],
            'admins': [{'id': 8, 'nickname': 'Operator'}],
            'countries': [{'country': 'United States', 'code': 'US'}]}
        def fetch(path, query, timeout, cap):
            calls.append(query)
            name = query['metadata']
            data = rows[name] if name in rows else [{'id': 10, 'title': 'Common'}, {'id': int(query['arguments']['gid']) + 20, 'title': 'Server'}]
            offset = query['page'] - 1
            return 200, json.dumps({'code': 1, 'data': {'options': data[offset:offset+1], 'total': len(data)}}).encode()
        self.deps['fetch'] = fetch
        def call(request, actor='actor'):
            return source.options_get(request, actor, deps=self.deps, run_source=lambda op, t: op())
        status, result = call({'progress': '7', 'game_ids': ['2', '3']})
        self.assertEqual(status, 200)
        options = result['options']
        self.assertEqual(set(options), {'sites', 'games', 'progress', 'status', 'cid', 'aid', 'admin_id', 'country'})
        self.assertEqual(options['sites'], [{'value': '267', 'label': '267 | Site'}])
        self.assertEqual([g['value'] for g in options['games']], ['2', '3', '99'])
        self.assertEqual([o['value'] for o in options['progress']], ['1', '7'])
        self.assertEqual([o['value'] for o in options['status']], ['71', '72'])
        self.assertEqual([o['value'] for o in options['cid']], ['0', '42'])
        self.assertEqual(options['aid'], [{'value': '10', 'label': 'Common'}])
        self.assertNotIn('unavailable', result)
        self.assertTrue(all(q['arguments'] == {'id': '7'} for q in calls if q['metadata'] == 'status'))
        self.assertEqual({q['arguments']['gid'] for q in calls if q['metadata'] == 'servers'}, {'2', '3'})
        self.assertTrue(all(q['arguments'] == {} for q in calls if q['metadata'] == 'types'))
        self.assertEqual([o['value'] for o in call({'game_ids': ['2']})[1]['options']['aid']], ['10', '22'])
        rows['servers'] = []
        self.assertEqual(call({'game_ids': ['2', '3']})[1]['options']['aid'], [])
        del rows['servers']
        self.assertTrue(all(set(o) == {'value', 'label'} and all(isinstance(v, str) for v in o.values()) for items in options.values() for o in items))
        self.assertTrue(any(q['page'] == 3 for q in calls))
        self.assertEqual(options['admin_id'], [])
        self.assertEqual(options['country'], [{'value': 'United States', 'label': 'US | United States'}])
        self.assertEqual(options['games'][0], {'value': '2', 'label': '2 | Game'})
        self.assertEqual({q['metadata'] for q in calls}, {'sites', 'games', 'countries', 'progress', 'status', 'types', 'servers'})
        calls.clear()
        status, initial = call({})
        self.assertEqual(status, 200)
        self.assertEqual(initial['options']['status'], [])
        self.assertEqual(initial['options']['cid'], [])
        self.assertEqual(initial['options']['aid'], [])
        self.assertNotIn('unavailable', initial)
        self.assertEqual({q['metadata'] for q in calls}, {'sites', 'games', 'countries', 'progress'})
        calls.clear()
        self.assertEqual(call({'progress': ''})[1]['options']['status'], [])
        self.assertFalse(any(q['metadata'] == 'status' for q in calls))
        calls.clear()
        self.assertEqual(call({'progress': '2'})[0], 422)
        self.assertFalse(any(q['metadata'] == 'status' for q in calls))
        calls.clear()
        self.assertEqual(call({'progress': '1'})[0], 200)
        self.assertEqual({q['metadata'] for q in calls}, {'sites', 'games', 'countries', 'progress', 'status'})
        for invalid in ({'progress': 1}, {'progress': '1' * 21}, {'progress': '１'},
                        {'game_ids': '2'}, {'game_ids': ['2', '2']}, {'game_ids': ['bad']},
                        {'game_ids': ['2'] * 101}, {'unknown': ''}):
            calls.clear()
            self.assertEqual(call(invalid)[0], 422)
            self.assertEqual(calls, [])
        self.assertEqual(call({'game_ids': ['99']})[0], 200)
        self.assertEqual(call({'game_ids': ['100']})[0], 403)
        self.assertEqual(call({'progress': 'bad'})[0], 422)
        self.assertEqual(call({}, actor=None)[0], 401)
        self.allowed = False
        calls.clear()
        self.assertEqual(call({})[0], 403)
        self.assertEqual(calls, [])

    def test_native_progress_dict_and_optional_server_refusal(self):
        rows = {'sites': [{'id': 267, 'full_title': 'Site'}],
                'games': [{'id': 1327, 'title': 'Game'}],
                'progress': {'0': {'title': '未支付', 'status': [0, 0], 'id': 0},
                             '1': {'title': '已支付', 'status': [10, 19], 'id': 1}},
                'status': [{'status': 11, 'progress': 1, 'title': 'Paid', 'color': '', 'en': '', 'logo': ''}],
                'types': [{'id': 0, 'title': 'Items', 'code': 'items'}],
                'servers': [{'id': 10, 'gid': 1327, 'title': 'Server', 'code': 's', 'sort': 0}],
                'countries': [{'country': 'US', 'code': 1}]}
        calls = []
        def fetch(path, query, timeout, cap):
            calls.append(query)
            return 200, json.dumps({'code': 1, 'data': {'list': rows[query['metadata']]}}).encode()
        self.deps['fetch'] = fetch
        def call(request=None):
            return source.options_get(request or {}, 'actor', deps=self.deps, run_source=lambda op,t: op())
        status, initial = call()
        self.assertEqual(status, 200)
        self.assertEqual(initial['options']['progress'][0], {'value': '0', 'label': '0 | 未支付'})
        for key in ('status', 'cid', 'aid', 'admin_id'):
            self.assertEqual(initial['options'][key], [])
        self.assertEqual({q['metadata'] for q in calls}, {'sites', 'games', 'progress', 'countries'})
        status, result = call({'progress': '1', 'game_ids': ['1327']})
        self.assertEqual(status, 200)
        self.assertEqual(result['options']['status'], [{'value': '11', 'label': '11 | Paid'}])
        self.assertEqual(result['options']['aid'], [{'value': '10', 'label': 'Server'}])
        self.assertIn({'id': '1'}, [q['arguments'] for q in calls if q['metadata'] == 'status'])
        calls.clear()
        self.assertEqual(call({'progress': '0'})[0], 200)
        self.assertEqual([q['arguments'] for q in calls if q['metadata'] == 'status'], [{'id': '0'}])
        for mandatory in ('sites', 'games', 'countries', 'progress', 'status', 'types', 'servers'):
            for refusal in ((401, b'{}'), (200, b'{"code":401,"msg":"You have no permission"}')):
                def fail_required(path, query, timeout, cap):
                    if query['metadata'] == mandatory:
                        return refusal
                    return fetch(path, query, timeout, cap)
                self.deps['fetch'] = fail_required
                status, payload = call({'progress': '1', 'game_ids': ['1327']})
                with self.subTest(directory=mandatory, refusal=refusal):
                    if mandatory == 'servers':
                        self.assertEqual(status, 200)
                        self.assertEqual(payload['options']['aid'], [])
                        self.assertEqual(payload['unavailable'], {'aid': 'metadata_source_unavailable'})
                    else:
                        self.assertEqual((status, payload), (503, {'error': 'metadata_source_unavailable', 'complete': False}))

    def test_progress_dict_rejects_invalid_keys_rows_duplicates_and_totals(self):
        good = {'0': {'title': '未支付', 'status': [0, 0], 'id': 0}}
        def read(raw):
            return source.directory_read('progress', {}, deps=dict(self.deps, fetch=lambda *a: (200, raw)),
                run_source=lambda op,t: op(), check=lambda: 'epoch', epoch='epoch')
        self.assertEqual(read(json.dumps({'code': 1, 'data': {'list': good, 'total': 1}}).encode()), list(good.values()))
        invalid = [{'x': good['0']}, {'00': good['0']}, {'１': good['0']},
                   {'1': good['0']}, {'0': None}, {'0': dict(good['0'], id=True)},
                   {'0': dict(good['0'], id='0')}, {'0': dict(good['0'], title='')},
                   {'0': dict(good['0'], status=[0])}, {'0': dict(good['0'], status=[False, 0])}]
        for batch in invalid:
            with self.subTest(batch=batch), self.assertRaises(RuntimeError):
                read(json.dumps({'code': 1, 'data': {'list': batch}}).encode())
        for total in (0, 2, True):
            with self.subTest(total=total), self.assertRaises(RuntimeError):
                read(json.dumps({'code': 1, 'data': {'list': good, 'total': total}}).encode())
        with self.assertRaises(RuntimeError):
            read(b'{"code":1,"data":{"options":[{"id":0},{"id":0}],"total":2}}')
        with self.assertRaises(RuntimeError):
            read(b'{"code":1,"data":{"list":{"0":{"id":0},"0":{"id":0}}}}')

    def test_options_fail_closed_on_partial_schema_and_revocation(self):
        for data in ({'options': []}, {'options': [], 'total': 1}, {'options': [{'id': 267, 'full_title': 'Site'}], 'total': 2}):
            calls = []
            def fetch(*args):
                calls.append(args)
                return 200, json.dumps({'code': 1, 'data': data}).encode()
            self.deps['fetch'] = fetch
            self.assertEqual(source.options_get({}, 'actor', deps=self.deps, run_source=lambda op,t: op())[0], 503)
            self.assertLessEqual(len(calls), 2)
        def revoke(op, timeout):
            self.allowed = False
            return op()
        self.allowed = True
        self.assertEqual(source.options_get({}, 'actor', deps=self.deps, run_source=revoke)[0], 403)

    def test_country_phone_variants_preserve_coverage_and_deduplicate_options(self):
        countries = [{'country': 'Dominican Republic', 'code': code, 'iso_code': 'DO / DOM'}
                     for code in ('1-809', '1-829', '1-849')]
        countries += [{'country': 'Puerto Rico', 'code': code, 'iso_code': 'PR / PRI'}
                      for code in ('1-787', '1-939')]
        rows = {'sites': [{'id': 266, 'full_title': 'Site'}],
                'games': [{'id': 2, 'title': 'Game'}], 'progress': [{'id': 1, 'title': 'Paid'}], 'countries': countries}
        for with_total in (False, True):
            def fetch(path, query, timeout, cap):
                batch = rows[query['metadata']]
                data = {'list': batch}
                if with_total:
                    data['total'] = len(batch)
                return 200, json.dumps({'code': 1, 'data': data}).encode()
            self.deps['fetch'] = fetch
            status, payload = source.options_get({}, 'actor', deps=self.deps, run_source=lambda op,t: op())
            self.assertEqual(status, 200)
            self.assertEqual(payload['options']['country'], [
                {'value': 'Dominican Republic', 'label': '1-849 | Dominican Republic'},
                {'value': 'Puerto Rico', 'label': '1-939 | Puerto Rico'}])
        countries.append(dict(countries[0]))
        self.assertEqual(source.options_get({}, 'actor', deps=self.deps, run_source=lambda op,t: op())[0], 503)
        countries.pop()
        rows['games'].append(dict(rows['games'][0]))
        self.assertEqual(source.options_get({}, 'actor', deps=self.deps, run_source=lambda op,t: op())[0], 503)

    def test_options_retained_fields_fail_closed_and_epoch_covers_directories(self):
        rows = {'sites': [{'id': 267, 'full_title': 'Site'}],
                'games': [{'id': 2, 'title': 'Game'}],
                'progress': [{'id': 0, 'title': 'Unpaid'}],
                'status': [{'status': 0, 'title': 'Pending'}],
                'types': [{'id': 0, 'title': 'Items'}],
                'countries': [{'country': 'China', 'code': 86}],
                'servers': []}
        calls = []
        def fetch(path, query, timeout, cap):
            calls.append(query)
            return 200, json.dumps({'code': 1, 'data': {'list': rows[query['metadata']]}}).encode()
        self.deps['fetch'] = fetch
        def call():
            return source.options_get({'progress': '0', 'game_ids': ['2']}, 'actor', deps=self.deps, run_source=lambda op,t: op())
        status, result = call()
        self.assertEqual(status, 200)
        self.assertEqual(result['options']['country'], [{'value': 'China', 'label': '86 | China'}])
        self.assertEqual({q['metadata'] for q in calls}, {'sites', 'games', 'countries', 'progress', 'status', 'types', 'servers'})
        rows['servers'] = [{'id': 10, 'title': 'Server'}]
        for name, field, invalid in (('sites', 'full_title', None), ('games', 'title', ''),
                                     ('games', 'title', 42), ('countries', 'code', None),
                                     ('countries', 'code', True), ('progress', 'title', ''),
                                     ('status', 'title', None), ('types', 'title', ''),
                                     ('servers', 'id', 'not-a-number'), ('servers', 'title', '')):
            original = rows[name][0].copy()
            rows[name][0][field] = invalid
            with self.subTest(directory=name, field=field, invalid=invalid):
                self.assertEqual(call()[0], 503)
            rows[name][0] = original
        for directory in ('sites', 'games', 'countries', 'progress', 'status', 'types', 'servers'):
            def revoke(path, query, timeout, cap):
                result = fetch(path, query, timeout, cap)
                if query['metadata'] == directory:
                    self.config['epoch'] = directory
                return result
            self.deps['fetch'] = revoke
            with self.subTest(revoke_directory=directory):
                self.assertEqual(call()[0], 403)

    def test_directory_list_pagination_stability_and_budget(self):
        def read(fetch):
            return source.directory_read('games', {}, deps=dict(self.deps, fetch=fetch), run_source=lambda op,t: op(), check=lambda: 'epoch', epoch='epoch')
        def response(page, total):
            return 200, json.dumps({'code': 1, 'data': {'list': [{'id': page, 'title': 'Game'}], 'total': total}}).encode()
        self.assertEqual(len(read(lambda p,q,t,c: response(q['page'], 3))), 3)
        self.assertEqual(read(lambda *a: (200, b'{"code":1,"data":{"list":[{"id":1,"title":"Game"}]}}')), [{'id': 1, 'title': 'Game'}])
        with self.assertRaisesRegex(RuntimeError, 'metadata_source_changed'):
            read(lambda p,q,t,c: response(q['page'], q['page'] + 1))
        calls = []
        def endless(p,q,t,c):
            calls.append(q)
            return response(q['page'], 101)
        with self.assertRaisesRegex(RuntimeError, 'metadata_coverage_incomplete'):
            read(endless)
        self.assertEqual(len(calls), 100)
        for result in ((500, b'{}'), (200, b'not json'), (200, b'{"code":0}')):
            with self.assertRaises(RuntimeError):
                read(lambda *args: result)
        self.assertEqual(source.options_get({}, 'actor')[0], 503)

    def test_worker_rejects_mutation_before_session_and_hash_pinned(self):
        params = source.source_params(self.request, 1, NOW)
        for changes in ({'limit': 21}, {'search[0][operator]': 'LIKE'}, {'search[14][field]': 'write'}):
            with self.assertRaises(ValueError):
                worker.handle(dict(path='/admin/order.Order/index', params=dict(params, **changes), max_bytes=100), loader=lambda: self.fail())
        self.assertEqual(hashlib.sha256(pathlib.Path(worker.__file__).read_bytes()).hexdigest(), source.WORKER_SHA256)

if __name__ == '__main__':
    unittest.main()
