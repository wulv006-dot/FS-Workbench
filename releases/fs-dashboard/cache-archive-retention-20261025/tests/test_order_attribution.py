"""Synthetic XLSX through both real readers; no sessions, exports or production files."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / 'source'
ROOT = SOURCE.parents[3]
sys.path[:0] = [str(SOURCE), str(ROOT/'releases/fs-dashboard/fs-business-baseline-20261021/source'),
                  str(ROOT/'releases/fs-dashboard/fs-business-baseline-20261021/fixtures')]


def reader(name):
    spec = importlib.util.spec_from_file_location('d0_' + name, SOURCE/(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


READERS = [reader(name) for name in ('es_order_structure', 'session_es_order_structure')]
HEADERS = list(READERS[0].COLUMNS.values()) + ['推广人ID', '折扣码', '优惠类型', '折扣比例', '折扣金额', '未使用列']
HEADERS += ['uid', 'buyer_id', '归因渠道', '归因来源明细', '首访时间']
Q = dict(profile='ALL', start='2026-11-10', end='2026-11-11', group_by='game', status='all')


def order(**changes):
    row = {key: '' for key in HEADERS}
    row.update({'订单号': 'synthetic-order-1', '游戏': 'FC 27', '订单金额（美元）': '40.00',
                '实付金额': '40.00', '实付币种': 'USD', '订单状态': '已完成',
                '付款时间': '2026/11/10 10:00:00', 'uid': '0', 'buyer_id': 'buyer-A',
                '归因渠道': 'Direct', '归因来源明细': 'direct', '首访时间': '2026-11-10 09:00:00',
                '订单来源': 'google-example', '折扣码': 'TEST', '推广人ID': 'example'})
    row.update(changes)
    return row


def xlsx(width, rows):
    headers = HEADERS[:width]
    cells = []
    for number, values in enumerate([headers] + [[row.get(h, '') for h in headers] for row in rows], 1):
        cells.append('<row>' + ''.join('<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>' %
                                     (chr(65+i), number, escape(str(v))) for i, v in enumerate(values)) + '</row>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as book:
        book.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(cells) + '</sheetData></worksheet>')
    return out.getvalue()


def write(path, raw):
    path.write_bytes(raw); os.chmod(path, 0o600)


def archive(root, width, rows, query=None, captured='2026-11-12T00:00:00+00:00'):
    raw = xlsx(width, rows); sha = hashlib.sha256(raw).hexdigest()
    write(root/(sha + '.xlsx'), raw)
    value = dict(query=query or dict(profile='ALL', start=Q['start'], end=Q['end']),
                 file_sha256=[sha], file_set=dict(declared_files=1, failed_files=0), captured_at=captured)
    raw = json.dumps(value, sort_keys=True).encode(); sha = hashlib.sha256(raw).hexdigest()
    write(root/(sha + '.json'), raw)
    return dict(name=sha + '.json', sha256=sha)


def publication(pins, revision='1'):
    value = dict(contract='fs-users-weekly-publication-v1', cutoff='2026-11-12T00:00:00+08:00',
                 published_at='2026-11-14T04:20:00+08:00', captured_at='2026-11-12T00:00:00+08:00',
                 data_version=revision, cadence='daily', config={'sites': ['site-A']}, jobs=[],
                 refresh_health={}, coverage_context={}, source_status_rule_versions=[], flag_manifests=pins)
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    return dict(value, publication_id='uw_' + hashlib.sha256(raw).hexdigest()[:32])


class Attribution(unittest.TestCase):
    def test_three_widths_preserve_money_identity_and_presence(self):
        for module in READERS:
            for width in (19, 21, 24):
                with self.subTest(reader=module.__name__, width=width):
                    raw = xlsx(width, [order()]); rows, hashes, errors = module.parse_files([raw])
                    value = module.make_dataset(rows, hashes, errors, 1, 0)
                    row = value['rows'][0]; fact = row['marketing_attribution']
                    self.assertEqual(row['订单金额（美元）'], '40.00')
                    self.assertEqual(row['订单号'], hashlib.sha256(b'synthetic-order-1').hexdigest())
                    self.assertEqual(fact['status'], 'available' if width == 24 else 'field_absent')
                    self.assertEqual('buyer_id' in row, width >= 21)
                    self.assertEqual(row.get('uid'), '0' if width >= 21 else None)
                    self.assertEqual(row['折扣码'], 'TEST')
                    self.assertEqual(row['推广人ID'], 'example')
                    self.assertEqual(row['_signature'], hashlib.sha256(json.dumps(rows[0], sort_keys=True, ensure_ascii=False).encode()).hexdigest())

    def test_channels_do_not_reclassify_legacy_source_or_first_purchase(self):
        for module in READERS:
            for channel, source, status in [('Direct', 'direct', 'available'), ('Campaign', 'google', 'available'),
                                             ('Referral', 'cardpay.com', 'available'), ('new-channel', 'google', 'unrecognized'),
                                             ('', '', 'empty')]:
                with self.subTest(reader=module.__name__, channel=channel):
                    row = order(**{'归因渠道': channel, '归因来源明细': source})
                    value = module.make_dataset([row], ['a'*64], 0, 1, 0)['rows'][0]
                    fact = value['marketing_attribution']
                    self.assertEqual(fact['channel_raw'], channel)
                    self.assertEqual(fact['source_raw'], source)
                    self.assertEqual(fact['status'], status)
                    self.assertEqual(fact['channel'], channel if status == 'available' else 'unknown')
                    self.assertEqual(value['订单来源'], 'google-example')
                    self.assertIsNone(fact['first_visit_at'])
                    self.assertEqual(fact['first_visit_status'], 'semantics_unverified')
                    self.assertNotIn('first_purchase_at', fact)

    def test_absent_is_not_explicit_empty_and_json_roundtrip(self):
        for module in READERS:
            old = {k: v for k, v in order().items() if k not in HEADERS[21:]}
            empty = order(**dict.fromkeys(HEADERS[21:], ''))
            absent, clear = [module.make_dataset([row], [], 0, 1, 0)['rows'][0]['marketing_attribution'] for row in (old, empty)]
            self.assertFalse(absent['field_presence']['channel_raw'])
            self.assertIsNone(absent['channel_raw'])
            self.assertTrue(clear['field_presence']['channel_raw'])
            self.assertEqual(clear['channel_raw'], '')
            self.assertEqual(json.loads(json.dumps(clear)), clear)


class PublishedRevisions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); os.chmod(self.root, 0o700)

    def tearDown(self):
        self.temp.cleanup()

    def read(self, module, pins, revision='1', query=None):
        return module.archived_dataset(query or Q, self.root, publication=publication(pins, revision))

    def test_pins_exclude_newer_unpublished_and_keep_old_publication_repeatable(self):
        first = archive(self.root, 24, [order()])
        newer = archive(self.root, 24, [order(**{'订单状态': '已退款', '归因渠道': '', '归因来源明细': ''})], captured='2026-11-13T00:00:00+00:00')
        for module in READERS:
            old = self.read(module, [first])
            revised = self.read(module, [newer], '2')
            self.assertEqual(old['rows'][0]['订单状态'], '已完成')
            self.assertEqual(revised['rows'][0]['订单状态'], '已退款')
            self.assertEqual(revised['rows'][0]['marketing_attribution']['status'], 'empty')
            self.assertEqual(old, self.read(module, [first]))
            self.assertEqual(revised['data_revision'], '2')
            self.assertEqual(revised['source_revision'], revised['publication_id'])

    def test_schema_superset_is_whole_row_not_last_nonempty(self):
        old = archive(self.root, 21, [order()])
        new = archive(self.root, 24, [order()])
        for module in READERS:
            for pins in ([old, new], [new, old]):
                value = self.read(module, pins)
                self.assertEqual(len(value['rows']), 1)
                self.assertEqual(value['rows'][0]['marketing_attribution']['channel'], 'Direct')
            absent = self.read(module, [old], '2')['rows'][0]['marketing_attribution']
            self.assertEqual(absent['status'], 'field_absent')

    def test_same_publication_conflict_retains_whole_variants(self):
        a = archive(self.root, 24, [order()])
        b = archive(self.root, 24, [order(**{'订单状态': '已退款', '归因渠道': 'PPC'})])
        for module in READERS:
            value = self.read(module, [a, b])
            self.assertEqual(value['status'], 'partial')
            self.assertEqual(len(value['revision_conflicts']), 1)
            self.assertEqual({(r['订单状态'], r['marketing_attribution']['channel_raw']) for r in value['rows']},
                             {('已完成', 'Direct'), ('已退款', 'PPC')})
            self.assertTrue(all(r['marketing_attribution']['status'] == 'conflict' for r in value['rows']))

    def test_duplicate_day_and_month_do_not_double_count(self):
        month = archive(self.root, 24, [order()])
        day = archive(self.root, 24, [order()], dict(profile='ALL', start='2026-11-10', end='2026-11-10'))
        for module in READERS:
            self.assertEqual(len(self.read(module, [month, day, day])['rows']), 1)

    def test_archive_profile_is_not_population_or_site_proof(self):
        pin = archive(self.root, 24, [order(), order(**{'订单号': 'synthetic-2', '游戏': 'Diablo 4'})])
        for module in READERS:
            value = self.read(module, [pin], query=dict(Q, profile='FC27'))
            self.assertEqual(len(value['rows']), 2)
            self.assertFalse(value['effective_scope']['site_verified'])
            self.assertFalse(value['effective_scope']['game_filter_applied'])
        wrong = archive(self.root, 24, [order()], dict(profile='FC27', start=Q['start'], end=Q['end']))
        for module in READERS:
            with self.assertRaisesRegex(ValueError, 'scope_unverified'): self.read(module, [wrong])

    def test_changed_manifest_and_missing_day_reject_without_export(self):
        pin = archive(self.root, 24, [order()], dict(profile='ALL', start=Q['start'], end=Q['start']))
        for module in READERS:
            with patch.object(module, 'export_bundle', side_effect=AssertionError('no export')):
                with self.assertRaisesRegex(ValueError, 'coverage'): self.read(module, [pin])
        write(self.root/pin['name'], b'{}')
        for module in READERS:
            with self.assertRaisesRegex(ValueError, 'manifest_changed'): self.read(module, [pin])

    def test_future_capture_and_incomplete_source_are_not_published_facts(self):
        future = archive(self.root, 24, [order()], captured='2026-11-15T00:00:00+00:00')
        for module in READERS:
            with self.assertRaisesRegex(ValueError, 'source_not_available'): self.read(module, [future])
        pin = archive(self.root, 24, [order()])
        value = json.loads((self.root/pin['name']).read_bytes())
        value['file_set']['failed_files'] = 1
        raw = json.dumps(value).encode(); sha = hashlib.sha256(raw).hexdigest()
        write(self.root/(sha + '.json'), raw)
        for module in READERS:
            with self.assertRaisesRegex(ValueError, 'incomplete'): self.read(module, [dict(name=sha + '.json', sha256=sha)])

    def test_invalid_publication_and_unsupported_query_never_fall_back(self):
        pin = archive(self.root, 24, [order()])
        for module in READERS:
            with patch.object(module, '_archived_dataset', side_effect=AssertionError('no legacy fallback')):
                bad = publication([pin]); bad['data_version'] = '9'
                with self.assertRaisesRegex(ValueError, 'integrity'):
                    module.archived_dataset(Q, self.root, publication=bad)
                with self.assertRaisesRegex(ValueError, 'es_query_fields'):
                    self.read(module, [pin], query=dict(Q, site='invented'))

    def test_snapshot_empty_cannot_erase_from_conflicting_snapshot(self):
        full = archive(self.root, 24, [order()])
        clear = archive(self.root, 24, [order(**dict.fromkeys(HEADERS[21:], ''))])
        for module in READERS:
            conflict = self.read(module, [full, clear])
            self.assertEqual(conflict['status'], 'partial')
            self.assertEqual({r['marketing_attribution']['channel_raw'] for r in conflict['rows']}, {'Direct', ''})
            explicit = self.read(module, [clear], '2')
            self.assertEqual(explicit['rows'][0]['marketing_attribution']['status'], 'empty')

    def test_legacy_reader_keeps_profile_label_separate_and_live_ttl(self):
        archive(self.root, 21, [order(), order(**{'订单号': 'synthetic-2', '游戏': 'Diablo 4'})],
                dict(profile='FC27', start=Q['start'], end=Q['end']))
        for module in READERS:
            value = module.archived_dataset(Q, self.root)
            self.assertEqual(len(value['rows']), 2)
            self.assertEqual(value['archive_profile'], 'FC27')
            self.assertEqual(value['revision_selection'], 'legacy_capture_unverified')
            self.assertFalse(value['effective_scope']['site_verified'])
            self.assertFalse(value['effective_scope']['game_filter_applied'])

    def test_helper_is_in_session_build_and_existing_public_projection_stays_compatible(self):
        self.assertIn('COPY order_attribution.py /usr/local/bin/order_attribution.py', (SOURCE/'Dockerfile.session').read_text())
        for module in READERS:
            rows, hashes, failed = module.parse_files([xlsx(24, [order()])])
            private = module.make_dataset(rows, hashes, failed, 1, 0)
            self.assertEqual(module.aggregate_rows(rows, hashes, failed, Q, 1, 0)['structure_totals'],
                             module.aggregate_rows(private['rows'], hashes, failed, Q, 1, 0)['structure_totals'])


if __name__ == '__main__':
    unittest.main()
