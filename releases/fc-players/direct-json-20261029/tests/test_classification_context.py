from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from test_direct_import import load, direct
from test_payload import source_row, form, DEFAULTS
from 球员维护工具.transformer import _write_xlsx

service = load('new_card_service')


class Source:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.fail = set()
        self.drift = False

    def list_players(self, filters, page, per_page):
        self.calls.append(('list', dict(filters.criteria), page))
        name = filters.criteria['q']
        if name in self.fail:
            raise TimeoutError('untrusted upstream details')
        rows = self.rows[name]
        values = [{'futbin_id': r['FUTBIN ID'], 'resource_id': r['FUTBIN ID'],
                   'name': r['name'], 'rare_type_name': r['Version']} for r in rows]
        return SimpleNamespace(total=len(values), page=page, per_page=per_page,
                               items=values[(page-1)*per_page:page*per_page])

    def export_players(self, filters, destination, overwrite=False):
        self.calls.append(('export', dict(filters.criteria)))
        rows = self.rows[filters.criteria['q']]
        _write_xlsx(destination, rows[:-1] if self.drift else rows)


class ClassificationContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.a = source_row()
        self.b = {**self.a, 'FUTBIN ID': 23700, 'IS': 40000}

    def tearDown(self):
        self.tmp.cleanup()

    def freeze(self, selected, source):
        path = self.root / 'selected.xlsx'
        _write_xlsx(path, selected)
        return service.prepare_classification_context(source, path, self.root, 1000)

    def test_window_external_sibling_and_one_lookup_per_name(self):
        # Input selection contains one card; sibling is outside its days_new export.
        source = Source({self.a['name']: [self.a, self.b]})
        context, errors, evidence = self.freeze([self.b], source)
        self.assertEqual(errors, {})
        self.assertEqual(direct.resolve_players_types(direct._source_rows(context))['23700'], 'Signature')
        self.assertEqual([c[0] for c in source.calls], ['list', 'export'])
        self.assertTrue(all(c[1] == {'q': self.a['name']} for c in source.calls))
        self.assertEqual(evidence[0]['status'], 'complete')

    def test_same_name_selection_reuses_lookup_and_excludes_fuzzy_hits(self):
        extra = {**self.a, 'name': 'Other Current Player', 'FUTBIN ID': 999}
        source = Source({self.a['name']: [self.a, self.b, extra]})
        context, errors, _ = self.freeze([self.a, self.b], source)
        self.assertFalse(errors)
        self.assertEqual(len(direct._source_rows(context)), 2)
        self.assertEqual(len(source.calls), 2)

    def test_reads_all_pages(self):
        extras = [{**self.a, 'name': 'Fuzzy ' + str(i), 'FUTBIN ID': 1000+i} for i in range(200)]
        source = Source({self.a['name']: extras + [self.a, self.b]})
        context, errors, _ = self.freeze([self.b], source)
        self.assertFalse(errors)
        self.assertEqual([c[2] for c in source.calls if c[0] == 'list'], [1, 2])
        self.assertEqual(len(direct._source_rows(context)), 2)

    def test_group_drift_is_explicitly_blocked(self):
        source = Source({self.a['name']: [self.a, self.b]})
        source.drift = True
        _, errors, evidence = self.freeze([self.a], source)
        self.assertEqual(errors[str(self.a['FUTBIN ID'])], 'DIRECT_CLASSIFICATION_GROUP_DRIFT')
        self.assertEqual(evidence[0]['status'], 'blocked')

    def test_page_incomplete_keeps_error_code_and_does_not_export(self):
        class Incomplete(Source):
            def list_players(self, *args, **kwargs):
                result = super().list_players(*args, **kwargs)
                result.total += 1
                return result
        source = Incomplete({self.a['name']: [self.a]})
        _, errors, evidence = self.freeze([self.a], source)
        self.assertEqual(errors[str(self.a['FUTBIN ID'])], 'SOURCE_PAGE_INCOMPLETE')
        self.assertEqual([call[0] for call in source.calls], ['list'])
        self.assertEqual(evidence[0]['error_code'], 'SOURCE_PAGE_INCOMPLETE')

    def test_other_version_does_not_turn_singleton_into_pair(self):
        other = {**self.b, 'Version': 'Gold Rare'}
        context, errors, _ = self.freeze([self.a], Source({self.a['name']: [self.a, other]}))
        self.assertFalse(errors)
        self.assertEqual(direct.resolve_players_types(direct._source_rows(context)),
                         {str(self.a['FUTBIN ID']): 'normal'})

    def test_one_version_drift_leaves_same_name_other_version_executable(self):
        good = {**self.a, 'Version': 'Gold Rare', 'FUTBIN ID': 444}
        source = Source({self.a['name']: [self.a, good, self.b]})
        source.drift = True
        context, errors, _ = self.freeze([self.a, good], source)
        self.assertEqual(set(errors), {str(self.a['FUTBIN ID'])})
        schema = form()
        for prop in schema['row']['more']['baseprop']:
            if prop['name'] == 'Version':
                prop['pvs'].append({'id': 99999, 'name': 'Gold Rare', 'checked': False})
        items = direct.prepare_direct_items(self.root / 'selected.xlsx',
                    [{'futbin_id': str(r['FUTBIN ID'])} for r in [self.a, good]], schema,
                    business_defaults=DEFAULTS, context_artifact_path=context, classification_errors=errors)
        self.assertIsNone(items[0]['payload'])
        self.assertIsNotNone(items[1]['payload'])
        self.assertEqual(len(source.calls), 2)

    def test_programming_error_is_not_converted_to_missing_evidence(self):
        class Broken(Source):
            def list_players(self, *args, **kwargs):
                raise AttributeError('programming defect')
        with self.assertRaises(AttributeError):
            self.freeze([self.a], Broken({self.a['name']: [self.a]}))

    def test_failed_name_does_not_block_other_group_or_classify_incomplete_singleton(self):
        other = {**self.a, 'name': 'Good Player', 'FUTBIN ID': 444}
        source = Source({self.a['name']: [self.a, self.b], 'Good Player': [other]})
        source.fail.add(self.a['name'])
        context, errors, evidence = self.freeze([self.a, other], source)
        selected = self.root / 'selected.xlsx'
        items = direct.prepare_direct_items(selected, [{'futbin_id': str(r['FUTBIN ID'])} for r in [self.a, other]],
                    form(), business_defaults=DEFAULTS, context_artifact_path=context, classification_errors=errors)
        self.assertIsNone(items[0]['payload'])
        self.assertIsNone(items[0]['players_type'])
        self.assertEqual(items[0]['blocked_error'], 'DIRECT_CLASSIFICATION_LOOKUP_FAILED')
        self.assertIsNotNone(items[1]['payload'])
        self.assertEqual(evidence[0]['error_type'], 'TimeoutError')


if __name__ == '__main__':
    unittest.main()
