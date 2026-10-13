"""Offline contract tests; never call a model or touch existing credential files."""
import copy
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fc_daily_model import MODEL
from boss_insights import build_messages, project_context, validate_response, management_analysis, MANAGEMENT_REVISION


def management():
    return {'scope': 'management', 'request_id': 'request_1234', 'context': {
        'period': {'start': '2026-10-01', 'end': '2026-10-13'},
        'projects': [{'key': 'fc', 'revenue_usd': 123.45, 'orders': 10,
                      'estimated_profit_usd': -12.34, 'target_revenue_usd': 500,
                      'missing': []}]}}


def game():
    return {'scope': 'game-monitor', 'request_id': 'request_5678', 'context': {'events': [
        {'game': 'FC', 'title': '公开版本更新', 'date': '2026-10-13',
         'source_url': 'https://www.ea.com/games/ea-sports-fc/news'}]}}


class ProjectionTests(unittest.TestCase):
    def test_real_catalog_uppercase_keys(self):
        for key in ('FC27', 'NBA2K27', 'DARK_AND_DARKER'):
            body = management()
            body['context']['projects'][0]['key'] = key
            self.assertEqual(project_context(body)['context']['projects'][0]['key'], key)

    def test_management_aggregate_only_and_snapshot(self):
        body = management()
        projected = project_context(body)
        self.assertEqual(set(projected), {'scope', 'context', 'analysis_revision'})
        self.assertNotIn('request_id', json.dumps(projected))
        body['context']['projects'][0]['orders'] = 42
        self.assertEqual(projected['context']['projects'][0]['orders'], 10)

    def test_game_projection_and_prompt(self):
        body = game()
        self.assertEqual(project_context(body)['context'], body['context'])
        messages = build_messages(body)
        self.assertEqual([item['role'] for item in messages], ['system', 'user'])
        self.assertEqual(json.loads(messages[1]['content']), project_context(body))
        self.assertIn('没有联网检索能力', messages[0]['content'])

    def test_missing_is_explicit(self):
        body = management()
        row = body['context']['projects'][0]
        row['estimated_profit_usd'] = None
        with self.assertRaises(ValueError):
            project_context(body)
        row['missing'] = ['estimated_profit_usd']
        self.assertIsNone(project_context(body)['context']['projects'][0]['estimated_profit_usd'])
        row['estimated_profit_usd'] = 0
        with self.assertRaises(ValueError):
            project_context(body)

    def test_rejects_nonfinite_bool_negative_sales_fractional_orders(self):
        for metric, value in [('revenue_usd', float('nan')), ('revenue_usd', float('inf')),
                              ('revenue_usd', -1), ('orders', 1.5), ('orders', True),
                              ('orders', -1), ('orders', 10 ** 400), ('target_revenue_usd', '500')]:
            with self.subTest(metric=metric, value_type=type(value).__name__):
                body = management()
                body['context']['projects'][0][metric] = value
                with self.assertRaises(ValueError):
                    project_context(body)

    def test_rejects_unknown_and_sensitive_fields_at_every_level(self):
        for extra in ['owner', 'customer', 'email', 'raw_orders', 'notes', 'api_key']:
            for level in ['root', 'context', 'row']:
                body = management()
                target = body if level == 'root' else body['context'] if level == 'context' else body['context']['projects'][0]
                target[extra] = 'do-not-forward'
                with self.subTest(extra=extra, level=level), self.assertRaises(ValueError):
                    build_messages(body)
        body = game()
        body['context']['events'][0]['notes'] = 'do-not-forward'
        with self.assertRaises(ValueError):
            project_context(body)

    def test_rejects_sensitive_public_text(self):
        for text in ['sk-example-secret', 'Bearer credential', 'customer@example.com', '负责人张三', '客户资料', 'API_KEY=placeholder']:
            for field in ['game', 'title']:
                body = game()
                body['context']['events'][0][field] = text
                with self.subTest(field=field), self.assertRaises(ValueError):
                    project_context(body)

    def test_rejects_nonpublic_or_credential_urls(self):
        for url in ['http://www.ea.com/a', 'https://user:pass@www.ea.com/a',
                    'https://127.0.0.1/a', 'https://localhost/a', 'https://host.internal/a',
                    'https://www.ea.com/a?token=hidden', 'https://www.ea.com/a?x=1',
                    'https://www.ea.com:8443/a', 'https://www.ea.com/a#private']:
            body = game()
            body['context']['events'][0]['source_url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                project_context(body)

    def test_rejects_invalid_dates_and_order(self):
        for value in ['2026-02-30', '20261013', '2026-1-2', '', False, 0, [], {}]:
            body = game()
            body['context']['events'][0]['date'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                project_context(body)
        body = management()
        body['context']['period']['start'] = '2026-10-14'
        with self.assertRaises(ValueError):
            project_context(body)

    def test_unknown_game_date_keeps_null_and_forbids_inference_in_prompt(self):
        body = game()
        body['context']['events'][0]['date'] = None
        projected = project_context(body)
        self.assertIsNone(projected['context']['events'][0]['date'])
        messages = build_messages(body)
        self.assertIsNone(json.loads(messages[1]['content'])['context']['events'][0]['date'])
        self.assertIn('date为null表示日期未知', messages[0]['content'])
        self.assertIn('不得推断上线日期、已上线、即将上线或倒计时', messages[0]['content'])
        self.assertEqual(validate_response(response(), projected)['status'], 'succeeded')
        for key in ('start', 'end'):
            business = management()
            business['context']['period'][key] = None
            with self.assertRaises(ValueError): project_context(business)

    def test_rejects_empty_oversized_lists_duplicate_projects(self):
        for body, field, count in [(game(), 'events', 0), (game(), 'events', 16),
                                   (management(), 'projects', 0), (management(), 'projects', 21),
                                   (management(), 'projects', 2)]:
            body['context'][field] *= count
            with self.subTest(field=field, count=count), self.assertRaises(ValueError):
                project_context(body)

    def test_rejects_identifier_and_scope_changes(self):
        for field, value in [('scope', 'admin'), ('request_id', '../request'),
                             ('request_id', ''), ('request_id', 'a' * 81)]:
            body = management()
            body[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                project_context(body)
        for key in ['FC!', '张三', 'customer@example.com', 'api_key', 'fc/../raw']:
            body = management()
            body['context']['projects'][0]['key'] = key
            with self.subTest(key=key), self.assertRaises(ValueError):
                project_context(body)

    def test_rejects_missing_types_duplicates_and_unlisted_metrics(self):
        for missing in ['orders', ['raw_orders'], ['orders', 'orders'], [None]]:
            body = management()
            body['context']['projects'][0]['missing'] = missing
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                project_context(body)

    def test_deterministic_projection_for_shared_dedupe(self):
        body = management()
        other = copy.deepcopy(body)
        other['request_id'] = 'different_1234'
        self.assertEqual(project_context(body), project_context(other))
        self.assertEqual(build_messages(body), build_messages(other))

    def test_context_utf8_limit_is_16_kib(self):
        body = game()
        event = body['context']['events'][0]
        event.update(game='游' * 100, title='事' * 160,
                     source_url='https://example.com/' + 'x' * 460)
        body['context']['events'] *= 15
        with self.assertRaisesRegex(ValueError, 'context_too_large'):
            project_context(body)

    def test_management_revision_is_internal_and_changes_shared_fingerprint(self):
        body = management()
        projected = project_context(body)
        previous = {key: projected[key] for key in ('scope', 'context')}
        hashed = lambda item: hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        self.assertNotEqual(hashed(projected), hashed(previous))
        self.assertEqual(projected['analysis_revision'], MANAGEMENT_REVISION)
        self.assertEqual(set(project_context(game())), {'scope', 'context'})
        for value in (MANAGEMENT_REVISION, 'old', None):
            with self.assertRaises(ValueError): project_context(dict(body, analysis_revision=value))
        with self.assertRaises(ValueError): build_messages(dict(body, analysis_revision='old'))
        with self.assertRaises(ValueError): build_messages(dict(game(), analysis_revision=MANAGEMENT_REVISION))
        with self.assertRaises(ValueError): validate_response(response(), previous)

    def test_management_reached_and_linear_forecast_are_derived_from_complete_days(self):
        body = management()
        body['context']['period']['end'] = '2026-10-12'
        body['context']['projects'][0].update(revenue_usd=110.6, target_revenue_usd=100)
        analysis = management_analysis(body['context'], date(2026, 10, 13))
        row = analysis['projects'][0]
        self.assertEqual(row['revenue_target_status'], 'reached')
        self.assertEqual(row['revenue_completion_ratio'], 1.106)
        self.assertEqual(row['revenue_forecast_usd'], 285.72)
        self.assertEqual(row['revenue_time_progress_status'], 'at_or_ahead')
        self.assertEqual(analysis['month_to_date_complete_days'], 12)
        self.assertAlmostEqual(analysis['time_progress_ratio'], 12 / 31, places=6)
        messages = build_messages(body)
        self.assertNotIn('date为null', messages[0]['content'])
        self.assertIn('绝不能说接近', messages[0]['content'])
        self.assertIn('Order全站参考估算', messages[0]['content'])

    def test_management_missing_zero_and_uncomparable_periods(self):
        body = management()
        body['context']['period']['end'] = '2026-10-12'
        row = body['context']['projects'][0]
        row.update(revenue_usd=None, missing=['revenue_usd'])
        fact = management_analysis(body['context'], date(2026, 10, 13))['projects'][0]
        self.assertEqual(fact['revenue_target_status'], 'missing')
        self.assertIsNone(fact['revenue_completion_ratio'])
        self.assertIsNone(fact['revenue_forecast_usd'])
        row.update(revenue_usd=0, target_revenue_usd=0, missing=[])
        fact = management_analysis(body['context'], date(2026, 10, 13))['projects'][0]
        self.assertEqual(fact['revenue_target_status'], 'reached')
        self.assertIsNone(fact['revenue_completion_ratio'])
        for start, end in [('2026-10-02', '2026-10-12'), ('2026-09-01', '2026-10-12'),
                           ('2026-11-01', '2026-11-12'), ('2026-10-01', '2026-10-13')]:
            body['context']['period'] = dict(start=start, end=end)
            analysis = management_analysis(body['context'], date(2026, 10, 13))
            self.assertFalse(analysis['period_comparable'])
            self.assertIsNone(analysis['time_progress_ratio'])
            self.assertEqual(analysis['projects'][0]['revenue_target_status'], 'period_not_comparable')
            self.assertIsNone(analysis['projects'][0]['revenue_forecast_usd'])

    def test_real_explain_boss_reprojects_and_validates_internal_revision(self):
        source = Path(__file__).with_name('ai_advisor_model.py')
        spec = importlib.util.spec_from_file_location('real_advisor_model_fixture', source)
        provider = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(provider)
        for body in (management(), game()):
            params = project_context(body)
            # Exact server management reproject -> shared bounded-model callback shape.
            if body['scope'] == 'management':
                params = project_context({'scope': params['scope'], 'context': params['context'],
                                          'request_id': 'server_verified_facts'})
            def request(messages, projected, validator):
                self.assertEqual(projected, params)
                sent = json.loads(messages[1]['content'])
                self.assertEqual(sent['scope'], params['scope'])
                self.assertEqual(sent['context'], params['context'])
                if params['scope'] == 'management':
                    self.assertEqual(sent['analysis_revision'], MANAGEMENT_REVISION)
                    self.assertIn('analysis', sent)
                else: self.assertEqual(set(sent), {'scope', 'context'})
                return validator(response(), projected)
            with patch.object(provider, 'request_model', side_effect=request) as called:
                result = provider.explain_boss(params)
            self.assertEqual(result['status'], 'succeeded')
            self.assertEqual(called.call_count, 1)


def response():
    return {'model': MODEL, 'id': 'chatcmpl_example-1234',
            'choices': [{'finish_reason': 'stop', 'message': {
                'content': json.dumps({'text': '建议先核对来源覆盖及缺项，再由业务人员评估目标完成情况。'})}}],
            'usage': {'prompt_tokens': 200, 'completion_tokens': 30, 'total_tokens': 230}}


class ResponseTests(unittest.TestCase):
    def test_management_rejects_game_topics_and_unqualified_profit(self):
        for text in ['建议先核对上线日期，再评估经营进度。', '建议先核对倒计时，再评估经营进度。',
                     '利润表现良好，建议继续保持当前经营安排。']:
            raw = response()
            raw['choices'][0]['message']['content'] = json.dumps({'text': text})
            with self.assertRaisesRegex(ValueError, 'invalid_management_output'):
                validate_response(raw, project_context(management()))
        for qualifier in ('Order全站参考估算', 'Order 全站参考估算', 'Order\n全站参考估算'):
            raw = response()
            raw['choices'][0]['message']['content'] = json.dumps({'text': '利润仅为' + qualifier + '，建议结合营收进度核对经营安排。'})
            self.assertEqual(validate_response(raw, project_context(management()))['status'], 'succeeded')

    def test_verified_receipt_usage_and_source_kind(self):
        for body, source_kind in [(game(), 'imported_snapshot'), (management(), 'fs_summary')]:
            result = validate_response(response(), project_context(body))
            self.assertEqual(result['source_kind'], source_kind)
            self.assertEqual(result['status'], 'succeeded')
            self.assertEqual(result['model'], MODEL)
            self.assertEqual(result['receipt'], 'chatcmpl_example-1234')
            self.assertEqual(result['tokens'], 230)
            self.assertEqual(set(result), {'status', 'text', 'model', 'receipt', 'tokens', 'source_kind'})

    def test_rejects_model_identity_receipt_finish_and_envelope(self):
        invalid = [None, [], {}, {'model': MODEL}]
        for key, value in [('model', 'other-model'), ('id', ''), ('id', 'bad\nreceipt'),
                           ('id', 'x' * 151), ('id', 123), ('choices', []),
                           ('choices', [None]), ('choices', 'not-a-list')]:
            raw = response()
            raw[key] = value
            invalid.append(raw)
        raw = response()
        raw['choices'][0]['finish_reason'] = 'length'
        invalid.append(raw)
        for raw in invalid:
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(ValueError):
                validate_response(raw, project_context(game()))

    def test_rejects_unverified_usage(self):
        for usage in [None, {}, {'total_tokens': 230},
                      {'prompt_tokens': True, 'completion_tokens': 30, 'total_tokens': 31},
                      {'prompt_tokens': 200, 'completion_tokens': -1, 'total_tokens': 199},
                      {'prompt_tokens': 200, 'completion_tokens': 30, 'total_tokens': 231},
                      {'prompt_tokens': 10000, 'completion_tokens': 30, 'total_tokens': 10030}]:
            raw = response()
            raw['usage'] = usage
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                validate_response(raw, project_context(management()))

    def test_rejects_secret_numeric_html_and_execution_claims(self):
        for text in ['建议将售价改为一美元。', '本期销售额为123美元。',
                     '已完成业务调整，请查看结果。', '<script>危险内容</script>',
                     '建议通过 customer@example.com 联系。', '已经联网检索并核实消息。',
                     'API_KEY=placeholder，请核对配置。', '建议' * 151, '短文本',
                     'Only English text is not valid.', '建议先核对\x00来源信息和目标情况。']:
            raw = response()
            raw['choices'][0]['message']['content'] = json.dumps({'text': text})
            with self.subTest(text_length=len(text)), self.assertRaises(ValueError):
                validate_response(raw, project_context(game()))

    def test_rejects_output_extra_fields_and_non_json(self):
        for content in [None, 'not-json', '[]', '{}',
                        json.dumps({'text': '建议核对来源覆盖及缺项。', 'execute': True}),
                        json.dumps({'text': 123}), 'x' * 4001]:
            raw = response()
            raw['choices'][0]['message']['content'] = content
            with self.subTest(content_type=type(content).__name__), self.assertRaises(ValueError):
                validate_response(raw, project_context(game()))

    def test_revalidates_projected_context(self):
        projected = project_context(management())
        projected['context']['projects'][0]['owner'] = 'private'
        with self.assertRaises(ValueError):
            validate_response(response(), projected)


if __name__ == '__main__':
    unittest.main()

