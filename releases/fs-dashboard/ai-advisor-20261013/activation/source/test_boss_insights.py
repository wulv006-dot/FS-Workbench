"""Offline contract tests; never call a model or touch existing credential files."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fc_daily_20261013' / 'candidate'))
from fc_daily_model import MODEL
from boss_insights import build_messages, project_context, validate_response


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
        self.assertEqual(set(projected), {'scope', 'context'})
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
        for value in ['2026-02-30', '20261013', '2026-1-2', None]:
            body = game()
            body['context']['events'][0]['date'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                project_context(body)
        body = management()
        body['context']['period']['start'] = '2026-10-14'
        with self.assertRaises(ValueError):
            project_context(body)

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


def response():
    return {'model': MODEL, 'id': 'chatcmpl_example-1234',
            'choices': [{'finish_reason': 'stop', 'message': {
                'content': json.dumps({'text': '建议先核对来源覆盖及缺项，再由业务人员评估目标完成情况。'})}}],
            'usage': {'prompt_tokens': 200, 'completion_tokens': 30, 'total_tokens': 230}}


class ResponseTests(unittest.TestCase):
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
