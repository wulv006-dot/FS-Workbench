import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from player_publish import PlayerPublishStore, TEST_GUILD, TEST_CHANNEL, OFFICIAL_GUILD, build_dispatch_plan


def url(mid):
    return f'https://discord.com/channels/{TEST_GUILD}/{TEST_CHANNEL}/{mid}'


class PlayerPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlayerPublishStore(self.temp.name)
        self.config = dict(enabled=True, guild_id=1041923524601851914,
            channel_id=1568260661010497627, featured_model_ids=[45490779],
            allowed_tag_ids=[], verified_prices={}, easysbc=dict(template='info',
            selection='featured', tag_match='any', with_card=True, mappings=[dict(
            model_id=45490779, easysbc_id='50524153', easysbc_role_id='44',
            easysbc_url='https://www.easysbc.io/players/romelu-lukaku/rttk/50524153?player-role-id=44')]))
        self.identity = dict(easysbc_id='50524153', easysbc_role_id='44',
            easysbc_url='https://www.easysbc.io/players/romelu-lukaku/rttk/50524153?player-role-id=44&utm_content=info',
            autocomplete_label='Romelu Lukaku | 87 - UEFA Champions League RTTK')
        self.key = str(uuid.uuid4())

    def create(self):
        return self.store.create(self.config, self.key, lambda mid: 'Lukaku RTTK')

    def test_short_saved_url_accepts_same_id_and_role_canonical_receipt(self):
        self.config['easysbc']['mappings'][0]['easysbc_url'] = 'https://www.easysbc.io/players/50524153?player-role-id=44'
        self.create()
        result = self.record()
        self.assertIsNotNone(result['items'][0]['receipt'])

    def test_unmapped_batch_keeps_candidates_and_rejects_other_identity(self):
        self.config['easysbc']['mappings'] = []
        match = {'status': 'ambiguous', 'candidates': [dict(self.identity)]}
        batch = self.store.create(self.config, self.key, lambda mid: 'Lukaku', lambda mid: match)
        self.assertEqual(batch['items'][0]['match']['status'], 'ambiguous')
        wrong = dict(self.identity, easysbc_id='123', easysbc_url='https://www.easysbc.io/players/123?player-role-id=44')
        with self.assertRaises(ValueError):
            self.store.record(self.key, 45490779, url(1569000000000000001), wrong, 1237241595674361962)
        self.assertIsNotNone(self.record()['items'][0]['receipt'])

    def record(self):
        return self.store.record(self.key, 45490779, url(1569000000000000001),
                                 self.identity, 1237241595674361962)

    def test_snapshot_immutable_and_request_id_idempotent(self):
        first = self.create()
        self.config['easysbc']['template'] = 'price'
        first['items'][0]['title'] = 'changed'
        again = self.create()
        self.assertEqual(again['template'], 'info')
        self.assertEqual(again['items'][0]['title'], 'Lukaku RTTK')
        self.assertEqual(again['guild_id'], TEST_GUILD)
        other = self.store.create(self.config, str(uuid.uuid4()), lambda mid: 'Lukaku RTTK')
        self.assertEqual(other['template'], 'price')

    def test_final_once_across_store_instances(self):
        self.create()
        self.record()
        self.record()
        calls = []
        result = self.store.finalize(self.key, lambda batch: calls.append(batch) or url(1569000000000000002))
        self.assertEqual(result['status'], 'sent')
        other = PlayerPublishStore(self.temp.name)
        other.finalize(self.key, lambda batch: self.fail('Duplicate send'))
        self.assertEqual(len(calls), 1)

    def test_incomplete_never_calls_sender(self):
        self.create()
        with self.assertRaises(ValueError):
            self.store.finalize(self.key, lambda batch: self.fail('Incomplete send'))
        self.assertEqual(self.store.get(self.key)['status'], 'pending')

    def test_send_failure_is_unknown_no_retry(self):
        self.create()
        self.record()
        def fail(batch):
            raise TimeoutError('May have sent')
        with self.assertRaises(TimeoutError):
            self.store.finalize(self.key, fail)
        with self.assertRaises(ValueError):
            self.store.finalize(self.key, lambda batch: self.fail('Blind retry'))
        self.assertEqual(self.store.get(self.key)['status'], 'unknown')

    def test_crash_after_sending_state_is_unknown(self):
        self.create()
        self.record()
        path = Path(self.temp.name) / (self.key + '.json')
        data = json.loads(path.read_text(encoding='utf-8'))
        data['status'] = 'sending'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            PlayerPublishStore(self.temp.name).finalize(self.key, lambda batch: self.fail('Crash retry'))
        self.assertEqual(self.store.get(self.key)['status'], 'unknown')

    def test_wrong_identity_and_production_receipt_rejected(self):
        self.create()
        wrong = dict(self.identity, easysbc_role_id='43')
        with self.assertRaises(ValueError):
            self.store.record(self.key, 45490779, url(1569000000000000001), wrong, 1237241595674361962)
        with self.assertRaises(ValueError):
            self.store.record(self.key, 45490779, url(1569000000000000001).replace(str(TEST_GUILD), '1041923524601851914'),
                              self.identity, 1237241595674361962)
        self.assertIsNone(self.store.get(self.key)['items'][0]['receipt'])

    def test_duplicate_receipt_cannot_confirm_other_model(self):
        self.config['featured_model_ids'].append(45490780)
        self.create()
        self.record()
        with self.assertRaises(ValueError):
            self.store.record(self.key, 45490780, url(1569000000000000001), self.identity, 1237241595674361962)

    def test_empty_list_and_tags_rejected(self):
        self.config['featured_model_ids'] = []
        with self.assertRaises(ValueError):
            self.create()
        self.config['featured_model_ids'] = [45490779]
        self.config['easysbc']['selection'] = 'tags'
        with self.assertRaises(ValueError):
            self.create()

    def test_bad_final_receipt_marks_unknown(self):
        self.create()
        self.record()
        with self.assertRaises(ValueError):
            self.store.finalize(self.key, lambda batch: 'https://discord.com/channels/1/2/3')
        self.assertEqual(self.store.get(self.key)['status'], 'unknown')

    def test_changed_mapping_is_not_used_for_existing_batch(self):
        self.create()
        self.config['easysbc']['mappings'][0]['easysbc_id'] = '9999'
        self.record()
        self.assertEqual(self.store.get(self.key)['items'][0]['mapping']['easysbc_id'], '50524153')

    def test_official_explicit_destination_snapshot_and_receipts(self):
        self.config['guild_id'] = OFFICIAL_GUILD
        self.config['channel_id'] = 1569999999999999999
        batch = self.store.create(self.config, self.key, lambda mid: 'Lukaku/87/ST/RTTK', target='official')
        self.assertEqual(batch['guild_id'], OFFICIAL_GUILD)
        self.assertEqual(batch['execution_plan']['target'], 'official')
        self.assertEqual(batch['execution_plan']['items'][0]['search_terms'], ['Lukaku'])
        self.config['channel_id'] = 1569999999999999998
        self.assertEqual(self.store.get(self.key)['channel_id'], 1569999999999999999)
        official_url = f'https://discord.com/channels/{OFFICIAL_GUILD}/1569999999999999999/1569000000000000001'
        self.store.record(self.key, 45490779, official_url, self.identity, 1237241595674361962)
        result = self.store.finalize(self.key, lambda batch: official_url[:-1] + '2')
        self.assertEqual(result['status'], 'sent')

    def test_same_request_cannot_switch_target(self):
        self.create()
        with self.assertRaises(ValueError):
            self.store.create(self.config, self.key, lambda mid: 'Lukaku', target='official')

    def test_official_rejects_test_config_and_unknown_target(self):
        self.config['guild_id'] = TEST_GUILD
        with self.assertRaises(ValueError):
            self.store.create(self.config, self.key, lambda mid: 'Lukaku', target='official')
        with self.assertRaises(ValueError):
            self.store.create(self.config, self.key, lambda mid: 'Lukaku', target='arbitrary')

    def test_plan_is_pure_saved_order_and_contains_dispatch_text(self):
        selected = [{'model_id': 45490779, 'title': 'Lukaku/87/ST/RTTK', 'model_available': True}]
        before = copy.deepcopy(self.config)
        plan = build_dispatch_plan(self.config, selected)
        self.assertEqual(self.config, before)
        self.assertEqual(plan['items'][0]['command'], '/player info')
        self.assertTrue(plan['items'][0]['with_card'])
        self.assertEqual(plan['final_action']['count'], 1)
        self.assertIn('plan --target test', plan['text'])
        self.assertEqual(list(Path(self.temp.name).glob('*.json')), [])
        with self.assertRaises(ValueError):
            build_dispatch_plan(self.config, [])

    def test_verified_standard_mapping_replaces_cosmetic_only_in_snapshot(self):
        standard = dict(self.config['easysbc']['mappings'][0], easysbc_id='123456',
                        easysbc_url='https://www.easysbc.io/players/123456?player-role-id=44')
        batch = self.store.create(self.config, self.key, lambda mid: 'Lukaku',
            lambda mid: {'status': 'matched', 'mapping': standard, 'candidates': []})
        item = batch['items'][0]
        self.assertEqual(item['mapping']['easysbc_id'], '123456')
        self.assertEqual(item['source_mapping']['easysbc_id'], '50524153')
        self.assertEqual(self.config['easysbc']['mappings'][0]['easysbc_id'], '50524153')

    def test_verified_same_asset_cosmetic_receipt_allowed_but_wrong_base_rejected(self):
        base = dict(model_id=45490779, easysbc_id='50524153', easysbc_role_id='44',
                    asset_id='12345', name='Romelu Lukaku', rating=87, version='RTTK',
                    season=27, cosmetic=False, identity_compatible=True)
        alternate = dict(base, easysbc_id='999999', cosmetic=True)
        identity = dict(self.identity, easysbc_id='999999',
                        easysbc_url='https://www.easysbc.io/players/999999?player-role-id=44')
        for field, value in [(None, None), ('asset_id', '111'), ('rating', 88), ('version', 'TOTW'),
                             ('identity_compatible', False), ('name', 'Another player')]:
            with self.subTest(field=field):
                key = str(uuid.uuid4())
                candidate = dict(alternate)
                if field:
                    candidate[field] = value
                match = dict(status='matched', mapping=self.config['easysbc']['mappings'][0],
                             selection_policy='same_base_standard_first_else_cosmetic', candidates=[base, candidate])
                self.store.create(self.config, key, lambda mid: 'Lukaku', lambda mid: match)
                if field:
                    with self.assertRaises(ValueError):
                        self.store.record(key, 45490779, url(1569000000000000001), identity, 1237241595674361962)
                else:
                    batch = self.store.record(key, 45490779, url(1569000000000000001), identity, 1237241595674361962)
                    self.assertEqual(batch['items'][0]['receipt']['identity']['easysbc_id'], '999999')


if __name__ == '__main__':
    unittest.main()
